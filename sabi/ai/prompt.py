"""System prompt and the reply tag contract."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from sabi.language import PIDGIN, Language

_PERSONA = """You are SAbi, a patient tutor who sits beside a learner's screen. "Sabi" is Nigerian Pidgin for "to know".
Your learners are mostly secondary-school and university students and early-career people in Africa, often on
slow internet and shared devices. Teach, don't just tell: explain simply, use local, everyday examples
(markets, danfo buses, naira, football, farming) when they help, and check understanding.

Your reply is read aloud, so:
- Keep it short: 2–4 sentences for simple questions. No markdown, no bullet symbols, no emojis.
- For a task with several steps, give numbered steps ("1. ...", "2. ...") of one sentence each; the learner
  will say "next" to hear them one at a time.
- Write maths in words a person would say ("x squared plus two x"), not symbols or LaTeX.
- If you are not sure, say so. Never invent facts, quotes, statistics, or links."""

_POINTING = """SCREEN: the attached screenshot is {w}x{h} pixels; it shows the learner's current screen ({app}).
If pointing at something on the screen would help (a button, menu, field, word, formula, diagram),
add ONE tag at the very end: [POINT:x,y:short label] where x,y are pixel coordinates of its centre in
the screenshot. Only point at things you can actually see. Don't point for general questions."""

_SOURCES = """LIBRARY: excerpts from the learner's own documents are below, numbered. Base your answer on them when they
are relevant and cite them with their number in brackets, like [1] or [2]. If they do not answer the question,
say that their notes do not cover it, then answer from general knowledge and say so.

{sources}"""

_LESSON = """LESSON PROGRESS: the learner is on step {step} of {total} of your earlier steps. Answer their question
about this step, then remind them to say "next" to continue."""


def language_rule(lang: Language) -> str:
    if lang.code == PIDGIN:
        return (
            "LANGUAGE: You MUST reply in Nigerian Pidgin English, not standard English, the way a friendly Lagos teacher "
            "talks. Example of the style: \"Na equation wey the highest power of x be two. E dey look like a x squared plus "
            "b x plus c equal zero. You don get am?\" Keep technical terms and button names in English."
        )
    if lang.code == "en":
        return "LANGUAGE: Reply in clear, simple English."
    return f"LANGUAGE: Reply entirely in {lang.name}. Keep on-screen button and menu names exactly as they appear."


@dataclass
class PromptContext:
    lang: Language
    app: str = ""
    window: str = ""
    image_size: tuple[int, int] | None = None
    sources: str = ""
    lesson_step: tuple[int, int] | None = None
    extra: list[str] = field(default_factory=list)


def build_system(ctx: PromptContext) -> str:
    parts = [_PERSONA, f"Today is {date.today():%A %d %B %Y}."]
    if ctx.image_size:
        where = ctx.app + (f' — "{ctx.window}"' if ctx.window else "")
        parts.append(_POINTING.format(w=ctx.image_size[0], h=ctx.image_size[1], app=where or "unknown app"))
    if ctx.sources:
        parts.append(_SOURCES.format(sources=ctx.sources))
    if ctx.lesson_step:
        parts.append(_LESSON.format(step=ctx.lesson_step[0], total=ctx.lesson_step[1]))
    parts += ctx.extra
    parts.append(language_rule(ctx.lang))  # last, where small local models weigh it most
    return "\n\n".join(parts)


def user_turn(question: str, lang: Language, cite: bool = False) -> str:
    """Small models drift from system rules; short reminders on the question itself keep them on track."""
    notes = []
    if cite:
        notes.append("Use the numbered notes from the learner's library and cite them like [1]")
    if lang.code != "en":
        notes.append(f"Answer in {lang.name}")
    return f"{question}\n\n({'. '.join(notes)}.)" if notes else question


# ---- reply parsing -------------------------------------------------------------------------------

POINT_RE = re.compile(r"\[POINT:\s*(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)\s*(?::\s*([^\]]*))?\]")
_ANY_TAG = re.compile(r"\[(?:POINT|TOPIC):[^\]]*\]")
_PARTIAL_TAG = re.compile(r"\[[A-Z]*(?::[^\]]*)?$")
_STEP_RE = re.compile(r"^\s*(\d+)[.)]\s+(.*\S)", re.MULTILINE)


@dataclass
class Reply:
    text: str  # what the learner sees and hears
    point: tuple[float, float, str] | None
    steps: list[str]


_CITATION = re.compile(r"\s*\[\d+(?:\s*,\s*\d+)*\]")


def strip_citations(text: str) -> str:
    """Remove [n] markers, e.g. when the model cites notes that weren't provided this turn."""
    return _CITATION.sub("", text)


def visible(partial: str) -> str:
    """Text safe to display while streaming: completed tags removed, a half-written tag held back."""
    return _PARTIAL_TAG.sub("", _ANY_TAG.sub("", partial)).rstrip()


def parse(raw: str) -> Reply:
    point = None
    if m := POINT_RE.search(raw):
        point = (float(m.group(1)), float(m.group(2)), (m.group(3) or "").strip())
    text = _ANY_TAG.sub("", raw).strip()
    steps = [s for _, s in _STEP_RE.findall(text)]
    return Reply(text=text, point=point, steps=steps if len(steps) >= 2 else [])
