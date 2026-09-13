"""Multi-provider LLM client (Gemini + OpenAI-compatible APIs)."""
from __future__ import annotations

import logging
from typing import Any, List, Optional

logger = logging.getLogger("sc2_chatbot.llm")


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

    def _log_empty(
        self,
        *,
        source: str,
        extra: Optional[dict] = None,
    ) -> None:
        """Structured diagnostics when the model returns no usable text."""
        parts = [
            f"LLM returned empty response",
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
                        # Some models put text in parts without .text aggregating
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
            logger.exception("Gemini error: %s", e)
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

        # Some gateways put a refusal string instead of content
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
                # Some newer APIs prefer max_completion_tokens
                err_s = str(e).lower()
                if "max_tokens" in err_s or "max_completion_tokens" in err_s:
                    create_kwargs.pop("max_tokens", None)
                    create_kwargs["max_completion_tokens"] = self.max_tokens
                    resp = self._openai.chat.completions.create(**create_kwargs)
                else:
                    raise

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

            # Empty content — dump diagnostics for DeepSeek / OpenRouter / NVIDIA / etc.
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
                # Reasoning models sometimes only fill reasoning fields
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
                # OpenRouter / some providers nest details
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
            logger.exception("OpenAI-compatible LLM error: %s", e)
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
