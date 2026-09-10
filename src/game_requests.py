"""Detect StarCraft 2 game / lobby request messages."""
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Optional

# Common patterns players use when looking for a game:
#   [1v1]  [2v2]  [3v3]  [4v4]
#   [1v1 me]  [2v2 any]  [zerg only]
#   [host]  [hosting]  [lfg]  [looking for game]
#   bare brackets with race / map hints

_BRACKET_RE = re.compile(
    r"""
    \[\s*
    (?P<body>
        (?:\d\s*v\s*\d)                  # 1v1, 2v2, ...
        | (?:host(?:ing)?)               # host / hosting
        | (?:lfg|looking\s*for\s*game)   # lfg
        | (?:anyone|any)\s*(?:up|for)?   # anyone up
        | (?:zerg|protoss|terran|random) # race
        | (?:me|us|open|spot)            # me / open spot
        | [^\]]{0,40}                    # short free-form inside brackets
    )
    \s*\]
    """,
    re.IGNORECASE | re.VERBOSE,
)

_LOOSE_REQUEST_RE = re.compile(
    r"(?i)\b(?:"
    r"1\s*v\s*1|2\s*v\s*2|3\s*v\s*3|4\s*v\s*4|"
    r"wanna\s*(?:play|game|1v1|2v2)|"
    r"looking\s*for\s*(?:game|1v1|2v2|team)|"
    r"hosting\s*(?:1v1|2v2|3v3|4v4|game)?|"
    r"lf\s*(?:1v1|2v2|game|team)|"
    r"glhf\s*\+\s*game"
    r")\b"
)


@dataclass(frozen=True)
class GameRequestInfo:
    is_request: bool
    kind: str = ""          # e.g. "1v1", "2v2", "host", "lfg", "other"
    raw_body: str = ""      # text inside brackets if any


def detect_game_request(text: str) -> GameRequestInfo:
    """Return whether a chat line looks like a game/lobby request."""
    if not text or not text.strip():
        return GameRequestInfo(False)

    m = _BRACKET_RE.search(text)
    if m:
        body = (m.group("body") or "").strip()
        kind = _classify_body(body)
        return GameRequestInfo(True, kind=kind, raw_body=body)

    if _LOOSE_REQUEST_RE.search(text):
        return GameRequestInfo(True, kind="other", raw_body=text.strip())

    return GameRequestInfo(False)


def _classify_body(body: str) -> str:
    b = body.lower()
    if re.search(r"1\s*v\s*1", b):
        return "1v1"
    if re.search(r"2\s*v\s*2", b):
        return "2v2"
    if re.search(r"3\s*v\s*3", b):
        return "3v3"
    if re.search(r"4\s*v\s*4", b):
        return "4v4"
    if "host" in b:
        return "host"
    if "lfg" in b or "looking" in b:
        return "lfg"
    return "other"
