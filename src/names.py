"""StarCraft 2 player name helpers + OCR cleanup."""
from __future__ import annotations

import re

_CLAN_TAG_RE = re.compile(
    r"^\s*[\[\{\(<][^\]\}\)>]{1,24}[\]\}\)>]\s*",
    re.UNICODE,
)
_BATTLETAG_RE = re.compile(r"#\d{4,5}$")

# OCR often mangles "17:52" into "1752" and glues it to the channel tag
_LEADING_TIME_RE = re.compile(
    r"^(?:"
    r"\d{1,2}:\d{2}"  # 17:52
    r"|\d{3,4}"  # 1752 (OCR lost the colon)
    r")\s*",
)
_CHANNEL_TAG_RE = re.compile(
    r"^[\|\[]?\s*\d*\.?\s*(?:All|Team|Whisper|General|Arcade|Chat|\d+)\s*[^\]\|]*[\]\|]?\s*",
    re.IGNORECASE,
)
# Strip leftover junk like "1. General]" or "[1, General]"
_LEFTOVER_CHAN_RE = re.compile(
    r"^[\|\[\]\s,\.]*\d*\.?\s*(?:All|Team|Whisper|General|Arcade)[\|\[\]\s,\.]*",
    re.IGNORECASE,
)


def strip_clan_tag(name: str) -> str:
    if not name:
        return name
    cleaned = _CLAN_TAG_RE.sub("", name).strip()
    return cleaned or name.strip()


def clean_ocr_player_name(raw: str) -> str:
    """Turn OCR garbage into a bare player name.

    Examples:
      '1752[1. General] FurryFemboy' -> 'FurryFemboy'
      '|1. General] Drunknmaster'    -> 'Drunknmaster'
      '[All] Serral'                 -> 'Serral'
      '17:52 [1. General] Bob'       -> 'Bob'
    """
    if not raw:
        return ""
    n = raw.strip()
    n = _LEADING_TIME_RE.sub("", n)
    n = _CHANNEL_TAG_RE.sub("", n)
    n = _LEFTOVER_CHAN_RE.sub("", n)
    n = n.strip(" []|()<>{},.")
    n = strip_clan_tag(n)
    n = re.sub(r"\s+", " ", n).strip()
    # Drop pure numeric leftovers from bad OCR
    if n.isdigit():
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
    n = re.sub(r"\s+", " ", n).strip()
    return n


def memory_key(name: str) -> str:
    return normalize_player_name(name).lower()


def short_display_name(name: str) -> str:
    """Name used when addressing someone in chat (no time/channel junk)."""
    n = normalize_player_name(name, strip_battletag=True)
    return n or (name or "").strip()
