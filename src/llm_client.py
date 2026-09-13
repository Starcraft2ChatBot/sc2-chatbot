"""Multi-provider LLM client (Gemini + OpenAI-compatible APIs)."""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from typing import Any, List, Optional

logger = logging.getLogger("sc2_chatbot.llm")

DEFAULT_REQUEST_TIMEOUT_SEC = 20.0
DEFAULT_CONNECT_TIMEOUT_SEC = 8.0
DEFAULT_HEALTH_TIMEOUT_SEC = 10.0
DEFAULT_FAIL_COOLDOWN_SEC = 45.0


def _is_timeout_error(exc: BaseException) -> bool:
    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    needles = ("timeout", "timed out", "time out", "deadline exceeded", "readtimeout", "connecttimeout")
    if any(n in name for n in ("timeout", "timedout", "deadline")):
        return True
    if any(n in msg for n in needles):
        return True
    for attr in ("__cause__", "__context__"):
        nested = getattr(exc, attr, None)
        if nested is not None and nested is not exc and _is_timeout_error(nested):
            return True
    return False


def _is_connection_error(exc: BaseException) -> bool:
    if _is_timeout_error(exc):
        return False
    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    needles = ("connection", "network", "name or service not known", "connection reset", "connection refused", "ssl", "proxy", "unreachable")
    if any(n in name for n in ("connection", "connecterror", "networkerror")):
        return True
    if any(n in msg for n in needles):
        return True
    for attr in ("__cause__", "__context__"):
        nested = getattr(exc, attr, None)
        if nested is not None and nested is not exc and _is_connection_error(nested):
            return True
    return False


class LLMClient:
    def __init__(
        self,
        *,
        provider: str = "gemini",
        api_key: str = "",
        model: str = "gemini-2.0-flash",
        temperature: float = 0.85,
        max_tokens: int = 180,
        base_url: str | None = None,
        request_timeout_sec: float = DEFAULT_REQUEST_TIMEOUT_SEC,
        connect_timeout_sec: float = DEFAULT_CONNECT_TIMEOUT_SEC,
        health_timeout_sec: float = DEFAULT_HEALTH_TIMEOUT_SEC,
        fail_cooldown_sec: float = DEFAULT_FAIL_COOLDOWN_SEC,
    ):
        self.provider = (provider or "gemini").lower().strip()
        self.api_key = api_key or ""
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.base_url = base_url
        self.request_timeout_sec = float(request_timeout_sec or DEFAULT_REQUEST_TIMEOUT_SEC)
        self.connect_timeout_sec = float(connect_timeout_sec or DEFAULT_CONNECT_TIMEOUT_SEC)
        self.health_timeout_sec = float(health_timeout_sec or DEFAULT_HEALTH_TIMEOUT_SEC)
        self.fail_cooldown_sec = float(fail_cooldown_sec or DEFAULT_FAIL_COOLDOWN_SEC)
        self._last_ok_at: float | None = None
        self._last_fail_at: float | None = None
        self._last_fail_reason: str = ""
        if not self.api_key:
            raise ValueError("LLM api_key is required (set in config under llm or gemini)")
        if self.provider in ("gemini", "google"):
            self._init_gemini()
        elif self.provider in ("openai", "openai_compatible", "openrouter", "custom"):
            self._init_openai()
        else:
            raise ValueError(f"Unknown llm.provider={self.provider!r}")

    def _init_gemini(self) -> None:
        import google.generativeai as genai
        genai.configure(api_key=self.api_key)
        self._genai = genai
        self._gemini_model = genai.GenerativeModel(self.model)
        logger.info("LLM provider=gemini model=%s timeout=%.1fs", self.model, self.request_timeout_sec)

    def _init_openai(self) -> None:
        from openai import OpenAI
        kwargs: dict[str, Any] = {"api_key": self.api_key}
        if self.base_url:
            kwargs["base_url"] = self.base_url
        try:
            import httpx
            kwargs["timeout"] = httpx.Timeout(self.request_timeout_sec, connect=self.connect_timeout_sec)
        except Exception:
            kwargs["timeout"] = self.request_timeout_sec
        self._openai = OpenAI(**kwargs)
        logger.info("LLM provider=%s model=%s timeout=%.1fs", self.provider, self.model, self.request_timeout_sec)

    def _mark_ok(self) -> None:
        self._last_ok_at = time.monotonic()
        self._last_fail_at = None
        self._last_fail_reason = ""

    def _mark_fail(self, reason: str) -> None:
        self._last_fail_at = time.monotonic()
        self._last_fail_reason = (reason or "unknown")[:200]

    def is_likely_reachable(self) -> bool:
        if self._last_fail_at is None:
            return True
        if self._last_ok_at is not None and self._last_ok_at >= self._last_fail_at:
            return True
        return (time.monotonic() - self._last_fail_at) >= self.fail_cooldown_sec

    def last_fail_reason(self) -> str:
        return self._last_fail_reason or ""

    def health_check(self, timeout_sec: float | None = None) -> bool:
        """Minimal probe so firewall/DNS failures fail fast instead of hanging."""
        timeout = float(timeout_sec if timeout_sec is not None else self.health_timeout_sec)
        timeout = max(2.0, min(timeout, 60.0))

        def _probe() -> str:
            if self.provider in ("gemini", "google"):
                resp = self._gemini_model.generate_content(
                    "Reply with exactly: OK",
                    generation_config={"max_output_tokens": 8, "temperature": 0},
                    request_options={"timeout": timeout},
                )
                try:
                    return (resp.text or "").strip()
                except Exception:
                    return ""
            kwargs: dict[str, Any] = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": "Reply with exactly: OK"},
                    {"role": "user", "content": "ping"},
                ],
                "temperature": 0,
                "max_tokens": 8,
            }
            try:
                resp = self._openai.chat.completions.create(**kwargs, timeout=timeout)
            except TypeError:
                resp = self._openai.chat.completions.create(**kwargs)
            choices = getattr(resp, "choices", None) or []
            if not choices:
                return ""
            message = getattr(choices[0], "message", None)
            content = getattr(message, "content", None) if message else None
            return (content or "").strip() if isinstance(content, str) else ""

        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                text = pool.submit(_probe).result(timeout=timeout + 2.0)
            if text:
                self._mark_ok()
                logger.info("LLM health_check OK provider=%s model=%s", self.provider, self.model)
                return True
            self._mark_fail("empty health response")
            return False
        except FuturesTimeout:
            self._mark_fail(f"health_check timed out after {timeout:.0f}s")
            logger.warning("LLM health_check TIMEOUT provider=%s after %.0fs", self.provider, timeout)
            return False
        except Exception as e:
            self._mark_fail(f"{type(e).__name__}: {e}")
            logger.warning("LLM health_check FAILED: %s", e)
            return False

    def generate(self, system_prompt: str, user_prompt: str, history: Optional[List[dict]] = None) -> str:
        if not self.is_likely_reachable():
            logger.warning("LLM skip generate (cooldown): %s", self.last_fail_reason())
            return ""
        try:
            if self.provider in ("gemini", "google"):
                text = self._generate_gemini(system_prompt, user_prompt, history)
            else:
                text = self._generate_openai(system_prompt, user_prompt, history)
            if text:
                self._mark_ok()
            return text
        except Exception as e:
            if _is_timeout_error(e) or _is_connection_error(e):
                self._mark_fail(f"{type(e).__name__}: {e}")
            logger.exception("LLM generate error: %s", e)
            return ""

    def _generate_gemini(self, system_prompt: str, user_prompt: str, history: Optional[List[dict]]) -> str:
        from google.generativeai.types import HarmCategory, HarmBlockThreshold
        def _call():
            chat = self._gemini_model.start_chat(history=history or [])
            full_prompt = f"{system_prompt}\n\n---\nCurrent message to reply to:\n{user_prompt}"
            return chat.send_message(
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
                request_options={"timeout": self.request_timeout_sec},
            )
        with ThreadPoolExecutor(max_workers=1) as pool:
            try:
                response = pool.submit(_call).result(timeout=self.request_timeout_sec + 2.0)
            except FuturesTimeout as e:
                raise TimeoutError(f"LLM gemini timed out after {self.request_timeout_sec:.0f}s") from e
        try:
            return (response.text or "").strip()
        except Exception:
            return ""

    def _generate_openai(self, system_prompt: str, user_prompt: str, history: Optional[List[dict]]) -> str:
        messages = [{"role": "system", "content": system_prompt}]
        for h in history or []:
            role = h.get("role", "user")
            if role == "model":
                role = "assistant"
            parts = h.get("parts") or h.get("content") or ""
            content = " ".join(str(p) for p in parts) if isinstance(parts, list) else str(parts)
            messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": user_prompt})
        create_kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        def _create():
            try:
                return self._openai.chat.completions.create(**create_kwargs, timeout=self.request_timeout_sec)
            except TypeError:
                return self._openai.chat.completions.create(**create_kwargs)
        with ThreadPoolExecutor(max_workers=1) as pool:
            try:
                resp = pool.submit(_create).result(timeout=self.request_timeout_sec + 2.0)
            except FuturesTimeout as e:
                raise TimeoutError(f"LLM openai timed out after {self.request_timeout_sec:.0f}s") from e
        choices = getattr(resp, "choices", None) or []
        if not choices:
            return ""
        message = getattr(choices[0], "message", None)
        content = getattr(message, "content", None) if message else None
        return (content or "").strip() if isinstance(content, str) else ""


class GeminiClient(LLMClient):
    def __init__(self, api_key: str, model: str = "gemini-2.0-flash", temperature: float = 0.85, max_tokens: int = 180):
        super().__init__(provider="gemini", api_key=api_key, model=model, temperature=temperature, max_tokens=max_tokens)
