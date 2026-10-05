import json

import httpx
import pytest

from homer.ollama import ModelUnavailableError, OllamaClient, OllamaResponseError


def test_chat_returns_message_content() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["model"] == "qwen2.5:7b"
        assert payload["format"] == "json"
        return httpx.Response(200, json={"message": {"content": '{"ok": true}'}})

    with OllamaClient(
        "http://localhost:11434",
        "qwen2.5:7b",
        transport=httpx.MockTransport(handler),
    ) as client:
        result = client.chat([{"role": "user", "content": "hello"}], json_mode=True)

    assert result == '{"ok": true}'


def test_transient_server_error_retries_once() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503, text="not ready")
        return httpx.Response(200, json={"message": {"content": "ready"}})

    with OllamaClient(
        "http://localhost:11434", "model", transport=httpx.MockTransport(handler)
    ) as client:
        assert client.chat([{"role": "user", "content": "hello"}]) == "ready"

    assert calls == 2


def test_missing_model_has_actionable_error() -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(404, text="missing"))
    with OllamaClient("http://localhost:11434", "missing", transport=transport) as client:
        with pytest.raises(ModelUnavailableError, match="ollama pull missing"):
            client.chat([{"role": "user", "content": "hello"}])


def test_malformed_response_is_rejected() -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json={"unexpected": True}))
    with OllamaClient("http://localhost:11434", "model", transport=transport) as client:
        with pytest.raises(OllamaResponseError, match="malformed"):
            client.chat([{"role": "user", "content": "hello"}])


def test_status_lists_models() -> None:
    transport = httpx.MockTransport(
        lambda _: httpx.Response(200, json={"models": [{"name": "qwen2.5:7b"}]})
    )
    with OllamaClient("http://localhost:11434", "qwen2.5:7b", transport=transport) as client:
        status = client.status()

    assert status.reachable
    assert status.models == ("qwen2.5:7b",)
