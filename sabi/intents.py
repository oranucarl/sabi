"""Voice commands handled before the model, in English and Pidgin."""

from __future__ import annotations

import re

_STOP = re.compile(r"^\W*(stop|quiet|be quiet|shut up|abeg stop|that'?s enough|cancel)\W*$", re.I)
_NEXT = re.compile(r"^\W*(next( step)?|continue|go on|carry go|wetin next|and then|okay next|ok next)\W*$", re.I)
_REPEAT = re.compile(r"^\W*(repeat( that)?|say (that|it|am) again|again|come again|one more time|i no hear)\W*$", re.I)
_QUIZ = re.compile(r"\b(quiz me|test me|ask me (a )?question|revise with me|review (time|with me)|make we revise)\b", re.I)
_PATH = re.compile(
    r"\b(what should i (learn|study) next|what (do i|to) (learn|study) next|what next for me|my (learning )?(path|progress)"
    r"|where (can|will) (this|my learning) (take|lead) me|wetin i go (learn|read) next)\b",
    re.I,
)
# Short commands only count when the clip is short: Whisper turns mumbles into "Continue."
SHORT_COMMAND_SECONDS = 2.5


def is_stop(text: str) -> bool:
    return bool(_STOP.match(text))


def is_next(text: str, seconds: float) -> bool:
    return seconds <= SHORT_COMMAND_SECONDS and bool(_NEXT.match(text))


def is_repeat(text: str, seconds: float) -> bool:
    return seconds <= SHORT_COMMAND_SECONDS and bool(_REPEAT.match(text))


def is_quiz(text: str) -> bool:
    return bool(_QUIZ.search(text))


def is_pathways(text: str) -> bool:
    return bool(_PATH.search(text))


_SCREEN = re.compile(
    r"\b(this|that|these|those|here|there|screen|page|see|look|showing|shown|click|button|menu|tab|window|"
    r"where|open|error|highlight|point|says?|dis|dat|wetin dey)\b|\bhow (do|can|to|should) i\b",
    re.I,
)


def needs_screen(text: str) -> bool:
    """Questions about what's on screen get a screenshot; general study questions skip it (about 2× faster)."""
    return bool(_SCREEN.search(text))


_SENSITIVE = re.compile(r"\b(password|passcode|1password|keychain|bank|banking|wallet|otp|pin code|login|sign in)\b", re.I)


def is_sensitive(app: str, window: str) -> bool:
    """Don't send screenshots of password managers, banking or sign-in screens."""
    return bool(_SENSITIVE.search(f"{app} {window}"))
