from __future__ import annotations

import report_change_summary


def _sample_chapters():
    return [
        {
            "title": "Infrastructure",
            "original_full_text": "AI infrastructure demand was emerging in 2023 and budgets were still cautious.",
            "draft_text": "AI infrastructure demand accelerated in 2025 as enterprises expanded budgets and deployment programs.",
            "executive_takeaway": "Infrastructure demand moved from cautious pilots to larger budgeted deployments.",
            "updated_claims": ["Budget caution gave way to larger deployment programs."],
            "new_claims": ["Enterprises expanded infrastructure budgets in 2025."],
            "retained_claims": ["Infrastructure demand remained an important constraint."],
            "open_questions": ["Whether supply can keep up with enterprise demand."],
        },
        {
            "title": "Governance",
            "original_full_text": "Governance programs were still forming across enterprises.",
            "draft_text": "Governance programs are now tied to deployment approvals and operating controls.",
            "executive_takeaway": "Governance became an operating requirement rather than a side initiative.",
            "updated_claims": ["Governance shifted from planning to operational control."],
            "new_claims": ["Deployment approvals now depend on governance controls."],
            "retained_claims": [],
            "open_questions": [],
        },
    ]


def test_build_report_change_payload_with_normal_chapter_data():
    payload = report_change_summary.build_report_change_payload(_sample_chapters())

    assert payload["counts"] == {
        "total_chapters": 2,
        "changed_chapters": 2,
        "total_updated_claims": 2,
        "total_new_claims": 2,
        "total_retained_claims": 1,
        "total_open_questions": 1,
    }
    assert len(payload["chapters"]) == 2
    assert payload["chapters"][0]["title"] == "Infrastructure"
    assert payload["chapters"][0]["changed"] is True
    assert payload["chapters"][0]["original_word_count"] > 0
    assert payload["chapters"][0]["final_word_count"] > 0
    assert "original_excerpt" in payload["chapters"][0]
    assert "final_excerpt" in payload["chapters"][0]
    assert payload["ai_input"]["counts"]["changed_chapters"] == 2


def test_build_report_change_payload_handles_missing_claim_buckets():
    payload = report_change_summary.build_report_change_payload(
        [
            {
                "title": "No Claims",
                "original_full_text": "Original text only.",
                "draft_text": "Original text only.",
            }
        ]
    )

    chapter = payload["chapters"][0]
    assert payload["counts"]["changed_chapters"] == 0
    assert chapter["updated_claims"] == []
    assert chapter["new_claims"] == []
    assert chapter["retained_claims"] == []
    assert chapter["open_questions"] == []
    assert chapter["changed"] is False


def test_build_report_change_payload_handles_empty_report():
    payload = report_change_summary.build_report_change_payload([])

    assert payload["counts"]["total_chapters"] == 0
    assert payload["counts"]["changed_chapters"] == 0
    assert payload["chapters"] == []
    assert payload["ai_input"]["chapters"] == []


def test_build_report_change_payload_truncates_excerpts_and_aggregates_counts():
    long_text = " ".join(f"token{i}" for i in range(250))
    payload = report_change_summary.build_report_change_payload(
        [
            {
                "title": "Long Chapter",
                "original_full_text": long_text,
                "draft_text": long_text + " updated",
                "updated_claims": ["Updated once", "Updated once", "Updated twice"],
                "new_claims": ["New one"],
                "retained_claims": ["Still true"],
                "open_questions": ["What happens next?"],
            }
        ]
    )

    chapter = payload["chapters"][0]
    assert chapter["original_excerpt"].endswith("...")
    assert len(chapter["original_excerpt"]) <= 900
    assert payload["counts"]["total_updated_claims"] == 2
    assert payload["counts"]["total_new_claims"] == 1
    assert payload["counts"]["total_retained_claims"] == 1
    assert payload["counts"]["total_open_questions"] == 1


def test_generate_ai_report_change_summary_normalizes_response(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    payload = report_change_summary.build_report_change_payload(_sample_chapters())
    captured = {}

    class FakeResponse:
        text = """
        {
          "headline": "Key report updates",
          "summary_bullets": ["Budgets rose", "Governance matured", "Operational controls expanded"],
          "important_changes": [
            {"chapter_title": "Infrastructure", "change": "Budget caution gave way to expansion."},
            {"chapter_title": "Governance", "change": "Governance now gates deployment approvals."}
          ],
          "notable_open_questions": [
            {"chapter_title": "Infrastructure", "question": "Whether supply can keep up."}
          ]
        }
        """

    def fake_generate_content(*, api_key, model, contents, response_mime_type=None, temperature=None, operation=None):
        captured["api_key"] = api_key
        captured["model"] = model
        captured["contents"] = contents
        captured["response_mime_type"] = response_mime_type
        captured["temperature"] = temperature
        captured["operation"] = operation
        return FakeResponse()

    monkeypatch.setattr(report_change_summary.llm_client, "generate_content", fake_generate_content)

    result = report_change_summary.generate_ai_report_change_summary(payload)

    assert result["headline"] == "Key report updates"
    assert len(result["summary_bullets"]) == 3
    assert result["important_changes"][0]["chapter_title"] == "Infrastructure"
    assert result["notable_open_questions"][0]["question"] == "Whether supply can keep up."
    assert captured["api_key"] == "test-key"
    assert captured["response_mime_type"] == "application/json"
    assert captured["operation"] == "report_change_summary.generate_ai_report_change_summary"
    assert '"counts"' in captured["contents"]


def test_generate_ai_report_change_summary_returns_error_on_invalid_response(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    payload = report_change_summary.build_report_change_payload(_sample_chapters())

    class FakeResponse:
        text = "not valid json"

    monkeypatch.setattr(
        report_change_summary.llm_client,
        "generate_content",
        lambda **kwargs: FakeResponse(),
    )

    result = report_change_summary.generate_ai_report_change_summary(payload)

    assert "error" in result
    assert "Unable to generate AI change summary" in result["error"]


def test_report_change_signature_changes_when_draft_text_changes():
    chapters = _sample_chapters()
    original_signature = report_change_summary.compute_report_change_signature(
        chapters,
        provider="openai",
        model="gpt-5.4-mini",
    )

    chapters[0]["draft_text"] = chapters[0]["draft_text"] + " Additional update."
    changed_signature = report_change_summary.compute_report_change_signature(
        chapters,
        provider="openai",
        model="gpt-5.4-mini",
    )

    assert changed_signature != original_signature
