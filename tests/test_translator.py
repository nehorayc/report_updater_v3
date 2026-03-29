from __future__ import annotations

import translator
from translator import translate_texts_batch


def test_translate_texts_batch_uses_single_model_call(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    calls = {"generate": 0}

    class FakeResponse:
        text = """
        {
          "translations": [
            {"id": "0", "text": "שלום"},
            {"id": "1", "text": "עולם"}
          ]
        }
        """

    def fake_generate_content(*, api_key, model, contents, response_mime_type=None, temperature=None):
        calls["generate"] += 1
        assert api_key == "test-key"
        assert model == "gemini-2.5-flash"
        assert "Hello" in contents
        assert "World" in contents
        assert response_mime_type == "application/json"
        return FakeResponse()

    monkeypatch.setattr(translator, "gemini_generate_content", fake_generate_content)

    translated = translate_texts_batch(["Hello", "World"], "Hebrew", preserve_markdown=False)

    assert calls["generate"] == 1
    assert translated == ["שלום", "עולם"]


def test_translate_texts_batch_falls_back_for_missing_items(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    class FakeResponse:
        text = """
        {
          "translations": [
            {"id": "0", "text": "שלום"}
          ]
        }
        """

    fallback_calls = []

    def fake_single(text, target_lang):
        fallback_calls.append((text, target_lang))
        return f"fallback:{text}"

    monkeypatch.setattr(
        translator,
        "gemini_generate_content",
        lambda **kwargs: FakeResponse(),
    )
    monkeypatch.setattr(translator, "translate_content", fake_single)

    translated = translate_texts_batch(["Hello", "World"], "Hebrew", preserve_markdown=True)

    assert translated == ["שלום", "fallback:World"]
    assert fallback_calls == [("World", "Hebrew")]
