"""Tests for the provider-agnostic LLM client (no network — httpx is mocked)."""

import httpx
import pytest

from app.services import llm
from app.services.llm import LlmConfig


def _openai_ok(*args, **kwargs):
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": '{"a": 1}'}}]},
    )


def test_openai_generate_json_parses_content():
    config = LlmConfig(provider="openai", model="gpt-4o-mini", api_key="k")
    with _patch_post(_openai_ok) as mock:
        result = llm.generate_json(config=config, prompt="p")
    assert result == {"a": 1}
    body = mock.call_args.kwargs["json"]
    assert body["model"] == "gpt-4o-mini"
    assert mock.call_args.kwargs["headers"] == {"Authorization": "Bearer k"}
    assert mock.call_args.args[0].endswith("/chat/completions")


def test_openai_401_rejects_key():
    config = LlmConfig(provider="openai", model="gpt-4o-mini", api_key="bad")
    with _patch_post(lambda *a, **k: httpx.Response(401, text="bad key")):
        with pytest.raises(llm.LlmBadResponse):
            llm.generate_text(config=config, prompt="p")


def test_opencode_uses_custom_base_url():
    config = LlmConfig(
        provider="opencode", model="anything", base_url="http://localhost:11434/v1"
    )
    with _patch_post(_openai_ok) as mock:
        llm.generate_text(config=config, prompt="p")
    assert mock.call_args.args[0].startswith("http://localhost:11434/v1")


def test_anthropic_posts_messages_api():
    def _ok(*args, **kwargs):
        return httpx.Response(
            200, json={"content": [{"type": "text", "text": '{"a": 2}'}]}
        )

    config = LlmConfig(provider="anthropic", model="claude-haiku-4-5", api_key="k")
    with _patch_post(_ok) as mock:
        result = llm.generate_json(config=config, prompt="p")
    assert result == {"a": 2}
    assert mock.call_args.args[0].endswith("/v1/messages")
    assert mock.call_args.kwargs["headers"]["x-api-key"] == "k"


def test_google_posts_generate_content():
    def _ok(*args, **kwargs):
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"text": '{"a": 3}'},
                            ]
                        }
                    }
                ]
            },
        )

    config = LlmConfig(provider="google", model="gemini-2.0-flash", api_key="k")
    with _patch_post(_ok) as mock:
        result = llm.generate_json(config=config, prompt="p")
    assert result == {"a": 3}
    assert "generateContent" in mock.call_args.args[0]


def test_ollama_still_supported():
    def _ok(*args, **kwargs):
        return httpx.Response(200, json={"response": '{"a": 4}'})

    config = LlmConfig(provider="ollama", model="gemma4", base_url="http://ollama.test")
    with _patch_post(_ok):
        assert llm.generate_json(config=config, prompt="p") == {"a": 4}


def test_unknown_provider_rejected():
    config = LlmConfig(provider="nope", model="x")
    with pytest.raises(llm.LlmBadResponse):
        llm.generate_text(config=config, prompt="p")


def test_list_models_openai_compatible():
    def _ok(*args, **kwargs):
        return httpx.Response(200, json={"data": [{"id": "m1"}, {"id": "m2"}]})

    import httpx as _httpx

    orig_get = _httpx.get
    _httpx.get = lambda *a, **k: _ok()
    try:
        config = LlmConfig(provider="openai", model="m1", api_key="k")
        assert llm.list_models(config=config) == ["m1", "m2"]
    finally:
        _httpx.get = orig_get


class _CallRecorder:
    """Minimal mock_post replacement exposing call_args like unittest.mock."""

    def __init__(self, fn):
        self.fn = fn
        self.call_args = None

    def __call__(self, *args, **kwargs):
        from unittest.mock import _Call

        self.call_args = _Call((args, kwargs))
        return self.fn(*args, **kwargs)


def _patch_post(fn):
    from contextlib import contextmanager

    @contextmanager
    def _ctx():
        import httpx as _httpx

        recorder = _CallRecorder(fn)
        orig = _httpx.post
        _httpx.post = recorder
        try:
            yield recorder
        finally:
            _httpx.post = orig

    return _ctx()
