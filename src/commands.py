from __future__ import annotations
import logging
from typing import Callable, Optional

from .models import ChatMessage
from .config_loader import Config
from .names import memory_key, normalize_player_name

logger = logging.getLogger("sc2_chatbot.commands")


class CommandHandler:
    def __init__(self, config: Config, on_reload: Callable, anti_spam, personality_state: dict):
        self.config = config
        self.on_reload = on_reload
        self.anti_spam = anti_spam
        self.state = personality_state
        self.prefix = config.owner.get("command_prefix", "!")
        # Owner names normalized the same way as chat names (clan tags stripped)
        self.owners = {memory_key(n) for n in config.owner.get("names", [])}

    def is_owner(self, player: str) -> bool:
        return memory_key(player) in self.owners

    def handle(self, msg: ChatMessage) -> Optional[str]:
        if not self.is_owner(msg.player):
            return None
        text = msg.text.strip()
        if not text.startswith(self.prefix):
            return None
        parts = text[len(self.prefix):].split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if cmd in ("tone", "aggro"):
            try:
                val = int(arg)
                if 1 <= val <= 10:
                    self.state["aggressiveness"] = val
                    return f"Aggressiveness set to {val}"
            except ValueError:
                pass
            return "Usage: !tone 1-10"

        if cmd in ("prop", "political"):
            allowed = {"neutral", "left", "right", "propaganda_left", "propaganda_right"}
            if arg.lower() in allowed:
                self.state["political_mode"] = arg.lower()
                return f"Political mode → {arg.lower()}"
            return f"Usage: !prop {'|'.join(allowed)}"

        if cmd == "mute":
            if arg:
                self.anti_spam.mute_player(arg)
                return f"Muted {normalize_player_name(arg) or arg}"
            return "Usage: !mute PlayerName"

        if cmd == "unmute":
            if arg:
                self.anti_spam.unmute_player(arg)
                return f"Unmuted {normalize_player_name(arg) or arg}"
            return "Usage: !unmute PlayerName"

        if cmd == "reload":
            self.on_reload()
            return "Config reloaded"

        if cmd == "status":
            return (
                f"Aggro={self.state['aggressiveness']} "
                f"Pol={self.state['political_mode']} "
                f"Muted={len(self.anti_spam.mute)}"
            )

        if cmd == "length":
            if arg in ("short", "medium", "long"):
                self.state["response_length"] = arg
                return f"Length → {arg}"
            return "Usage: !length short|medium|long"

        return None
