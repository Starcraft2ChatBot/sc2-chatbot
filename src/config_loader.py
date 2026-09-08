from __future__ import annotations
import os
import shutil
from pathlib import Path
from typing import Any, Dict
import yaml
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()


class GeminiConfig(BaseModel):
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
    gemini: GeminiConfig
    owner: Dict[str, Any]
    personality: PersonalityConfig
    behaviour: Dict[str, Any]
    anti_spam: Dict[str, Any]
    memory: Dict[str, Any]
    triggers: list = Field(default_factory=list)
    canned_blocks: list = Field(default_factory=list)
    logging: Dict[str, Any]
    chat_backend: str = "simulated"
    sc2_stub: Dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path = "config/config.yaml") -> "Config":
        path = Path(path)

        # First-run convenience: create config.yaml from the example if it is missing
        if not path.exists():
            example = path.parent / "config.example.yaml"
            if example.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(example, path)
                print(
                    f"[config] Created {path} from {example}.\n"
                    f"         Edit it and put your Gemini API key (or set GEMINI_API_KEY)."
                )
            else:
                raise FileNotFoundError(
                    f"Config not found: {path}\n"
                    f"Also missing the example file: {example}"
                )

        with path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        # Prefer environment variable over an empty key in the file
        if not data.get("gemini", {}).get("api_key"):
            data.setdefault("gemini", {})["api_key"] = os.getenv("GEMINI_API_KEY", "")

        return cls(**data)
