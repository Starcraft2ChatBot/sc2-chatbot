from __future__ import annotations
import random
import logging
from typing import Optional
from datetime import datetime
from ..models import ChatMessage, Channel
from .gemini_client import GeminiClient
from .personality import build_system_prompt
from .triggers import TriggerEngine
from .memory import ConversationMemory
from .anti_spam import AntiSpam

logger = logging.getLogger("sc2_chatbot.decision")

FALLBACKS = ["lol", "true", "idk", "gg", "nice", "bruh", "skill issue", "lmao"]

# Short, natural replies when someone posts a game request
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
        gemini: GeminiClient,
        triggers: TriggerEngine,
        memory: ConversationMemory,
        anti_spam: AntiSpam,
        personality_state: dict,
        behaviour: dict,
    ):
        self.gemini = gemini
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
        if random.random() > self.behaviour.get("reply_probability", 0.75):
            return False
        return self.anti_spam.can_reply(msg)

    def decide_and_generate(self, msg: ChatMessage) -> Optional[str]:
        if not self.should_consider(msg):
            return None

        # 1. Triggers first
        canned = self.triggers.check(msg, self.state["aggressiveness"])
        if canned:
            self.anti_spam.record_reply(msg.player)
            self.memory.add(msg)
            return canned

        # 2. Game-request awareness (optional short reply or extra context for Gemini)
        if msg.is_game_request and self.behaviour.get("reply_to_game_requests", True):
            # Prefer a short natural line; still allow Gemini if desired
            if self.behaviour.get("game_request_use_canned", True):
                pool = GAME_REQUEST_REPLIES.get(msg.game_request_kind) or GAME_REQUEST_REPLIES["other"]
                reply = random.choice(pool)
                self.anti_spam.record_reply(msg.player)
                self.memory.add(msg)
                self.memory.add(
                    ChatMessage.from_parts(
                        player="BOT", text=reply, channel=msg.channel, is_self=True
                    )
                )
                return reply

        # 3. Gemini with conversation history
        system = build_system_prompt(
            aggressiveness=self.state["aggressiveness"],
            political_mode=self.state["political_mode"],
            response_length=self.state["response_length"],
            emoji_intensity=self.state["emoji_intensity"],
            topics=self.state.get("topics", {}),
            channel=msg.channel.value,
        )

        # Extra hint when it's a game request but we fell through to Gemini
        extra = ""
        if msg.is_game_request:
            extra = (
                f"\nNote: this message looks like a game/lobby request "
                f"(kind={msg.game_request_kind or 'other'}). "
                f"Reply briefly and naturally as a player."
            )

        history_msgs = self.memory.get_context(msg.player)
        history = []
        for h in history_msgs[-8:]:
            role = "user" if not h.is_self else "model"
            history.append({"role": role, "parts": [h.text]})

        label = msg.display_name or msg.player
        user_prompt = f"{label} ({msg.channel.value}): {msg.text}{extra}"
        reply = self.gemini.generate(system, user_prompt, history)

        if not reply:
            reply = random.choice(FALLBACKS)

        if random.random() < self.behaviour.get("typo_chance", 0.08):
            reply = self._introduce_typo(reply)

        self.anti_spam.record_reply(msg.player)
        self.memory.add(msg)
        self.memory.add(
            ChatMessage.from_parts(
                player="BOT", text=reply, channel=msg.channel, is_self=True
            )
        )
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
