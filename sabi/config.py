"""Settings loaded from the environment (and an optional .env file)."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

APP_SUPPORT = Path.home() / "Library" / "Application Support" / "Sabi"
PACKAGE_DATA = Path(__file__).parent / "data"
# Set when running from the packaged SAbi.app.
FROZEN = getattr(sys, "frozen", False)
BUNDLED_WHISPER = Path(getattr(sys, "_MEIPASS", "")) / "whisper-model" if FROZEN else None

# A .env in the working directory (running from source) or in the app's data folder (installed app).
load_dotenv()
load_dotenv(APP_SUPPORT / ".env")


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass(frozen=True)
class Settings:
    ollama_url: str = field(default_factory=lambda: _env("SABI_OLLAMA_URL", "http://localhost:11434"))
    vision_model: str = field(default_factory=lambda: _env("SABI_VISION_MODEL", "qwen2.5vl:7b"))
    embed_model: str = field(default_factory=lambda: _env("SABI_EMBED_MODEL", "nomic-embed-text"))
    # Optional: when set, Claude answers screen questions (better pointing). Local stays the default.
    anthropic_api_key: str = field(default_factory=lambda: _env("ANTHROPIC_API_KEY"))
    anthropic_model: str = field(default_factory=lambda: _env("SABI_ANTHROPIC_MODEL", "claude-haiku-5-5"))
    whisper_model: str = field(default_factory=lambda: _env("SABI_WHISPER_MODEL", "small"))
    # "auto" follows the learner; "pcm" forces Nigerian Pidgin; any ISO code pins a language.
    reply_language: str = field(default_factory=lambda: _env("SABI_REPLY_LANGUAGE", "auto"))
    # Online neural voices when available, macOS `say` otherwise.
    tts_engine: str = field(default_factory=lambda: _env("SABI_TTS", "edge"))
    data_dir: Path = field(default_factory=lambda: Path(_env("SABI_DATA_DIR") or APP_SUPPORT))

    @property
    def use_cloud(self) -> bool:
        return bool(self.anthropic_api_key)

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
