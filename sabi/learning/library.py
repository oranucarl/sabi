"""Local document library with cited retrieval.

Learners drop in PDFs or text notes (past questions, textbooks, lecture notes). Pages are split into
chunks, embedded locally with Ollama, and stored in SQLite. Every answer that uses the library
cites the document and page, so learners can check the source themselves.
Without an embedding model, retrieval falls back to keyword overlap so it still works offline.
"""

from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

CHUNK_CHARS = 900
CHUNK_OVERLAP = 150
_WORD = re.compile(r"[a-zA-Z0-9]{3,}")


@dataclass(frozen=True)
class Source:
    number: int
    title: str
    page: int
    text: str
    path: str

    @property
    def label(self) -> str:
        return f"{self.title}, p. {self.page}" if self.page else self.title


def _read_pages(path: Path) -> list[tuple[int, str]]:
    if path.suffix.lower() == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        return [(i + 1, page.extract_text() or "") for i, page in enumerate(reader.pages)]
    return [(0, path.read_text(errors="ignore"))]


def _chunks(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    out, start = [], 0
    while start < len(text):
        end = min(len(text), start + CHUNK_CHARS)
        if end < len(text):
            cut = text.rfind(". ", start + CHUNK_CHARS // 2, end)
            end = cut + 1 if cut != -1 else end
        out.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - CHUNK_OVERLAP, start + 1)
    return out


class Library:
    def __init__(self, db_path: Path, embed=None) -> None:
        """`embed` is a callable list[str] -> list[list[float]], or None for keyword-only mode."""
        self._db = sqlite3.connect(str(db_path), check_same_thread=False)
        self._embed = embed
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY, path TEXT UNIQUE, title TEXT, added_at REAL);
            CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY, doc_id INTEGER REFERENCES documents(id) ON DELETE CASCADE,
                page INTEGER, text TEXT, embedding BLOB);
            """
        )

    def documents(self) -> list[tuple[int, str]]:
        return list(self._db.execute("SELECT id, title FROM documents ORDER BY added_at DESC"))

    def add(self, path: Path) -> int:
        """Index a document. Returns the number of chunks stored."""
        path = path.expanduser().resolve()
        self._db.execute("DELETE FROM documents WHERE path = ?", (str(path),))
        cur = self._db.execute(
            "INSERT INTO documents (path, title, added_at) VALUES (?, ?, ?)", (str(path), path.stem, time.time())
        )
        doc_id = cur.lastrowid
        rows = [(page, chunk) for page, text in _read_pages(path) for chunk in _chunks(text)]
        vectors: list[bytes | None] = [None] * len(rows)
        if self._embed and rows:
            try:
                embedded = []
                for i in range(0, len(rows), 32):
                    embedded += self._embed([f"search_document: {c}" for _, c in rows[i : i + 32]])
                vectors = [np.asarray(v, dtype=np.float32).tobytes() for v in embedded]
            except Exception:
                vectors = [None] * len(rows)
        self._db.executemany(
            "INSERT INTO chunks (doc_id, page, text, embedding) VALUES (?, ?, ?, ?)",
            [(doc_id, page, chunk, vec) for (page, chunk), vec in zip(rows, vectors)],
        )
        self._db.commit()
        return len(rows)

    def search(self, query: str, k: int = 4, min_score: float = 0.65) -> list[Source]:
        rows = list(
            self._db.execute(
                "SELECT c.text, c.page, c.embedding, d.title, d.path FROM chunks c JOIN documents d ON d.id = c.doc_id"
            )
        )
        if not rows or not query.strip():
            return []
        scores = self._vector_scores(query, rows)
        if scores is None:
            scores = self._keyword_scores(query, rows)
            min_score = 0.2
        order = np.argsort(scores)[::-1][:k]
        hits = [rows[i] for i in order if scores[i] >= min_score]
        return [Source(n + 1, title, page, text, path) for n, (text, page, _, title, path) in enumerate(hits)]

    def _vector_scores(self, query: str, rows) -> np.ndarray | None:
        if not self._embed or any(r[2] is None for r in rows):
            return None
        try:
            q = np.asarray(self._embed([f"search_query: {query}"])[0], dtype=np.float32)
        except Exception:
            return None
        mat = np.stack([np.frombuffer(r[2], dtype=np.float32) for r in rows])
        return mat @ q / (np.linalg.norm(mat, axis=1) * np.linalg.norm(q) + 1e-9)

    @staticmethod
    def _keyword_scores(query: str, rows) -> np.ndarray:
        terms = {w.lower() for w in _WORD.findall(query)}
        if not terms:
            return np.zeros(len(rows))
        return np.array([len(terms & {w.lower() for w in _WORD.findall(r[0])}) / len(terms) for r in rows])


def format_sources(sources: list[Source]) -> str:
    return "\n\n".join(f"[{s.number}] {s.label}\n{s.text}" for s in sources)
