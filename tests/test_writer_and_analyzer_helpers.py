from __future__ import annotations

import chapter_analyzer
from chapter_analyzer import _fallback_analysis, analyze_chapter_content, analyze_chapters_batch
from writer_agent import (
    _normalize_inline_citations,
    _normalize_references,
    _reshape_bullet_heavy_text,
    _soften_outline_structure,
)


def test_fallback_analysis_returns_required_baseline_fields():
    analysis = _fallback_analysis(
        "AI Market Outlook",
        (
            "OpenAI and Anthropic expanded enterprise offerings in 2024. "
            "The market grew by 20% and included references [1] plus [Figure abcdef12: Growth chart]."
        ),
    )

    required_fields = {
        "summary",
        "keywords",
        "core_claims",
        "dated_facts",
        "named_entities",
        "stats",
        "original_citations",
        "original_figures",
        "chapter_role",
        "language",
    }

    assert required_fields.issubset(analysis)
    assert analysis["language"] == "English"
    assert analysis["original_citations"] == ["1"]
    assert analysis["original_figures"]


def test_analyze_chapter_content_without_api_key_uses_fallback(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    analysis = analyze_chapter_content(
        "Introduction",
        "AI adoption accelerated in 2024. OpenAI expanded enterprise deployments globally.",
    )

    assert analysis["summary"]
    assert analysis["chapter_role"] == "introduction"
    assert analysis["language"] == "English"


def test_analyze_chapters_batch_without_api_key_uses_fallback(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    analyses = analyze_chapters_batch(
        [
            {
                "id": "chapter-1",
                "title": "Introduction",
                "content": "AI adoption accelerated in 2024. OpenAI expanded enterprise deployments globally.",
            }
        ]
    )

    assert "chapter-1" in analyses
    assert analyses["chapter-1"]["summary"]
    assert analyses["chapter-1"]["chapter_role"] == "introduction"


def test_analyze_chapters_batch_uses_single_model_call(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    calls = {"generate": 0}

    class FakeResponse:
        text = """
        {
          "chapters": [
            {
              "id": "chapter-1",
              "summary": "Chapter one summary.",
              "keywords": ["AI"],
              "core_claims": ["Claim one"],
              "dated_facts": ["2024 adoption accelerated."],
              "named_entities": ["OpenAI"],
              "stats": ["20%"],
              "original_citations": ["1"],
              "original_figures": ["abcdef12"],
              "chapter_role": "introduction",
              "language": "English"
            },
            {
              "id": "chapter-2",
              "summary": "Chapter two summary.",
              "keywords": ["Policy"],
              "core_claims": ["Claim two"],
              "dated_facts": ["2025 regulation expanded."],
              "named_entities": ["EU"],
              "stats": ["15%"],
              "original_citations": ["2"],
              "original_figures": [],
              "chapter_role": "body",
              "language": "English"
            }
          ]
        }
        """

    def fake_generate_content(*, api_key, model, contents, response_mime_type=None, temperature=None):
        calls["generate"] += 1
        assert api_key == "test-key"
        assert model == "gemini-2.5-flash"
        assert "chapter-1" in contents
        assert "chapter-2" in contents
        assert response_mime_type == "application/json"
        return FakeResponse()

    monkeypatch.setattr(chapter_analyzer, "gemini_generate_content", fake_generate_content)

    analyses = analyze_chapters_batch(
        [
            {"id": "chapter-1", "title": "Introduction", "content": "AI adoption accelerated in 2024."},
            {"id": "chapter-2", "title": "Policy", "content": "AI regulation expanded in 2025."},
        ]
    )

    assert calls["generate"] == 1
    assert analyses["chapter-1"]["summary"] == "Chapter one summary."
    assert analyses["chapter-2"]["summary"] == "Chapter two summary."


def test_analyze_chapters_batch_falls_back_for_missing_results(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    class FakeResponse:
        text = """
        {
          "chapters": [
            {
              "id": "chapter-1",
              "summary": "Batch summary.",
              "keywords": ["AI"],
              "core_claims": ["Claim one"],
              "dated_facts": ["2024 adoption accelerated."],
              "named_entities": ["OpenAI"],
              "stats": ["20%"],
              "original_citations": ["1"],
              "original_figures": ["abcdef12"],
              "chapter_role": "introduction",
              "language": "English"
            }
          ]
        }
        """

    fallback_calls = []

    def fake_single(title, text):
        fallback_calls.append(title)
        return {
            "summary": f"Fallback for {title}",
            "keywords": [title],
            "core_claims": [],
            "dated_facts": [],
            "named_entities": [],
            "stats": [],
            "original_citations": [],
            "original_figures": [],
            "chapter_role": "body",
            "language": "English",
        }

    monkeypatch.setattr(
        chapter_analyzer,
        "gemini_generate_content",
        lambda **kwargs: FakeResponse(),
    )
    monkeypatch.setattr(chapter_analyzer, "analyze_chapter_content", fake_single)

    analyses = analyze_chapters_batch(
        [
            {"id": "chapter-1", "title": "Introduction", "content": "AI adoption accelerated in 2024."},
            {"id": "chapter-2", "title": "Policy", "content": "AI regulation expanded in 2025."},
        ]
    )

    assert analyses["chapter-1"]["summary"] == "Batch summary."
    assert analyses["chapter-2"]["summary"] == "Fallback for Policy"
    assert fallback_calls == ["Policy"]


def test_analyze_chapters_batch_stops_remote_calls_after_quota_error(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    calls = {"generate": 0, "single": 0}

    class FirstChunkResponse:
        text = """
        {
          "chapters": [
            {
              "id": "chapter-1",
              "summary": "Batch summary.",
              "keywords": ["AI"],
              "core_claims": ["Claim one"],
              "dated_facts": ["2024 adoption accelerated."],
              "named_entities": ["OpenAI"],
              "stats": ["20%"],
              "original_citations": ["1"],
              "original_figures": ["abcdef12"],
              "chapter_role": "introduction",
              "language": "English"
            }
          ]
        }
        """

    def fake_generate_content(**kwargs):
        calls["generate"] += 1
        if calls["generate"] == 1:
            return FirstChunkResponse()
        raise RuntimeError("429 RESOURCE_EXHAUSTED quota exceeded")

    def fake_single(title, text):
        calls["single"] += 1
        return {"summary": f"Should not be called for {title}"}

    monkeypatch.setattr(chapter_analyzer, "gemini_generate_content", fake_generate_content)
    monkeypatch.setattr(chapter_analyzer, "analyze_chapter_content", fake_single)

    analyses = analyze_chapters_batch(
        [
            {"id": "chapter-1", "title": "Introduction", "content": "AI adoption accelerated in 2024."},
            {"id": "chapter-2", "title": "Policy", "content": "AI regulation expanded in 2025."},
            {"id": "chapter-3", "title": "Market", "content": "Spending grew by 15% in 2026."},
        ],
        max_chapters=1,
    )

    assert calls["generate"] == 2
    assert calls["single"] == 0
    assert analyses["chapter-1"]["summary"] == "Batch summary."
    assert analyses["chapter-2"]["summary"]
    assert analyses["chapter-3"]["summary"]


def test_normalize_references_filters_unused_sources_and_maps_original():
    research_findings = [
        {
            "title": "Allowed Web Source",
            "url": "https://example.com/allowed",
            "source_type": "web",
            "source_credible": True,
        },
        {
            "title": "Internal Memo",
            "source_type": "uploaded",
            "source_credible": True,
        },
    ]
    references = [
        {
            "index": 1,
            "title": "Allowed Web Source",
            "url": "https://example.com/allowed",
            "category": "Web",
        },
        {
            "index": 2,
            "title": "Bad Web Source",
            "url": "https://example.com/bad",
            "category": "Web",
        },
        {
            "index": 3,
            "title": "Internal Memo",
            "category": "Uploaded",
        },
    ]

    normalized_refs, citation_map = _normalize_references(
        references,
        research_findings,
        include_original_reference=True,
        edition_title="AI Report",
        original_report_date="2023-03-15",
    )

    titles = [ref["title"] for ref in normalized_refs]
    assert "Allowed Web Source" in titles
    assert "Internal Memo" in titles
    assert "Bad Web Source" not in titles
    assert any(ref["category"] == "Original" for ref in normalized_refs)

    normalized_text = _normalize_inline_citations(
        "Claim [1]. Historical framing [Original Report].",
        citation_map,
    )
    assert "[Original Report]" not in normalized_text


def test_outline_and_bullet_shaping_helpers_reduce_outline_noise():
    outline_text = "1. Intro\n2. Data\n3. Risks\n4. Outlook"
    softened = _soften_outline_structure(outline_text)
    assert "1." not in softened
    assert "Intro" in softened

    bullet_text = (
        "- **Trend**: Growth accelerated\n"
        "- Enterprises expanded deployment\n"
        "- Regulators increased scrutiny\n"
        "- Costs continued to decline\n"
        "- Safety questions remained open\n"
        "- Competition intensified\n"
    )
    reshaped = _reshape_bullet_heavy_text(bullet_text)
    assert "### Trend" in reshaped
    assert "- " not in reshaped
