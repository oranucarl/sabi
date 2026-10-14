"""Microphone capture for push-to-talk."""

from __future__ import annotations

import threading

import numpy as np
import sounddevice as sd

SAMPLE_RATE = 16_000


class Recorder:
    def __init__(self) -> None:
        self._chunks: list[np.ndarray] = []
        self._lock = threading.Lock()
        self._stream: sd.InputStream | None = None
        self.level = 0.0  # last RMS, drives the listening animation

    def start(self) -> None:
        with self._lock:
            self._chunks = []
        self._stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32", callback=self._callback)
        self._stream.start()

    def stop(self) -> np.ndarray:
        """Stop recording and return mono float32 audio at 16 kHz."""
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        with self._lock:
            audio = np.concatenate(self._chunks)[:, 0] if self._chunks else np.zeros(0, dtype=np.float32)
        self.level = 0.0
        return audio

    def _callback(self, indata, frames, time_info, status) -> None:
        with self._lock:
            self._chunks.append(indata.copy())
        self.level = float(np.sqrt(np.mean(indata**2)))


def duration(audio: np.ndarray) -> float:
    return len(audio) / SAMPLE_RATE
