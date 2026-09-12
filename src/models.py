from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from .game_requests import GameRequestInfo, detect_game_request
from .names import short_display_name


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
    display_name: Optional[str] = None
    is_game_request: bool = False
    game_request_kind: str = ""
    chat_tab: str = ""
    chat_tab_index: int = 0

    def __str__(self) -> str:
        tag = " [game-req]" if self.is_game_request else ""
        tab = f" tab={self.chat_tab}" if self.chat_tab else ""
        # Always bare nickname — never timestamp/clan/channel chrome
        shown = self.display_name or self.player
        return f"[{self.timestamp:%H:%M:%S}] [{self.channel.value}{tab}] {shown}: {self.text}{tag}"

    @staticmethod
    def from_parts(
        player: str,
        text: str,
        channel: Channel,
        *,
        is_self: bool = False,
        raw: Optional[str] = None,
        timestamp: Optional[datetime] = None,
        chat_tab: str = "",
        chat_tab_index: int = 0,
    ) -> "ChatMessage":
        # BOTH fields are the cleaned bare name only
        clean = short_display_name(player) or short_display_name(player or "")
        if not clean:
            clean = re_fallback(player)
        info: GameRequestInfo = detect_game_request(text or "")
        return ChatMessage(
            player=clean,
            text=text,
            channel=channel,
            timestamp=timestamp or datetime.utcnow(),
            is_self=is_self,
            raw=raw,
            display_name=clean,
            is_game_request=info.is_request,
            game_request_kind=info.kind,
            chat_tab=chat_tab or "",
            chat_tab_index=int(chat_tab_index or 0),
        )


def re_fallback(player: str) -> str:
    import re

    s = (player or "").strip()
    s = re.sub(r"[\[\{\(<][^\]\}\)>]*[\]\}\)>]", " ", s)
    toks = re.findall(r"[A-Za-z][A-Za-z0-9_'\-]{1,23}", s)
    return toks[-1] if toks else (s[:24] if s else "unknown")
