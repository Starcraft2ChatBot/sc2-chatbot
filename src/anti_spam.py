from __future__ import annotations
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Set

from .models import ChatMessage
from .names import memory_key


class AntiSpam:
    def __init__(self, cfg: dict):
        self.global_cd = cfg.get("global_cooldown_sec", 8)
        self.player_cd = cfg.get("per_player_cooldown_sec", 25)
        self.max_per_min = cfg.get("max_replies_per_player_per_minute", 3)
        # Normalize mute list the same way as memory keys (clan tags stripped)
        self.mute: Set[str] = {memory_key(n) for n in cfg.get("mute_list", [])}
        self._last_global = 0.0
        self._last_player: Dict[str, float] = {}
        self._recent: Dict[str, Deque[float]] = defaultdict(lambda: deque(maxlen=20))

    def _key(self, player: str) -> str:
        return memory_key(player)

    def is_muted(self, player: str) -> bool:
        return self._key(player) in self.mute

    def mute_player(self, player: str) -> None:
        self.mute.add(self._key(player))

    def unmute_player(self, player: str) -> None:
        self.mute.discard(self._key(player))

    def can_reply(self, msg: ChatMessage) -> bool:
        if self.is_muted(msg.player):
            return False
        now = time.time()
        if now - self._last_global < self.global_cd:
            return False
        key = self._key(msg.player)
        last = self._last_player.get(key, 0)
        if now - last < self.player_cd:
            return False
        q = self._recent[key]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= self.max_per_min:
            return False
        return True

    def record_reply(self, player: str) -> None:
        now = time.time()
        key = self._key(player)
        self._last_global = now
        self._last_player[key] = now
        self._recent[key].append(now)
