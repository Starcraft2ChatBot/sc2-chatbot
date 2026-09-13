"""Multi-provider LLM client (Gemini + OpenAI-compatible APIs)."""
from __future__ import annotations

import logging
from typing import Any, List, Optional

logger = logging.getLogger("sc2_chatbot.llm")


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
    # Walk cause/context chain
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
    """Unified generate() for Gemini or any OpenAI-compatible chat API."""

    def __init__(
        self,
        *,
        provider: str = "gemini",
        api_key: str = "",
        model: str = "gemini-2.0-flash",
        temperature: float = 0.85,
        max_tokens: int = 180,
        base_url: str | None = None,
    ):
        self.provider = (provider or "gemini").lower().strip()
        self.api_key = api_key or ""
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.base_url = base_url

        if not self.api_key:
            raise ValueError("LLM api_key is required (set in config under llm or gemini)")

        if self.provider in ("gemini", "google"):
            self._init_gemini()
        elif self.provider in ("openai", "openai_compatible", "openrouter", "custom"):
            self._init_openai()
        else:
            raise ValueError(
                f"Unknown llm.provider={self.provider!r}. "
                "Use: gemini | openai | openai_compatible | openrouter | custom"
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
                "OpenAI-compatible provider requires:  pip install openai"
            ) from e

        kwargs = {"api_key": self.api_key}
        if self.base_url:
            kwargs["base_url"] = self.base_url
        self._openai = OpenAI(**kwargs)
        logger.info(
            "LLM provider=%s model=%s base_url=%s",
            self.provider,
            self.model,
            self.base_url or "(default)",
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
        """Structured diagnostics line for empty replies, timeouts, connection errors."""
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
        """Classify timeout vs connection vs other API failures with hints."""
        err_type = type(exc).__name__
        err_msg = str(exc).replace("\n", " ")[:400]
        status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
        request_id = None
        body = None
        try:
            resp = getattr(exc, "response", None)
            if resp is not None:
                status = status or getattr(resp, "status_code", None)
                request_id = (
                    getattr(resp, "headers", {}) or {}
                ).get("x-request-id") or (getattr(resp, "headers", {}) or {}).get(
                    "X-Request-Id"
                )
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
                "Connection/read timed out — provider slow or unreachable; "
                "retry later, switch model/endpoint, or check network/VPN/firewall"
            )
            self._log_diag(
                kind="LLM connection timeout",
                source=source,
                extra=extra,
            )
            return

        if _is_connection_error(exc):
            extra["hint"] = (
                "Could not reach LLM API — check network, DNS, base_url, "
                "VPN/firewall, and that the provider is online"
            )
            self._log_diag(
                kind="LLM connection error",
                source=source,
                extra=extra,
            )
            return

        # Rate limit / auth / other HTTP-style errors often surface here too
        msg_l = err_msg.lower()
        if status == 429 or "rate limit" in msg_l or "429" in msg_l:
            extra["hint"] = (
                "Rate limited (429) — wait and retry, slow anti-spam, "
                "or switch model/provider"
            )
            self._log_diag(kind="LLM rate limit error", source=source, extra=extra)
            return
        if status in (401, 403) or "unauthorized" in msg_l or "invalid api" in msg_l:
            extra["hint"] = "Auth failed — check llm.api_key and provider account"
            self._log_diag(kind="LLM auth error", source=source, extra=extra)
            return
        if status == 404 or "not found" in msg_l:
            extra["hint"] = "Model or endpoint not found — verify llm.model and base_url"
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
                # response.text can throw when candidates are blocked/empty
                self._log_empty(
                    source="gemini",
                    extra={
                        "text_accessor_error": type(te).__name__,
                        "text_accessor_detail": str(te)[:200],
                    },
                )

            if text:
                return text

            # Diagnostics from candidates / finish reason / safety
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
                    if parts:
                        snippets = []
                        for p in parts[:3]:
                            t = getattr(p, "text", None)
                            if t:
                                snippets.append(str(t)[:80])
                        if snippets:
                            extra["part_preview"] = " | ".join(snippets)
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
        """Pull visible text from an OpenAI-style message (content / refusal / parts)."""
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

        refusal = getattr(message, "refusal", None)
        if isinstance(refusal, str) and refusal.strip():
            return ""

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
                # Retry once with max_completion_tokens if API rejects max_tokens
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
                    self._log_transport_error(source="openai_compatible", exc=e)
                    return ""

            choices = getattr(resp, "choices", None) or []
            if not choices:
                self._log_empty(
                    source="openai_compatible",
                    extra={
                        "choices": 0,
                        "id": getattr(resp, "id", None),
                        "hint": "API returned no choices (rate limit, filter, or bad model id)",
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
                refusal = getattr(message, "refusal", None)
                if refusal:
                    extra["refusal"] = str(refusal)[:200]
                    extra["hint"] = "Model refused; content empty (safety/policy)"
                for attr in (
                    "reasoning_content",
                    "reasoning",
                    "reasoning_details",
                ):
                    val = getattr(message, attr, None)
                    if val:
                        extra[attr] = str(val)[:120]
                        extra["hint"] = (
                            extra.get("hint")
                            or "Reasoning field present but message.content empty "
                            "— try a non-thinking chat model or higher max_tokens"
                        )
                tool_calls = getattr(message, "tool_calls", None)
                if tool_calls:
                    extra["tool_calls"] = len(tool_calls)
                    extra["hint"] = (
                        extra.get("hint")
                        or "Model returned tool_calls instead of text"
                    )

            usage = getattr(resp, "usage", None)
            if usage is not None:
                extra["prompt_tokens"] = getattr(usage, "prompt_tokens", None)
                extra["completion_tokens"] = getattr(usage, "completion_tokens", None)
                extra["total_tokens"] = getattr(usage, "total_tokens", None)
                details = getattr(usage, "completion_tokens_details", None)
                if details is not None:
                    rt = getattr(details, "reasoning_tokens", None)
                    if rt:
                        extra["reasoning_tokens"] = rt
                        if not extra.get("hint"):
                            extra["hint"] = (
                                "Tokens spent on reasoning; visible content empty "
                                "— raise max_output_tokens or disable thinking mode"
                            )

            fr = str(getattr(choice, "finish_reason", "") or "").lower()
            if fr in ("length", "max_tokens") and not extra.get("hint"):
                extra["hint"] = "finish_reason=length — raise llm.max_output_tokens"
            elif fr in ("content_filter", "safety") and not extra.get("hint"):
                extra["hint"] = "Content filtered by provider"

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
