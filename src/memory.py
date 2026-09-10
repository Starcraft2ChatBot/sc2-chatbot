from __future__ import annotations
import json
import logging
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path
from typing import Deque, Dict, List, Optional

from ..models import ChatMessage, Channel
from .names import memory_key

logger = logging.getLogger("sc2_chatbot.memory")


class ConversationMemory:
    """Per-player rolling conversation memory with optional disk persistence."""

    def __init__(
        self,
        max_per_player: int = 30,
        persist_path: Optional[str | Path] = None,
    ):
        self.max = max(1, max_per_player)
        self.persist_path = Path(persist_path) if persist_path else None
        self._store: Dict[str, Deque[ChatMessage]] = defaultdict(
            lambda: deque(maxlen=self.max)
        )
        if self.persist_path:
            self._load()

    def add(self, msg: ChatMessage) -> None:
        key = memory_key(msg.player)
        self._store[key].append(msg)
        if self.persist_path:
            self._save_player(key)

    def get_context(self, player: str) -> List[ChatMessage]:
        return list(self._store[memory_key(player)])

    def clear_player(self, player: str) -> None:
        key = memory_key(player)
        self._store.pop(key, None)
        if self.persist_path and self.persist_path.exists():
            self._save_all()

    def known_players(self) -> List[str]:
        return sorted(self._store.keys())

    # ------------------------------------------------------------------
    # Persistence (optional)
    # ------------------------------------------------------------------
    def _load(self) -> None:
        if not self.persist_path or not self.persist_path.exists():
            return
        try:
            data = json.loads(self.persist_path.read_text(encoding="utf-8"))
            for key, items in data.items():
                dq: Deque[ChatMessage] = deque(maxlen=self.max)
                for it in items[-self.max:]:
                    try:
                        dq.append(
                            ChatMessage(
                                player=it["player"],
                                text=it["text"],
                                channel=Channel(it.get("channel", "all")),
                                timestamp=datetime.fromisoformat(it["timestamp"]),
                                is_self=bool(it.get("is_self", False)),
                                is_game_request=bool(it.get("is_game_request", False)),
                                game_request_kind=it.get("game_request_kind", ""),
                                display_name=it.get("display_name"),
                            )
                        )
                    except Exception:
                        continue
                if dq:
                    self._store[key] = dq
            logger.info("Loaded conversation memory for %d players from %s", len(self._store), self.persist_path)
        except Exception:
            logger.exception("Failed to load memory from %s", self.persist_path)

    def _save_player(self, key: str) -> None:
        # Simple approach: rewrite the whole file (small data)
        self._save_all()

    def _save_all(self) -> None:
        if not self.persist_path:
            return
        try:
            self.persist_path.parent.mkdir(parents=True, exist_ok=True)
            out = {}
            for key, dq in self._store.items():
                out[key] = [
                    {
                        "player": m.player,
                        "text": m.text,
                        "channel": m.channel.value,
                        "timestamp": m.timestamp.isoformat(),
                        "is_self": m.is_self,
                        "is_game_request": m.is_game_request,
                        "game_request_kind": m.game_request_kind,
                        "display_name": m.display_name,
                    }
                    for m in dq
                ]
            self.persist_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            logger.exception("Failed to save memory to %s", self.persist_path)
