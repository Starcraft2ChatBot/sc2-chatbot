"""Multi-provider LLM client (Gemini + OpenAI-compatible APIs)."""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from typing import Any, List, Optional

logger = logging.getLogger("sc2_chatbot.llm")

# Defaults: fail fast on firewall / dead routes instead of hanging 1–2 minutes
DEFAULT_REQUEST_TIMEOUT_SEC = 20.0
DEFAULT_CONNECT_TIMEOUT_SEC = 8.0
DEFAULT_HEALTH_TIMEOUT_SEC = 10.0
# After a transport failure, skip full LLM calls for this long (fail fast)
DEFAULT_FAIL_COOLDOWN_SEC = 45.0


def _is_timeout_error(exc: BaseException) -> bool:
    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    needles = (
        "timeout",
        "timed out",
        "time out",
        "deadline exceeded",
        "readtimeout",
        "connecttimeout",
        "writetimeout",
        "pooltimeout",
        "apitimeout",
    )
    if any(n in name for n in ("timeout", "timedout", "deadline")):
        return True
    if any(n in msg for n in needles):
        return True
    for attr in ("__cause__", "__context__"):
        nested = getattr(exc, attr, None)
        if nested is not None and nested is not exc:
            if _is_timeout_error(nested):
                return True
    return False


def _is_connection_error(exc: BaseException) -> bool:
    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    if _is_timeout_error(exc):
        return False
    needles = (
        "connection",
        "connect error",
        "connecterror",
        "network",
        "name or service not known",
        "nodename nor servname",
        "temporary failure in name resolution",
        "connection reset",
        "connection refused",
        "broken pipe",
        "remote end closed",
        "ssl",
        "proxy",
        "unreachable",
    )
    if any(n in name for n in ("connection", "connecterror", "networkerror")):
        return True
    if any(n in msg for n in needles):
        return True
    for attr in ("__cause__", "__context__"):
        nested = getattr(exc, attr, None)
        if nested is not None and nested is not exc:
            if _is_connection_error(nested):
                return True
    return False


def _is_transport_error(exc: BaseException) -> bool:
    return _is_timeout_error(exc) or _is_connection_error(exc)
