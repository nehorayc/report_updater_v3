from __future__ import annotations

from pathlib import Path

import research_agent
from research_agent import (
    _assess_web_source,
    _build_queries,
    _load_reference_text,
    _translate_terms_to_english,
    perform_comprehensive_research,
    search_internal,
    search_web,
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
    research_agent._RESEARCH_RESULT_CACHE.clear()
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
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


def test_translate_terms_to_english_batches_hebrew_terms(monkeypatch):
    research_agent._TRANSLATION_CACHE.clear()
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    calls = {"generate": 0}
    hebrew_ai = "\u05d1\u05d9\u05e0\u05d4 \u05de\u05dc\u05d0\u05db\u05d5\u05ea\u05d9\u05ea"
    hebrew_regulation = "\u05e8\u05d2\u05d5\u05dc\u05e6\u05d9\u05d4"

    class FakeResponse:
        text = """
        {
          "translations": [
            {"source": "\\u05d1\\u05d9\\u05e0\\u05d4 \\u05de\\u05dc\\u05d0\\u05db\\u05d5\\u05ea\\u05d9\\u05ea", "translation": "artificial intelligence"},
            {"source": "\\u05e8\\u05d2\\u05d5\\u05dc\\u05e6\\u05d9\\u05d4", "translation": "regulation"}
          ]
        }
        """

    def fake_generate_content(*, api_key, model, contents, response_mime_type=None, temperature=None):
        calls["generate"] += 1
        assert api_key == "test-key"
        assert model == "gemini-2.0-flash"
        assert hebrew_ai in contents
        assert hebrew_regulation in contents
        assert response_mime_type == "application/json"
        return FakeResponse()

    monkeypatch.setattr(research_agent, "gemini_generate_content", fake_generate_content)

    translations = _translate_terms_to_english([hebrew_ai, "regulation", hebrew_regulation])

    assert calls["generate"] == 1
    assert translations[hebrew_ai] == "artificial intelligence"
    assert translations["regulation"] == "regulation"
    assert translations[hebrew_regulation] == "regulation"


def test_search_web_uses_query_cache(monkeypatch):
    research_agent._WEB_SEARCH_CACHE.clear()
    research_agent._ARTICLE_TEXT_CACHE.clear()

    calls = {"ddg": 0, "fetch": 0}

    class FakeDDGS:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def text(self, query, max_results=5):
            calls["ddg"] += 1
            return [
                {
                    "title": "Cached result",
                    "href": "https://example.com/a",
                    "body": "Snippet body",
                    "date": "2025-01-01",
                }
            ]

    def fake_fetch(url):
        calls["fetch"] += 1
        return "Full article body for caching."

    monkeypatch.setattr(research_agent, "DDGS", FakeDDGS)
    monkeypatch.setattr(research_agent, "_fetch_article_text", fake_fetch)

    first = search_web("AI policy", start_year=2024, end_year=2026)
    second = search_web("AI policy", start_year=2024, end_year=2026)

    assert first == second
    assert calls["ddg"] == 1
    assert calls["fetch"] == 1


def test_perform_comprehensive_research_uses_result_cache(monkeypatch):
    research_agent._RESEARCH_RESULT_CACHE.clear()
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    calls = {"translate_terms": 0, "web": 0, "academic": 0}

    monkeypatch.setattr(research_agent.time, "sleep", lambda _: None)
    monkeypatch.setattr(research_agent, "_translate_terms_to_english", lambda texts: calls.__setitem__("translate_terms", calls["translate_terms"] + 1) or {str(text).strip(): str(text).strip() for text in texts if str(text).strip()})
    monkeypatch.setattr(research_agent, "search_internal", lambda query, ref_paths: [])
    monkeypatch.setattr(
        research_agent,
        "search_web",
        lambda *args, **kwargs: calls.__setitem__("web", calls["web"] + 1) or [
            {
                "title": "Credible Web Source",
                "url": "https://example.com/web",
                "snippet": "AI policy update for 2025 and 2026.",
                "source": "web",
                "published_date": "2025-04-10",
            }
        ],
    )
    monkeypatch.setattr(
        research_agent,
        "search_academic",
        lambda *args, **kwargs: calls.__setitem__("academic", calls["academic"] + 1) or [],
    )

    blueprint = {
        "topic": "AI policy",
        "keywords": ["governance"],
        "original_report_date": "2023-01-01",
        "update_start_date": "2024-01-01",
        "update_end_date": "2026-03-22",
    }

    first = perform_comprehensive_research(blueprint)
    second = perform_comprehensive_research(blueprint)

    assert first == second
    assert calls["translate_terms"] == 1
    assert calls["web"] == 4
    assert calls["academic"] == 4


def test_prefilter_findings_for_topic_drops_clearly_off_topic_sources():
    findings = [
        {
            "title": "DNA data storage commercialization roadmap",
            "snippet": "DNA storage systems are moving toward archival deployment and synthesis cost reduction.",
            "source": "academic",
            "source_type": "academic",
            "source_quality": 1.0,
            "freshness_score": 1.0,
            "relevance_score": 1.5,
        },
        {
            "title": "Personalized nutrition and omics data integration",
            "snippet": "Nutrition data fusion and omics analytics support personalized dietary recommendations.",
            "source": "academic",
            "source_type": "academic",
            "source_quality": 1.0,
            "freshness_score": 1.0,
            "relevance_score": 0.7,
        },
    ]

    filtered = research_agent._prefilter_findings_for_topic(
        findings,
        {
            "topic": "DNA digital data storage",
            "source_chapter_title": "DNA digital data storage",
            "report_subject": "DNA digital data storage",
            "keywords": ["DNA storage", "archival storage"],
        },
        "DNA digital data storage",
        ["DNA storage", "archival storage"],
    )

    assert len(filtered) == 1
    assert filtered[0]["title"] == "DNA data storage commercialization roadmap"


def test_llm_rerank_marks_only_direct_sources_as_approved(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("RESEARCH_RANKER_MODEL", "gemini-2.5-flash")

    class FakeResponse:
        text = """
        {
          "sources": [
            {
              "id": "1",
              "relevance_score": 0.96,
              "directly_on_topic": true,
              "background_only": false,
              "cross_domain_analogy": false,
              "keep": true,
              "reason": "Directly about DNA data storage."
            },
            {
              "id": "2",
              "relevance_score": 0.18,
              "directly_on_topic": false,
              "background_only": true,
              "cross_domain_analogy": true,
              "keep": false,
              "reason": "Only tangential biotech analogy."
            }
          ]
        }
        """

    def fake_generate_content(*, api_key, model, contents, response_mime_type=None, temperature=None):
        assert api_key == "test-key"
        assert model == "gemini-2.5-flash"
        assert "DNA digital data storage" in contents
        assert response_mime_type == "application/json"
        return FakeResponse()

    monkeypatch.setattr(research_agent, "gemini_generate_content", fake_generate_content)

    reranked = research_agent._llm_rerank_findings_for_topic(
        [
            {
                "title": "DNA data storage commercialization roadmap",
                "snippet": "DNA storage systems are moving toward archival deployment.",
                "source": "academic",
                "source_type": "academic",
                "source_quality": 1.0,
                "freshness_score": 1.0,
                "relevance_score": 1.2,
                "priority_topic_hits": ["dna", "storage"],
                "topic_phrase_hits": ["DNA digital data storage"],
                "context_topic_hits": ["digital", "storage"],
                "deterministic_topic_score": 4.2,
                "passes_topic_prefilter": True,
            },
            {
                "title": "Personalized nutrition and omics data integration",
                "snippet": "Nutrition data fusion and omics analytics support personalized dietary recommendations.",
                "source": "academic",
                "source_type": "academic",
                "source_quality": 1.0,
                "freshness_score": 1.0,
                "relevance_score": 0.4,
                "priority_topic_hits": [],
                "topic_phrase_hits": [],
                "context_topic_hits": ["data"],
                "deterministic_topic_score": 0.9,
                "passes_topic_prefilter": True,
            },
        ],
        {
            "topic": "DNA digital data storage",
            "source_chapter_title": "DNA digital data storage",
            "report_subject": "DNA digital data storage",
            "keywords": ["DNA storage", "archival storage"],
        },
        "DNA digital data storage",
        ["DNA storage", "archival storage"],
    )

    approved = [item for item in reranked if item.get("approved_for_writing")]
    assert len(approved) == 1
    assert approved[0]["title"] == "DNA data storage commercialization roadmap"
