from __future__ import annotations
import os
import shutil
from pathlib import Path
from typing import Any, Dict, Optional
import yaml
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()


class LLMConfig(BaseModel):
    """Which AI to use. provider=gemini (default) or openai-compatible."""
    provider: str = "gemini"  # gemini | openai | openai_compatible | openrouter | custom
    api_key: str = Field(default_factory=lambda: os.getenv("LLM_API_KEY") or os.getenv("GEMINI_API_KEY", ""))
    model: str = "gemini-2.0-flash"  # e.g. gemini-2.0-flash, gpt-4o-mini, etc.
    temperature: float = 0.85
    max_output_tokens: int = 180
    # Required for openai_compatible / openrouter / custom (API base URL)
    base_url: Optional[str] = None


class GeminiConfig(BaseModel):
    """Legacy section — still works; values merge into llm if llm is omitted."""
    api_key: str = Field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    model: str = "gemini-2.0-flash"
    temperature: float = 0.85
    max_output_tokens: int = 180


class PersonalityConfig(BaseModel):
    aggressiveness: int = Field(5, ge=1, le=10)
    political_mode: str = "neutral"
    response_length: str = "medium"
    emoji_intensity: int = Field(3, ge=0, le=10)
    topics: Dict[str, bool] = Field(default_factory=dict)
    channel_overrides: Dict[str, Dict[str, Any]] = Field(default_factory=dict)


class Config(BaseModel):
    llm: Optional[LLMConfig] = None
    gemini: GeminiConfig = Field(default_factory=GeminiConfig)
    owner: Dict[str, Any] = Field(default_factory=dict)
    personality: PersonalityConfig = Field(default_factory=PersonalityConfig)
    behaviour: Dict[str, Any] = Field(default_factory=dict)
    anti_spam: Dict[str, Any] = Field(default_factory=dict)
    memory: Dict[str, Any] = Field(default_factory=dict)
    triggers: list = Field(default_factory=list)
    canned_blocks: list = Field(default_factory=list)
    logging: Dict[str, Any] = Field(default_factory=dict)
    chat_backend: str = "simulated"
    sc2_stub: Dict[str, Any] = Field(default_factory=dict)

    def resolved_llm(self) -> LLMConfig:
        """Prefer explicit llm block; fall back to legacy gemini block."""
        if self.llm and (self.llm.api_key or self.llm.provider != "gemini"):
            # Fill empty api_key from gemini / env
            key = self.llm.api_key or self.gemini.api_key or os.getenv("GEMINI_API_KEY", "")
            return self.llm.model_copy(update={"api_key": key})
        return LLMConfig(
            provider="gemini",
            api_key=self.gemini.api_key or os.getenv("GEMINI_API_KEY", ""),
            model=self.gemini.model,
            temperature=self.gemini.temperature,
            max_output_tokens=self.gemini.max_output_tokens,
        )

    @classmethod
    def load(cls, path: str | Path = "config/config.yaml") -> "Config":
        path = Path(path)

        if not path.exists():
            example = path.parent / "config.example.yaml"
            if example.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(example, path)
                print(
                    f"[config] Created {path} from {example}.\n"
                    f"         Edit it and put your API key under llm: or gemini:."
                )
            else:
                raise FileNotFoundError(
                    f"Config not found: {path}\nAlso missing example: {example}"
                )

        with path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        if not data.get("gemini", {}).get("api_key"):
            data.setdefault("gemini", {})["api_key"] = os.getenv("GEMINI_API_KEY", "")
        if data.get("llm") is not None and not data["llm"].get("api_key"):
            data["llm"]["api_key"] = (
                os.getenv("LLM_API_KEY")
                or data.get("gemini", {}).get("api_key")
                or os.getenv("GEMINI_API_KEY", "")
            )

        return cls(**data)
