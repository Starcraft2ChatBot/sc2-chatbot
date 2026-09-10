from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from .names import normalize_player_name
from .game_requests import detect_game_request, GameRequestInfo


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
    # Optional enrichment (filled by from_parts)
    display_name: Optional[str] = None          # original name including clan tag
    is_game_request: bool = False
    game_request_kind: str = ""

    def __str__(self) -> str:
        tag = " [game-req]" if self.is_game_request else ""
        shown = self.display_name or self.player
        return f"[{self.timestamp:%H:%M:%S}] [{self.channel.value}] {shown}: {self.text}{tag}"

    @staticmethod
    def from_parts(
        player: str,
        text: str,
        channel: Channel,
        *,
        is_self: bool = False,
        raw: Optional[str] = None,
        timestamp: Optional[datetime] = None,
    ) -> "ChatMessage":
        """Build a ChatMessage with clan-tag stripping and game-request detection."""
        display = (player or "").strip()
        normalized = normalize_player_name(display)
        info: GameRequestInfo = detect_game_request(text or "")
        return ChatMessage(
            player=normalized or display,
            text=text,
            channel=channel,
            timestamp=timestamp or datetime.utcnow(),
            is_self=is_self,
            raw=raw,
            display_name=display if display != normalized else None,
            is_game_request=info.is_request,
            game_request_kind=info.kind,
        )
