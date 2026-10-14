"""Pathways: from what the learner has studied to what to do next.

Recommendations come only from the curated catalog (never model-invented links), so every
suggestion is traceable. The model is used only to phrase the summary.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache

from sabi.config import PACKAGE_DATA

_WORD = re.compile(r"[a-z0-9']+")


@lru_cache(maxsize=1)
def catalog() -> dict:
    return json.loads((PACKAGE_DATA / "catalog.json").read_text())


def match_subject(subject: str, topic: str = "") -> str | None:
    text = f"{subject} {topic}".lower()
    words = set(_WORD.findall(text))
    for name, info in catalog()["subjects"].items():
        if name.lower() in text or words & set(info["aliases"]):
            return name
    return None


def match_syllabus(subject: str, topic: str) -> int | None:
    """Index of the syllabus item closest to the topic, by word overlap."""
    words = set(_WORD.findall(topic.lower()))
    best, best_score = None, 0.0
    for i, item in enumerate(catalog()["subjects"][subject]["syllabus"]):
        item_words = set(_WORD.findall(item.lower()))
        score = len(words & item_words) / max(1, len(item_words))
        if score > best_score:
            best, best_score = i, score
    return best if best_score >= 0.34 else None


def classify_prompt(question: str, answer: str) -> str:
    """Prompt asking the model to file a question under a catalog subject and syllabus topic."""
    lines = [f"{name}: {', '.join(info['syllabus'])}" for name, info in catalog()["subjects"].items()]
    return (
        f'Classify this study question.\nQuestion: "{question}"\nTutor answer (start): "{answer[:300]}"\n\n'
        "Subjects and their syllabus topics:\n" + "\n".join(lines) + "\n\n"
        'Return JSON {"subject": one subject name above, another single-word school subject, or "General" for small '
        'talk, "topic": the best matching topic exactly as listed, or a short new topic name in English}'
    )


def clean_classification(result: dict) -> tuple[str, str]:
    subject = str(result.get("subject", "")).strip()
    topic = str(result.get("topic", "")).strip()
    if not subject or subject.lower() == "general" or topic.lower() in {"", "none", "general", "small talk"}:
        return "", ""
    return subject, topic


@dataclass
class SubjectPath:
    subject: str
    studied: list[str] = field(default_factory=list)
    strong: list[str] = field(default_factory=list)
    review: list[str] = field(default_factory=list)
    next_topics: list[str] = field(default_factory=list)
    resources: list[dict] = field(default_factory=list)
    opportunities: list[dict] = field(default_factory=list)


def build(mastery: list[tuple[str, str, float, int]]) -> list[SubjectPath]:
    """mastery rows: (subject, topic, score 0–1, times asked) from the journal."""
    cat = catalog()
    paths: dict[str, SubjectPath] = {}
    reached: dict[str, int] = {}
    for subject, topic, score, _ in mastery:
        name = match_subject(subject, topic)
        if not name:
            continue
        path = paths.setdefault(name, SubjectPath(name))
        path.studied.append(topic)
        (path.strong if score >= 0.6 else path.review).append(topic)
        idx = match_syllabus(name, topic)
        if idx is not None:
            reached[name] = max(reached.get(name, -1), idx)

    for name, path in paths.items():
        info = cat["subjects"][name]
        syllabus = info["syllabus"]
        start = reached.get(name, -1) + 1
        studied = {t.lower() for t in path.studied}
        path.next_topics = [t for t in syllabus[start:] if t.lower() not in studied][:3]
        path.resources = [cat["resources"][r] for r in info["resources"]][:3]
        path.opportunities = [cat["opportunities"][o] for o in info["opportunities"]]
    return sorted(paths.values(), key=lambda p: -len(p.studied))


def as_markdown(paths: list[SubjectPath]) -> str:
    if not paths:
        return "Ask me a few questions first, then I can map your next steps."
    lines = []
    for p in paths:
        lines.append(f"### {p.subject}")
        if p.strong:
            lines.append("**Going well:** " + ", ".join(p.strong))
        if p.review:
            lines.append("**Review soon:** " + ", ".join(p.review))
        if p.next_topics:
            lines.append("**Learn next:** " + " → ".join(p.next_topics))
        if p.resources:
            lines.append("**Free resources:** " + "; ".join(f"[{r['title']}]({r['url']})" for r in p.resources))
        if p.opportunities:
            lines.append("**Where it leads:** " + "; ".join(f"[{o['title']}]({o['url']}) ({o['why']})" for o in p.opportunities))
        lines.append("")
    return "\n".join(lines).strip()


def as_speech_brief(paths: list[SubjectPath]) -> str:
    """Plain facts for the model to phrase in the learner's language."""
    parts = []
    for p in paths[:2]:
        parts.append(
            f"Subject {p.subject}. Strong: {', '.join(p.strong) or 'none yet'}. Needs review: {', '.join(p.review) or 'none'}. "
            f"Next topics: {', '.join(p.next_topics) or 'syllabus complete'}. "
            f"Opportunities: {', '.join(o['title'] for o in p.opportunities)}."
        )
    return " ".join(parts)
