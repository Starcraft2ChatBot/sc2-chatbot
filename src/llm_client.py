"""Multi-provider LLM client (Gemini + OpenAI-compatible + Ollama local)."""
from __future__ import annotations

import logging
from typing import Any, List, Optional

logger = logging.getLogger("sc2_chatbot.llm")

# Local inference can be slow on first load / CPU
_DEFAULT_LOCAL_TIMEOUT = 120.0
_DEFAULT_CLOUD_TIMEOUT = 60.0


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
            and any(
                h in self.base_url
                for h in ("127.0.0.1", "localhost", "0.0.0.0")
            )
        )

        if is_local and self.provider in ("openai", "openai_compatible", "custom"):
            # Treat localhost OpenAI-compatible as local (LM Studio, etc.)
            pass

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
                # OpenAI SDK requires a non-empty string; local servers ignore it
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

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        history: Optional[List[dict]] = None,
    ) -> str:
        if self.provider in ("gemini", "google"):
            return self._generate_gemini(system_prompt, user_prompt, history)
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

    def _log_empty(
        self,
        *,
        source: str,
        extra: Optional[dict] = None,
    ) -> None:
        self._log_diag(kind="LLM returned empty response", source=source, extra=extra)

    def _log_transport_error(
        self,
        *,
        source: str,
        exc: BaseException,
    ) -> None:
        err_type = type(exc).__name__
        err_msg = str(exc).replace("\n", " ")[:400]
        status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
        request_id = None
        body = None
        try:
            resp = getattr(exc, "response", None)
            if resp is not None:
                status = status or getattr(resp, "status_code", None)
                headers = getattr(resp, "headers", None) or {}
                request_id = headers.get("x-request-id") or headers.get("X-Request-Id")
                try:
                    body = getattr(resp, "text", None) or getattr(resp, "content", None)
                    if body is not None:
                        body = str(body)[:200]
                except Exception:
                    body = None
        except Exception:
            pass

        extra: dict[str, Any] = {
            "error_type": err_type,
            "error": err_msg,
        }
        if status is not None:
            extra["status_code"] = status
        if request_id:
            extra["request_id"] = request_id
        if body:
            extra["response_body"] = body

        if _is_timeout_error(exc):
            extra["hint"] = (
                "Connection/read timed out — for Ollama try a smaller model, "
                "raise llm.request_timeout_sec, or wait for model load"
            )
            self._log_diag(kind="LLM connection timeout", source=source, extra=extra)
            return

        if _is_connection_error(exc):
            extra["hint"] = (
                "Could not reach LLM API — for Ollama ensure `ollama serve` is running "
                "and base_url is http://127.0.0.1:11434/v1"
            )
            self._log_diag(kind="LLM connection error", source=source, extra=extra)
            return

        msg_l = err_msg.lower()
        if status == 429 or "rate limit" in msg_l or "429" in msg_l:
            extra["hint"] = "Rate limited (429) — wait and retry or switch model"
            self._log_diag(kind="LLM rate limit error", source=source, extra=extra)
            return
        if status in (401, 403) or "unauthorized" in msg_l or "invalid api" in msg_l:
            extra["hint"] = "Auth failed — check llm.api_key (Ollama can use any dummy key)"
            self._log_diag(kind="LLM auth error", source=source, extra=extra)
            return
        if status == 404 or "not found" in msg_l:
            extra["hint"] = (
                "Model or endpoint not found — run `ollama list` and set llm.model "
                "to an exact name (e.g. qwen3.5:9b)"
            )
            self._log_diag(kind="LLM not found error", source=source, extra=extra)
            return

        extra["hint"] = "See error_type/error above; full traceback follows if logged"
        self._log_diag(kind="LLM request error", source=source, extra=extra)
        logger.exception("%s LLM error: %s", source, exc)

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
                    extra={
                        "text_accessor_error": type(te).__name__,
                        "text_accessor_detail": str(te)[:200],
                    },
                )

            if text:
                return text

            extra: dict[str, Any] = {}
            try:
                cands = getattr(response, "candidates", None) or []
                extra["candidates"] = len(cands)
                if cands:
                    c0 = cands[0]
                    fr = getattr(c0, "finish_reason", None)
                    extra["finish_reason"] = str(fr)
                    safety = getattr(c0, "safety_ratings", None)
                    if safety:
                        extra["safety"] = str(safety)[:300]
                    content = getattr(c0, "content", None)
                    parts = getattr(content, "parts", None) if content else None
                    extra["parts"] = len(parts) if parts is not None else 0
                pf = getattr(response, "prompt_feedback", None)
                if pf is not None:
                    extra["prompt_feedback"] = str(pf)[:300]
            except Exception as de:
                extra["diag_error"] = f"{type(de).__name__}: {de}"[:200]

            self._log_empty(source="gemini", extra=extra)
            return ""
        except Exception as e:
            self._log_transport_error(source="gemini", exc=e)
            return ""

    def _extract_openai_message_text(self, message: Any) -> str:
        if message is None:
            return ""

        content = getattr(message, "content", None)
        if isinstance(content, str) and content.strip():
            return content.strip()
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
                return joined

        return ""

    def _generate_openai(
        self,
        system_prompt: str,
        user_prompt: str,
        history: Optional[List[dict]],
    ) -> str:
        try:
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
            }

            try:
                resp = self._openai.chat.completions.create(**create_kwargs)
            except Exception as e:
                err_s = str(e).lower()
                if (
                    not _is_timeout_error(e)
                    and not _is_connection_error(e)
                    and ("max_tokens" in err_s or "max_completion_tokens" in err_s)
                ):
                    create_kwargs.pop("max_tokens", None)
                    create_kwargs["max_completion_tokens"] = self.max_tokens
                    try:
                        resp = self._openai.chat.completions.create(**create_kwargs)
                    except Exception as e2:
                        self._log_transport_error(source="openai_compatible", exc=e2)
                        return ""
                else:
                    self._log_transport_error(source="openai_compatible", exp=e) if False else None
                    self._log_transport_error(source="openai_compatible", exc=e)
                    return ""

            choices = getattr(resp, "choices", None) or []
            if not choices:
                self._log_empty(
                    source="openai_compatible",
                    extra={
                        "choices": 0,
                        "id": getattr(resp, "id", None),
                        "hint": "API returned no choices — check model name with `ollama list`",
                    },
                )
                return ""

            choice = choices[0]
            message = getattr(choice, "message", None)
            text = self._extract_openai_message_text(message)

            if text:
                return text

            extra: dict[str, Any] = {
                "choices": len(choices),
                "finish_reason": getattr(choice, "finish_reason", None),
                "id": getattr(resp, "id", None),
            }

            if message is not None:
                raw_content = getattr(message, "content", None)
                extra["content_type"] = type(raw_content).__name__
                extra["content_repr"] = repr(raw_content)[:120]
                for attr in ("reasoning_content", "reasoning", "reasoning_details"):
                    val = getattr(message, attr, None)
                    if val:
                        extra[attr] = str(val)[:120]
                        extra["hint"] = (
                            "Reasoning field present but message.content empty — "
                            "raise max_output_tokens or disable thinking mode"
                        )

            usage = getattr(resp, "usage", None)
            if usage is not None:
                extra["prompt_tokens"] = getattr(usage, "prompt_tokens", None)
                extra["completion_tokens"] = getattr(usage, "completion_tokens", None)

            fr = str(getattr(choice, "finish_reason", "") or "").lower()
            if fr in ("length", "max_tokens") and not extra.get("hint"):
                extra["hint"] = "finish_reason=length — raise llm.max_output_tokens"

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
