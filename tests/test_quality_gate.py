from __future__ import annotations

from quality_gate import clean_fixable_issues, evaluate_report_quality


def test_quality_gate_flags_export_and_citation_defects(report_metadata):
    chapter = {
        "title": "Risky Chapter",
        "draft_text": (
            "Revenue grew 20% in 2024 without support.\n\n"
            "[Original Report]\n\n"
            "[visual: deadbeef placeholder]\n\n"
            "[Figure ID: badc0ffe_missing: Missing visual]\n\n"
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
            "[Figure ID: dead_beef: Missing visual]"
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
    assert "[Figure ID:" not in chapter["draft_text"]
    assert "[Original Report]" not in chapter["draft_text"]
    assert "[1]" in chapter["draft_text"]
    assert "[2]" in chapter["draft_text"]
    assert "url" not in chapter["references"][1]


def test_quality_gate_flags_and_cleans_meta_leakage_duplicate_headings_and_artifacts(report_metadata):
    chapter = {
        "title": "Outlook",
        "draft_text": (
            "### Outlook\n\n"
            "This updated edition addresses the topic of outlook, diverging from the original report's focus.\n\n"
            "### Area boxes. •\n\n"
            "### Innovators\n\n"
            "### Early Adopters\n\n"
            "### Late Majority\n"
            "15+ years\n\n"
            "\n\n"
            "7-10 years 7-10 years 7-10 years\n\n"
            "Supported assessment [1]."
        ),
        "references": [
            {"index": 1, "title": "Recent Update", "url": "https://example.com/update", "category": "Web"},
        ],
        "approved_visuals": [],
    }

    result = evaluate_report_quality([chapter], report_metadata)
    codes = {issue["code"] for issue in result["chapters"][0]["issues"]}

    assert {"meta_prompt_leakage", "duplicate_lead_heading", "pdf_artifact_text", "empty_heading_block"}.issubset(codes)

    cleanup = clean_fixable_issues([chapter])

    assert cleanup["summary"]["fixes_applied"] >= 4
    assert not chapter["draft_text"].startswith("### Outlook")
    assert "### Area boxes. •" not in chapter["draft_text"]
    assert "" not in chapter["draft_text"]
    assert "### Innovators" not in chapter["draft_text"]
    assert "### Early Adopters" not in chapter["draft_text"]
    assert "7-10 years 7-10 years 7-10 years" not in chapter["draft_text"]


def test_quality_gate_flags_grouped_citation_mismatches_and_analyst_agent_leak(report_metadata):
    chapter = {
        "title": "Quantitative Analysis",
        "draft_text": (
            "The Analyst Agent reports that the market grew 20% in 2025 [1, 4].\n\n"
            "[Figure ai_dna_a: AI Architecture]"
        ),
        "references": [
            {"index": 1, "title": "Recent Update", "url": "https://example.com/update", "category": "Web"},
        ],
        "approved_visuals": [],
    }

    result = evaluate_report_quality([chapter], report_metadata)
    codes = {issue["code"] for issue in result["chapters"][0]["issues"]}

    assert {"meta_prompt_leakage", "citation_reference_mismatch", "broken_figure_marker"}.issubset(codes)
    assert result["summary"]["blocking"] is True
