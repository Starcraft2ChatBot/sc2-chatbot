from __future__ import annotations
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Set
from ..models import ChatMessage


class AntiSpam:
    def __init__(self, cfg: dict):
        self.global_cd = cfg.get("global_cooldown_sec", 8)
        self.player_cd = cfg.get("per_player_cooldown_sec", 25)
        self.max_per_min = cfg.get("max_replies_per_player_per_minute", 3)
        self.mute: Set[str] = {n.lower() for n in cfg.get("mute_list", [])}
        self._last_global = 0.0
        self._last_player: Dict[str, float] = {}
        self._recent: Dict[str, Deque[float]] = defaultdict(lambda: deque(maxlen=20))

    def is_muted(self, player: str) -> bool:
        return player.lower() in self.mute

    def mute_player(self, player: str) -> None:
        self.mute.add(player.lower())

    def unmute_player(self, player: str) -> None:
        self.mute.discard(player.lower())

    def can_reply(self, msg: ChatMessage) -> bool:
        if self.is_muted(msg.player):
            return False
        now = time.time()
        if now - self._last_global < self.global_cd:
            return False
        last = self._last_player.get(msg.player.lower(), 0)
        if now - last < self.player_cd:
            return False
        q = self._recent[msg.player.lower()]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= self.max_per_min:
            return False
        return True

    def record_reply(self, player: str) -> None:
        now = time.time()
        self._last_global = now
        self._last_player[player.lower()] = now
        self._recent[player.lower()].append(now)
