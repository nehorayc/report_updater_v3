from __future__ import annotations

import zipfile
from pathlib import Path

from doc_builder import build_final_report, build_markdown_report
from quality_gate import clean_fixable_issues, evaluate_report_quality


def test_cleanup_then_export_produces_token_free_outputs(tmp_path: Path, report_metadata, sample_visual):
    chapter = {
        "title": "Pipeline Chapter",
        "draft_text": (
            "Current state [1].\n\n"
            "Revenue grew 20% in 2024 [2].\n\n"
            "[Original Report]\n\n"
            "[visual: deadbeef placeholder]\n\n"
            "[Figure abcdef12: Dummy Visual]\n\n"
            "[Figure deadbeef: Broken visual]"
        ),
        "approved_visuals": [sample_visual],
        "references": [
            {"index": 1, "title": "Baseline Report", "category": "Original"},
            {"index": 2, "title": "Recent Update", "url": "https://example.com/update", "category": "Web"},
        ],
    }

    cleanup = clean_fixable_issues([chapter])
    quality = evaluate_report_quality([chapter], report_metadata)

    assert cleanup["summary"]["fixes_applied"] >= 3
    assert quality["summary"]["blocking"] is False

    markdown_zip = build_markdown_report(
        [chapter],
        output_path=str(tmp_path / "pipeline.md"),
        title="Pipeline Report",
        report_metadata=report_metadata,
    )
    docx_path = build_final_report(
        [chapter],
        output_path=str(tmp_path / "pipeline.docx"),
        title="Pipeline Report",
        report_metadata=report_metadata,
    )

    with zipfile.ZipFile(markdown_zip) as archive:
        md_name = next(name for name in archive.namelist() if name.endswith(".md"))
        markdown_text = archive.read(md_name).decode("utf-8")
    with zipfile.ZipFile(docx_path) as archive:
        document_xml = archive.read("word/document.xml").decode("utf-8")

    assert "[visual:" not in markdown_text
    assert "[Original Report]" not in markdown_text
    assert "[Figure deadbeef" not in markdown_text
    assert "[visual:" not in document_xml
    assert "Dummy Visual" in markdown_text
    assert "Recent Update" in document_xml
