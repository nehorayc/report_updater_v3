from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

import llm_client
from llm_usage import get_usage_rows, reset_usage


def test_provider_defaults_to_gemini_and_uses_gemini_key(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")

    assert llm_client.get_provider() == "gemini"
    assert llm_client.required_api_key_env() == "GEMINI_API_KEY"
    assert llm_client.get_api_key() == "gemini-key"


def test_openai_provider_uses_openai_key_and_default_model(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.delenv("OPENAI_MODEL", raising=False)

    assert llm_client.get_provider() == "openai"
    assert llm_client.required_api_key_env() == "OPENAI_API_KEY"
    assert llm_client.get_api_key() == "openai-key"
    assert llm_client.resolve_model("gemini-2.5-flash", role="writer") == "gpt-5.4-mini"


def test_openai_role_override_wins(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-5.4-mini")
    monkeypatch.setenv("OPENAI_WRITER_MODEL", "gpt-5.4")

    assert llm_client.resolve_model("gemini-3-flash-preview", role="writer") == "gpt-5.4"


def test_openai_text_request_maps_to_responses_api(monkeypatch):
    reset_usage()
    captured = {}

    class FakeResponses:
        def create(self, **kwargs):
            captured.update(kwargs)
            usage = SimpleNamespace(
                input_tokens=100,
                output_tokens=40,
                total_tokens=140,
                input_tokens_details=SimpleNamespace(cached_tokens=10),
            )
            return SimpleNamespace(model=kwargs["model"], output_text='{"ok": true}', usage=usage)

    class FakeOpenAI:
        def __init__(self, *, api_key):
            captured["api_key"] = api_key
            self.responses = FakeResponses()

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))
    monkeypatch.setenv("LLM_PROVIDER", "openai")

    response = llm_client.generate_content(
        api_key="openai-key",
        model="gpt-5.4-mini",
        contents="Return JSON.",
        response_mime_type="application/json",
        temperature=0.2,
        operation="test.openai_text",
    )

    assert response.text == '{"ok": true}'
    assert captured["api_key"] == "openai-key"
    assert captured["model"] == "gpt-5.4-mini"
    assert captured["input"] == "Return JSON."
    assert captured["text"] == {"format": {"type": "json_object"}}
    assert captured["temperature"] == 0.2
    assert captured["reasoning"] == {"effort": "low"}

    rows = get_usage_rows()
    assert len(rows) == 1
    assert rows[0]["provider"] == "openai"
    assert rows[0]["input_tokens"] == 100
    assert rows[0]["cached_input_tokens"] == 10
    assert rows[0]["output_tokens"] == 40
    assert rows[0]["estimated_cost_usd"] is not None


def test_openai_multimodal_contents_are_converted(monkeypatch):
    captured = {}

    class FakeResponses:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(model=kwargs["model"], output_text="done", usage=None)

    class FakeOpenAI:
        def __init__(self, *, api_key):
            self.responses = FakeResponses()

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))
    monkeypatch.setenv("LLM_PROVIDER", "openai")

    response = llm_client.generate_content(
        api_key="openai-key",
        model="gpt-5.4-mini",
        contents=[
            "Analyze this.",
            {"mime_type": "image/png", "data": b"abc"},
        ],
        operation="test.openai_multimodal",
    )

    assert response.text == "done"
    message = captured["input"][0]
    assert message["role"] == "user"
    assert message["content"][0] == {"type": "input_text", "text": "Analyze this."}
    assert message["content"][1]["type"] == "input_image"
    assert message["content"][1]["image_url"].startswith("data:image/png;base64,")


def test_gemini_usage_metadata_is_recorded(monkeypatch):
    reset_usage()

    class FakeResponse:
        text = "ok"
        model_version = "gemini-2.5-flash"
        usage_metadata = SimpleNamespace(
            prompt_token_count=80,
            cached_content_token_count=20,
            candidates_token_count=25,
            total_token_count=105,
        )

    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setattr(llm_client.gemini_client, "generate_content", lambda **kwargs: FakeResponse())

    response = llm_client.generate_content(
        api_key="gemini-key",
        model="gemini-2.5-flash",
        contents="hello",
        operation="test.gemini_usage",
    )

    assert response.text == "ok"
    rows = get_usage_rows()
    assert rows[0]["provider"] == "gemini"
    assert rows[0]["input_tokens"] == 80
    assert rows[0]["cached_input_tokens"] == 20
    assert rows[0]["output_tokens"] == 25
    assert rows[0]["total_tokens"] == 105


def test_failed_call_is_recorded_without_cost(monkeypatch):
    reset_usage()

    def fail(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setattr(llm_client.gemini_client, "generate_content", fail)

    with pytest.raises(RuntimeError):
        llm_client.generate_content(
            api_key="gemini-key",
            model="gemini-2.5-flash",
            contents="hello",
            operation="test.failure",
        )

    rows = get_usage_rows()
    assert rows[0]["success"] is False
    assert rows[0]["estimated_cost_usd"] is None
    assert rows[0]["error"] == "boom"
