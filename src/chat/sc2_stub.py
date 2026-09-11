"""
SC2 Stub Backend

WARNING
-------
This backend interacts with the live StarCraft II client via
keyboard simulation and (optionally) screen OCR.
Any such automation violates Blizzard's Terms of Service and
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
        # Log a short OCR sample every N polls when no messages parse (troubleshooting)
        self._debug_every = int(self.cfg.get("ocr_debug_every_n_polls", 8))
        self._poll_count = 0

        self._connected = False
        self._seen: Deque[str] = deque(maxlen=120)
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
            else:
                try:
                    _l, _t, w, h = [int(x) for x in self.chat_region]
                    if w > 1200 or h > 900:
                        logger.warning(
                            "chat_region width/height looks very large (%sx%s). "
                            "Format must be [left, top, width, height] — not right/bottom.",
                            w,
                            h,
                        )
                except Exception:
                    logger.warning("chat_region is not a valid [left, top, width, height] list")

    async def connect(self) -> None:
        self._connected = True
        logger.info("SC2StubBackend connected (OCR=%s)", self.ocr_enabled)
        if self.ocr_enabled and self.chat_region:
            logger.info("OCR chat_region=%s  poll=%.1fs", self.chat_region, self.poll_interval)

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
        left, top, width, height = [int(x) for x in self.chat_region]
        monitor = {"left": left, "top": top, "width": width, "height": height}
        try:
            with mss.mss() as sct:
                shot = sct.grab(monitor)
                return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        except Exception as e:
            logger.warning("Screenshot failed: %s", e)
            return None

    def _ocr_image(self, img) -> str:
        if not HAS_TESSERACT:
            return ""
        try:
            config = "--psm 6 --oem 3"
            text = pytesseract.image_to_string(img, lang="eng", config=config)
            return text.strip()
        except Exception as e:
            logger.warning("OCR failed (is Tesseract installed?): %s", e)
            return ""

    def _parse_messages(self, raw: str) -> list[Tuple[str, str, Channel]]:
        """Parse OCR lines into (raw_player_name, text, channel).

        Handles common SC2 lobby / arcade forms, e.g.:
          Serral: gl hf
          [All] Serral: gl hf
          [1. General] antonBuffer: hello
          16:32 [2. Arcade] Kelvin: hi
        """
        results = []
        lines = [l.strip() for l in raw.splitlines() if l.strip()]

        # Optional time, optional [channel], then name: text
        pattern = re.compile(
            r"^(?:\d{1,2}:\d{2}\s+)?"  # optional HH:MM
            r"(?:\[(?P<chan>[^\]]+)\]\s*)?"  # optional [All] / [1. General] / …
            r"(?P<player>[^:]{2,48}?)\s*:\s*(?P<text>.+)$",
            re.IGNORECASE,
        )
        for line in lines:
            m = pattern.match(line)
            if not m:
                continue
            player = m.group("player").strip()
            text = m.group("text").strip()
            if len(player) < 2 or len(player) > 48:
                continue
            # Drop pure numeric "names" from bad OCR of timestamps
            if player.isdigit():
                continue
            chan_raw = (m.group("chan") or "all").lower()
            if "team" in chan_raw:
                channel = Channel.TEAM
            elif "whisper" in chan_raw:
                channel = Channel.WHISPER
            else:
                channel = Channel.ALL
            results.append((player, text, channel))
        return results

    def _fingerprint(self, player: str, text: str) -> str:
        return f"{player.lower()}|{text.lower()[:60]}"

    async def _poll_once(self) -> list[ChatMessage]:
        if not self.ocr_enabled:
            return []
        self._poll_count += 1
        img = self._capture_chat_region()
        if img is None:
            if self._poll_count % self._debug_every == 1:
                logger.warning("OCR capture returned no image — check chat_region coordinates")
            return []
        raw = self._ocr_image(img)
        if not raw:
            if self._poll_count % self._debug_every == 1:
                logger.warning(
                    "OCR returned empty text — wrong region, or Tesseract cannot read this UI"
                )
            return []

        if raw == self._last_ocr_text:
            return []
        self._last_ocr_text = raw

        parsed = self._parse_messages(raw)
        if not parsed and self._poll_count % self._debug_every == 1:
            sample = raw.replace("\n", " | ")[:180]
            logger.info("OCR text seen but no lines parsed. Sample: %s", sample)

        new_msgs = []
        for player, text, channel in parsed:
            fp = self._fingerprint(player, text)
            if fp in self._seen:
                continue
            self._seen.append(fp)
            msg = ChatMessage.from_parts(
                player=player,
                text=text,
                channel=channel,
                is_self=False,
                raw=raw,
            )
            if msg.player.lower() == self.self_name.lower():
                continue
            new_msgs.append(msg)
        return new_msgs

    async def listen(self) -> AsyncIterator[ChatMessage]:
        logger.info("SC2StubBackend listen() started (OCR=%s)", self.ocr_enabled)
        if not self.ocr_enabled:
            logger.warning("OCR reader is disabled. No messages will be yielded.")
        else:
            logger.info(
                "Polling screen every %.1fs. Waiting for chat lines… "
                "(status samples every ~%d polls if nothing parses)",
                self.poll_interval,
                self._debug_every,
            )

        while self._connected:
            try:
                msgs = await self._poll_once()
                for msg in msgs:
                    yield msg
            except Exception:
                logger.exception("Error in OCR poll")
            await asyncio.sleep(self.poll_interval)
