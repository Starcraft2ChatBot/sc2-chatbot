from __future__ import annotations
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from rich.logging import RichHandler
from rich.console import Console


def setup_logger(cfg: dict) -> logging.Logger:
    log_dir = Path(cfg.get("file", "logs/sc2_chatbot.log")).parent
    log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("sc2_chatbot")
    logger.setLevel(getattr(logging, cfg.get("level", "INFO").upper()))
    logger.handlers.clear()

    fmt = logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")

    if cfg.get("console", True):
        rh = RichHandler(console=Console(stderr=True), rich_tracebacks=True, show_path=False)
        rh.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(rh)

    fh = RotatingFileHandler(
        cfg.get("file", "logs/sc2_chatbot.log"),
        maxBytes=cfg.get("max_bytes", 10_485_760),
        backupCount=cfg.get("backup_count", 5),
        encoding="utf-8",
    )
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    return logger
