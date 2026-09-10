from __future__ import annotations
import asyncio
import random
import logging
from pathlib import Path

from .config_loader import Config
from .logger import setup_logger
from .chat.simulated import SimulatedChatBackend
from .chat.sc2_stub import SC2StubBackend
from .chat.base import ChatBackend
from .gemini_client import GeminiClient
from .triggers import TriggerEngine
from .memory import ConversationMemory
from .anti_spam import AntiSpam
from .commands import CommandHandler
from .decision_engine import DecisionEngine
from .models import ChatMessage, Channel
from .paths import resolve_path

logger = logging.getLogger("sc2_chatbot")


class SC2ChatBot:
    def __init__(self, config_path: str = "config/config.yaml"):
        self.config_path = str(config_path)
        self.config = Config.load(self.config_path)

        # Make log + memory paths absolute under the portable/app root when relative
        log_cfg = dict(self.config.logging or {})
        if log_cfg.get("file"):
            log_cfg["file"] = str(resolve_path(log_cfg["file"]))
        self.logger = setup_logger(log_cfg)

        self.personality_state = {
            "aggressiveness": self.config.personality.aggressiveness,
            "political_mode": self.config.personality.political_mode,
            "response_length": self.config.personality.response_length,
            "emoji_intensity": self.config.personality.emoji_intensity,
            "topics": dict(self.config.personality.topics),
        }

        self.gemini = GeminiClient(
            api_key=self.config.gemini.api_key,
            model=self.config.gemini.model,
            temperature=self.config.gemini.temperature,
            max_tokens=self.config.gemini.max_output_tokens,
        )
        self.triggers = TriggerEngine(self.config.triggers, self.config.canned_blocks)

        mem_cfg = dict(self.config.memory or {})
        persist = mem_cfg.get("persist_path")
        if persist:
            persist = str(resolve_path(persist))

        self.memory = ConversationMemory(
            max_per_player=int(mem_cfg.get("max_messages_per_player", 30)),
            persist_path=persist,
        )
        self.anti_spam = AntiSpam(self.config.anti_spam)

        self.commands = CommandHandler(
            self.config,
            on_reload=self.reload_config,
            anti_spam=self.anti_spam,
            personality_state=self.personality_state,
        )

        self.engine = DecisionEngine(
            self.gemini,
            self.triggers,
            self.memory,
            self.anti_spam,
            self.personality_state,
            self.config.behaviour,
        )

        self.backend: ChatBackend = self._create_backend()
        self._running = False

    def _create_backend(self) -> ChatBackend:
        if self.config.chat_backend == "sc2_stub":
            return SC2StubBackend(self.config.sc2_stub)
        return SimulatedChatBackend(self_name="ChatBot")

    def reload_config(self) -> None:
        """Reload YAML settings. Note: changing chat_backend requires a full restart."""
        old_backend = self.config.chat_backend
        self.config = Config.load(self.config_path)
        self.triggers = TriggerEngine(self.config.triggers, self.config.canned_blocks)

        self.personality_state["aggressiveness"] = self.config.personality.aggressiveness
        self.personality_state["political_mode"] = self.config.personality.political_mode
        self.personality_state["response_length"] = self.config.personality.response_length
        self.personality_state["emoji_intensity"] = self.config.personality.emoji_intensity
        self.personality_state["topics"] = dict(self.config.personality.topics)

        if self.config.chat_backend != old_backend:
            self.logger.warning(
                "chat_backend changed from '%s' to '%s'. "
                "A full restart is required for the new backend to take effect.",
                old_backend,
                self.config.chat_backend,
            )
        else:
            self.logger.info("Configuration reloaded")

    async def _human_delay(self) -> None:
        lo = self.config.behaviour.get("min_reply_delay_sec", 1.2)
        hi = self.config.behaviour.get("max_reply_delay_sec", 7.5)
        await asyncio.sleep(random.uniform(lo, hi))

    async def _process_message(self, msg: ChatMessage) -> None:
        self.logger.info("RECV %s", msg)

        cmd_reply = self.commands.handle(msg)
        if cmd_reply:
            await self._human_delay()
            await self.backend.send(cmd_reply, channel=msg.channel)
            self.logger.info("CMD  → %s", cmd_reply)
            return

        reply = self.engine.decide_and_generate(msg)
        if reply:
            await self._human_delay()
            await self.backend.send(
                reply,
                channel=msg.channel,
                target=msg.player if msg.channel == Channel.WHISPER else None,
            )
            self.logger.info("SEND → %s", reply)

    async def run(self) -> None:
        self._running = True
        self.logger.info("SC2 Chat Bot starting (backend=%s)", self.config.chat_backend)
        self.logger.warning(
            "REMINDER: Any automation that interacts with the live SC2 client "
            "may violate Blizzard Terms of Service and risk account bans."
        )

        while self._running:
            try:
                await self.backend.connect()
                async for msg in self.backend.listen():
                    if not self._running:
                        break
                    try:
                        await self._process_message(msg)
                    except Exception:
                        self.logger.exception("Error processing message")
            except Exception:
                self.logger.exception("Chat backend error – reconnecting in 5 s")
                await asyncio.sleep(5)
            finally:
                await self.backend.disconnect()

    def stop(self) -> None:
        self._running = False
