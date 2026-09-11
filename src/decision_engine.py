from __future__ import annotations

import logging
import random
import re
from typing import Any, Optional, Set

from .anti_spam import AntiSpam
from .memory import ConversationMemory
from .models import Channel, ChatMessage
from .names import memory_key, short_display_name
from .personality import build_system_prompt
from .triggers import TriggerEngine

logger = logging.getLogger("sc2_chatbot.decision")

FALLBACKS = ["lol", "true", "idk", "gg", "nice", "bruh", "lmao"]

GAME_REQUEST_REPLIES = {
    "1v1": ["gl hf", "1v1? sure", "come on then", "bet"],
    "2v2": ["looking for 2v2 too", "I can fill", "gl"],
    "3v3": ["gl", "maybe later"],
    "4v4": ["gl", "big lobby"],
    "host": ["inv me", "send invite"],
    "lfg": ["what mode?", "1v1 or 2v2?"],
    "other": ["gl", "down", "sure"],
}


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
    ):
        self.llm = llm
        self.gemini = llm
        self.triggers = triggers
        self.memory = memory
        self.anti_spam = anti_spam
        self.state = personality_state
        self.behaviour = behaviour
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

        # Always prioritize messages that @ the bot / contain our name
        if self._mentions_bot(msg):
            return self.anti_spam.can_reply(msg)

        prob = float(self.behaviour.get("reply_probability", 0.85))
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

    def decide_and_generate(self, msg: ChatMessage) -> Optional[str]:
        if not self.should_consider(msg):
            return None

        label = short_display_name(msg.display_name or msg.player)

        canned = self.triggers.check(msg, self.state["aggressiveness"])
        if canned:
            reply = self._address_player(msg, canned)
            self.anti_spam.record_reply(msg.player)
            self._store_exchange(msg, reply)
            return reply

        if msg.is_game_request and self.behaviour.get("reply_to_game_requests", True):
            if self.behaviour.get("game_request_use_canned", False):
                pool = GAME_REQUEST_REPLIES.get(msg.game_request_kind) or GAME_REQUEST_REPLIES["other"]
                reply = self._address_player(msg, random.choice(pool))
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
        )

        extra = ""
        if self._mentions_bot(msg):
            extra += "\nThey mentioned you / your name — reply to them directly."
        if msg.is_game_request:
            extra += (
                f"\nThis looks like a game request (kind={msg.game_request_kind or 'other'})."
            )

        history_msgs = self.memory.get_context(msg.player)
        history = []
        for h in history_msgs[-10:]:
            role = "user" if not h.is_self else "model"
            history.append({"role": role, "parts": [h.text]})

        user_prompt = (
            f"Player '{label}' said:\n\"{msg.text}\"\n\n"
            f"Reply to THAT message only as a SC2 player.{extra}"
        )
        body = self.llm.generate(system, user_prompt, history)

        if not body:
            body = "what do you mean" if "?" in (msg.text or "") else random.choice(FALLBACKS)

        if random.random() < self.behaviour.get("typo_chance", 0.05):
            body = self._introduce_typo(body)

        body = body.strip().strip('"').strip("'")
        reply = self._address_player(msg, body)
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
