"""StarCraft 2 player name helpers + OCR cleanup.

Goal: every public name is ONLY the bare nickname — no time, channel, or clan tag.
"""
from __future__ import annotations

import re

_BATTLETAG_RE = re.compile(r"#\d{4,5}$")

# 17:52 / 17:52:01 / OCR mangled 1752
_TIME_RE = re.compile(
    r"(?:^|\s)(?:\d{1,2}:\d{2}(?::\d{2})?|\d{3,4})(?=\s|$|[\[\|])",
)

_CHAN_NAMES = (
    r"All|Team|Whisper|General|Arcade|Chat|"
    r"Co-?op(?:\s*Missions)?|PM|Party|Battle\.net"
)

# [1. General], |2. Arcade|, (All), etc. — any bracketed chunk
_BRACKET_CHUNK_RE = re.compile(
    r"[\[\{\(<\|]+[^\]\}\)>\|]{0,48}[\]\}\)>\|]*",
)

_CHANNEL_WORD_RE = re.compile(
    rf"(?:^|\s)\d{{0,2}}\s*[.\:,]?\s*(?:{_CHAN_NAMES})(?=\s|$)",
    re.IGNORECASE,
)

# Clan-style tag stuck to name: [LG]Serral or {TSM}ByuN
_CLAN_PREFIX_RE = re.compile(
    r"^[\[\{\(<][^\]\}\)>]{1,24}[\]\}\)>]",
    re.UNICODE,
)

# Valid nickname token (letters first; allow digits/_/-/' inside)
_NAME_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_'\-]{1,23}")

_ONLY_CHANNEL_RE = re.compile(
    rf"^[\|\[\s]*\d{{0,2}}\s*[.\:,]?\s*(?:{_CHAN_NAMES})[\]\|\s]*$",
    re.IGNORECASE,
)


def strip_clan_tag(name: str) -> str:
    if not name:
        return name
    n = name.strip()
    for _ in range(4):
        n2 = _CLAN_PREFIX_RE.sub("", n).strip()
        if n2 == n:
            break
        n = n2
    return n or name.strip()


def clean_ocr_player_name(raw: str) -> str:
    """Return ONLY the bare player nickname.

    Examples:
      '18:36 [3. Co-op Missions] [LG]Serral' -> 'Serral'
      '1752[1. General] FurryFemboy'         -> 'FurryFemboy'
      'PM [2. General] PM [2. General] Bob'  -> 'Bob'
      '|1. General] Drunknmaster'            -> 'Drunknmaster'
    """
    if not raw:
        return ""

    n = raw.strip()

    # 1) Times
    n = _TIME_RE.sub(" ", n)
    # 2) Any bracketed UI / clan / channel chunks
    n = _BRACKET_CHUNK_RE.sub(" ", n)
    # 3) Channel words left outside brackets
    n = _CHANNEL_WORD_RE.sub(" ", n)
    # 4) Leading clan tag if still present without brackets stripped
    n = strip_clan_tag(n)
    # 5) Junk punctuation / pipes
    n = re.sub(r"[\|\[\]\{\}\(\)<>:,]+", " ", n)
    n = re.sub(r"\s+", " ", n).strip()

    if not n or n.isdigit() or _ONLY_CHANNEL_RE.match(n):
        return ""

    # 6) Prefer the last name-like token (tags/times usually precede the name)
    tokens = _NAME_TOKEN_RE.findall(n)
    if not tokens:
        # Fallback: strip non-name junk
        n = re.sub(r"[^A-Za-z0-9_'\-]+", "", n)
        if len(n) < 2 or len(n) > 32 or n.isdigit():
            return ""
        return n

    # Drop pure channel-word tokens if any slipped through
    chan_l = {
        "all",
        "team",
        "whisper",
        "general",
        "arcade",
        "chat",
        "coop",
        "missions",
        "pm",
        "party",
    }
    tokens = [t for t in tokens if t.lower() not in chan_l]
    if not tokens:
        return ""

    name = tokens[-1]
    if len(name) < 2 or len(name) > 32:
        return ""
    return name


def normalize_player_name(name: str, strip_battletag: bool = False) -> str:
    if not name:
        return ""
    n = clean_ocr_player_name(name)
    if not n:
        # Last resort: strip clan only
        n = strip_clan_tag(name)
        n = _BRACKET_CHUNK_RE.sub(" ", n)
        n = re.sub(r"\s+", " ", n).strip()
        tokens = _NAME_TOKEN_RE.findall(n)
        n = tokens[-1] if tokens else ""
    if strip_battletag and n:
        n = _BATTLETAG_RE.sub("", n).strip()
    return n


def memory_key(name: str) -> str:
    return normalize_player_name(name).lower()


def short_display_name(name: str) -> str:
    """Bare nickname only — used for RECV logs and 'Name, reply' addressing."""
    return normalize_player_name(name, strip_battletag=True)


def is_ui_channel_label(line: str) -> bool:
    s = (line or "").strip()
    if not s:
        return True
    if _ONLY_CHANNEL_RE.match(s):
        return True
    # Line is only brackets / channel words
    cleaned = clean_ocr_player_name(s)
    if not cleaned and re.search(_CHAN_NAMES, s, re.I):
        return True
    return False
