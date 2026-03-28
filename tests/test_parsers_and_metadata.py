from __future__ import annotations

from pathlib import Path

from parse_docx import extract_docx_content
from parse_pdf import _structure_single_chapter_text, extract_pdf_content
from report_metadata_analyzer import infer_report_metadata


def test_structure_single_chapter_text_promotes_internal_headings():
    text = (
        "Executive Summary\n"
        "AI adoption accelerated in 2024 and spending rose materially.\n"
        "Key Findings\n"
        "Enterprises increased deployment activity across regulated sectors."
    )

    structured = _structure_single_chapter_text(text)

    assert "## Executive Summary" in structured
    assert "## Key Findings" in structured


def test_structure_single_chapter_text_promotes_numbered_internal_headings():
    text = (
        "1. Executive Summary\n"
        "AI adoption accelerated in 2024 and spending rose materially.\n"
        "2. Key Findings\n"
        "Enterprises increased deployment activity across regulated sectors."
    )

    structured = _structure_single_chapter_text(text)

    assert "## Executive Summary" in structured
    assert "## Key Findings" in structured
    assert "## 1. Executive Summary" not in structured


def test_extract_docx_content_pulls_chapters_and_assets(sample_docx_path: Path, tmp_path: Path):
    parsed = extract_docx_content(str(sample_docx_path), output_dir=str(tmp_path / "assets"))

    assert len(parsed["chapters"]) == 1
    assert parsed["chapters"][0]["title"] == "Chapter One"
    assert parsed["assets"]
    assert "[Asset:" in parsed["chapters"][0]["content"]


def test_extract_pdf_content_reads_heading_and_body(sample_pdf_path: Path, tmp_path: Path):
    parsed = extract_pdf_content(str(sample_pdf_path), output_dir=str(tmp_path / "pdf_assets"))

    assert parsed["chapters"]
    assert any("AI adoption accelerated" in chapter["content"] for chapter in parsed["chapters"])


def test_infer_report_metadata_prefers_full_front_matter_date():
    chapters = [
        {
            "title": "Executive Summary",
            "content": "Published March 15 2024. This report reviews AI adoption trends.",
        },
        {
            "title": "Outlook",
            "content": "In 2026 the market may mature further.",
        },
    ]

    metadata = infer_report_metadata("AI Report", chapters)

    assert metadata["original_report_date"] == "2024-03-15"


def test_infer_report_metadata_falls_back_to_year_only():
    chapters = [
        {
            "title": "Overview",
            "content": "2023 Annual AI Report for enterprise leaders.",
        }
    ]

    metadata = infer_report_metadata("AI Report", chapters)

    assert metadata["original_report_date"] == "2023-01-01"
