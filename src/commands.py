from __future__ import annotations
import logging
from typing import Callable, Optional

from .models import ChatMessage
from .config_loader import Config
from .names import memory_key, normalize_player_name

logger = logging.getLogger("sc2_chatbot.commands")

# Modes accepted by !prop (political + non-political troll modes)
ALLOWED_MODES = {
    "neutral",
    "left",
    "right",
    "propaganda_left",
    "propaganda_right",
    "troll",
    "ragebait",
}


class CommandHandler:
    def __init__(self, config: Config, on_reload: Callable, anti_spam, personality_state: dict):
        self.config = config
        self.on_reload = on_reload
        self.anti_spam = anti_spam
        self.state = personality_state
        self.prefix = str(config.owner.get("command_prefix", "!") or "!")
        self.owners: set[str] = set()
        self.reload_owners(config)

    def reload_owners(self, config: Config) -> None:
        """Refresh owner name keys from config (owner.names + sc2_stub.self_name)."""
        self.config = config
        self.prefix = str(config.owner.get("command_prefix", "!") or "!")
        owners = {memory_key(n) for n in (config.owner.get("names") or []) if n}
        stub_self = (config.sc2_stub or {}).get("self_name")
        if stub_self:
            owners.add(memory_key(stub_self))
        self.owners = {o for o in owners if o}
        logger.debug("Command owners loaded: %s", sorted(self.owners))

    def is_owner(self, player: str) -> bool:
        return memory_key(player) in self.owners

    def handle(self, msg: ChatMessage) -> Optional[str]:
        if not self.is_owner(msg.player):
            return None
        text = (msg.text or "").strip()
        if not text.startswith(self.prefix):
            return None
        parts = text[len(self.prefix) :].split(maxsplit=1)
        if not parts or not parts[0]:
            return None
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        logger.info("Owner command from %s: %s %s", msg.player, cmd, arg)

        if cmd in ("tone", "aggro"):
            try:
                val = int(arg)
                if 1 <= val <= 10:
                    self.state["aggressiveness"] = val
                    return f"Aggressiveness set to {val}"
            except ValueError:
                pass
            return f"Usage: {self.prefix}tone 1-10"

        if cmd in ("prop", "political", "mode"):
            mode = arg.lower().strip()
            if mode in ALLOWED_MODES:
                self.state["political_mode"] = mode
                return f"Mode → {mode}"
            return f"Usage: {self.prefix}prop {'|'.join(sorted(ALLOWED_MODES))}"

        if cmd == "mute":
            if arg:
                self.anti_spam.mute_player(arg)
                return f"Muted {normalize_player_name(arg) or arg}"
            return f"Usage: {self.prefix}mute PlayerName"

        if cmd == "unmute":
            if arg:
                self.anti_spam.unmute_player(arg)
                return f"Unmuted {normalize_player_name(arg) or arg}"
            return f"Usage: {self.prefix}unmute PlayerName"

        if cmd == "reload":
            self.on_reload()
            return "Config reloaded"

        if cmd == "status":
            return (
                f"Aggro={self.state['aggressiveness']} "
                f"Mode={self.state['political_mode']} "
                f"Muted={len(self.anti_spam.mute)}"
            )

        if cmd == "length":
            if arg in ("short", "medium", "long"):
                self.state["response_length"] = arg
                return f"Length → {arg}"
            return f"Usage: {self.prefix}length short|medium|long"

        return None
