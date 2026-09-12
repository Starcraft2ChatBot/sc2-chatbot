from __future__ import annotations

import asyncio
import logging
import random

from .anti_spam import AntiSpam
from .chat.base import ChatBackend
from .chat.sc2_stub import SC2StubBackend
from .chat.simulated import SimulatedChatBackend
from .commands import CommandHandler
from .config_loader import Config
from .decision_engine import DecisionEngine
from .diagnostics import run_startup_diagnostics
from .llm_client import LLMClient
from .logger import setup_logger
from .memory import ConversationMemory
from .models import Channel, ChatMessage
from .names import memory_key, short_display_name
from .paths import resolve_path
from .triggers import TriggerEngine

logger = logging.getLogger("sc2_chatbot")


class SC2ChatBot:
    def __init__(self, config_path: str = "config/config.yaml"):
        self.config_path = str(config_path)
        self.config = Config.load(self.config_path)

        log_cfg = dict(self.config.logging or {})
        if log_cfg.get("file"):
            log_cfg["file"] = str(resolve_path(log_cfg["file"]))
        self.logger = setup_logger(log_cfg)

        try:
            run_startup_diagnostics(self.config)
        except Exception:
            self.logger.exception("Diagnostics failed (continuing startup)")

        p = self.config.personality
        self.personality_state = {
            "aggressiveness": p.aggressiveness,
            "political_mode": p.political_mode,
            "response_length": p.response_length,
            "emoji_intensity": p.emoji_intensity,
            "sc2_reference_level": getattr(p, "sc2_reference_level", 2),
            "topics": dict(p.topics),
        }

        owner_names = list(self.config.owner.get("names") or [])
        stub_self = (self.config.sc2_stub or {}).get("self_name")
        if stub_self:
            owner_names.append(stub_self)
        self.self_names = {short_display_name(n) for n in owner_names if n}
        self.self_names.discard("")

        llm_cfg = self.config.resolved_llm()
        self.llm = LLMClient(
            provider=llm_cfg.provider,
            api_key=llm_cfg.api_key,
            model=llm_cfg.model,
            temperature=llm_cfg.temperature,
            max_tokens=llm_cfg.max_output_tokens,
            base_url=llm_cfg.base_url,
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
            self.llm,
            self.triggers,
            self.memory,
            self.anti_spam,
            self.personality_state,
            self.config.behaviour,
            self_names=self.self_names,
        )

        self.backend: ChatBackend = self._create_backend()
        self._running = False

    def _create_backend(self) -> ChatBackend:
        if self.config.chat_backend == "sc2_stub":
            return SC2StubBackend(
                self.config.sc2_stub,
                self_name=next(iter(self.self_names), "ChatBot"),
                self_names=self.self_names,
            )
        return SimulatedChatBackend(self_name=next(iter(self.self_names), "ChatBot"))

    def reload_config(self) -> None:
        old_backend = self.config.chat_backend
        self.config = Config.load(self.config_path)
        self.triggers = TriggerEngine(self.config.triggers, self.config.canned_blocks)
        p = self.config.personality
        self.personality_state["aggressiveness"] = p.aggressiveness
        self.personality_state["political_mode"] = p.political_mode
        self.personality_state["response_length"] = p.response_length
        self.personality_state["emoji_intensity"] = p.emoji_intensity
        self.personality_state["sc2_reference_level"] = getattr(p, "sc2_reference_level", 2)
        self.personality_state["topics"] = dict(p.topics)
        if self.config.chat_backend != old_backend:
            self.logger.warning("chat_backend changed — full restart required")
        else:
            self.logger.info("Configuration reloaded")

    def _priority_for(self, msg: ChatMessage) -> int:
        text = (msg.text or "").lower()
        for name in self.self_names:
            if name and name.lower() in text:
                return 0
        if msg.channel == Channel.WHISPER:
            return 1
        return 5

    async def _human_delay(self, directed: bool = False) -> None:
        lo = float(self.config.behaviour.get("min_reply_delay_sec", 0.35))
        hi = float(self.config.behaviour.get("max_reply_delay_sec", 0.8))
        if directed:
            lo *= 0.6
            hi *= 0.7
        if hi < lo:
            hi = lo
        await asyncio.sleep(random.uniform(lo, hi))

    async def _process_message(self, msg: ChatMessage) -> None:
        if memory_key(msg.player) in {memory_key(n) for n in self.self_names}:
            self.logger.debug("Skip own message from %s", msg.player)
            return

        self.logger.info("RECV %s", msg)

        cmd_reply = self.commands.handle(msg)
        if cmd_reply:
            await self._human_delay(directed=True)
            await self._send(cmd_reply, msg)
            self.logger.info("CMD  → %s", cmd_reply)
            return

        reply = self.engine.decide_and_generate(msg)
        if reply:
            directed = self._priority_for(msg) == 0
            await self._human_delay(directed=directed)
            await self._send(reply, msg)
            self.logger.info("SEND → %s", reply)

    async def _send(self, text: str, msg: ChatMessage) -> None:
        kwargs = {
            "channel": msg.channel,
            "target": msg.player if msg.channel == Channel.WHISPER else None,
        }
        try:
            await self.backend.send(
                text,
                chat_tab_index=getattr(msg, "chat_tab_index", 0) or 0,
                chat_tab=getattr(msg, "chat_tab", "") or "",
                **kwargs,
            )
        except TypeError:
            await self.backend.send(text, **kwargs)

    async def run(self) -> None:
        self._running = True
        llm_cfg = self.config.resolved_llm()
        self.logger.info(
            "SC2 Chat Bot starting (backend=%s, llm=%s/%s, mode=%s, sc2_ref=%s, self=%s)",
            self.config.chat_backend,
            llm_cfg.provider,
            llm_cfg.model,
            self.personality_state.get("political_mode"),
            self.personality_state.get("sc2_reference_level"),
            sorted(self.self_names),
        )
        self.logger.warning(
            "REMINDER: Live SC2 automation may violate Blizzard Terms of Service."
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
