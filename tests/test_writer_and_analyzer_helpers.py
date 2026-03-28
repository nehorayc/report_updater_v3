from __future__ import annotations

from chapter_analyzer import _fallback_analysis, analyze_chapter_content
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
