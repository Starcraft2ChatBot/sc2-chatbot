from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class Channel(str, Enum):
    ALL = "all"
    TEAM = "team"
    WHISPER = "whisper"
    SYSTEM = "system"


@dataclass(frozen=True)
class ChatMessage:
    player: str
    text: str
    channel: Channel
    timestamp: datetime = field(default_factory=datetime.utcnow)
    is_self: bool = False
    raw: Optional[str] = None

    def __str__(self) -> str:
        return f"[{self.timestamp:%H:%M:%S}] [{self.channel.value}] {self.player}: {self.text}"
