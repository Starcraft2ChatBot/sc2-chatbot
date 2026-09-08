from __future__ import annotations
import logging
from typing import List, Optional
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold

logger = logging.getLogger("sc2_chatbot.gemini")


class GeminiClient:
    def __init__(self, api_key: str, model: str = "gemini-2.0-flash", temperature: float = 0.85, max_tokens: int = 180):
        if not api_key:
            raise ValueError("Gemini API key is required")
        genai.configure(api_key=api_key)
        self.model_name = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._model = genai.GenerativeModel(model)

    def generate(self, system_prompt: str, user_prompt: str, history: Optional[List[dict]] = None) -> str:
        try:
            chat = self._model.start_chat(history=history or [])
            full_prompt = f"{system_prompt}\n\n---\nCurrent message to reply to:\n{user_prompt}"
            response = chat.send_message(
                full_prompt,
                generation_config=genai.types.GenerationConfig(
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
                logger.warning("Gemini returned empty response")
                return ""
            return text
        except Exception as e:
            logger.exception("Gemini error: %s", e)
            return ""
