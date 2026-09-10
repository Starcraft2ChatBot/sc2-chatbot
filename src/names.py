"""StarCraft 2 player name helpers."""
from __future__ import annotations
import re

# Matches leading clan tags like [Foo], {Foo}, <Foo>, (Foo)
_CLAN_TAG_RE = re.compile(
    r"^\s*[\[\{\(<][^\]\}\)>]{1,24}[\]\}\)>]\s*",
    re.UNICODE,
)

# BattleTag discriminator: Name#1234 or Name#12345
_BATTLETAG_RE = re.compile(r"#\d{4,5}$")


def strip_clan_tag(name: str) -> str:
    """Remove a leading clan tag from a display name.

    Examples:
        [LG]Serral      -> Serral
        {TSM}ByuN       -> ByuN
        <Liquid>Clem    -> Clem
        Serral          -> Serral
    """
    if not name:
        return name
    cleaned = _CLAN_TAG_RE.sub("", name).strip()
    return cleaned or name.strip()


def normalize_player_name(name: str, strip_battletag: bool = False) -> str:
    """Normalize a player name for memory keys and comparisons.

    - Strips leading clan tags
    - Optionally strips #1234 BattleTag discriminators
    - Collapses internal whitespace
    - Returns lowercased key form is NOT applied here (callers decide)
    """
    if not name:
        return ""
    n = strip_clan_tag(name)
    if strip_battletag:
        n = _BATTLETAG_RE.sub("", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n


def memory_key(name: str) -> str:
    """Stable case-insensitive key used by conversation memory."""
    return normalize_player_name(name).lower()
