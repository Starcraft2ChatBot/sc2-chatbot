from __future__ import annotations
from collections import defaultdict, deque
from typing import Deque, Dict, List
from ..models import ChatMessage


class ConversationMemory:
    def __init__(self, max_per_player: int = 12):
        self.max = max_per_player
        self._store: Dict[str, Deque[ChatMessage]] = defaultdict(lambda: deque(maxlen=self.max))

    def add(self, msg: ChatMessage) -> None:
        self._store[msg.player.lower()].append(msg)

    def get_context(self, player: str) -> List[ChatMessage]:
        return list(self._store[player.lower()])

    def clear_player(self, player: str) -> None:
        self._store.pop(player.lower(), None)
