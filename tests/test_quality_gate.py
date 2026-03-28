from __future__ import annotations

from quality_gate import clean_fixable_issues, evaluate_report_quality


def test_quality_gate_flags_export_and_citation_defects(report_metadata):
    chapter = {
        "title": "Risky Chapter",
        "draft_text": (
            "Revenue grew 20% in 2024 without support.\n\n"
            "[Original Report]\n\n"
            "[visual: deadbeef placeholder]\n\n"
            "[Figure badc0ffe: Missing visual]\n\n"
            "Later claim [4]."
        ),
        "references": [
            {"index": 1, "title": "Broken Ref", "url": "not-a-url", "category": "Web"},
        ],
        "approved_visuals": [],
    }

    result = evaluate_report_quality([chapter], report_metadata)
    issues = result["chapters"][0]["issues"]
    codes = {issue["code"] for issue in issues}

    expected = {
        "unsupported_claim_no_citation",
        "citation_reference_mismatch",
        "invalid_reference_url",
        "raw_original_citation_token",
        "raw_visual_token",
        "broken_figure_marker",
    }
    assert expected.issubset(codes)
    assert result["summary"]["blocking"] is True


def test_clean_fixable_issues_repairs_common_export_problems():
    chapter = {
        "title": "Cleanup Chapter",
        "draft_text": (
            "Supported paragraph [2].\n\n"
            "Revenue grew 20% in 2024.\n\n"
            "[Original Report]\n\n"
            "[visual: deadbeef placeholder]\n\n"
            "[Figure deadbeef: Missing visual]"
        ),
        "references": [
            {"index": 1, "title": "Baseline Report", "category": "Original"},
            {"index": 2, "title": "Recent Update", "url": "bad url", "category": "Web"},
        ],
        "approved_visuals": [],
    }

    cleanup = clean_fixable_issues([chapter])

    assert cleanup["summary"]["changed_chapters"] == 1
    assert cleanup["summary"]["fixes_applied"] >= 4
    assert "[visual:" not in chapter["draft_text"]
    assert "[Figure deadbeef" not in chapter["draft_text"]
    assert "[Original Report]" not in chapter["draft_text"]
    assert "[1]" in chapter["draft_text"]
    assert "[2]" in chapter["draft_text"]
    assert "url" not in chapter["references"][1]
