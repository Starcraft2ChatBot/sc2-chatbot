from __future__ import annotations

import logging
import random
import re
from typing import Any, Dict, List, Optional, Set

from rich.console import Console
from rich.status import Status

from .anti_spam import AntiSpam
from .memory import ConversationMemory
from .models import Channel, ChatMessage
from .names import memory_key, short_display_name
from .personality import build_system_prompt
from .triggers import TriggerEngine

logger = logging.getLogger("sc2_chatbot.decision")

FALLBACKS = ["lol", "true", "idk", "nice", "bruh", "lmao", "sure"]

GAME_REQUEST_REPLIES = {
    "1v1": ["gl hf", "1v1? sure", "bet"],
    "2v2": ["I can fill", "gl"],
    "3v3": ["gl", "maybe later"],
    "4v4": ["gl"],
    "host": ["inv me", "send invite"],
    "lfg": ["what mode?"],
    "other": ["gl", "sure"],
}


def apply_blacklist(text: str, cfg: Optional[Dict[str, Any]]) -> str:
    """Remove or replace blacklisted words, symbols, letters, and substrings.

    Config keys (all optional):
      case_sensitive: bool (default False for words)
      words: list[str] — whole-word matches removed
      symbols: list[str] — removed (or replaced if in replacements)
      letters: list[str] — single characters removed
      substrings: list[str] — any occurrence removed
      replacements: dict[str, str] — exact string → replacement (applied first)
    """
    if not text or not cfg:
        return text or ""

    out = text
    case_sensitive = bool(cfg.get("case_sensitive", False))
    flags = 0 if case_sensitive else re.IGNORECASE

    replacements = cfg.get("replacements") or {}
    if isinstance(replacements, dict):
        # Longer keys first so multi-char sequences win over single chars
        for src in sorted(replacements.keys(), key=lambda s: len(str(s)), reverse=True):
            dst = replacements[src]
            if src is None or src == "":
                continue
            if case_sensitive:
                out = out.replace(str(src), str(dst))
            else:
                out = re.sub(re.escape(str(src)), str(dst), out, flags=re.IGNORECASE)

    def _as_list(val: Any) -> List[str]:
        if not val:
            return []
        if isinstance(val, str):
            return [val]
        return [str(x) for x in val if x is not None and str(x) != ""]

    for sym in _as_list(cfg.get("symbols")):
        if case_sensitive:
            out = out.replace(sym, "")
        else:
            out = re.sub(re.escape(sym), "", out, flags=re.IGNORECASE)

    for letter in _as_list(cfg.get("letters")):
        if not letter:
            continue
        # Only strip single-character entries from letters list
        ch = letter[0]
        if case_sensitive:
            out = out.replace(ch, "")
        else:
            out = re.sub(re.escape(ch), "", out, flags=re.IGNORECASE)

    for sub in _as_list(cfg.get("substrings")):
        if case_sensitive:
            out = out.replace(sub, "")
        else:
            out = re.sub(re.escape(sub), "", out, flags=re.IGNORECASE)

    for word in _as_list(cfg.get("words")):
        # Whole-word style: word boundaries when the token is alphanumeric
        if re.fullmatch(r"[\w']+", word, flags=re.UNICODE):
            pattern = rf"\b{re.escape(word)}\b"
        else:
            pattern = re.escape(word)
        out = re.sub(pattern, "", out, flags=flags)

    # Collapse leftover whitespace / empty punctuation runs
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r" +([,.;:!?])", r"\1", out)
    return out.strip()


def _favorite_words(cfg: Optional[Dict[str, Any]]) -> List[str]:
    if not cfg:
        return []
    raw = cfg.get("words")
    if raw is None and isinstance(cfg, list):
        raw = cfg
    if isinstance(raw, str):
        return [raw] if raw.strip() else []
    if not isinstance(raw, list):
        return []
    return [str(w).strip() for w in raw if w is not None and str(w).strip()]


class DecisionEngine:
    def __init__(
        self,
        llm: Any,
        triggers: TriggerEngine,
        memory: ConversationMemory,
        anti_spam: AntiSpam,
        personality_state: dict,
        behaviour: dict,
        self_names: Optional[Set[str]] = None,
        blacklist: Optional[Dict[str, Any]] = None,
        favorites: Optional[Dict[str, Any]] = None,
    ):
        self.llm = llm
        self.gemini = llm
        self.triggers = triggers
        self.memory = memory
        self.anti_spam = anti_spam
        self.state = personality_state
        self.behaviour = behaviour
        self.blacklist = blacklist or {}
        self.favorites = favorites or {}
        self._self_keys = {memory_key(n) for n in (self_names or set()) if n}

    def _is_own_player(self, msg: ChatMessage) -> bool:
        if msg.is_self:
            return True
        return memory_key(msg.player) in self._self_keys

    def _mentions_bot(self, msg: ChatMessage) -> bool:
        text = (msg.text or "").lower()
        for key in self._self_keys:
            if key and key in text:
                return True
        return False

    def should_consider(self, msg: ChatMessage) -> bool:
        if self.behaviour.get("ignore_self", True) and self._is_own_player(msg):
            return False
        if msg.channel == Channel.SYSTEM and self.behaviour.get("ignore_system", True):
            return False
        if self._mentions_bot(msg):
            return self.anti_spam.can_reply(msg)
        prob = float(self.behaviour.get("reply_probability", 0.9))
        if random.random() > prob:
            return False
        return self.anti_spam.can_reply(msg)

    def _store_exchange(self, incoming: ChatMessage, reply: str) -> None:
        self.memory.add(incoming)
        self.memory.add(
            ChatMessage(
                player=incoming.player,
                text=reply,
                channel=incoming.channel,
                is_self=True,
                display_name=incoming.display_name,
            )
        )

    def _address_player(self, msg: ChatMessage, body: str) -> str:
        if not self.behaviour.get("address_by_name", True):
            return body
        name = short_display_name(msg.display_name or msg.player)
        body = (body or "").strip()
        if not name:
            return body
        if not body:
            return name
        if re.match(re.escape(name) + r"\b", body, flags=re.IGNORECASE):
            return body
        sep = self.behaviour.get("name_separator", ", ")
        return f"{name}{sep}{body}"

    def _finalize_reply(self, msg: ChatMessage, body: str) -> str:
        body = apply_blacklist(body or "", self.blacklist)
        if not (body or "").strip():
            body = random.choice(FALLBACKS)
        reply = self._address_player(msg, body)
        # Address prefix should not reintroduce banned symbols from the model body only;
        # still scrub once more in case separator/name path is odd.
        reply = apply_blacklist(reply, self.blacklist)
        if not (reply or "").strip():
            reply = random.choice(FALLBACKS)
        return reply.strip()

    def _favorites_prompt_hint(self) -> str:
        words = _favorite_words(self.favorites)
        if not words:
            return ""
        intensity = str((self.favorites or {}).get("intensity", "medium") or "medium").lower()
        sample = ", ".join(words[:40])
        if intensity in ("strong", "high", "force"):
            return (
                f"\nStrongly prefer using these favorite words/phrases when they fit naturally "
                f"(use at least one when possible): {sample}"
            )
        if intensity in ("soft", "low", "light"):
            return (
                f"\nWhen natural, lightly prefer vocabulary like: {sample}"
            )
        return (
            f"\nPrefer using these favorite words/phrases often when they fit the reply "
            f"(do not force them awkwardly): {sample}"
        )

    def decide_and_generate(self, msg: ChatMessage) -> Optional[str]:
        if not self.should_consider(msg):
            return None

        label = short_display_name(msg.display_name or msg.player)

        canned = self.triggers.check(msg, self.state["aggressiveness"])
        if canned:
            reply = self._finalize_reply(msg, canned)
            self.anti_spam.record_reply(msg.player)
            self._store_exchange(msg, reply)
            return reply

        if msg.is_game_request and self.behaviour.get("reply_to_game_requests", True):
            if self.behaviour.get("game_request_use_canned", False):
                pool = GAME_REQUEST_REPLIES.get(msg.game_request_kind) or GAME_REQUEST_REPLIES["other"]
                reply = self._finalize_reply(msg, random.choice(pool))
                self.anti_spam.record_reply(msg.player)
                self._store_exchange(msg, reply)
                return reply

        system = build_system_prompt(
            aggressiveness=self.state["aggressiveness"],
            political_mode=self.state["political_mode"],
            response_length=self.state["response_length"],
            emoji_intensity=self.state["emoji_intensity"],
            topics=self.state.get("topics", {}),
            channel=msg.channel.value,
            player_name=label,
            sc2_reference_level=int(self.state.get("sc2_reference_level", 2)),
        )

        extra = ""
        if self._mentions_bot(msg):
            extra += "\nThey mentioned you — reply to them directly."
        if msg.is_game_request:
            extra += f"\nLooks like a lobby/game request ({msg.game_request_kind or 'other'})."

        # Hint the model away from blacklisted symbols/words (filter still enforces).
        banned_hint_parts: List[str] = []
        for key in ("symbols", "words", "substrings"):
            items = self.blacklist.get(key) or []
            if isinstance(items, list) and items:
                sample = ", ".join(repr(x) for x in items[:12])
                banned_hint_parts.append(f"{key}: {sample}")
        if banned_hint_parts:
            extra += (
                "\nDo not use these banned characters/words in your reply: "
                + "; ".join(banned_hint_parts)
            )

        extra += self._favorites_prompt_hint()

        history = []
        for h in self.memory.get_context(msg.player)[-10:]:
            role = "user" if not h.is_self else "model"
            history.append({"role": role, "parts": [h.text]})

        user_prompt = (
            f"Player '{label}' said:\n\"{msg.text}\"\n\n"
            f"Write one in-character chat reply.{extra}"
        )

        # Show progress only while the actual LLM call is running (the slow part).
        # Canned / trigger replies above skip this entirely.
        with Status(
            "[cyan]AI generating reply…[/cyan]",
            console=Console(stderr=True),
            spinner="dots",
        ):
            body = self.llm.generate(system, user_prompt, history)

        if not body:
            body = "what do you mean" if "?" in (msg.text or "") else random.choice(FALLBACKS)

        if random.random() < self.behaviour.get("typo_chance", 0.0):
            body = self._introduce_typo(body)

        body = body.strip().strip('"').strip("'")
        # Strip accidental channel tags the model might echo
        body = re.sub(
            r"^\[?\d*\.?\s*(?:General|Arcade|Co-?op|All|Team|Whisper)\]?\s*",
            "",
            body,
            flags=re.I,
        ).strip()

        reply = self._finalize_reply(msg, body)
        self.anti_spam.record_reply(msg.player)
        self._store_exchange(msg, reply)
        return reply

    @staticmethod
    def _introduce_typo(text: str) -> str:
        if len(text) < 4:
            return text
        i = random.randint(1, len(text) - 2)
        chars = list(text)
        if random.random() < 0.5:
            chars[i], chars[i + 1] = chars[i + 1], chars[i]
        else:
            chars.pop(i)
        return "".join(chars)
