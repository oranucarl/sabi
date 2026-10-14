"""ChatGPT plan authentication and Responses API streaming.

SAbi is an open-source, locally hosted app, so eligible users can authorize it to
use their ChatGPT plan without an API key. This module implements OpenAI's public
OAuth/PKCE flow for that use case and deliberately never reads ChatGPT cookies or
private backend endpoints.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import threading
import time
import uuid
import webbrowser
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Callable, Iterator
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from sabi.ai.providers import Message

ISSUER = "https://auth.openai.com"
AUTHORIZE_URL = f"{ISSUER}/api/accounts/authorize"
TOKEN_URL = f"{ISSUER}/api/accounts/oauth/token"
RESOURCE = "https://api.openai.com/v1"
RESPONSES_URL = f"{RESOURCE}/responses"
MODELS_URL = f"{RESOURCE}/models"
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
REQUIRED_SCOPE = "chatgpt.tokens.use.direct"
AUTH_FILENAME = "chatgpt-auth.json"
CALLBACK_PATH = "/auth/callback"


class ChatGPTError(RuntimeError):
    """An actionable ChatGPT connection or inference error."""

    def __init__(self, message: str, code: str = "") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ChatGPTModel:
    slug: str
    display_name: str


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def pkce_challenge(verifier: str) -> str:
    return _b64url(hashlib.sha256(verifier.encode("ascii")).digest())


def normalize_models(payload: dict) -> list[ChatGPTModel]:
    """Return displayable account models while preserving the server's order."""
    rows = payload.get("models", payload.get("data", []))
    result: list[ChatGPTModel] = []
    seen: set[str] = set()
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or row.get("visibility", "list") != "list":
            continue
        slug = str(row.get("slug") or row.get("id") or "").strip()
        if not slug or slug in seen:
            continue
        seen.add(slug)
        result.append(ChatGPTModel(slug, str(row.get("display_name") or slug)))
    return result


def choose_model(models: list[ChatGPTModel], saved: str = "") -> str:
    slugs = [m.slug for m in models]
    if saved in slugs:
        return saved
    for preferred in ("gpt-6.1-sol", "gpt-6-sol", "gpt-6-luna"):
        if preferred in slugs:
            return preferred
    return slugs[0] if slugs else ""


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urlparse(self.path)
        if parsed.path != CALLBACK_PATH:
            self.send_error(404)
            return
        self.server.oauth_result = {k: v[-1] for k, v in parse_qs(parsed.query).items()}  # type: ignore[attr-defined]
        body = (
            "<!doctype html><meta charset='utf-8'><title>SAbi connected</title>"
            "<style>body{font:17px -apple-system;padding:48px;max-width:620px;margin:auto;color:#141816}"
            "h1{color:#008751}</style><h1>Return to SAbi</h1>"
            "<p>ChatGPT has returned control to SAbi. You can close this tab.</p>"
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args) -> None:
        return


def _wait_for_callback(timeout: float) -> tuple[HTTPServer, str, Callable[[], dict[str, str]]]:
    server = HTTPServer(("127.0.0.1", 0), _CallbackHandler)
    server.timeout = 0.4
    server.oauth_result = None  # type: ignore[attr-defined]
    port = server.server_address[1]
    redirect_uri = f"http://127.0.0.1:{port}{CALLBACK_PATH}"

    def wait() -> dict[str, str]:
        deadline = time.monotonic() + timeout
        try:
            while time.monotonic() < deadline and server.oauth_result is None:  # type: ignore[attr-defined]
                server.handle_request()
            result = server.oauth_result  # type: ignore[attr-defined]
            if result is None:
                raise ChatGPTError("ChatGPT sign-in timed out. Please try again.", "sign_in_timeout")
            return result
        finally:
            server.server_close()

    return server, redirect_uri, wait


class ChatGPTSession:
    """One locally stored ChatGPT account registration and its renewable session."""

    def __init__(self, data_dir: Path, client: httpx.Client | None = None) -> None:
        self.path = data_dir / AUTH_FILENAME
        self._client = client or httpx.Client(timeout=httpx.Timeout(60, connect=10))
        self._lock = threading.RLock()
        self._state = self._load()
        if not self._state.get("host_id"):
            self._state["host_id"] = f"urn:uuid:{uuid.uuid4()}"
            self._save()

    @property
    def connected(self) -> bool:
        profile = self._state.get("profile") or {}
        scopes = set(profile.get("scopes") or [])
        return bool(profile.get("client_id") and (profile.get("access_token") or profile.get("refresh_token")) and REQUIRED_SCOPE in scopes)

    @property
    def enabled(self) -> bool:
        return self.connected and self._state.get("online_enabled", True)

    @property
    def email(self) -> str:
        return str((self._state.get("profile") or {}).get("email") or "")

    @property
    def selected_model(self) -> str:
        return str(self._state.get("selected_model") or "")

    @property
    def provider_name(self) -> str:
        return f"chatgpt:{self.selected_model or 'account model'}"

    def set_enabled(self, enabled: bool) -> None:
        self._state["online_enabled"] = bool(enabled)
        self._save()

    def set_model(self, slug: str) -> None:
        self._state["selected_model"] = slug
        self._save()

    def sign_in(self, timeout: float = 180, open_browser: Callable[[str], bool] = webbrowser.open) -> list[ChatGPTModel]:
        """Run browser authorization, validate the result, save it, and return account models."""
        with self._lock:
            profile = self._state.get("profile") or {}
            existing_client_id = str(profile.get("client_id") or "")
            client_id = existing_client_id or "dynamic_agent_client"
            verifier = secrets.token_urlsafe(64)
            state = secrets.token_urlsafe(32)
            nonce = secrets.token_urlsafe(32)
            _server, redirect_uri, wait = _wait_for_callback(timeout)
            params = {
                "client_id": client_id,
                "response_type": "code",
                "redirect_uri": redirect_uri,
                "scope": SCOPES,
                "resource": RESOURCE,
                "state": state,
                "nonce": nonce,
                "code_challenge_method": "S256",
                "code_challenge": pkce_challenge(verifier),
                "ext_agent_host_id": self._state["host_id"],
            }
            if not existing_client_id:
                params["agent_name_hint"] = "SAbi Tutor"
            elif profile.get("id_token"):
                params["id_token_hint"] = profile["id_token"]
            elif profile.get("email"):
                params["login_hint"] = profile["email"]

            try:
                opened = open_browser(f"{AUTHORIZE_URL}?{urlencode(params)}")
            except Exception as exc:
                _server.server_close()
                raise ChatGPTError(f"Could not open the ChatGPT sign-in page: {exc}", "browser_open_failed") from exc
            if not opened:
                _server.server_close()
                raise ChatGPTError("Could not open the ChatGPT sign-in page.", "browser_open_failed")
            callback = wait()
            if not secrets.compare_digest(callback.get("state", ""), state):
                raise ChatGPTError("ChatGPT sign-in returned an invalid state value.", "invalid_state")
            if error := callback.get("error"):
                raise ChatGPTError(callback.get("error_description") or f"ChatGPT sign-in was not completed: {error}", error)
            code = callback.get("code", "")
            issued_client_id = callback.get("client_id", "") or existing_client_id
            if not code or not issued_client_id or issued_client_id == "dynamic_agent_client":
                raise ChatGPTError("ChatGPT registration did not return the required credentials.", "incomplete_registration")
            if existing_client_id and issued_client_id != existing_client_id:
                raise ChatGPTError("ChatGPT returned a different account registration.", "client_mismatch")

            response = self._client.post(
                TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "client_id": issued_client_id,
                    "code": code,
                    "code_verifier": verifier,
                    "redirect_uri": redirect_uri,
                    "resource": RESOURCE,
                },
            )
            token = self._json_response(response, "ChatGPT token exchange failed")
            claims = self._validate_id_token(str(token.get("id_token") or ""), issued_client_id, nonce)
            scopes = str(token.get("scope") or callback.get("scope") or "").split()
            if REQUIRED_SCOPE not in scopes:
                raise ChatGPTError("ChatGPT connected, but permission to use your plan was not granted.", "plan_permission_missing")
            if existing_client_id and profile.get("subject") and claims.get("sub") != profile.get("subject"):
                raise ChatGPTError("The returned ChatGPT account does not match this saved connection.", "account_mismatch")

            self._state["profile"] = self._profile_from_token(token, issued_client_id, claims, scopes)
            self._state["online_enabled"] = True
            self._save()
            models = self.list_models()
            selected = choose_model(models, self.selected_model)
            if selected:
                self.set_model(selected)
            return models

    def sign_out(self) -> None:
        """Revoke the renewable session, erase tokens, and retain the client registration."""
        with self._lock:
            profile = self._state.get("profile") or {}
            refresh = profile.get("refresh_token")
            if refresh:
                try:
                    metadata = self._client.get(f"{ISSUER}/.well-known/openid-configuration").json()
                    endpoint = metadata.get("revocation_endpoint")
                    if endpoint:
                        self._client.post(
                            endpoint,
                            data={"token": refresh, "token_type_hint": "refresh_token", "client_id": profile.get("client_id", "")},
                        )
                except Exception:
                    pass
            self._state["profile"] = {
                k: profile[k]
                for k in ("client_id", "subject", "email", "name")
                if profile.get(k)
            }
            self._state["online_enabled"] = False
            self._save()

    def access_token(self) -> str:
        with self._lock:
            if not self.connected:
                raise ChatGPTError("Connect your ChatGPT account in SAbi first.", "not_connected")
            profile = self._state["profile"]
            if float(profile.get("expires_at") or 0) <= time.time() + 60:
                self._refresh()
            return str(self._state["profile"]["access_token"])

    def list_models(self) -> list[ChatGPTModel]:
        token = self.access_token()
        response = self._client.get(MODELS_URL, headers={"Authorization": f"Bearer {token}"})
        payload = self._json_response(response, "Could not load models from your ChatGPT account")
        models = normalize_models(payload)
        if not models:
            raise ChatGPTError("Your ChatGPT account did not return any models available to SAbi.", "no_models")
        return models

    def stream_response(self, body: dict) -> Iterator[str]:
        token = self.access_token()
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Accept": "text/event-stream"}
        with self._client.stream("POST", RESPONSES_URL, headers=headers, json=body) as response:
            if response.is_error:
                try:
                    response.read()
                    detail = response.json().get("error", {})
                except Exception:
                    detail = {}
                code = str(detail.get("code") or response.status_code)
                message = str(detail.get("message") or f"ChatGPT request failed ({response.status_code}).")
                raise ChatGPTError(message, code)
            yield from stream_response_events(response.iter_lines())

    def close(self) -> None:
        self._client.close()

    def _refresh(self) -> None:
        profile = self._state.get("profile") or {}
        refresh = profile.get("refresh_token")
        if not refresh:
            raise ChatGPTError("Your ChatGPT session expired. Connect it again.", "reauthorize")
        response = self._client.post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "client_id": profile.get("client_id", ""),
                "refresh_token": refresh,
                "resource": RESOURCE,
            },
        )
        token = self._json_response(response, "ChatGPT session refresh failed")
        merged = dict(profile)
        merged.update(token)
        scopes = str(token.get("scope") or " ".join(profile.get("scopes") or [])).split()
        if REQUIRED_SCOPE not in scopes:
            raise ChatGPTError("Your ChatGPT plan permission is no longer enabled.", "plan_permission_missing")
        if token.get("id_token"):
            claims = self._validate_id_token(str(token["id_token"]), str(profile["client_id"]), nonce=None)
            if claims.get("sub") != profile.get("subject"):
                raise ChatGPTError("ChatGPT refreshed a different account.", "account_mismatch")
            merged.update({"subject": claims.get("sub"), "email": claims.get("email", profile.get("email", "")), "name": claims.get("name", profile.get("name", ""))})
        merged["scopes"] = scopes
        merged["saved_at"] = datetime.now(timezone.utc).isoformat()
        merged["expires_at"] = time.time() + int(token.get("expires_in") or 3600)
        self._state["profile"] = merged
        self._save()

    def _validate_id_token(self, token: str, client_id: str, nonce: str | None) -> dict:
        if not token:
            raise ChatGPTError("ChatGPT did not return an identity token.", "missing_id_token")
        try:
            import jwt

            metadata = self._client.get(f"{ISSUER}/.well-known/openid-configuration").json()
            jwks = self._client.get(metadata["jwks_uri"]).json()
            header = jwt.get_unverified_header(token)
            alg, kid = header.get("alg"), header.get("kid")
            if alg not in {"RS256", "ES256"}:
                raise ValueError("unsupported signing algorithm")
            key_data = next(k for k in jwks["keys"] if k.get("kid") == kid)
            key = jwt.PyJWK.from_dict(key_data, algorithm=alg).key
            claims = jwt.decode(token, key=key, algorithms=[alg], audience=client_id, issuer=ISSUER)
            if nonce is not None and not secrets.compare_digest(str(claims.get("nonce") or ""), nonce):
                raise ValueError("nonce mismatch")
            return claims
        except ChatGPTError:
            raise
        except Exception as exc:
            raise ChatGPTError(f"Could not validate the ChatGPT identity: {exc}", "invalid_id_token") from exc

    @staticmethod
    def _profile_from_token(token: dict, client_id: str, claims: dict, scopes: list[str]) -> dict:
        return {
            "client_id": client_id,
            "subject": claims.get("sub", ""),
            "email": claims.get("email", ""),
            "name": claims.get("name", ""),
            "id_token": token.get("id_token", ""),
            "access_token": token.get("access_token", ""),
            "refresh_token": token.get("refresh_token", ""),
            "token_type": token.get("token_type", "Bearer"),
            "expires_in": int(token.get("expires_in") or 3600),
            "expires_at": time.time() + int(token.get("expires_in") or 3600),
            "earliest_refresh_at": token.get("earliest_refresh_at"),
            "scopes": scopes,
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }

    @staticmethod
    def _json_response(response: httpx.Response, message: str) -> dict:
        try:
            payload = response.json()
        except Exception:
            payload = {}
        if response.is_error:
            error = payload.get("error", payload)
            if isinstance(error, dict):
                code = str(error.get("code") or error.get("type") or response.status_code)
                detail = str(error.get("message") or error.get("error_description") or "")
            else:
                code, detail = str(response.status_code), str(error)
            raise ChatGPTError(f"{message}{': ' + detail if detail else ''}", code)
        return payload

    def _load(self) -> dict:
        try:
            return json.loads(self.path.read_text())
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {"version": 1, "profile": {}, "online_enabled": False, "selected_model": ""}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "w") as fh:
                json.dump(self._state, fh, indent=2, sort_keys=True)
                fh.write("\n")
                fh.flush()
                os.fsync(fh.fileno())
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.path)
            os.chmod(self.path, 0o600)
        except Exception:
            try:
                tmp.unlink()
            except OSError:
                pass
            raise


def response_request(
    model: str,
    system: str,
    history: list[Message],
    user_text: str,
    image_b64: str | None,
) -> dict:
    """Build a request allowed by the ChatGPT plan-usage preview contract."""
    input_items: list[dict] = [{"role": m.role, "content": m.content} for m in history]
    if image_b64:
        content: str | list[dict] = [
            {"type": "input_image", "image_url": f"data:image/jpeg;base64,{image_b64}", "detail": "auto"},
            {"type": "input_text", "text": user_text},
        ]
    else:
        content = user_text
    input_items.append({"role": "user", "content": content})
    return {"model": model, "instructions": system, "input": input_items, "store": False, "stream": True}


def stream_response_events(lines: Iterator[str]) -> Iterator[str]:
    """Parse Responses API SSE lines and yield only visible text deltas."""
    completed = False
    for line in lines:
        if not line.startswith("data:"):
            continue
        raw = line[5:].strip()
        if not raw or raw == "[DONE]":
            continue
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        kind = event.get("type", "")
        if kind == "response.output_text.delta":
            if delta := event.get("delta"):
                yield str(delta)
        elif kind == "response.completed":
            completed = True
        elif kind in {"response.failed", "response.incomplete", "error"}:
            error = (event.get("response") or {}).get("error") or event.get("error") or {}
            code = str(error.get("code") or kind) if isinstance(error, dict) else kind
            detail = str(error.get("message") or "") if isinstance(error, dict) else str(error)
            if code == "subscription_sharing_usage_limit_exceeded":
                detail = "Your ChatGPT plan limit for SAbi was reached. Review usage in ChatGPT settings."
            elif code == "subscription_sharing_usage_unavailable":
                detail = "ChatGPT could not check plan usage right now. Try again shortly."
            raise ChatGPTError(detail or "The ChatGPT response did not complete.", code)
    if not completed:
        raise ChatGPTError("The ChatGPT response stream ended before completion.", "incomplete_stream")


class ChatGPTProvider:
    def __init__(self, session: ChatGPTSession) -> None:
        self.session = session

    @property
    def name(self) -> str:
        return self.session.provider_name

    def stream(self, system: str, history: list[Message], user_text: str, image_b64: str | None) -> Iterator[str]:
        model = self.session.selected_model
        if not model:
            raise ChatGPTError("Choose a ChatGPT model before asking a question.", "no_model")
        body = response_request(model, system, history, user_text, image_b64)
        yield from self.session.stream_response(body)
