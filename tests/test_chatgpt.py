"""Tests for ChatGPT plan auth helpers and Responses request handling."""

from __future__ import annotations

import json
import stat
import time

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from sabi.ai.chatgpt import (
    ChatGPTError,
    ChatGPTModel,
    ChatGPTProvider,
    ChatGPTSession,
    choose_model,
    normalize_models,
    pkce_challenge,
    response_request,
    stream_response_events,
)
from sabi.ai.providers import Message


def test_pkce_uses_rfc7636_s256_example():
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    assert pkce_challenge(verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def test_model_catalog_preserves_order_and_chooses_sol():
    payload = {
        "models": [
            {"slug": "gpt-6-luna", "display_name": "Luna", "visibility": "list"},
            {"slug": "hidden", "visibility": "hidden"},
            {"slug": "gpt-6.1-sol", "display_name": "GPT-6.1 Sol", "visibility": "list"},
        ]
    }
    models = normalize_models(payload)
    assert [m.slug for m in models] == ["gpt-6-luna", "gpt-6.1-sol"]
    assert choose_model(models) == "gpt-6.1-sol"
    assert choose_model(models, "gpt-6-luna") == "gpt-6-luna"


def test_response_request_matches_plan_usage_contract():
    body = response_request(
        "gpt-6.1-sol",
        "You are SAbi.",
        [Message("user", "Earlier"), Message("assistant", "Yes")],
        "What is this?",
        "abc123",
    )
    assert body["store"] is False and body["stream"] is True
    assert body["instructions"] == "You are SAbi."
    assert not any(item.get("role") == "system" for item in body["input"])
    current = body["input"][-1]["content"]
    assert current[0] == {"type": "input_image", "image_url": "data:image/jpeg;base64,abc123", "detail": "auto"}
    assert current[1] == {"type": "input_text", "text": "What is this?"}
    for forbidden in ("temperature", "max_output_tokens", "previous_response_id"):
        assert forbidden not in body


def test_stream_parser_requires_completion_and_surfaces_plan_limit():
    lines = iter(
        [
            'data: {"type":"response.output_text.delta","delta":"Hello"}',
            'data: {"type":"response.output_text.delta","delta":" there"}',
            'data: {"type":"response.completed"}',
        ]
    )
    assert "".join(stream_response_events(lines)) == "Hello there"

    with pytest.raises(ChatGPTError, match="plan limit") as exc:
        list(
            stream_response_events(
                iter(
                    [
                        'data: {"type":"response.failed","response":{"error":'
                        '{"code":"subscription_sharing_usage_limit_exceeded"}}}'
                    ]
                )
            )
        )
    assert exc.value.code == "subscription_sharing_usage_limit_exceeded"

    with pytest.raises(ChatGPTError, match="before completion"):
        list(stream_response_events(iter(['data: {"type":"response.output_text.delta","delta":"partial"}'])))


def test_session_file_is_owner_only_and_refresh_rotates_token(tmp_path):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/oauth/token"):
            return httpx.Response(
                200,
                json={
                    "access_token": "new-access",
                    "refresh_token": "new-refresh",
                    "expires_in": 3600,
                    "scope": "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct",
                },
            )
        raise AssertionError(f"unexpected request: {request.url}")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    session = ChatGPTSession(tmp_path, client=client)
    session._state["profile"] = {
        "client_id": "oaiapp_test",
        "subject": "account-1",
        "access_token": "expired-access",
        "refresh_token": "old-refresh",
        "expires_at": time.time() - 1,
        "scopes": ["chatgpt.tokens.use.direct"],
    }
    session._state["online_enabled"] = True
    session._save()

    assert session.access_token() == "new-access"
    saved = json.loads(session.path.read_text())
    assert saved["profile"]["refresh_token"] == "new-refresh"
    assert stat.S_IMODE(session.path.stat().st_mode) == 0o600
    assert requests and b"grant_type=refresh_token" in requests[0].content


def test_provider_streams_with_saved_plan_token(tmp_path):
    seen_body = {}

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_body
        assert request.headers["authorization"] == "Bearer access"
        seen_body = json.loads(request.content)
        sse = (
            'data: {"type":"response.output_text.delta","delta":"Smart"}\n\n'
            'data: {"type":"response.completed"}\n\n'
        )
        return httpx.Response(200, text=sse, headers={"content-type": "text/event-stream"})

    session = ChatGPTSession(tmp_path, client=httpx.Client(transport=httpx.MockTransport(handler)))
    session._state.update(
        {
            "selected_model": "gpt-6.1-sol",
            "online_enabled": True,
            "profile": {
                "client_id": "oaiapp_test",
                "access_token": "access",
                "refresh_token": "refresh",
                "expires_at": time.time() + 3600,
                "scopes": ["chatgpt.tokens.use.direct"],
            },
        }
    )
    provider = ChatGPTProvider(session)
    assert "".join(provider.stream("Tutor", [], "Help", None)) == "Smart"
    assert seen_body["model"] == "gpt-6.1-sol"
    assert seen_body["store"] is False and seen_body["stream"] is True


def test_id_token_signature_audience_issuer_and_nonce_are_verified(tmp_path):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    jwk.update({"kid": "test-key", "alg": "RS256", "use": "sig"})

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("openid-configuration"):
            return httpx.Response(200, json={"jwks_uri": "https://auth.openai.com/test-jwks"})
        if request.url.path.endswith("test-jwks"):
            return httpx.Response(200, json={"keys": [jwk]})
        raise AssertionError(f"unexpected request: {request.url}")

    now = int(time.time())
    token = jwt.encode(
        {
            "iss": "https://auth.openai.com",
            "aud": "oaiapp_test",
            "sub": "account-1",
            "email": "learner@example.com",
            "nonce": "expected-nonce",
            "iat": now,
            "exp": now + 300,
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )
    session = ChatGPTSession(tmp_path, client=httpx.Client(transport=httpx.MockTransport(handler)))
    claims = session._validate_id_token(token, "oaiapp_test", "expected-nonce")
    assert claims["sub"] == "account-1"
    with pytest.raises(ChatGPTError, match="nonce"):
        session._validate_id_token(token, "oaiapp_test", "wrong-nonce")
