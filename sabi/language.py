"""Reply language and voice selection, with Nigerian Pidgin as a first-class option."""

from __future__ import annotations

import re
from dataclasses import dataclass

PIDGIN = "pcm"

# Words that are common in Pidgin and rare in standard English.
_PIDGIN_MARKERS = re.compile(
    r"\b(wetin|abeg|una|dey|wahala|oya|sabi|abi|shey|sef|comot|pikin|dem go|no be|e don|how far|wey|o jare|wan)\b",
    re.IGNORECASE,
)
_SWITCH_TO = re.compile(
    r"\b(?:speak|talk|answer|reply|explain)\b.*\b(pidgin|english|french|portuguese|arabic|swahili|yoruba|hausa|igbo)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Language:
    code: str
    name: str
    edge_voice: str  # neural voice (needs internet)
    say_voice: str  # offline macOS voice


LANGUAGES: dict[str, Language] = {
    "en": Language("en", "English", "en-NG-EzinneNeural", "Samantha"),
    PIDGIN: Language(PIDGIN, "Nigerian Pidgin", "en-NG-AbeoNeural", "Samantha"),
    "fr": Language("fr", "French", "fr-FR-DeniseNeural", "Thomas"),
    "pt": Language("pt", "Portuguese", "pt-BR-FranciscaNeural", "Luciana"),
    "ar": Language("ar", "Arabic", "ar-EG-SalmaNeural", "Majed"),
    "sw": Language("sw", "Swahili", "sw-KE-ZuriNeural", "Samantha"),
    # Whisper's recognition of these is weaker; replies are written in the language
    # and read with a Nigerian English voice.
    "yo": Language("yo", "Yoruba", "en-NG-EzinneNeural", "Samantha"),
    "ha": Language("ha", "Hausa", "en-NG-AbeoNeural", "Samantha"),
    "ig": Language("ig", "Igbo", "en-NG-EzinneNeural", "Samantha"),
}
_BY_NAME = {lang.name.split()[-1].lower(): lang.code for lang in LANGUAGES.values()}


def requested_switch(text: str) -> str | None:
    """'Abeg talk Pidgin' / 'explain in French' → language code."""
    m = _SWITCH_TO.search(text)
    return _BY_NAME.get(m.group(1).lower()) if m else None


def looks_like_pidgin(text: str) -> bool:
    return len(_PIDGIN_MARKERS.findall(text)) >= 2


class LanguageTracker:
    """Picks the reply language. A detected change must repeat before it sticks, because learners
    mix Pidgin and English freely and single-turn detection flips back and forth."""

    def __init__(self, pinned: str = "auto") -> None:
        self.pinned = pinned if pinned in LANGUAGES else None
        self.current = self.pinned or "en"
        self._candidate: str | None = None

    def update(self, transcript: str, whisper_lang: str) -> Language:
        if self.pinned:
            return LANGUAGES[self.pinned]
        if looks_like_pidgin(transcript):
            # Unambiguous: switch at once. Whisper reports Pidgin as English, so this never flip-flops.
            self.current, self._candidate = PIDGIN, None
            return LANGUAGES[PIDGIN]
        detected = whisper_lang
        if self.current == PIDGIN and detected == "en":
            # Pidgin speakers often ask in plain English too; stay in Pidgin until they ask to switch.
            return LANGUAGES[PIDGIN]
        if detected not in LANGUAGES or detected == self.current:
            self._candidate = None
        elif detected == self._candidate:
            self.current, self._candidate = detected, None
        else:
            self._candidate = detected
        return LANGUAGES[self.current]

    def pin(self, code: str) -> Language:
        self.pinned = code
        self.current = code
        return LANGUAGES[code]
