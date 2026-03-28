from __future__ import annotations

from pathlib import Path

import research_agent
from research_agent import (
    _assess_web_source,
    _build_queries,
    _load_reference_text,
    perform_comprehensive_research,
    search_internal,
)


def test_build_queries_uses_window_and_dedupes():
    blueprint = {
        "original_report_date": "2023-01-01",
        "update_start_date": "2024-01-01",
        "update_end_date": "2026-03-22",
    }

    queries = _build_queries("AI policy", ["AI policy", "EU AI Act"], blueprint)

    assert queries == [
        "AI policy 2024 2026",
        "AI policy latest 2026",
        "AI policy",
        "AI policy since 2023",
    ]


def test_assess_web_source_rejects_generic_archive_pages():
    quality, is_credible, reason = _assess_web_source(
        "News Archives",
        "https://example.com/news/archive",
        "Short snippet",
    )

    assert is_credible is False
    assert quality < 0.4
    assert "generic_path" in reason or "generic_title" in reason


def test_load_reference_text_supports_txt_docx_and_pdf(sample_txt_path: Path, sample_docx_path: Path, sample_pdf_path: Path):
    assert "AI adoption accelerated" in _load_reference_text(str(sample_txt_path))
    assert "AI adoption accelerated" in _load_reference_text(str(sample_docx_path))
    assert "AI adoption accelerated" in _load_reference_text(str(sample_pdf_path))


def test_search_internal_returns_paragraph_matches(sample_txt_path: Path):
    results = search_internal("spending adoption", [str(sample_txt_path)])

    assert results
    assert results[0]["source"] == "uploaded"
    assert "spending" in results[0]["snippet"].lower() or "adoption" in results[0]["snippet"].lower()


def test_perform_comprehensive_research_sorts_and_dedupes(monkeypatch, sample_txt_path: Path):
    monkeypatch.setattr(research_agent, "_translate_to_english", lambda text: text)
    monkeypatch.setattr(research_agent.time, "sleep", lambda _: None)
    monkeypatch.setattr(
        research_agent,
        "search_internal",
        lambda query, ref_paths: [
            {
                "title": "Internal Memo",
                "snippet": "AI policy adoption update for 2025 and 2026.",
                "source": "uploaded",
                "published_date": None,
            }
        ],
    )
    monkeypatch.setattr(
        research_agent,
        "search_web",
        lambda *args, **kwargs: [
            {
                "title": "Credible Web Source",
                "url": "https://example.com/web",
                "snippet": "AI policy update for 2025 and 2026.",
                "source": "web",
                "published_date": "2025-04-10",
            },
            {
                "title": "Credible Web Source Duplicate",
                "url": "https://example.com/web",
                "snippet": "Duplicate URL should be removed.",
                "source": "web",
                "published_date": "2026-01-15",
            },
        ],
    )
    monkeypatch.setattr(
        research_agent,
        "search_academic",
        lambda *args, **kwargs: [
            {
                "title": "Academic Study",
                "url": "https://openalex.org/W123",
                "snippet": "Peer-reviewed AI policy study with 2026 publication year.",
                "source": "academic",
                "published_date": "2026",
            }
        ],
    )

    blueprint = {
        "topic": "AI policy",
        "keywords": ["governance", "deployment"],
        "ref_paths": [str(sample_txt_path)],
        "original_report_date": "2023-01-01",
        "update_start_date": "2024-01-01",
        "update_end_date": "2026-03-22",
    }

    results = perform_comprehensive_research(blueprint)

    assert results
    assert results[0]["source_type"] == "academic"
    assert sum(1 for item in results if item.get("url") == "https://example.com/web") == 1
