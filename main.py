#!/usr/bin/env python3
"""StarCraft 2 Chat-Only Bot – entry point (dev + portable exe)."""
from __future__ import annotations

import asyncio
import os
import signal
import sys
from pathlib import Path

# Dev mode: allow `python main.py` from repo root
if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).parent))

from src.paths import app_root, config_path
from src.bot import SC2ChatBot


def _prepare_cwd() -> Path:
    """Run with CWD = app root so relative log/config paths stay predictable."""
    root = app_root()
    os.chdir(root)
    return root


async def main() -> None:
    root = _prepare_cwd()
    cfg = config_path("config/config.yaml")
    print(f"[sc2-chatbot] app root: {root}")
    print(f"[sc2-chatbot] config:   {cfg}")

    bot = SC2ChatBot(str(cfg))

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
