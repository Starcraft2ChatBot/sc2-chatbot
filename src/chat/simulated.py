from __future__ import annotations
import asyncio
from datetime import datetime
from typing import AsyncIterator, Optional, List
from ..models import ChatMessage, Channel
from .base import ChatBackend


class SimulatedChatBackend(ChatBackend):
    """Fully functional backend for development and demos."""

    def __init__(self, self_name: str = "ChatBot"):
        self.self_name = self_name
        self._queue: asyncio.Queue[ChatMessage] = asyncio.Queue()
        self._connected = False
        self._history: List[ChatMessage] = []

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def is_connected(self) -> bool:
        return self._connected

    async def listen(self) -> AsyncIterator[ChatMessage]:
        while self._connected:
            try:
                msg = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                self._history.append(msg)
                yield msg
            except asyncio.TimeoutError:
                continue

    async def send(self, text: str, channel: Channel = Channel.ALL, target: Optional[str] = None) -> None:
        msg = ChatMessage(
            player=self.self_name,
            text=text,
            channel=channel,
            is_self=True,
            timestamp=datetime.utcnow(),
        )
        print(f">>> BOT [{channel.value}] {text}")
        await self._queue.put(msg)

    def inject(self, player: str, text: str, channel: Channel = Channel.ALL) -> None:
        """Helper for tests / interactive demos."""
        msg = ChatMessage(player=player, text=text, channel=channel)
        self._queue.put_nowait(msg)
