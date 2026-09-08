#!/usr/bin/env python3
"""StarCraft 2 Chat-Only Bot – entry point."""
from __future__ import annotations
import asyncio
import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.bot import SC2ChatBot


async def main() -> None:
    bot = SC2ChatBot("config/config.yaml")

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, bot.stop)
        except NotImplementedError:
            pass  # Windows

    await bot.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutting down…")
