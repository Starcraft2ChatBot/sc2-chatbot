"""Resolve project paths for normal runs and frozen (PyInstaller) portable builds."""
from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_root() -> Path:
    """Directory that contains config/, logs/, and the executable (or main.py)."""
    if is_frozen():
        # PyInstaller onefile/onedir: executable lives next to the portable folder files
        return Path(sys.executable).resolve().parent
    # Development: repository root (parent of src/)
    return Path(__file__).resolve().parent.parent


def resolve_path(path: str | Path | None, *, base: Path | None = None) -> Path | None:
    """Resolve a possibly-relative path against the app root."""
    if path is None:
        return None
    p = Path(path)
    if p.is_absolute():
        return p
    root = base or app_root()
    return (root / p).resolve()


def config_path(name: str = "config/config.yaml") -> Path:
    return resolve_path(name)  # type: ignore[return-value]
