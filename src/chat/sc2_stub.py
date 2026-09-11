"""
SC2 Stub Backend

WARNING: keyboard + OCR automation can violate Blizzard ToS.
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
HAS_PYPERCLIP = False

try:
    import pyautogui
    import pygetwindow as gw

    HAS_PYAUTOGUI = True
    pyautogui.FAILSAFE = True
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

try:
    import pyperclip

    HAS_PYPERCLIP = True
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
        # paste = whole message via clipboard (avoids Enter mid-sentence). type = per-char.
        self.input_method = str(self.cfg.get("input_method", "paste")).lower()

        self.ocr_enabled = bool(self.cfg.get("ocr_enabled", False))
        self.poll_interval = float(self.cfg.get("poll_interval_sec", 1.8))
        self.chat_region = self.cfg.get("chat_region")
        self.tesseract_cmd = self.cfg.get("tesseract_cmd")
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
        if self.input_method == "paste" and not HAS_PYPERCLIP:
            logger.warning("pyperclip not installed – falling back to slow typing")
            self.input_method = "type"
        if self.ocr_enabled:
            if not (HAS_MSS and HAS_TESSERACT):
                logger.warning("OCR enabled but mss or pytesseract missing.")
                self.ocr_enabled = False
            elif not self.chat_region:
                logger.warning("OCR enabled but chat_region not set.")
                self.ocr_enabled = False

    async def connect(self) -> None:
        self._connected = True
        logger.info(
            "SC2StubBackend connected (OCR=%s, input=%s)",
            self.ocr_enabled,
            self.input_method,
        )
        if self.ocr_enabled and self.chat_region:
            logger.info("OCR chat_region=%s poll=%.1fs", self.chat_region, self.poll_interval)

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
            time.sleep(0.3)
            return True
        except Exception as e:
            logger.warning("Could not focus SC2 window: %s", e)
            return False

    def _paste_text(self, text: str) -> None:
        """Paste the full message in one shot (no mid-message Enter)."""
        old = None
        try:
            try:
                old = pyperclip.paste()
            except Exception:
                old = None
            pyperclip.copy(text)
            time.sleep(0.05)
            pyautogui.hotkey("ctrl", "v")
            time.sleep(0.12)
        finally:
            if old is not None:
                try:
                    pyperclip.copy(old)
                except Exception:
                    pass

    def _type_text(self, text: str) -> None:
        """Fallback character typing — never sends Enter until caller does."""
        # Replace newlines so we cannot accidentally "send" mid-message
        safe = text.replace("\r", " ").replace("\n", " ")
        delay = 1.0 / max(self.typing_cps, 1.0)
        for char in safe:
            if char == "\t":
                continue
            pyautogui.write(char, interval=0)
            time.sleep(delay * random.uniform(0.7, 1.3))

    async def send(self, text: str, channel: Channel = Channel.ALL, target: Optional[str] = None) -> None:
        if not HAS_PYAUTOGUI:
            logger.error("Cannot send – pyautogui not available")
            return

        # Single-line only for SC2 chat
        text = (text or "").replace("\r", " ").replace("\n", " ").strip()
        if not text:
            return

        async with self._lock:
            window = self._find_sc2_window()
            if window is None:
                logger.error("StarCraft II window not found")
                return

            if not self._focus_window(window):
                return

            await asyncio.sleep(random.uniform(0.2, 0.4))

            # Open chat box (Enter). Wait long enough so SC2 does not treat the
            # next action as a second Enter / empty send.
            pyautogui.press(self.chat_key)
            await asyncio.sleep(random.uniform(0.35, 0.55))

            if self.input_method == "paste" and HAS_PYPERCLIP:
                self._paste_text(text)
            else:
                self._type_text(text)

            # Wait until the full message is in the box, THEN send once
            await asyncio.sleep(random.uniform(0.2, 0.35))
            pyautogui.press(self.send_key)
            logger.info("Sent to %s: %s", channel.value, text[:100])

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
        results = []
        lines = [l.strip() for l in raw.splitlines() if l.strip()]
        pattern = re.compile(
            r"^(?:\d{1,2}:\d{2}\s+)?"
            r"(?:\[(?P<chan>[^\]]+)\]\s*)?"
            r"(?P<player>[^:]{2,48}?)\s*:\s*(?P<text>.+)$",
            re.IGNORECASE,
        )
        for line in lines:
            m = pattern.match(line)
            if not m:
                continue
            player = m.group("player").strip()
            text = m.group("text").strip()
            if len(player) < 2 or len(player) > 48 or player.isdigit():
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
                logger.warning("OCR capture returned no image — check chat_region")
            return []
        raw = self._ocr_image(img)
        if not raw:
            if self._poll_count % self._debug_every == 1:
                logger.warning("OCR returned empty text — wrong region or Tesseract issue")
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
                player=player, text=text, channel=channel, is_self=False, raw=raw
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
            logger.info("Polling every %.1fs for chat lines…", self.poll_interval)

        while self._connected:
            try:
                msgs = await self._poll_once()
                for msg in msgs:
                    yield msg
            except Exception:
                logger.exception("Error in OCR poll")
            await asyncio.sleep(self.poll_interval)
