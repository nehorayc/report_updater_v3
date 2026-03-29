from __future__ import annotations

from report_context import (
    build_chapter_blueprint_defaults,
    build_prior_chapter_context,
    infer_report_subject,
)


def test_infer_report_subject_strips_report_prefixes():
    subject = infer_report_subject("report-DNA-digital-data-storage")
    assert subject == "DNA digital data storage"


def test_build_chapter_blueprint_defaults_anchor_generic_title_to_report_subject(report_metadata):
    chapter = {
        "title": "Qualitative analysis",
        "baseline": {
            "chapter_role": "body",
            "keywords": ["technology assessment", "innovation diffusion"],
            "named_entities": ["Harvard University"],
            "core_claims": ["The chapter evaluates the technology qualitatively."],
        },
    }

    defaults = build_chapter_blueprint_defaults(
        chapter,
        report_metadata=report_metadata,
        report_title="report-DNA-digital-data-storage",
    )

    assert defaults["report_subject"] == "DNA digital data storage"
    assert defaults["topic"] == "Qualitative analysis of DNA digital data storage"
    assert "DNA digital data storage" in defaults["keywords"]


def test_build_prior_chapter_context_uses_recent_generated_chapters():
    chapters = [
        {
            "title": "Background",
            "draft_text": "DNA storage remains a high-density archival medium with steep synthesis costs.",
            "executive_takeaway": "DNA storage remains promising for archival density.",
            "updated_claims": ["Synthesis cost remains a bottleneck."],
            "new_claims": ["Recent pilot systems improved retrieval workflows."],
            "open_questions": ["When will write costs fall enough for broader adoption?"],
        },
        {
            "title": "Quantitative Analysis",
            "draft_text": "Publication growth remains strong, but commercialization signals are still mixed.",
            "executive_takeaway": "Publication growth outpaces commercial deployment.",
            "updated_claims": ["Patent growth no longer maps cleanly to readiness."],
            "new_claims": ["Commercial evidence remains limited."],
        },
        {
            "title": "Current Chapter",
        },
    ]

    context = build_prior_chapter_context(chapters, current_index=2)

    assert [item["title"] for item in context] == ["Background", "Quantitative Analysis"]
    assert context[0]["summary"] == "DNA storage remains promising for archival density."
    assert "Synthesis cost remains a bottleneck." in context[0]["key_points"]
