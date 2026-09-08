"""
SC2 Stub Backend

WARNING
-------
This backend interacts with the live StarCraft II client via
keyboard simulation and (optionally) screen OCR.
Any such automation violates Blizzard’s Terms of Service and
can result in account suspension or permanent ban.
Use only for educational / research purposes and at your own risk.
Prefer the SimulatedChatBackend for development.
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
import time
from collections import deque
from datetime import datetime
from typing import AsyncIterator, Deque, Optional, Tuple

from ..models import ChatMessage, Channel
from .base import ChatBackend

logger = logging.getLogger("sc2_chatbot.sc2_stub")

HAS_PYAUTOGUI = False
HAS_MSS = False
HAS_TESSERACT = False

try:
    import pyautogui
    import pygetwindow as gw
    HAS_PYAUTOGUI = True
except ImportError:
    pass

try:
    import mss
    from PIL import Image
    HAS_MSS = True
except ImportError:
    pass

try:
    import pytesseract
    HAS_TESSERACT = True
except ImportError:
    pass


class SC2StubBackend(ChatBackend):
    def __init__(self, cfg: dict, self_name: str = "ChatBot"):
        self.cfg = cfg or {}
        self.self_name = self_name

        self.chat_key = self.cfg.get("chat_key", "enter")
        self.send_key = self.cfg.get("send_key", "enter")
        self.typing_cps = float(self.cfg.get("typing_speed_cps", 11))
        self.window_title_substring = self.cfg.get("window_title", "StarCraft II")

        self.ocr_enabled = bool(self.cfg.get("ocr_enabled", False))
        self.poll_interval = float(self.cfg.get("poll_interval_sec", 1.8))
        self.chat_region = self.cfg.get("chat_region")
        self.tesseract_cmd = self.cfg.get("tesseract_cmd")

        self._connected = False
        self._seen: Deque[str] = deque(maxlen=80)
        self._last_ocr_text = ""
        self._lock = asyncio.Lock()

        if self.tesseract_cmd and HAS_TESSERACT:
            pytesseract.pytesseract.tesseract_cmd = self.tesseract_cmd

        self._validate_capabilities()

    def _validate_capabilities(self) -> None:
        if not HAS_PYAUTOGUI:
            logger.warning("pyautogui / pygetwindow not installed – sending will fail")
        if self.ocr_enabled:
            if not (HAS_MSS and HAS_TESSERACT):
                logger.warning("OCR enabled but mss or pytesseract missing.")
                self.ocr_enabled = False
            elif not self.chat_region:
                logger.warning("OCR enabled but chat_region not set.")
                self.ocr_enabled = False

    async def connect(self) -> None:
        self._connected = True
        logger.info("SC2StubBackend connected (OCR=%s)", self.ocr_enabled)

    async def disconnect(self) -> None:
        self._connected = False

    async def is_connected(self) -> bool:
        return self._connected

    def _find_sc2_window(self):
        if not HAS_PYAUTOGUI:
            return None
        try:
            windows = gw.getWindowsWithTitle(self.window_title_substring)
            for w in windows:
                if w.visible and not w.isMinimized:
                    return w
        except Exception as e:
            logger.debug("Window search failed: %s", e)
        return None

    def _focus_window(self, window) -> bool:
        try:
            if window.isMinimized:
                window.restore()
            window.activate()
            time.sleep(0.25)
            return True
        except Exception as e:
            logger.warning("Could not focus SC2 window: %s", e)
            return False

    async def send(self, text: str, channel: Channel = Channel.ALL, target: Optional[str] = None) -> None:
        if not HAS_PYAUTOGUI:
            logger.error("Cannot send – pyautogui not available")
            return

        async with self._lock:
            window = self._find_sc2_window()
            if window is None:
                logger.error("StarCraft II window not found")
                return

            if not self._focus_window(window):
                return

            await asyncio.sleep(random.uniform(0.15, 0.35))
            pyautogui.press(self.chat_key)
            await asyncio.sleep(random.uniform(0.18, 0.32))

            delay = 1.0 / max(self.typing_cps, 1.0)
            for char in text:
                pyautogui.write(char, interval=delay * random.uniform(0.65, 1.45))
                if random.random() < 0.04:
                    await asyncio.sleep(random.uniform(0.05, 0.18))

            await asyncio.sleep(random.uniform(0.08, 0.18))
            pyautogui.press(self.send_key)
            logger.info("Sent to %s: %s", channel.value, text[:80])

    def _capture_chat_region(self):
        if not (HAS_MSS and self.chat_region):
            return None
        left, top, width, height = self.chat_region
        monitor = {"left": left, "top": top, "width": width, "height": height}
        try:
            with mss.mss() as sct:
                shot = sct.grab(monitor)
                return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        except Exception as e:
            logger.debug("Screenshot failed: %s", e)
            return None

    def _ocr_image(self, img) -> str:
        if not HAS_TESSERACT:
            return ""
        try:
            config = "--psm 6 --oem 3"
            text = pytesseract.image_to_string(img, lang="eng", config=config)
            return text.strip()
        except Exception as e:
            logger.debug("OCR failed: %s", e)
            return ""

    def _parse_messages(self, raw: str) -> list[Tuple[str, str, Channel]]:
        results = []
        lines = [l.strip() for l in raw.splitlines() if l.strip()]
        pattern = re.compile(
            r"^(?:\[(?P<chan>All|Team|Whisper)\]\s*)?"
            r"(?P<player>[^\s:]{2,32})\s*:\s*(?P<text>.+)$",
            re.IGNORECASE,
        )
        for line in lines:
            m = pattern.match(line)
            if not m:
                continue
            player = m.group("player").strip()
            text = m.group("text").strip()
            chan_raw = (m.group("chan") or "All").lower()
            if chan_raw == "team":
                channel = Channel.TEAM
            elif chan_raw == "whisper":
                channel = Channel.WHISPER
            else:
                channel = Channel.ALL
            if player.lower() == self.self_name.lower():
                continue
            results.append((player, text, channel))
        return results

    def _fingerprint(self, player: str, text: str) -> str:
        return f"{player.lower()}|{text.lower()[:60]}"

    async def _poll_once(self) -> list[ChatMessage]:
        if not self.ocr_enabled:
            return []
        img = self._capture_chat_region()
        if img is None:
            return []
        raw = self._ocr_image(img)
        if not raw or raw == self._last_ocr_text:
            return []
        self._last_ocr_text = raw
        parsed = self._parse_messages(raw)
        new_msgs = []
        for player, text, channel in parsed:
            fp = self._fingerprint(player, text)
            if fp in self._seen:
                continue
            self._seen.append(fp)
            new_msgs.append(
                ChatMessage(
                    player=player,
                    text=text,
                    channel=channel,
                    timestamp=datetime.utcnow(),
                    is_self=False,
                    raw=raw,
                )
            )
        return new_msgs

    async def listen(self) -> AsyncIterator[ChatMessage]:
        logger.info("SC2StubBackend listen() started (OCR=%s)", self.ocr_enabled)
        if not self.ocr_enabled:
            logger.warning("OCR reader is disabled. No messages will be yielded.")

        while self._connected:
            try:
                msgs = await self._poll_once()
                for msg in msgs:
                    yield msg
            except Exception:
                logger.exception("Error in OCR poll")
            await asyncio.sleep(self.poll_interval)
