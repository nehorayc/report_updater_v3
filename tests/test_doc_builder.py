from __future__ import annotations

import zipfile
from pathlib import Path

from doc_builder import build_final_report, build_markdown_report, normalize_report_citations


def test_normalize_report_citations_remaps_and_dedupes():
    chapters = [
        {
            "title": "Chapter A",
            "draft_text": "Legacy claim [1]. Baseline framing [Original Report].",
            "references": [
                {"index": 1, "title": "Source A", "url": "https://example.com/a", "category": "Web"},
                {"index": "Original", "title": "Baseline Report", "category": "Original"},
            ],
        },
        {
            "title": "Chapter B",
            "draft_text": "Updated claim [1, 2].",
            "references": [
                {"index": 1, "title": "Source B", "url": "https://example.com/b", "category": "Academic"},
                {"index": 2, "title": "Source A", "url": "https://example.com/a", "category": "Web"},
            ],
        },
    ]

    normalized_chapters, ordered_refs = normalize_report_citations(chapters)

    assert [ref["title"] for ref in ordered_refs] == ["Source A", "Baseline Report", "Source B"]
    assert normalized_chapters[0]["draft_text"] == "Legacy claim [1]. Baseline framing [2]."
    assert normalized_chapters[1]["draft_text"] == "Updated claim [3, 1]."


def test_markdown_and_docx_exports_strip_raw_visual_tokens(tmp_path: Path, report_metadata, sample_visual):
    chapter = {
        "title": "Visual Chapter",
        "draft_text": (
            "Current state [1].\n\n"
            "[Figure abcdef12: Dummy Visual]\n\n"
            "[visual: deadbeef placeholder]"
        ),
        "approved_visuals": [sample_visual],
        "references": [
            {"index": 1, "title": "Recent Update", "url": "https://example.com/update", "category": "Web"}
        ],
    }

    markdown_zip = build_markdown_report(
        [chapter],
        output_path=str(tmp_path / "report.md"),
        title="Test Report",
        report_metadata=report_metadata,
    )
    assert Path(markdown_zip).exists()
    with zipfile.ZipFile(markdown_zip) as archive:
        md_name = next(name for name in archive.namelist() if name.endswith(".md"))
        markdown_text = archive.read(md_name).decode("utf-8")

    assert "[visual:" not in markdown_text
    assert "[Figure abcdef12" not in markdown_text
    assert "Dummy Visual" in markdown_text

    docx_path = build_final_report(
        [chapter],
        output_path=str(tmp_path / "report.docx"),
        title="Test Report",
        report_metadata=report_metadata,
    )
    assert Path(docx_path).exists()
    with zipfile.ZipFile(docx_path) as archive:
        document_xml = archive.read("word/document.xml").decode("utf-8")

    assert "[visual:" not in document_xml
    assert "Dummy Visual" in document_xml


def test_exports_omit_synthetic_front_matter_by_default(tmp_path: Path, report_metadata):
    chapter = {
        "title": "Background",
        "draft_text": "DNA storage remains relevant for archival workloads [1].",
        "references": [
            {"index": 1, "title": "Recent Update", "url": "https://example.com/update", "category": "Web"}
        ],
    }

    markdown_zip = build_markdown_report(
        [chapter],
        output_path=str(tmp_path / "report.md"),
        title="DNA Report",
        report_metadata=report_metadata,
    )
    with zipfile.ZipFile(markdown_zip) as archive:
        md_name = next(name for name in archive.namelist() if name.endswith(".md"))
        markdown_text = archive.read(md_name).decode("utf-8")

    assert "Updated and Researched via AI Agent" not in markdown_text
    assert "\n## Executive Summary\n" not in markdown_text
    assert "\n## Methodology\n" not in markdown_text
    assert markdown_text.count("# Background") == 1
