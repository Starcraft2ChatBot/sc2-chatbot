from __future__ import annotations
import re
import time
from dataclasses import dataclass, field
from typing import List, Optional, Pattern
from ..models import ChatMessage


@dataclass
class Trigger:
    name: str
    patterns: List[Pattern]
    response: str
    priority: int = 50
    cooldown_sec: float = 10.0
    channels: Optional[List[str]] = None
    once_per_player: bool = False
    aggressiveness_min: int = 1
    last_fired: float = 0.0
    fired_for: set = field(default_factory=set)

    def matches(self, msg: ChatMessage, aggressiveness: int) -> bool:
        if aggressiveness < self.aggressiveness_min:
            return False
        if self.channels and msg.channel.value not in self.channels:
            return False
        now = time.time()
        if now - self.last_fired < self.cooldown_sec:
            return False
        if self.once_per_player and msg.player in self.fired_for:
            return False
        for p in self.patterns:
            if p.search(msg.text):
                return True
        return False

    def fire(self, player: str) -> str:
        self.last_fired = time.time()
        self.fired_for.add(player)
        return self.response


class TriggerEngine:
    def __init__(self, raw_triggers: list, canned: list):
        self.triggers: List[Trigger] = []
        for t in raw_triggers:
            pats = [re.compile(p, re.IGNORECASE) for p in t.get("patterns", [])]
            self.triggers.append(
                Trigger(
                    name=t["name"],
                    patterns=pats,
                    response=t["response"],
                    priority=t.get("priority", 50),
                    cooldown_sec=t.get("cooldown_sec", 10),
                    channels=t.get("channels"),
                    once_per_player=t.get("once_per_player", False),
                    aggressiveness_min=t.get("aggressiveness_min", 1),
                )
            )
        for c in canned:
            pats = [re.compile(p, re.IGNORECASE) for p in c.get("triggers", [])]
            self.triggers.append(
                Trigger(
                    name=c.get("id", "canned"),
                    patterns=pats,
                    response=c["text"].strip(),
                    priority=c.get("priority", 40),
                )
            )
        self.triggers.sort(key=lambda x: -x.priority)

    def check(self, msg: ChatMessage, aggressiveness: int) -> Optional[str]:
        for t in self.triggers:
            if t.matches(msg, aggressiveness):
                return t.fire(msg.player)
        return None
