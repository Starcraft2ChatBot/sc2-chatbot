"""Multi-provider LLM client (Gemini + OpenAI-compatible APIs)."""
from __future__ import annotations

import logging
from typing import List, Optional

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
            text = (response.text or "").strip()
            if not text:
                logger.warning("LLM returned empty response")
            return text
        except Exception as e:
            logger.exception("Gemini error: %s", e)
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

            resp = self._openai.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
            text = (resp.choices[0].message.content or "").strip()
            if not text:
                logger.warning("LLM returned empty response")
            return text
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
