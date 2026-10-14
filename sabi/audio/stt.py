"""Offline speech-to-text with faster-whisper."""

from __future__ import annotations

import threading

import numpy as np


class Transcriber:
    def __init__(self, model_name: str) -> None:
        self._model_name = model_name
        self._model = None
        self._lock = threading.Lock()

    def _load(self):
        with self._lock:
            if self._model is None:
                from faster_whisper import WhisperModel

                from sabi.config import BUNDLED_WHISPER

                # The packaged app ships its model so speech works offline from the first launch.
                name = str(BUNDLED_WHISPER) if BUNDLED_WHISPER and BUNDLED_WHISPER.exists() else self._model_name
                self._model = WhisperModel(name, device="cpu", compute_type="int8")
        return self._model

    def warm_up(self) -> None:
        self._load()

    def transcribe(self, audio: np.ndarray) -> tuple[str, str]:
        """Return (text, detected language code)."""
        if audio.size < 1600:  # under 0.1 s
            return "", ""
        segments, info = self._load().transcribe(audio, beam_size=1, vad_filter=True)
        text = " ".join(s.text.strip() for s in segments).strip()
        return text, info.language or ""
