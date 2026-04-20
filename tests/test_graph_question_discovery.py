from __future__ import annotations

from graph_question_discovery import (
    discover_graphable_questions,
    evaluate_graphable_question_candidates,
)


def test_discover_graphable_questions_finds_trend_comparison_and_composition():
    findings = [
        {
            "id": "finding_patents",
            "title": "Annual patent filings for DNA data storage",
            "snippet": "Patent filings rose from 14 in 2021 to 19 in 2022, 28 in 2023, and 41 in 2024.",
            "source_type": "academic",
            "source_quality": 1.0,
            "freshness_score": 1.0,
            "relevance_score": 1.1,
            "approved_for_writing": True,
        },
        {
            "id": "finding_density",
            "title": "Storage density comparison across media",
            "snippet": "Synthetic DNA reached 215000000 TB per gram, archival tape 45, and SSD 3.5 in 2026.",
            "source_type": "academic",
            "source_quality": 1.0,
            "freshness_score": 1.0,
            "relevance_score": 1.0,
            "approved_for_writing": True,
        },
        {
            "id": "finding_trl",
            "title": "TRL distribution across active projects",
            "snippet": "TRL 3 represented 12%, TRL 4 18%, TRL 5 27%, and TRL 6 43% of projects in 2026.",
            "source_type": "web",
            "source_quality": 0.8,
            "freshness_score": 1.0,
            "relevance_score": 1.0,
            "approved_for_writing": True,
            "source_credible": True,
        },
    ]

    questions = discover_graphable_questions(
        findings,
        {
            "topic": "DNA digital data storage",
            "source_chapter_title": "Quantitative Analysis",
            "report_subject": "DNA digital data storage",
        },
    )

    assert len(questions) == 3
    assert {question["question_type"] for question in questions} == {"trend", "comparison", "composition"}
    assert all(question["graphable"] is True for question in questions)


def test_evaluate_graphable_question_candidates_rejects_sparse_questions():
    candidates = evaluate_graphable_question_candidates(
        [
            {
                "id": "finding_sparse",
                "title": "Recent cost shift",
                "snippet": "Costs changed in 2025.",
                "source_type": "web",
                "source_quality": 0.7,
                "freshness_score": 0.9,
                "relevance_score": 0.8,
                "approved_for_writing": True,
                "source_credible": True,
            }
        ],
        {
            "topic": "DNA digital data storage",
            "source_chapter_title": "Economics",
            "report_subject": "DNA digital data storage",
        },
    )

    assert len(candidates) == 1
    assert candidates[0]["graphable"] is False
    assert candidates[0]["rejected_reason"]
