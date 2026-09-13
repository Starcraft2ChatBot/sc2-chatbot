"""Multi-provider LLM client (Gemini + OpenAI-compatible + Ollama local)."""
from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from typing import Any, List, Optional

logger = logging.getLogger("sc2_chatbot.llm")

_DEFAULT_LOCAL_TIMEOUT = 120.0
_DEFAULT_CLOUD_TIMEOUT = 60.0

_THINK_BLOCK_RE = re.compile(r"<think>[\s\S]*?</think>", flags=re.IGNORECASE)
_THINK_OPEN_RE = re.compile(r"<think>[\s\S]*$", flags=re.IGNORECASE)

# Text that is clearly system/planning echo — never send to game chat
_META_MARKERS = (
    "**priority",
    "**format",
    "**formatting",
    "**constraint",
    "**constraints",
    "**length",
    "**user input",
    "priority:",
    "formatting:",
    "constraint:",
    "constraints:",
    "aggressiveness",
    "emoji intensity",
    "thinking process",
    "do not use banned",
    "banned character",
    "internet shorthand",
    "no trailing periods",
    "single line only",
    "lowercase/mixed",
    "pivot to politics",
    "propaganda bot",
    "starcraft reference",
    "as an ai",
    "system prompt",
    "roleplay",
)


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


def _looks_like_meta(text: str) -> bool:
    low = (text or "").lower()
    if not low.strip():
        return True
    if any(m in low for m in _META_MARKERS):
        return True
    # Bullet / markdown instruction dumps
    if low.count("*") >= 3 or low.count("**") >= 2:
        return True
    if low.strip().startswith("*") and (":" in low[:40] or "**" in low[:40]):
        return True
    if "step " in low[:80] and ("analyze" in low or "intent" in low):
        return True
    return False


def _clean_model_text(text: str) -> str:
    """Strip think blocks; return a short chat-like line or empty if only meta."""
    if not text:
        return ""
    out = str(text)
    out = _THINK_BLOCK_RE.sub("", out)
    out = _THINK_OPEN_RE.sub("", out)
    out = out.strip().strip('"').strip("'")

    for marker in (
        "final answer:",
        "final reply:",
        "reply:",
        "response:",
        "say:",
        "output:",
        "chat message:",
    ):
        idx = out.lower().rfind(marker)
        if idx >= 0:
            candidate = out[idx + len(marker) :].strip()
            if candidate and not _looks_like_meta(candidate):
                out = candidate
                break

    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    chat_lines: List[str] = []
    for ln in lines:
        if _looks_like_meta(ln):
            continue
        # skip pure markdown bullets of instructions
        if re.match(r"^[\-\*]\s+\*\*", ln):
            continue
        chat_lines.append(ln)

    if not chat_lines:
        return ""

    picked = " ".join(chat_lines[-2:]).strip()
    # Strip leftover markdown stars
    picked = re.sub(r"\*+", "", picked).strip()
    if len(picked) > 280:
        picked = picked[:280].rsplit(" ", 1)[0]
    if _looks_like_meta(picked):
        return ""
    return picked


class LLMClient:
    """Unified generate() for Gemini, OpenAI-compatible APIs, and local Ollama."""

    def __init__(
        self,
        *,
        provider: str = "gemini",
        api_key: str = "",
        model: str = "gemini-2.0-flash",
        temperature: float = 0.85,
        max_tokens: int = 180,
        base_url: str | None = None,
        request_timeout_sec: float | None = None,
        connect_timeout_sec: float | None = None,
    ):
        self.provider = (provider or "gemini").lower().strip()
        self.api_key = (api_key or "").strip()
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.base_url = (base_url or "").strip() or None

        is_local = self.provider in ("ollama", "local") or (
            self.base_url
            and any(h in self.base_url for h in ("127.0.0.1", "localhost", "0.0.0.0"))
        )

        if self.provider in ("ollama", "local"):
            if not self.base_url:
                self.base_url = "http://127.0.0.1:11434/v1"
            if not self.api_key:
                self.api_key = "ollama"
            is_local = True

        default_timeout = _DEFAULT_LOCAL_TIMEOUT if is_local else _DEFAULT_CLOUD_TIMEOUT
        self.request_timeout_sec = float(
            request_timeout_sec if request_timeout_sec is not None else default_timeout
        )
        self.connect_timeout_sec = float(
            connect_timeout_sec if connect_timeout_sec is not None else 10.0
        )

        if self.provider in ("gemini", "google"):
            if not self.api_key:
                raise ValueError("LLM api_key is required for Gemini")
            self._init_gemini()
        elif self.provider in (
            "openai",
            "openai_compatible",
            "openrouter",
            "custom",
            "ollama",
            "local",
        ):
            if not self.api_key:
                self.api_key = "ollama" if is_local else ""
            if not self.api_key:
                raise ValueError(
                    "LLM api_key is required (set in config under llm). "
                    "For Ollama use provider: ollama (key is optional)."
                )
            self._init_openai()
        else:
            raise ValueError(
                f"Unknown llm.provider={self.provider!r}. "
                "Use: gemini | openai | openai_compatible | openrouter | ollama | local | custom"
            )

    def _init_gemini(self) -> None:
        import google.generativeai as genai

        genai.configure(api_key=self.api_key)
        self._genai = genai
        self._gemini_model = genai.GenerativeModel(self.model)
        logger.info("LLM provider=gemini model=%s", self.model)

    def _init_openai(self) -> None:
        try:
            from openai import OpenAI
        except ImportError as e:
            raise ImportError(
                "OpenAI-compatible / Ollama provider requires:  pip install openai"
            ) from e

        kwargs: dict[str, Any] = {
            "api_key": self.api_key,
            "timeout": self.request_timeout_sec,
        }
        if self.base_url:
            kwargs["base_url"] = self.base_url
        self._openai = OpenAI(**kwargs)
        logger.info(
            "LLM provider=%s model=%s base_url=%s timeout=%.0fs",
            self.provider,
            self.model,
            self.base_url or "(default)",
            self.request_timeout_sec,
        )

    def _ollama_native_base(self) -> str:
        """Map OpenAI-style .../v1 to Ollama root."""
        base = (self.base_url or "http://127.0.0.1:11434/v1").rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]
        return base.rstrip("/") or "http://127.0.0.1:11434"

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        history: Optional[List[dict]] = None,
    ) -> str:
        if self.provider in ("gemini", "google"):
            return self._generate_gemini(system_prompt, user_prompt, history)
        # Native Ollama chat + think=false is more reliable for Qwen3 thinking models
        if self.provider in ("ollama", "local") or (
            self.base_url and "11434" in (self.base_url or "")
        ):
            text = self._generate_ollama_native(system_prompt, user_prompt, history)
            if text:
                return text
            logger.info("Ollama native empty; falling back to OpenAI-compatible path")
        return self._generate_openai(system_prompt, user_prompt, history)

    def _log_diag(
        self,
        *,
        kind: str,
        source: str,
        extra: Optional[dict] = None,
    ) -> None:
        parts = [
            kind,
            f"provider={self.provider}",
            f"model={self.model}",
            f"source={source}",
            f"temperature={self.temperature}",
            f"max_tokens={self.max_tokens}",
        ]
        if self.base_url:
            parts.append(f"base_url={self.base_url}")
        if extra:
            for k, v in extra.items():
                if v is None or v == "":
                    continue
                parts.append(f"{k}={v}")
        logger.warning("%s", " | ".join(parts))

    def _log_empty(self, *, source: str, extra: Optional[dict] = None) -> None:
        self._log_diag(kind="LLM returned empty response", source=source, extra=extra)

    def _log_transport_error(self, *, source: str, exc: BaseException) -> None:
        err_type = type(exc).__name__
        err_msg = str(exc).replace("\n", " ")[:400]
        status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
        extra: dict[str, Any] = {"error_type": err_type, "error": err_msg}
        if status is not None:
            extra["status_code"] = status

        if _is_timeout_error(exc):
            extra["hint"] = (
                "Timed out — raise llm.request_timeout_sec or use a smaller model"
            )
            self._log_diag(kind="LLM connection timeout", source=source, extra=extra)
            return
        if _is_connection_error(exc):
            extra["hint"] = (
                "Could not reach Ollama — is `ollama serve` running? "
                "base_url should be http://127.0.0.1:11434/v1"
            )
            self._log_diag(kind="LLM connection error", source=source, extra=extra)
            return
        if status == 404 or "not found" in err_msg.lower():
            extra["hint"] = "Model not found — run `ollama list` and set llm.model exactly"
            self._log_diag(kind="LLM not found error", source=source, extra=extra)
            return
        extra["hint"] = "See error above"
        self._log_diag(kind="LLM request error", source=source, extra=extra)
        logger.exception("%s LLM error: %s", source, exc)

    def _generate_ollama_native(
        self,
        system_prompt: str,
        user_prompt: str,
        history: Optional[List[dict]],
    ) -> str:
        """POST /api/chat with think=false so content is the real reply."""
        messages: List[dict] = [
            {
                "role": "system",
                "content": (
                    f"{system_prompt}\n\n"
                    "OUTPUT RULES: Reply with ONE short in-game chat line only. "
                    "No markdown, no bullets, no lists, no analysis, no planning."
                ),
            }
        ]
        for h in history or []:
            role = h.get("role", "user")
            if role == "model":
                role = "assistant"
            parts = h.get("parts") or h.get("content") or ""
            if isinstance(parts, list):
                content = " ".join(str(p) for p in parts)
            else:
                content = str(parts)
            messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": user_prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "think": False,
            "options": {
                "temperature": self.temperature,
                "num_predict": int(self.max_tokens),
            },
        }
        url = f"{self._ollama_native_base()}/api/chat"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.request_timeout_sec) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            self._log_transport_error(source="ollama_native", exp=e) if False else None
            self._log_transport_error(source="ollama_native", exc=e)
            return ""

        msg = (body or {}).get("message") or {}
        content = (msg.get("content") or "").strip()
        thinking = (msg.get("thinking") or msg.get("reasoning") or "").strip()

        text = _clean_model_text(content)
        if text:
            return text
        if content and not _looks_like_meta(content):
            return content[:280]

        # Only use thinking if it cleans into a real chat line (not constraints)
        if thinking:
            cleaned = _clean_model_text(thinking)
            if cleaned:
                logger.info("Ollama native: using cleaned thinking as chat line")
                return cleaned

        self._log_empty(
            source="ollama_native",
            extra={
                "content_repr": repr(content)[:120],
                "thinking_len": len(thinking),
                "hint": (
                    "Empty content with think=false — lower temperature to ~0.9, "
                    "max_output_tokens ~150, or try model qwen2.5:7b"
                ),
            },
        )
        return ""

    def _generate_gemini(
        self,
        system_prompt: str,
        user_prompt: str,
        history: Optional[List[dict]],
    ) -> str:
        try:
            from google.generativeai.types import HarmCategory, HarmBlockThreshold

            chat = self._gemini_model.start_chat(history=history or [])
            full_prompt = (
                f"{system_prompt}\n\n---\n"
                f"Current message to reply to:\n{user_prompt}"
            )
            response = chat.send_message(
                full_prompt,
                generation_config=self._genai.types.GenerationConfig(
                    temperature=self.temperature,
                    max_output_tokens=self.max_tokens,
                ),
                safety_settings={
                    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
                },
            )
            text = ""
            try:
                text = (response.text or "").strip()
            except Exception as te:
                self._log_empty(
                    source="gemini",
                    extra={"text_accessor_error": type(te).__name__},
                )
            if text:
                cleaned = _clean_model_text(text)
                return cleaned or (text if not _looks_like_meta(text) else "")
            self._log_empty(source="gemini", extra={})
            return ""
        except Exception as e:
            self._log_transport_error(source="gemini", exc=e)
            return ""

    def _extract_openai_message_text(self, message: Any) -> str:
        if message is None:
            return ""

        content = getattr(message, "content", None)
        if isinstance(content, str) and content.strip():
            cleaned = _clean_model_text(content)
            if cleaned:
                return cleaned
            if not _looks_like_meta(content):
                return content.strip()[:280]
            return ""

        if isinstance(content, list):
            bits: List[str] = []
            for block in content:
                if isinstance(block, str):
                    bits.append(block)
                elif isinstance(block, dict):
                    t = block.get("text") or block.get("content")
                    if t:
                        bits.append(str(t))
                else:
                    t = getattr(block, "text", None)
                    if t:
                        bits.append(str(t))
            joined = " ".join(bits).strip()
            if joined:
                cleaned = _clean_model_text(joined)
                if cleaned:
                    return cleaned
                if not _looks_like_meta(joined):
                    return joined[:280]

        # reasoning only if it becomes a real chat line — never dump planning notes
        for attr in ("reasoning_content", "reasoning", "reasoning_details", "thinking"):
            val = getattr(message, attr, None)
            if not val:
                continue
            cleaned = _clean_model_text(str(val))
            if cleaned:
                logger.info("Using cleaned %s field as chat line", attr)
                return cleaned
        return ""

    def _generate_openai(
        self,
        system_prompt: str,
        user_prompt: str,
        history: Optional[List[dict]],
    ) -> str:
        try:
            system_prompt = (
                f"{system_prompt}\n\n"
                "OUTPUT: one short in-game chat message only. "
                "No markdown, no bullets, no analysis, no constraint lists."
            )
            messages = [{"role": "system", "content": system_prompt}]
            for h in history or []:
                role = h.get("role", "user")
                if role == "model":
                    role = "assistant"
                parts = h.get("parts") or h.get("content") or ""
                if isinstance(parts, list):
                    content = " ".join(str(p) for p in parts)
                else:
                    content = str(parts)
                messages.append({"role": role, "content": content})
            messages.append({"role": "user", "content": user_prompt})

            create_kwargs: dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "extra_body": {"think": False},
            }

            try:
                resp = self._openai.chat.completions.create(**create_kwargs)
            except Exception as e:
                err_s = str(e).lower()
                if "extra_body" in create_kwargs:
                    create_kwargs.pop("extra_body", None)
                    try:
                        resp = self._openai.chat.completions.create(**create_kwargs)
                    except Exception as e2:
                        self._log_transport_error(source="openai_compatible", exc=e2)
                        return ""
                elif "max_tokens" in err_s or "max_completion_tokens" in err_s:
                    create_kwargs.pop("max_tokens", None)
                    create_kwargs["max_completion_tokens"] = self.max_tokens
                    try:
                        resp = self._openai.chat.completions.create(**create_kwargs)
                    except Exception as e2:
                        self._log_transport_error(source="openai_compatible", exc=e2)
                        return ""
                else:
                    self._log_transport_error(source="openai_compatible", exc=e)
                    return ""

            choices = getattr(resp, "choices", None) or []
            if not choices:
                self._log_empty(source="openai_compatible", extra={"choices": 0})
                return ""

            choice = choices[0]
            message = getattr(choice, "message", None)
            text = self._extract_openai_message_text(message)
            if text:
                return text

            extra: dict[str, Any] = {
                "finish_reason": getattr(choice, "finish_reason", None),
                "hint": (
                    "No usable chat line (only planning/meta). "
                    "Set temperature 0.9, max_output_tokens 150, pull latest code, "
                    "or switch to qwen2.5:7b"
                ),
            }
            self._log_empty(source="openai_compatible", extra=extra)
            return ""
        except Exception as e:
            self._log_transport_error(source="openai_compatible", exc=e)
            return ""


class GeminiClient(LLMClient):
    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.0-flash",
        temperature: float = 0.85,
        max_tokens: int = 180,
    ):
        super().__init__(
            provider="gemini",
            api_key=api_key,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
