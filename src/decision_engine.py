from __future__ import annotations
import random
import logging
import re
from typing import Optional, Any

from .models import ChatMessage, Channel
from .personality import build_system_prompt
from .triggers import TriggerEngine
from .memory import ConversationMemory
from .anti_spam import AntiSpam

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
    ):
        self.llm = llm
        self.gemini = llm  # backwards alias
        self.triggers = triggers
        self.memory = memory
        self.anti_spam = anti_spam
        self.state = personality_state
        self.behaviour = behaviour

    def should_consider(self, msg: ChatMessage) -> bool:
        if msg.is_self and self.behaviour.get("ignore_self", True):
            return False
        if msg.channel == Channel.SYSTEM and self.behaviour.get("ignore_system", True):
            return False
        if random.random() > self.behaviour.get("reply_probability", 0.85):
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
        """Prefix reply with the player's name so chat reads: Name, message…"""
        if not self.behaviour.get("address_by_name", True):
            return body
        name = (msg.display_name or msg.player or "").strip()
        # Strip clan tags for a cleaner ping: [LG]Serral -> Serral
        name = re.sub(r"^[\[\{\<][^\]\}\>]+[\]\}\>]\s*", "", name).strip() or msg.player
        body = (body or "").strip()
        if not body:
            return name
        # Avoid "Name, Name is ..." if model already started with the name
        if re.match(re.escape(name) + r"\b", body, flags=re.IGNORECASE):
            return body
        sep = self.behaviour.get("name_separator", ", ")
        return f"{name}{sep}{body}"

    def decide_and_generate(self, msg: ChatMessage) -> Optional[str]:
        if not self.should_consider(msg):
            return None

        label = msg.display_name or msg.player

        # 1. Triggers
        canned = self.triggers.check(msg, self.state["aggressiveness"])
        if canned:
            reply = self._address_player(msg, canned)
            self.anti_spam.record_reply(msg.player)
            self._store_exchange(msg, reply)
            return reply

        # 2. Optional canned game-request replies
        if msg.is_game_request and self.behaviour.get("reply_to_game_requests", True):
            if self.behaviour.get("game_request_use_canned", False):
                pool = GAME_REQUEST_REPLIES.get(msg.game_request_kind) or GAME_REQUEST_REPLIES["other"]
                reply = self._address_player(msg, random.choice(pool))
                self.anti_spam.record_reply(msg.player)
                self._store_exchange(msg, reply)
                return reply

        # 3. LLM with per-player history — real conversation
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
        if msg.is_game_request:
            extra = (
                f"\nNote: this looks like a game/lobby request "
                f"(kind={msg.game_request_kind or 'other'}). Reply briefly as a player."
            )

        history_msgs = self.memory.get_context(msg.player)
        history = []
        for h in history_msgs[-10:]:
            role = "user" if not h.is_self else "model"
            history.append({"role": role, "parts": [h.text]})

        user_prompt = (
            f"Player '{label}' said in {msg.channel.value} chat:\n"
            f"\"{msg.text}\"\n\n"
            f"Write your in-character reply to THAT message only.{extra}"
        )
        body = self.llm.generate(system, user_prompt, history)

        if not body:
            # Prefer a minimal contextual fallback over pure random spam
            body = f"what do you mean" if "?" in (msg.text or "") else random.choice(FALLBACKS)

        if random.random() < self.behaviour.get("typo_chance", 0.05):
            body = self._introduce_typo(body)

        # Strip accidental surrounding quotes from the model
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
