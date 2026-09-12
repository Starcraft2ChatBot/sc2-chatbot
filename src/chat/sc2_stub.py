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
from typing import AsyncIterator, Deque, Iterable, List, Optional, Set, Tuple

from ..models import Channel, ChatMessage
from ..names import clean_ocr_player_name, is_ui_channel_label, memory_key, short_display_name
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

_TAB_RE = re.compile(
    r"[\[\|]?\s*(\d{1,2})\s*[.\:,]?\s*"
    r"(General|Arcade|Co-?op(?:\s*Missions)?|All|Team|Whisper|Chat|PM)"
    r"[\]\|]?",
    re.IGNORECASE,
)

ParsedLine = Tuple[str, str, Channel, str, int, str]


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
        self.switch_channels = bool(self.cfg.get("switch_channels", False))
        self.assume_chat_opens_on_tab = int(self.cfg.get("assume_chat_opens_on_tab", 1))

        self.ocr_enabled = bool(self.cfg.get("ocr_enabled", False))
        self.poll_interval = max(0.25, float(self.cfg.get("poll_interval_sec", 0.45) or 0.45))
        self.chat_region = self.cfg.get("chat_region")
        self.tesseract_cmd = self.cfg.get("tesseract_cmd")
        self._debug_every = int(self.cfg.get("ocr_debug_every_n_polls", 15))
        self._poll_count = 0

        self._connected = False
        # Long-term dedup (exact + fuzzy) — never removed as a feature
        self._seen: Set[str] = set()
        self._seen_order: Deque[str] = deque(maxlen=1000)
        self._prev_frame_fps: Set[str] = set()
        self._recent_sends: Deque[str] = deque(maxlen=40)
        self._history_seeded = False
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
            if s and (t == s or (len(t) > 12 and (t in s or s in t))):
                return True
        return False

    def _remember_fp(self, fp: str) -> None:
        if not fp or fp in self._seen:
            return
        self._seen.add(fp)
        self._seen_order.append(fp)
        while len(self._seen) > 1000 and self._seen_order:
            old = self._seen_order.popleft()
            self._seen.discard(old)

    def _norm_text(self, text: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", (text or "").lower())

    def _already_seen(self, player: str, text: str, fp: str) -> bool:
        """Exact fingerprint or fuzzy match (OCR noise on the same line)."""
        if fp in self._seen:
            return True
        p = memory_key(player)
        t = self._norm_text(text)
        if len(t) < 4:
            return fp in self._seen
        prefix = p + "|"
        for old in self._seen:
            if not old.startswith(prefix):
                continue
            ot = old[len(prefix) :]
            if not ot:
                continue
            if t == ot:
                return True
            # Same line with OCR glitch / partial read
            if len(t) >= 10 and len(ot) >= 10 and (t in ot or ot in t):
                return True
            if len(t) >= 12 and len(ot) >= 12 and t[:12] == ot[:12]:
                return True
        return False

    async def connect(self) -> None:
        self._connected = True
        logger.info(
            "SC2StubBackend connected (OCR=%s, poll=%.2fs, switch_channels=%s)",
            self.ocr_enabled,
            self.poll_interval,
            self.switch_channels,
        )

    async def disconnect(self) -> None:
        self._connected = False

    async def is_connected(self) -> bool:
        return self._connected

    def _find_sc2_window(self):
        if not HAS_PYAUTOGUI:
            return None
        try:
            for w in gw.getWindowsWithTitle(self.window_title_substring):
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
            time.sleep(0.2)
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
            time.sleep(0.04)
            pyautogui.hotkey("ctrl", "v")
            time.sleep(0.08)
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

    def _switch_to_tab_absolute(self, target_index: int) -> None:
        if not self.switch_channels:
            return
        if not target_index or target_index < 1 or target_index > self.max_chat_tabs:
            return
        origin = max(1, self.assume_chat_opens_on_tab)
        steps = target_index - origin
        if steps < 0:
            steps = target_index
        if steps == 0:
            return
        logger.info(
            "Chat switch: assume open on tab %s → target %s (%s x %s)",
            origin,
            target_index,
            self.channel_switch_key,
            steps,
        )
        for _ in range(steps):
            pyautogui.press(self.channel_switch_key)
            time.sleep(0.1)

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

            await asyncio.sleep(random.uniform(0.08, 0.18))
            pyautogui.press(self.chat_key)
            await asyncio.sleep(random.uniform(0.22, 0.35))

            idx = chat_tab_index
            if not idx and chat_tab:
                m = re.search(r"(\d{1,2})", chat_tab)
                if m:
                    idx = int(m.group(1))
            if idx and 1 <= idx <= self.max_chat_tabs:
                self._switch_to_tab_absolute(idx)
                await asyncio.sleep(0.1)

            if self.input_method == "paste" and HAS_PYPERCLIP:
                self._paste_text(text)
            else:
                self._type_text(text)

            await asyncio.sleep(random.uniform(0.12, 0.2))
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
        matches = list(_TAB_RE.finditer(head or ""))
        if not matches:
            return "", 0
        m = matches[-1]
        try:
            idx = int(m.group(1))
        except ValueError:
            return "", 0
        if idx < 1 or idx > self.max_chat_tabs:
            return "", 0
        return f"{idx}. {m.group(2).strip()}", idx

    def _fingerprint(self, player: str, text: str) -> str:
        p = memory_key(player)
        t = self._norm_text(text)[:70]
        return f"{p}|{t}"

    def _parse_messages(self, raw: str) -> List[ParsedLine]:
        """Parse OCR text into messages, joining multi-line chat continuations.

        SC2 chat shows long messages as:
          [1. General] PlayerName: first line of text
          second line of text
          third line...
        until the next [n. Channel] Name: header appears.

        The previous implementation only kept the header line and discarded
        every continuation, so the AI only ever saw the first line.
        """
        results: List[ParsedLine] = []
        lines = [l.strip() for l in raw.splitlines() if l.strip()]
        # Allow empty text after the colon (header-only line + continuations below).
        pattern = re.compile(r"^(?P<head>.*?)\s*:\s*(?P<text>.*)$")

        current: Optional[List] = None  # [player, text, channel, tab, tab_idx]

        def flush() -> None:
            nonlocal current
            if current is None:
                return
            player_c, text_c, channel_c, tab_c, tab_idx_c = current
            text_c = (text_c or "").strip()
            if text_c and not is_ui_channel_label(text_c):
                fp = self._fingerprint(player_c, text_c)
                results.append((player_c, text_c, channel_c, tab_c, tab_idx_c, fp))
            current = None

        for line in lines:
            if is_ui_channel_label(line):
                continue
            m = pattern.match(line)
            if m:
                head = m.group("head").strip()
                text = m.group("text").strip()
                player = clean_ocr_player_name(head)
                if player:
                    # Valid new message header → close previous message and start new one
                    flush()
                    tab, tab_idx = self._extract_tab(head)
                    head_l = head.lower()
                    if "team" in head_l:
                        channel = Channel.TEAM
                    elif "whisper" in head_l or re.search(r"\bpm\b", head_l):
                        channel = Channel.WHISPER
                    else:
                        channel = Channel.ALL
                    current = [player, text, channel, tab, tab_idx]
                    continue
                # Matched "something: text" but clean_ocr_player_name found no
                # valid player → treat the whole line as a continuation.
            # Continuation line (no header match, or invalid header)
            if current is not None:
                if current[1]:
                    current[1] = f"{current[1]} {line}".strip()
                else:
                    current[1] = line

        flush()
        return results

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

        parsed = self._parse_messages(raw)
        if not parsed:
            if self._poll_count % self._debug_every == 1:
                sample = raw.replace("\n", " | ")[:200]
                logger.info("OCR text but no parse. Sample: %s", sample)
            return []

        curr_fps = {fp for *_, fp in parsed}

        # --- Keep history seed (NOT removed) ---
        # First successful OCR: remember everything on screen, emit nothing.
        if not self._history_seeded:
            for *_, fp in parsed:
                self._remember_fp(fp)
            self._prev_frame_fps = set(curr_fps)
            self._history_seeded = True
            logger.info(
                "Seeded %d existing chat lines (dedup active). "
                "Only messages that appear AFTER this will be RECV/logged.",
                len(parsed),
            )
            return []

        # Lines not present on the previous frame (helps spot truly new text)
        appeared = curr_fps - self._prev_frame_fps
        self._prev_frame_fps = set(curr_fps)

        new_msgs: list[ChatMessage] = []
        for player, text, channel, tab, tab_idx, fp in reversed(parsed):
            # Primary anti-repeat: long-term seen (exact + fuzzy)
            if self._already_seen(player, text, fp):
                self._remember_fp(fp)
                continue
            # Prefer lines that are new vs last frame (OCR flicker still blocked by _already_seen)
            if appeared and fp not in appeared:
                self._remember_fp(fp)
                continue
            if self._is_self(player) or self._is_echo_of_own_send(text):
                self._remember_fp(fp)
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

        # Always mark every currently visible line as seen so OCR noise
        # cannot re-fire the same chat later under a slightly different string.
        for *_, fp in parsed:
            self._remember_fp(fp)

        new_msgs.reverse()
        return new_msgs

    async def listen(self) -> AsyncIterator[ChatMessage]:
        logger.info(
            "SC2StubBackend listen() OCR=%s poll=%.2fs switch_channels=%s",
            self.ocr_enabled,
            self.poll_interval,
            self.switch_channels,
        )
        if not self.ocr_enabled:
            logger.warning("OCR disabled — no messages will be yielded.")

        while self._connected:
            try:
                for msg in await self._poll_once():
                    yield msg
            except Exception:
                logger.exception("Error in OCR poll")
            await asyncio.sleep(self.poll_interval)
