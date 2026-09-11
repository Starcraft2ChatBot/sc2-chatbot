"""
SC2 Stub Backend — OCR + keyboard (ToS risk).
"""
from __future__ import annotations

import asyncio
import logging
import random
import re
import time
from collections import deque
from typing import AsyncIterator, Deque, Iterable, Optional, Set, Tuple

from ..models import Channel, ChatMessage
from ..names import clean_ocr_player_name, memory_key, short_display_name
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

# [1. General] or [2. Arcade] or 1. General]
_TAB_RE = re.compile(
    r"[\[\|]?\s*(\d+)\s*[\.,]?\s*([A-Za-z][^\]\|]*)[\]\|]?",
    re.IGNORECASE,
)


class SC2StubBackend(ChatBackend):
    def __init__(
        self,
        cfg: dict,
        self_name: str = "ChatBot",
        self_names: Optional[Iterable[str]] = None,
    ):
        self.cfg = cfg or {}
        self.self_name = self_name
        names = {self_name}
        if self_names:
            names.update(n for n in self_names if n)
        self._self_keys: Set[str] = {memory_key(n) for n in names if n}

        self.chat_key = self.cfg.get("chat_key", "enter")
        self.send_key = self.cfg.get("send_key", "enter")
        self.channel_switch_key = self.cfg.get("channel_switch_key", "tab")
        self.typing_cps = float(self.cfg.get("typing_speed_cps", 11))
        self.window_title_substring = self.cfg.get("window_title", "StarCraft II")
        self.input_method = str(self.cfg.get("input_method", "paste")).lower()
        self.max_chat_tabs = int(self.cfg.get("max_chat_tabs", 8))
        self.switch_channels = bool(self.cfg.get("switch_channels", True))

        self.ocr_enabled = bool(self.cfg.get("ocr_enabled", False))
        self.poll_interval = float(self.cfg.get("poll_interval_sec", 0.6))
        self.chat_region = self.cfg.get("chat_region")
        self.tesseract_cmd = self.cfg.get("tesseract_cmd")
        self._debug_every = int(self.cfg.get("ocr_debug_every_n_polls", 15))
        # Only treat the last N parsed lines as candidates for *new* messages
        self._new_line_window = int(self.cfg.get("new_message_line_window", 5))
        self._poll_count = 0

        self._connected = False
        self._seen: Set[str] = set()
        self._seen_order: Deque[str] = deque(maxlen=500)
        self._recent_sends: Deque[str] = deque(maxlen=40)
        self._last_ocr_text = ""
        self._history_seeded = False
        self._current_tab_index = 1  # assume General / first tab
        self._lock = asyncio.Lock()

        if self.tesseract_cmd and HAS_TESSERACT:
            pytesseract.pytesseract.tesseract_cmd = self.tesseract_cmd

        self._validate_capabilities()

    def _validate_capabilities(self) -> None:
        if not HAS_PYAUTOGUI:
            logger.warning("pyautogui / pygetwindow not installed – sending will fail")
        if self.input_method == "paste" and not HAS_PYPERCLIP:
            logger.warning("pyperclip not installed – falling back to typing")
            self.input_method = "type"
        if self.ocr_enabled:
            if not (HAS_MSS and HAS_TESSERACT):
                logger.warning("OCR enabled but mss or pytesseract missing.")
                self.ocr_enabled = False
            elif not self.chat_region:
                logger.warning("OCR enabled but chat_region not set.")
                self.ocr_enabled = False

    def _is_self(self, player: str) -> bool:
        return memory_key(player) in self._self_keys

    def _is_echo_of_own_send(self, text: str) -> bool:
        t = re.sub(r"[^a-z0-9]+", "", (text or "").lower())
        if len(t) < 8:
            return False
        for sent in self._recent_sends:
            s = re.sub(r"[^a-z0-9]+", "", (sent or "").lower())
            if not s:
                continue
            if t == s or (len(t) > 12 and (t in s or s in t)):
                return True
        return False

    def _remember_fp(self, fp: str) -> None:
        if fp in self._seen:
            return
        self._seen.add(fp)
        self._seen_order.append(fp)
        while len(self._seen) > 500 and self._seen_order:
            old = self._seen_order.popleft()
            self._seen.discard(old)

    async def connect(self) -> None:
        self._connected = True
        logger.info(
            "SC2StubBackend connected (OCR=%s, input=%s, switch_channels=%s, ignore=%s)",
            self.ocr_enabled,
            self.input_method,
            self.switch_channels,
            sorted(self._self_keys),
        )

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

    def _paste_text(self, text: str) -> None:
        old = None
        try:
            try:
                old = pyperclip.paste()
            except Exception:
                old = None
            pyperclip.copy(text)
            time.sleep(0.05)
            pyautogui.hotkey("ctrl", "v")
            time.sleep(0.1)
        finally:
            if old is not None:
                try:
                    pyperclip.copy(old)
                except Exception:
                    pass

    def _type_text(self, text: str) -> None:
        safe = text.replace("\r", " ").replace("\n", " ")
        delay = 1.0 / max(self.typing_cps, 1.0)
        for char in safe:
            if char == "\t":
                continue
            pyautogui.write(char, interval=0)
            time.sleep(delay * random.uniform(0.7, 1.2))

    def _switch_to_tab(self, target_index: int) -> None:
        """Cycle chat tabs with Tab until target index (best-effort)."""
        if not target_index or target_index < 1:
            return
        if target_index == self._current_tab_index:
            return
        if not self.switch_channels:
            return

        # Unknown current tab: Tab forward up to max_chat_tabs to land on target
        # SC2 cycles tabs with Tab while chat is focused.
        steps = (target_index - self._current_tab_index) % max(self.max_chat_tabs, 2)
        if steps == 0:
            steps = 0
        logger.info(
            "Switching chat tab %s → %s (%s x %s)",
            self._current_tab_index,
            target_index,
            self.channel_switch_key,
            steps,
        )
        for _ in range(steps):
            pyautogui.press(self.channel_switch_key)
            time.sleep(0.12)
        self._current_tab_index = target_index

    async def send(
        self,
        text: str,
        channel: Channel = Channel.ALL,
        target: Optional[str] = None,
        chat_tab_index: int = 0,
        chat_tab: str = "",
    ) -> None:
        if not HAS_PYAUTOGUI:
            logger.error("Cannot send – pyautogui not available")
            return

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

            await asyncio.sleep(random.uniform(0.12, 0.25))

            # Open chat input first, then switch channel with Tab if needed
            pyautogui.press(self.chat_key)
            await asyncio.sleep(random.uniform(0.3, 0.45))

            if chat_tab_index and chat_tab_index != self._current_tab_index:
                self._switch_to_tab(chat_tab_index)
                await asyncio.sleep(0.15)
            elif chat_tab:
                m = re.search(r"(\d+)", chat_tab)
                if m:
                    idx = int(m.group(1))
                    if idx != self._current_tab_index:
                        self._switch_to_tab(idx)
                        await asyncio.sleep(0.15)

            if self.input_method == "paste" and HAS_PYPERCLIP:
                self._paste_text(text)
            else:
                self._type_text(text)

            await asyncio.sleep(random.uniform(0.18, 0.28))
            pyautogui.press(self.send_key)
            self._recent_sends.append(text)
            logger.info(
                "Sent to %s%s: %s",
                channel.value,
                f"/{chat_tab}" if chat_tab else "",
                text[:100],
            )

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
            return pytesseract.image_to_string(img, lang="eng", config="--psm 6 --oem 3").strip()
        except Exception as e:
            logger.warning("OCR failed: %s", e)
            return ""

    def _extract_tab(self, head: str) -> Tuple[str, int]:
        m = _TAB_RE.search(head or "")
        if not m:
            return "", 0
        try:
            idx = int(m.group(1))
        except ValueError:
            idx = 0
        label = f"{m.group(1)}. {m.group(2).strip()}"
        return label, idx

    def _parse_messages(
        self, raw: str
    ) -> list[Tuple[str, str, Channel, str, int]]:
        """(player, text, channel, chat_tab, chat_tab_index)"""
        results = []
        lines = [l.strip() for l in raw.splitlines() if l.strip()]
        pattern = re.compile(r"^(?P<head>.*?)\s*:\s*(?P<text>.+)$")

        for line in lines:
            m = pattern.match(line)
            if not m:
                continue
            head = m.group("head").strip()
            text = m.group("text").strip()
            if not text:
                continue

            player = clean_ocr_player_name(head)
            if not player or len(player) < 2 or len(player) > 32 or player.isdigit():
                continue

            tab, tab_idx = self._extract_tab(head)
            head_l = head.lower()
            if "team" in head_l:
                channel = Channel.TEAM
            elif "whisper" in head_l:
                channel = Channel.WHISPER
            else:
                channel = Channel.ALL

            results.append((player, text, channel, tab, tab_idx))
        return results

    def _fingerprint(self, player: str, text: str) -> str:
        # Normalize so OCR noise on old lines does not re-fire
        p = memory_key(player)
        t = re.sub(r"[^a-z0-9]+", "", (text or "").lower())[:70]
        return f"{p}|{t}"

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
                logger.warning("OCR returned empty text")
            return []
        if raw == self._last_ocr_text:
            return []
        self._last_ocr_text = raw

        parsed = self._parse_messages(raw)
        if not parsed:
            if self._poll_count % self._debug_every == 1:
                sample = raw.replace("\n", " | ")[:180]
                logger.info("OCR text but no parse. Sample: %s", sample)
            return []

        # First successful OCR: seed history so we do NOT dump old chat as new
        if not self._history_seeded:
            for player, text, channel, tab, tab_idx in parsed:
                self._remember_fp(self._fingerprint(player, text))
            self._history_seeded = True
            logger.info(
                "Seeded %d existing chat lines (will only report NEW messages after this)",
                len(parsed),
            )
            return []

        # Newest lines are at the bottom of the OCR block
        window = max(1, self._new_line_window)
        candidates = parsed[-window:]

        new_msgs: list[ChatMessage] = []
        for player, text, channel, tab, tab_idx in candidates:
            if self._is_self(player):
                continue
            if self._is_echo_of_own_send(text):
                continue
            fp = self._fingerprint(player, text)
            if fp in self._seen:
                continue
            self._remember_fp(fp)

            clean = short_display_name(player) or player
            msg = ChatMessage.from_parts(
                player=clean,
                text=text,
                channel=channel,
                is_self=False,
                raw=raw,
                chat_tab=tab,
                chat_tab_index=tab_idx,
            )
            object.__setattr__(msg, "display_name", clean)
            new_msgs.append(msg)

            # Track last seen tab from incoming traffic
            if tab_idx:
                # don't force current tab from OCR of other people's channels
                pass

        return new_msgs

    async def listen(self) -> AsyncIterator[ChatMessage]:
        logger.info(
            "SC2StubBackend listen() OCR=%s poll=%.2fs window=%d",
            self.ocr_enabled,
            self.poll_interval,
            self._new_line_window,
        )
        if not self.ocr_enabled:
            logger.warning("OCR disabled — no messages will be yielded.")

        while self._connected:
            try:
                msgs = await self._poll_once()
                for msg in msgs:
                    yield msg
            except Exception:
                logger.exception("Error in OCR poll")
            await asyncio.sleep(self.poll_interval)
