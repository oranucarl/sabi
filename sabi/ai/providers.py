"""Model providers. Local Ollama is the default; Claude is optional when an API key is set."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Iterator, Protocol

import httpx


@dataclass
class Message:
    role: str  # "user" | "assistant"
    content: str


class Provider(Protocol):
    name: str

    def stream(self, system: str, history: list[Message], user_text: str, image_b64: str | None) -> Iterator[str]: ...


class OllamaProvider:
    def __init__(self, base_url: str, model: str) -> None:
        self.name = f"ollama:{model}"
        self._url = base_url.rstrip("/")
        self._model = model

    def stream(self, system: str, history: list[Message], user_text: str, image_b64: str | None) -> Iterator[str]:
        user: dict = {"role": "user", "content": user_text}
        if image_b64:
            user["images"] = [image_b64]
        messages = [{"role": "system", "content": system}]
        messages += [{"role": m.role, "content": m.content} for m in history]
        messages.append(user)
        body = {
            "model": self._model,
            "messages": messages,
            "stream": True,
            "think": False,
            "keep_alive": "30m",
            "options": {"temperature": 0.3, "num_ctx": 8192},
        }
        with httpx.stream("POST", f"{self._url}/api/chat", json=body, timeout=httpx.Timeout(180, connect=5)) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line:
                    continue
                chunk = json.loads(line)
                if chunk.get("error"):
                    raise RuntimeError(chunk["error"])
                text = chunk.get("message", {}).get("content", "")
                if text:
                    yield text
                if chunk.get("done"):
                    break


class ClaudeProvider:
    def __init__(self, api_key: str, model: str) -> None:
        import anthropic

        self.name = f"claude:{model}"
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def stream(self, system: str, history: list[Message], user_text: str, image_b64: str | None) -> Iterator[str]:
        content: list[dict] = []
        if image_b64:
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_b64}})
        content.append({"type": "text", "text": user_text})
        messages = [{"role": m.role, "content": m.content} for m in history] + [{"role": "user", "content": content}]
        with self._client.messages.stream(model=self._model, max_tokens=1024, system=system, messages=messages) as s:
            yield from s.text_stream


class OllamaTools:
    """Small non-streaming helpers: embeddings and short JSON tasks on the local model."""

    def __init__(self, base_url: str, text_model: str, embed_model: str) -> None:
        self._url = base_url.rstrip("/")
        self._text_model = text_model
        self._embed_model = embed_model

    def available(self) -> bool:
        try:
            return httpx.get(f"{self._url}/api/version", timeout=2).status_code == 200
        except httpx.HTTPError:
            return False

    def warm(self) -> None:
        """Load the vision model into memory so the first question doesn't wait for it."""
        body = {"model": self._text_model, "prompt": "", "keep_alive": "30m"}
        httpx.post(f"{self._url}/api/generate", json=body, timeout=300)

    def embed(self, texts: list[str]) -> list[list[float]]:
        r = httpx.post(f"{self._url}/api/embed", json={"model": self._embed_model, "input": texts}, timeout=120)
        r.raise_for_status()
        return r.json()["embeddings"]

    def json(self, prompt: str) -> dict:
        body = {
            "model": self._text_model,
            "prompt": prompt,
            "format": "json",
            "stream": False,
            "think": False,
            "keep_alive": "30m",
            "options": {"temperature": 0},
        }
        r = httpx.post(f"{self._url}/api/generate", json=body, timeout=120)
        r.raise_for_status()
        try:
            return json.loads(r.json().get("response", "{}"))
        except json.JSONDecodeError:
            return {}
