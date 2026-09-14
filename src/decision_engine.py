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
    if not text or not cfg:
        return text or ""

    out = text
    case_sensitive = bool(cfg.get("case_sensitive", False))
    flags = 0 if case_sensitive else re.IGNORECASE

    replacements = cfg.get("replacements") or {}
    if isinstance(replacements, dict):
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
        if re.fullmatch(r"[\w']+", word, flags=re.UNICODE):
            pattern = rf"\b{re.escape(word)}\b"
        else:
            pattern = re.escape(word)
        out = re.sub(pattern, "", out, flags=flags)

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

    def _address_name_chance(self) -> float:
        raw = self.behaviour.get("address_by_name_chance", 0.3)
        try:
            chance = float(raw)
        except (TypeError, ValueError):
            chance = 0.3
        return max(0.0, min(1.0, chance))

    def _address_player(self, msg: ChatMessage, body: str) -> str:
        if not self.behaviour.get("address_by_name", True):
            return body
        chance = self._address_name_chance()
        if chance <= 0.0 or random.random() > chance:
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

    def _finalize_reply(self, msg: ChatMessage, body: str) -> Optional[str]:
        body = apply_blacklist(body or "", self.blacklist)
        if not (body or "").strip():
            return None
        reply = self._address_player(msg, body)
        reply = apply_blacklist(reply, self.blacklist)
        if not (reply or "").strip():
            return None
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
            return f"\nWhen natural, lightly prefer vocabulary like: {sample}"
        return (
            f"\nPrefer using these favorite words/phrases often when they fit the reply "
            f"(do not force them awkwardly): {sample}"
        )

    def _is_echo(self, incoming_text: str, generated_text: str) -> bool:
        inc = (incoming_text or "").strip().lower()
        gen = (generated_text or "").strip().lower()
        if not inc or not gen:
            return False
        if gen == inc or inc in gen:
            return True
        inc_words = set(re.findall(r"\w+", inc))
        gen_words = set(re.findall(r"\w+", gen))
        if len(inc_words) >= 3 and len(gen_words) >= 3:
            overlap = inc_words.intersection(gen_words)
            if len(overlap) / float(len(inc_words)) > 0.8:
                return True
        return False

    def decide_and_generate(self, msg: ChatMessage) -> Optional[str]:
        if not self.should_consider(msg):
            return None

        label = short_display_name(msg.display_name or msg.player)

        canned = self.triggers.check(msg, self.state["aggressiveness"])
        if canned:
            reply = self._finalize_reply(msg, canned)
            if not reply:
                return None
            self.anti_spam.record_reply(msg.player)
            self._store_exchange(msg, reply)
            return reply

        if msg.is_game_request and self.behaviour.get("reply_to_game_requests", True):
            if self.behaviour.get("game_request_use_canned", False):
                pool = GAME_REQUEST_REPLIES.get(msg.game_request_kind) or GAME_REQUEST_REPLIES["other"]
                reply = self._finalize_reply(msg, random.choice(pool))
                if not reply:
                    return None
                self.anti_spam.record_reply(msg.player)
                self._store_exchange(msg, reply)
                return reply

        system = build_system_prompt(
            aggressiveness=self.state["aggressiveness"],
            political_mode=self.state.get("political_mode", "neutral"),
            response_length=self.state["response_length"],
            emoji_intensity=self.state.get("emoji_intensity", 0),
            topics=self.state.get("topics", {}),
            channel=msg.channel.value,
            player_name=label,
            sc2_reference_level=int(self.state.get("sc2_reference_level", 2)),
            custom_enabled=bool(self.state.get("custom_enabled", False)),
            custom_prompt=str(self.state.get("custom_prompt") or ""),
        )

        extra = ""
        if self._mentions_bot(msg):
            extra += "\nThey mentioned you — reply to them directly."
        if msg.is_game_request:
            extra += f"\nLooks like a lobby/game request ({msg.game_request_kind or 'other'})."

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

        with Status(
            "[cyan]AI generating reply…[/cyan]",
            console=Console(stderr=True),
            spinner="dots",
        ):
            body = self.llm.generate(system, user_prompt, history)

        if body and self._is_echo(msg.text, body):
            logger.warning("LLM echoed user prompt ('%s'). Requesting rewrite...", body)
            rewrite_prompt = (
                f"{user_prompt}\n\n"
                f"CRITICAL INSTRUCTION: Your previous response was '{body}', which repeated the user's prompt. "
                "Do NOT repeat, echo, or quote their words. Write a totally new, direct reaction response instead."
            )
            with Status(
                "[cyan]AI rewriting response…[/cyan]",
                console=Console(stderr=True),
                spinner="dots",
            ):
                body = self.llm.generate(system, rewrite_prompt, history)

            if body and self._is_echo(msg.text, body):
                logger.warning("Rewrite still echoed user prompt — dropping response.")
                return None

        if not (body or "").strip():
            logger.info("LLM returned empty — not sending a reply")
            return None

        if random.random() < self.behaviour.get("typo_chance", 0.0):
            body = self._introduce_typo(body)

        body = body.strip().strip('"').strip("'")
        body = re.sub(
            r"^\[?\d*\.?\s*(?:General|Arcade|Co-?op|All|Team|Whisper)\]?\s*",
            "",
            body,
            flags=re.I,
        ).strip()

        if not body:
            logger.info("Reply empty after cleanup — not sending")
            return None

        reply = self._finalize_reply(msg, body)
        if not reply:
            logger.info("Reply empty after blacklist — not sending")
            return None

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
