"""The tutor loop: listen → understand → look → answer → point → speak → remember.

Runs work on one background thread and talks to the UI only through Qt signals.
"""

from __future__ import annotations

import json
import queue
import re
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import Quartz
from PyQt6.QtCore import QObject, pyqtSignal

from sabi import intents
from sabi.ai.chatgpt import ChatGPTModel, ChatGPTProvider, ChatGPTSession
from sabi.ai import prompt
from sabi.ai.providers import ClaudeProvider, Message, OllamaProvider, OllamaTools
from sabi.audio.recorder import Recorder, duration
from sabi.audio.stt import Transcriber
from sabi.audio.tts import Speaker, split_sentences
from sabi.config import Settings
from sabi.language import LANGUAGES, Language, LanguageTracker, requested_switch
from sabi.learning import pathways
from sabi.learning.journal import Card, Journal
from sabi.learning.library import Library, format_sources
from sabi.platform.macos import screens, windows

MAX_HISTORY = 12


def log(msg: str) -> None:
    print(f"[sabi {time.strftime('%H:%M:%S')}] {msg}", flush=True)


@dataclass
class Review:
    card: Card
    question: str
    reference: str  # the correct answer, written in English before the learner replies
    source: str  # library citation backing the reference, if any


def cursor_position() -> tuple[float, float]:
    loc = Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))
    return loc.x, loc.y


class Controller(QObject):
    state_changed = pyqtSignal(str)  # idle | listening | thinking | speaking
    transcript = pyqtSignal(str)
    answer_delta = pyqtSignal(str)  # full visible text so far
    answer_done = pyqtSignal(str, list)  # text, source labels
    point_at = pyqtSignal(float, float, str)
    clear_point = pyqtSignal()
    show_markdown = pyqtSignal(str, str)  # title, markdown
    notice = pyqtSignal(str)
    language_changed = pyqtSignal(str)
    provider_changed = pyqtSignal(object)

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        settings.ensure_dirs()
        self.settings = settings
        self.recorder = Recorder()
        self.stt = Transcriber(settings.whisper_model)
        self.speaker = Speaker(settings.tts_engine)
        self.languages = LanguageTracker(settings.reply_language)
        self.tools = OllamaTools(settings.ollama_url, settings.vision_model, settings.embed_model)
        self.local = OllamaProvider(settings.ollama_url, settings.vision_model)
        self.cloud = ClaudeProvider(settings.anthropic_api_key, settings.anthropic_model) if settings.use_cloud else None
        self.chatgpt_session = ChatGPTSession(settings.data_dir)
        self.chatgpt = ChatGPTProvider(self.chatgpt_session)
        self._provider_mode = "chatgpt" if self.chatgpt_session.enabled else ("claude" if self.cloud else "local")
        self._chatgpt_models: list[ChatGPTModel] = []
        self.journal = Journal(settings.data_dir / "journal.db")
        self.library = Library(settings.data_dir / "library.db", embed=self.tools.embed)
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sabi-worker")
        self._busy = threading.Lock()
        self._listening = False
        self._history: list[Message] = []
        self._last_answer = ""
        self._last_lang: Language = LANGUAGES["en"]
        self._steps: list[str] = []
        self._step = 0
        self._review: Review | None = None
        self.state = "idle"

    # ---- lifecycle ---------------------------------------------------------------------------

    def warm_up(self) -> None:
        def run():
            try:
                self.stt.warm_up()
            except Exception as exc:
                self.notice.emit(f"Speech model failed to load: {exc}")
            if self.tools.available():
                try:
                    self.tools.warm()
                    log("model warmed up")
                except Exception as exc:
                    log(f"warm-up failed: {exc!r}")
            elif not self.cloud and not self.chatgpt_session.connected:
                self.notice.emit("Ollama is not running. Start it, or connect your ChatGPT plan.")
            if self.chatgpt_session.connected:
                try:
                    self._chatgpt_models = self.chatgpt_session.list_models()
                except Exception as exc:
                    log(f"ChatGPT model refresh failed: {exc!r}")
                    self.notice.emit(f"ChatGPT needs attention: {exc}")
                self._emit_provider()

        threading.Thread(target=run, daemon=True).start()

    @property
    def provider(self):
        if self._provider_mode == "chatgpt" and self.chatgpt_session.enabled:
            return self.chatgpt
        if self._provider_mode == "claude" and self.cloud:
            return self.cloud
        return self.local

    def provider_snapshot(self) -> dict:
        return {
            "mode": self._provider_mode,
            "connected": self.chatgpt_session.connected,
            "email": self.chatgpt_session.email,
            "selected_model": self.chatgpt_session.selected_model,
            "models": [(m.display_name, m.slug) for m in self._chatgpt_models],
            "active_name": self.provider.name,
        }

    def _emit_provider(self) -> None:
        self.provider_changed.emit(self.provider_snapshot())

    def connect_chatgpt(self) -> None:
        self._set_state("connecting")
        self._pool.submit(self._guard, self._connect_chatgpt)

    def _connect_chatgpt(self) -> None:
        self.notice.emit("Finish signing in with ChatGPT in your browser…")
        try:
            self._chatgpt_models = self.chatgpt_session.sign_in()
        except Exception:
            # Authorization may have completed before model discovery failed. Reflect the saved
            # connection in the UI so the learner can disconnect or retry cleanly.
            self._emit_provider()
            raise
        self._provider_mode = "chatgpt"
        self.chatgpt_session.set_enabled(True)
        self._history = []
        self._emit_provider()
        self.notice.emit(f"Using your ChatGPT plan with {self.chatgpt_session.selected_model}.")

    def disconnect_chatgpt(self) -> None:
        self._set_state("thinking")
        self._pool.submit(self._guard, self._disconnect_chatgpt)

    def _disconnect_chatgpt(self) -> None:
        self.chatgpt_session.sign_out()
        self._provider_mode = "local"
        self._chatgpt_models = []
        self._history = []
        self._emit_provider()
        self.notice.emit("ChatGPT disconnected. SAbi is using local Ollama.")

    def select_provider(self, value: str) -> None:
        if value == "local":
            self._provider_mode = "local"
            self.chatgpt_session.set_enabled(False)
        elif value == "claude" and self.cloud:
            self._provider_mode = "claude"
            self.chatgpt_session.set_enabled(False)
        elif value.startswith("chatgpt:") and self.chatgpt_session.connected:
            self.chatgpt_session.set_model(value.split(":", 1)[1])
            self.chatgpt_session.set_enabled(True)
            self._provider_mode = "chatgpt"
        else:
            return
        self._history = []
        self._emit_provider()

    def _set_state(self, state: str) -> None:
        self.state = state
        self.state_changed.emit(state)

    # ---- input -------------------------------------------------------------------------------

    def on_hotkey_press(self) -> None:
        if self._listening or self._busy.locked() and self.state == "thinking":
            return
        self.speaker.stop()
        try:
            self.recorder.start()
        except Exception as exc:
            self.notice.emit(f"Microphone unavailable: {exc}")
            return
        self._listening = True
        log("hotkey down: recording")
        self._set_state("listening")

    def on_hotkey_release(self) -> None:
        if not self._listening:
            return
        self._listening = False
        audio = self.recorder.stop()
        log(f"hotkey up: {duration(audio):.1f}s of audio, peak {float(abs(audio).max()) if audio.size else 0:.3f}")
        self._set_state("thinking")
        self._pool.submit(self._guard, self._handle_voice, audio)

    def on_escape(self) -> None:
        self.speaker.stop()

    def ask_text(self, text: str) -> None:
        """Typed questions: for noisy rooms, and learners who can't or prefer not to speak."""
        if text.strip():
            self._set_state("thinking")
            self._pool.submit(self._guard, self._handle_text, text.strip(), "", 99.0)

    def add_document(self, path: str) -> None:
        def run():
            self.notice.emit(f"Reading {Path(path).name}…")
            n = self.library.add(Path(path))
            self.notice.emit(f"Added {Path(path).name} to your library ({n} passages). Answers will cite it.")

        self._pool.submit(self._guard, run)

    def show_pathways(self, speak: bool = False) -> None:
        self._pool.submit(self._guard, self._pathways, speak)

    def start_quiz(self) -> None:
        self._set_state("thinking")
        self._pool.submit(self._guard, self._quiz)

    def set_language(self, code: str) -> None:
        if code == "auto":
            self.languages = LanguageTracker("auto")
        else:
            self.languages.pin(code)
        self.language_changed.emit(code)

    # ---- worker --------------------------------------------------------------------------------

    def _guard(self, fn, *args) -> None:
        with self._busy:
            try:
                fn(*args)
            except Exception as exc:
                traceback.print_exc()
                log(f"error: {exc!r}")
                self.notice.emit(f"Something went wrong: {exc}")
            finally:
                self.clear_point.emit()
                self._set_state("idle")

    def _handle_voice(self, audio: np.ndarray) -> None:
        seconds = duration(audio)
        text, whisper_lang = self.stt.transcribe(audio)
        if not text:
            self.notice.emit("I didn't catch that. Hold Control+Option while you speak.")
            return
        self._handle_text(text, whisper_lang, seconds)

    def _handle_text(self, text: str, whisper_lang: str, seconds: float) -> None:
        log(f"heard ({whisper_lang or 'typed'}): {text!r}")
        self.transcript.emit(text)

        if intents.is_stop(text):
            self._steps, self._review = [], None
            return
        if self._steps and intents.is_next(text, seconds):
            return self._next_step()
        if intents.is_repeat(text, seconds) and self._last_answer:
            return self._say(self._last_answer, self._last_lang)
        if code := requested_switch(text):
            lang = self.languages.pin(code)
            self.language_changed.emit(code)
            return self._say(self._complete(f"In one short sentence, tell the learner you will now speak {lang.name}.", lang), lang)
        if self._review:
            return self._grade(text)
        if intents.is_quiz(text):
            return self._quiz()
        if intents.is_pathways(text):
            return self._pathways(speak=True)

        lang = self.languages.update(text, whisper_lang)
        self._answer(text, lang)

    def _answer(self, question: str, lang: Language) -> None:
        app, window = windows.frontmost_context()
        shot = None
        wants_screen = intents.needs_screen(question) or bool(self._steps)
        if wants_screen and windows.has_screen_recording() and not intents.is_sensitive(app, window):
            shot = screens.capture_screen_at(*cursor_position())

        sources = self.library.search(question) if self.library.documents() else []
        ctx = prompt.PromptContext(
            lang=lang,
            app=app,
            window=window,
            image_size=(shot.image_width, shot.image_height) if shot else None,
            sources=format_sources(sources),
            lesson_step=(self._step + 1, len(self._steps)) if self._steps else None,
        )
        log(f"asking {self.provider.name}; screenshot={'yes' if shot else 'no'} app={app!r} sources={len(sources)}")

        # Speak sentence by sentence while the answer streams in. Speech stops at a numbered list:
        # lessons are taught one step at a time once the full list is known.
        speech: queue.Queue = queue.Queue()
        voice = threading.Thread(target=self.speaker.speak_queue, args=(speech, lang), daemon=True)
        spoken: list[str] = []
        said_upto, streaming, pointed = 0, True, False

        def say(sentences: list[str]) -> None:
            if not sentences:
                return
            if not voice.is_alive() and not spoken:
                log(f"speaking [{lang.code}] (streaming)")
                self._set_state("speaking")
                voice.start()
            for sentence in sentences:
                speech.put(sentence)
                spoken.append(sentence)

        raw = shown = ""
        system = prompt.build_system(ctx)
        turn = prompt.user_turn(question, lang, cite=bool(sources))
        for delta in self.provider.stream(system, self._history, turn, shot.jpeg_b64 if shot else None):
            raw += delta
            shown = prompt.visible(raw if sources else prompt.strip_citations(raw))
            self.answer_delta.emit(shown)
            if shot and not pointed and (m := prompt.POINT_RE.search(raw)):
                pointed = True
                x, y = shot.to_screen(float(m.group(1)), float(m.group(2)))
                self.point_at.emit(x, y, (m.group(3) or "").strip())
            if streaming:
                pending = shown[said_upto:]
                if steps_start := re.search(r"(?:^|\n)\s*1[.)]\s", pending):
                    pending, streaming = pending[: steps_start.start()], False
                ends = [m.end() for m in re.finditer(r"[.!?](?=\s)", pending)]
                cut = len(pending) if not streaming else (ends[-1] if ends else 0)
                if cut:
                    say(split_sentences(pending[:cut]))
                    said_upto += cut

        reply = prompt.parse(raw if sources else prompt.strip_citations(raw))
        cited = [s for s in sources if f"[{s.number}]" in reply.text]
        self.answer_done.emit(reply.text, [f"[{s.number}] {s.label}" for s in cited])
        self._history += [Message("user", question), Message("assistant", reply.text)]
        self._history = self._history[-MAX_HISTORY:]

        if reply.steps and not streaming:
            self._steps, self._step = reply.steps, 0
            say([f"Step 1 of {len(self._steps)}: {self._steps[0]}", "Say next when you are ready."])
        else:
            say(split_sentences(shown[said_upto:]) if streaming else [])
        speech.put(None)
        if voice.is_alive():
            voice.join()
        self._last_answer, self._last_lang = " ".join(spoken), lang

        # File the question under a syllabus topic in the background, so the next question never waits for it.
        def file_topic() -> None:
            try:
                subject, topic = pathways.clean_classification(self._json(pathways.classify_prompt(question, reply.text)))
            except Exception as exc:
                log(f"topic filing failed: {exc!r}")
                subject, topic = "", ""
            self.journal.log(app, question, reply.text, subject, topic, lang.code, json.dumps([s.label for s in cited]))

        threading.Thread(target=file_topic, name="sabi-journal", daemon=True).start()

    def _next_step(self) -> None:
        self._step += 1
        lang = self._last_lang
        if self._step >= len(self._steps):
            self._steps = []
            return self._say(self._complete("In one short sentence, congratulate the learner on finishing all the steps.", lang), lang)
        line = f"Step {self._step + 1} of {len(self._steps)}: {self._steps[self._step]}"
        if self._step + 1 < len(self._steps):
            line += " Say next when you are ready."
        self.answer_done.emit(line, [])
        self._last_answer = line
        self._say(line, lang)

    def _say(self, text: str, lang: Language) -> None:
        log(f"speaking [{lang.code}] {len(text)} chars")
        self._set_state("speaking")
        self.speaker.speak(text, lang)

    def _complete(self, instruction: str, lang: Language) -> str:
        system = f"You are SAbi, a warm tutor. {prompt.language_rule(lang)} Reply in plain text, no tags."
        return "".join(self.provider.stream(system, [], instruction, None)).strip()

    # ---- review & pathways ---------------------------------------------------------------------

    def _quiz(self) -> None:
        lang = self.languages.update("", "")
        card = self.journal.due_card()
        if card is None:
            msg = self._complete("Tell the learner in one sentence that there is nothing to review yet: ask SAbi some questions first.", lang)
            self.answer_done.emit(msg, [])
            return self._say(msg, lang)
        hits = self.library.search(f"{card.topic} {card.last_question}", k=2) if self.library.documents() else []
        grounding = (
            f"Base the question and answer ONLY on these notes from the learner's library:\n{format_sources(hits)}\n\n"
            if hits
            else "Use only well-established textbook facts.\n\n"
        )
        made = self._json(
            f"{grounding}Write ONE short quiz question, answerable out loud in one sentence, that checks understanding of "
            f"'{card.topic}' ({card.subject}). The learner earlier asked: '{card.last_question}'.\n"
            'Return JSON {"question": "<question in English>", "answer": "<the correct answer, one accurate sentence>"}'
        )
        question_en, reference = str(made.get("question", "")).strip(), str(made.get("answer", "")).strip()
        if not question_en or not reference:
            raise RuntimeError("couldn't write a quiz question; try again")
        question = question_en
        if lang.code != "en":
            question = self._complete(f"Translate this quiz question for the learner. Output only the question: {question_en}", lang)
        source = hits[0].label if hits else ""
        self._review = Review(card, question, reference, source)
        self.answer_done.emit(f"Quiz — {card.topic}\n\n{question}\n\n(Hold Control+Option and answer out loud.)", [])
        self._last_answer, self._last_lang = question, lang
        self._say(question, lang)

    def _grade(self, answer: str) -> None:
        review, self._review = self._review, None
        lang = self._last_lang
        result = self._json(
            f"Question: {review.question}\nCorrect answer: {review.reference}\n"
            f"Learner's spoken answer (from speech recognition; ignore small transcription errors): {answer}\n\n"
            "Compare the learner's answer with the correct answer only; do not add other facts. Grade 0-5 "
            "(0 = wrong or no idea, 3 = partly correct, 5 = fully correct). Then write one or two encouraging sentences "
            "of feedback that state the correct answer if they missed it.\n"
            f"Feedback language rule: {prompt.language_rule(lang)}\n"
            'Return JSON {"grade": <int>, "feedback": "<text>"}'
        )
        try:
            grade = max(0, min(5, int(result.get("grade", 0))))
        except (TypeError, ValueError):
            grade = 0
        feedback = str(result.get("feedback", "")).strip() or f"The answer is: {review.reference}"
        card = self.journal.record_attempt(review.card, review.question, answer, grade)
        days = int(card.interval_days)
        self.answer_done.emit(
            f"{feedback}\n\nCorrect answer: {review.reference}\nScore {grade}/5 · next review in {days} day{'s' if days != 1 else ''}.",
            [review.source] if review.source else [],
        )
        self._last_answer = feedback
        self._say(feedback, lang)

    def _json(self, instruction: str) -> dict:
        if self.tools.available():
            return self.tools.json(instruction)
        raw = self._complete(instruction + "\nOutput only the JSON.", LANGUAGES["en"])
        m = re.search(r"\{.*\}", raw, re.S)
        try:
            return json.loads(m.group(0)) if m else {}
        except json.JSONDecodeError:
            return {}

    def _pathways(self, speak: bool) -> None:
        paths = pathways.build(self.journal.mastery())
        self.show_markdown.emit("Your learning path", pathways.as_markdown(paths))
        if not speak:
            return
        lang = self.languages.update("", "")
        if not paths:
            text = self._complete("In one sentence, tell the learner to ask a few study questions first so you can map their next steps.", lang)
        else:
            text = self._complete(
                "Using only these facts, tell the learner in three short sentences what is going well, what to learn next, "
                f"and where it can lead. The links are on screen. Facts: {pathways.as_speech_brief(paths)}",
                lang,
            )
        self._last_answer, self._last_lang = text, lang
        self._say(text, lang)

    def shutdown(self) -> None:
        self.speaker.stop()
        self._pool.shutdown(wait=False, cancel_futures=True)
        self.chatgpt_session.close()
