"""Text-to-speech, spoken sentence by sentence so the first words play quickly.

Neural voices (edge-tts) are used when online; macOS `say` is the offline fallback.
"""

from __future__ import annotations

import asyncio
import queue
import re
import subprocess
import tempfile
import threading
from pathlib import Path

from sabi.language import Language

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def speakable(text: str) -> str:
    """Strip markdown, tags and LaTeX that sound bad read aloud."""
    text = re.sub(r"\[[A-Z]+:[^\]]*\]", "", text)
    text = re.sub(r"\[\d+(?:,\s*\d+)*\]", "", text)  # citation markers
    text = re.sub(r"\$+([^$]*)\$+", r"\1", text)
    text = re.sub(r"[*_`#>|]", "", text)
    text = re.sub(r"https?://\S+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def split_sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE_END.split(text) if s.strip()]


class Speaker:
    def __init__(self, engine: str = "edge") -> None:
        self._engine = engine
        self._proc: subprocess.Popen | None = None
        self._stop = threading.Event()
        self._tmp = Path(tempfile.mkdtemp(prefix="sabi-tts-"))
        self._count = 0

    def stop(self) -> None:
        self._stop.set()
        proc = self._proc
        if proc and proc.poll() is None:
            proc.terminate()

    def speak(self, text: str, lang: Language) -> None:
        """Blocking. Speak a complete text."""
        q: queue.Queue = queue.Queue()
        for sentence in split_sentences(text):
            q.put(sentence)
        q.put(None)
        self.speak_queue(q, lang)

    def speak_queue(self, q: queue.Queue, lang: Language) -> None:
        """Blocking. Speak sentences from `q` as they arrive, until None. The next sentence is
        synthesized while the current one plays, so speech can start before the answer is finished."""
        self._stop.clear()
        loop = asyncio.new_event_loop()
        try:
            text = self._next(q)
            audio = self._render(loop, text, lang)
            while text is not None and not self._stop.is_set():
                player = threading.Thread(target=self._play, args=(audio,))
                player.start()
                text = self._next(q)
                audio = self._render(loop, text, lang) if text is not None else None
                player.join()
        finally:
            loop.close()
            # Drain so a producer never blocks on a full queue after Esc.
            while not q.empty():
                q.get_nowait()

    def _next(self, q: queue.Queue) -> str | None:
        while not self._stop.is_set():
            try:
                item = q.get(timeout=0.1)
            except queue.Empty:
                continue
            if item is None:
                return None
            if text := speakable(item):
                return text
        return None

    def _render(self, loop, text: str, lang: Language) -> list[str]:
        """Command that plays this sentence: a neural-voice MP3, or the offline system voice."""
        if self._engine == "edge":
            self._count += 1
            path = loop.run_until_complete(self._synth(text, lang, self._count))
            if path is not None:
                return ["afplay", str(path)]
        return ["say", "-v", lang.say_voice, text]

    async def _synth(self, sentence: str, lang: Language, index: int) -> Path | None:
        import edge_tts

        out = self._tmp / f"s{index}.mp3"
        try:
            await asyncio.wait_for(edge_tts.Communicate(sentence, lang.edge_voice).save(str(out)), timeout=8)
            return out
        except Exception:
            return None

    def _play(self, cmd: list[str]) -> None:
        if self._stop.is_set():
            return
        self._proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self._proc.wait()
