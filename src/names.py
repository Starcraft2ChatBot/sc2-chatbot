"""StarCraft 2 player name helpers + OCR cleanup."""
from __future__ import annotations

import re

_CLAN_TAG_RE = re.compile(
    r"^\s*[\[\{\(<][^\]\}\)>]{1,24}[\]\}\)>]\s*",
    re.UNICODE,
)
_BATTLETAG_RE = re.compile(r"#\d{4,5}$")

_LEADING_TIME_RE = re.compile(
    r"^(?:\d{1,2}:\d{2}|\d{3,4})\s*",
)

# Known SC2 chat channel names (used to strip UI chrome / doubled tags)
_CHAN_NAMES = (
    r"All|Team|Whisper|General|Arcade|Chat|"
    r"Co-?op(?:\s*Missions)?|PM|Party|Battle\.net"
)

# Repeated / doubled channel tags anywhere in the head
_CHANNEL_CHUNK_RE = re.compile(
    rf"[\|\[\(\s]*\d{{0,2}}\s*[.\:,]?\s*(?:{_CHAN_NAMES})[\]\)\|\s,]*",
    re.IGNORECASE,
)

_ONLY_CHANNEL_RE = re.compile(
    rf"^[\|\[\s]*\d{{0,2}}\s*[.\:,]?\s*(?:{_CHAN_NAMES})[\]\|\s]*$",
    re.IGNORECASE,
)


def strip_clan_tag(name: str) -> str:
    if not name:
        return name
    cleaned = _CLAN_TAG_RE.sub("", name).strip()
    return cleaned or name.strip()


def clean_ocr_player_name(raw: str) -> str:
    """Turn OCR garbage into a bare player name.

    Handles doubled tags like:
      'PM [2. General] PM [2. General] TvTisTrash' -> 'TvTisTrash'
      '1752[1. General] FurryFemboy' -> 'FurryFemboy'
    """
    if not raw:
        return ""
    n = raw.strip()
    n = _LEADING_TIME_RE.sub("", n)
    # Strip channel chunks repeatedly (OCR often doubles them)
    for _ in range(6):
        n2 = _CHANNEL_CHUNK_RE.sub(" ", n)
        n2 = re.sub(r"\s+", " ", n2).strip(" []|()<>{},.")
        if n2 == n:
            break
        n = n2
    n = strip_clan_tag(n)
    n = re.sub(r"\s+", " ", n).strip()
    if not n or n.isdigit() or _ONLY_CHANNEL_RE.match(n):
        return ""
    # Drop leftover leading "PM" / numbers
    n = re.sub(r"^(?:PM|\d+)\s+", "", n, flags=re.I).strip()
    if len(n) < 2 or len(n) > 32:
        return ""
    return n


def normalize_player_name(name: str, strip_battletag: bool = False) -> str:
    if not name:
        return ""
    n = clean_ocr_player_name(name)
    if not n:
        n = strip_clan_tag(name)
    if strip_battletag:
        n = _BATTLETAG_RE.sub("", n)
    return re.sub(r"\s+", " ", n).strip()


def memory_key(name: str) -> str:
    return normalize_player_name(name).lower()


def short_display_name(name: str) -> str:
    n = normalize_player_name(name, strip_battletag=True)
    return n or (name or "").strip()


def is_ui_channel_label(line: str) -> bool:
    """True if the whole line is just a channel indicator (not a player message)."""
    s = (line or "").strip()
    if not s:
        return True
    if _ONLY_CHANNEL_RE.match(s):
        return True
    # "[2. General]:" with empty / tiny text handled by caller
    return False
