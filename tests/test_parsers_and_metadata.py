from __future__ import annotations

from pathlib import Path

import fitz
from PIL import Image, ImageDraw

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


def test_extract_pdf_content_preserves_soft_mask_transparency(tmp_path: Path):
    source_image_path = tmp_path / "alpha_chart.png"
    source_image = Image.new("RGBA", (220, 120), (0, 0, 0, 0))
    drawer = ImageDraw.Draw(source_image)
    drawer.rounded_rectangle((20, 20, 200, 100), radius=16, fill=(88, 196, 209, 180))
    source_image.save(source_image_path)

    pdf_path = tmp_path / "soft_mask_reference.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Masked Figure", fontsize=26)
    page.insert_image(fitz.Rect(72, 120, 292, 240), filename=str(source_image_path))
    doc.save(pdf_path)
    doc.close()

    parsed = extract_pdf_content(str(pdf_path), output_dir=str(tmp_path / "pdf_assets"))

    assert parsed["assets"]
    extracted_path = Path(parsed["assets"][0]["path"])
    extracted_image = Image.open(extracted_path).convert("RGBA")
    assert extracted_image.getpixel((0, 0))[3] == 0
    assert extracted_image.getpixel((110, 60))[3] > 0


def test_extract_pdf_content_uses_printed_toc_for_top_level_chapters(tmp_path: Path):
    path = tmp_path / "toc_reference.pdf"
    doc = fitz.open()

    page1 = doc.new_page()
    page1.insert_text((72, 72), "Sample Report", fontsize=28)
    page1.insert_text((220, 150), "Table of Contents", fontsize=16)
    page1.insert_text((260, 190), "Background", fontsize=14)
    page1.insert_text((96, 212), "- Technical description and context", fontsize=9)
    page1.insert_text((260, 240), "Assessment", fontsize=14)
    page1.insert_text((96, 262), "- Analyst findings and outlook", fontsize=9)

    page2 = doc.new_page()
    page2.insert_text((240, 90), "Background", fontsize=22)
    page2.insert_text((72, 132), "Description", fontsize=18)
    page2.insert_textbox(
        fitz.Rect(72, 156, 520, 250),
        "DNA storage uses synthetic strands to preserve dense archival information.",
        fontsize=10,
    )
    page2.insert_text((72, 270), "History", fontsize=18)
    page2.insert_textbox(
        fitz.Rect(72, 294, 520, 380),
        "Researchers demonstrated multiple proof-of-concept encoding workflows.",
        fontsize=10,
    )

    page3 = doc.new_page()
    page3.insert_text((240, 90), "Assessment", fontsize=22)
    page3.insert_text((72, 132), "Current State", fontsize=18)
    page3.insert_textbox(
        fitz.Rect(72, 156, 520, 250),
        "Commercial activity remains early while research output keeps expanding.",
        fontsize=10,
    )

    doc.save(path)
    doc.close()

    parsed = extract_pdf_content(str(path), output_dir=str(tmp_path / "toc_assets"))

    assert [chapter["title"] for chapter in parsed["chapters"]] == ["Background", "Assessment"]
    assert "### Description" in parsed["chapters"][0]["content"]
    assert "### History" in parsed["chapters"][0]["content"]
    assert "### Current State" in parsed["chapters"][1]["content"]


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
