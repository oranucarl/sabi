"""Learning journal and spaced-repetition review (SM-2).

Every answered question is logged with its subject and topic. Each topic becomes a review card;
"quiz me" asks a question on a due card, the learner answers out loud, the answer is graded 0–5,
and SM-2 schedules the next review. All data stays on the device.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

DAY = 86_400.0


@dataclass
class Card:
    topic: str
    subject: str
    ease: float
    interval_days: float
    reps: int
    due: float
    last_question: str


def sm2(card: Card, grade: int, now: float) -> Card:
    """Standard SM-2 update. grade: 0 (blank) … 5 (perfect)."""
    grade = max(0, min(5, grade))
    if grade < 3:
        card.reps = 0
        card.interval_days = 1
    else:
        card.reps += 1
        card.interval_days = 1 if card.reps == 1 else 6 if card.reps == 2 else round(card.interval_days * card.ease)
    card.ease = max(1.3, card.ease + 0.1 - (5 - grade) * (0.08 + (5 - grade) * 0.02))
    card.due = now + card.interval_days * DAY
    return card


class Journal:
    def __init__(self, db_path: Path) -> None:
        self._db = sqlite3.connect(str(db_path), check_same_thread=False)
        self._lock = threading.Lock()  # answers are filed from a background thread
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS entries (
                id INTEGER PRIMARY KEY, ts REAL, app TEXT, question TEXT, answer TEXT,
                subject TEXT, topic TEXT, language TEXT, sources TEXT);
            CREATE TABLE IF NOT EXISTS cards (
                topic TEXT PRIMARY KEY, subject TEXT, ease REAL DEFAULT 2.5, interval_days REAL DEFAULT 0,
                reps INTEGER DEFAULT 0, due REAL, last_question TEXT);
            CREATE TABLE IF NOT EXISTS attempts (
                id INTEGER PRIMARY KEY, ts REAL, topic TEXT, question TEXT, answer TEXT, grade INTEGER);
            """
        )

    def log(self, app: str, question: str, answer: str, subject: str, topic: str, language: str, sources: str) -> None:
        with self._lock:
            self._log(app, question, answer, subject, topic, language, sources)

    def _log(self, app: str, question: str, answer: str, subject: str, topic: str, language: str, sources: str) -> None:
        now = time.time()
        self._db.execute(
            "INSERT INTO entries (ts, app, question, answer, subject, topic, language, sources) VALUES (?,?,?,?,?,?,?,?)",
            (now, app, question, answer, subject, topic, language, sources),
        )
        if topic:
            self._db.execute(
                "INSERT OR IGNORE INTO cards (topic, subject, due, last_question) VALUES (?, ?, ?, ?)",
                (topic, subject, now + DAY, question),
            )
        self._db.commit()

    def due_card(self, now: float | None = None, include_new: bool = True) -> Card | None:
        """Most overdue card. With include_new, falls back to the least-practised card so a demo
        can review something learned minutes ago."""
        now = now or time.time()
        row = self._db.execute(
            "SELECT topic, subject, ease, interval_days, reps, due, last_question FROM cards WHERE due <= ? ORDER BY due LIMIT 1",
            (now,),
        ).fetchone()
        if row is None and include_new:
            row = self._db.execute(
                "SELECT topic, subject, ease, interval_days, reps, due, last_question FROM cards ORDER BY reps, due LIMIT 1"
            ).fetchone()
        return Card(*row) if row else None

    def record_attempt(self, card: Card, question: str, answer: str, grade: int) -> Card:
        with self._lock:
            return self._record_attempt(card, question, answer, grade)

    def _record_attempt(self, card: Card, question: str, answer: str, grade: int) -> Card:
        now = time.time()
        card = sm2(card, grade, now)
        self._db.execute(
            "INSERT INTO attempts (ts, topic, question, answer, grade) VALUES (?,?,?,?,?)",
            (now, card.topic, question, answer, grade),
        )
        self._db.execute(
            "UPDATE cards SET ease=?, interval_days=?, reps=?, due=?, last_question=? WHERE topic=?",
            (card.ease, card.interval_days, card.reps, card.due, question, card.topic),
        )
        self._db.commit()
        return card

    def mastery(self) -> list[tuple[str, str, float, int]]:
        """(subject, topic, mastery 0–1, times asked) for every studied topic."""
        rows = self._db.execute(
            """
            SELECT c.subject, c.topic, c.reps, c.ease,
                   (SELECT COUNT(*) FROM entries e WHERE e.topic = c.topic),
                   (SELECT AVG(grade) FROM attempts a WHERE a.topic = c.topic)
            FROM cards c
            """
        ).fetchall()
        out = []
        for subject, topic, reps, ease, asked, avg_grade in rows:
            graded = (avg_grade or 0) / 5
            score = min(1.0, 0.15 + 0.25 * reps + 0.4 * graded) if avg_grade is not None else 0.15
            out.append((subject or "General", topic, round(score, 2), asked))
        return out

    def today(self) -> list[tuple[str, str]]:
        since = time.time() - DAY
        return list(self._db.execute("SELECT subject, topic FROM entries WHERE ts >= ? AND topic != '' GROUP BY topic", (since,)))
