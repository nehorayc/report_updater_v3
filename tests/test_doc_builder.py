from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from doc_builder import ExportValidationError, build_final_report, build_markdown_report, normalize_report_citations
from PIL import Image


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
            "[Figure ID: abcdef1234567890: Dummy Visual]\n\n"
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
    assert "[Figure ID:" not in markdown_text
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
    assert "[Figure ID:" not in document_xml
    assert "Dummy Visual" in document_xml


def test_docx_export_embeds_visual_assets(tmp_path: Path, report_metadata, sample_visual):
    chapter = {
        "title": "Embedded Visual Chapter",
        "draft_text": (
            "Overview [1].\n\n"
            "[Figure abcdef12: Dummy Visual]\n\n"
            "The exported DOCX should contain an embedded image asset."
        ),
        "approved_visuals": [sample_visual],
        "references": [
            {"index": 1, "title": "Recent Update", "url": "https://example.com/update", "category": "Web"}
        ],
    }

    docx_path = build_final_report(
        [chapter],
        output_path=str(tmp_path / "embedded-report.docx"),
        title="Embedded Visual Report",
        report_metadata=report_metadata,
    )

    with zipfile.ZipFile(docx_path) as archive:
        archive_members = archive.namelist()
        media_members = [name for name in archive_members if name.startswith("word/media/")]
        document_xml = archive.read("word/document.xml").decode("utf-8")
        rels_xml = archive.read("word/_rels/document.xml.rels").decode("utf-8")

    assert len(media_members) == 1
    assert "Dummy Visual" in document_xml
    assert "[Figure abcdef12" not in document_xml
    assert "relationships/image" in rels_xml


def test_exports_include_external_image_attribution(tmp_path: Path, report_metadata, sample_visual):
    visual = dict(sample_visual)
    visual.update(
        {
            "provider": "pexels",
            "photographer_name": "Alex Smith",
            "source": "Pexels",
            "source_url": "https://www.pexels.com/photo/robotics-lab-123/",
            "license_label": "Pexels License",
            "attribution_text": "Photo by Alex Smith on Pexels",
        }
    )
    chapter = {
        "title": "Attributed Visual Chapter",
        "draft_text": "[Figure abcdef12: Dummy Visual]",
        "approved_visuals": [visual],
        "references": [],
    }

    markdown_zip = build_markdown_report(
        [chapter],
        output_path=str(tmp_path / "attributed.md"),
        title="Attributed Report",
        report_metadata=report_metadata,
    )
    with zipfile.ZipFile(markdown_zip) as archive:
        md_name = next(name for name in archive.namelist() if name.endswith(".md"))
        markdown_text = archive.read(md_name).decode("utf-8")

    assert "Figure: Dummy Visual - Photo by Alex Smith on Pexels" in markdown_text

    docx_path = build_final_report(
        [chapter],
        output_path=str(tmp_path / "attributed.docx"),
        title="Attributed Report",
        report_metadata=report_metadata,
    )
    with zipfile.ZipFile(docx_path) as archive:
        document_xml = archive.read("word/document.xml").decode("utf-8")

    assert "Figure: Dummy Visual - Photo by Alex Smith on Pexels" in document_xml


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


def test_export_resolves_exact_marker_ids_before_short_alias_collisions(tmp_path: Path, report_metadata):
    generated_path = tmp_path / "generated.png"
    original_path = tmp_path / "original.png"
    Image.new("RGB", (320, 240), color="crimson").save(generated_path)
    Image.new("RGB", (320, 240), color="forestgreen").save(original_path)

    generated_marker = "deadbeef111111111111111111111111"
    original_asset_id = "deadbeef222222222222222222222222"

    chapter = {
        "title": "Collision Chapter",
        "draft_text": (
            f"[Figure {generated_marker}: Generated Graph]\n\n"
            "[Figure deadbeef: Original Visual]"
        ),
        "approved_visuals": [
            {
                "id": generated_marker,
                "marker_id": generated_marker,
                "type": "graph",
                "path": str(generated_path),
                "title": "Generated Graph",
                "short_caption": "Generated Graph",
            },
            {
                "original_asset_id": original_asset_id,
                "type": "image",
                "path": str(original_path),
                "title": "Original Visual",
                "short_caption": "Original Visual",
            },
        ],
        "references": [],
    }

    markdown_zip = build_markdown_report(
        [chapter],
        output_path=str(tmp_path / "collision.md"),
        title="Collision Report",
        report_metadata=report_metadata,
    )
    with zipfile.ZipFile(markdown_zip) as archive:
        md_name = next(name for name in archive.namelist() if name.endswith(".md"))
        markdown_text = archive.read(md_name).decode("utf-8")
        archive_names = set(archive.namelist())

    assert "Generated Graph" in markdown_text
    assert "Original Visual" in markdown_text
    assert "[Figure deadbeef" not in markdown_text
    assert f"images/{generated_marker}.png" in archive_names
    assert f"images/{original_asset_id}.png" in archive_names

    docx_path = build_final_report(
        [chapter],
        output_path=str(tmp_path / "collision.docx"),
        title="Collision Report",
        report_metadata=report_metadata,
    )
    with zipfile.ZipFile(docx_path) as archive:
        document_xml = archive.read("word/document.xml").decode("utf-8")
        media_members = [name for name in archive.namelist() if name.startswith("word/media/")]

    assert "Generated Graph" in document_xml
    assert "Original Visual" in document_xml
    assert len(media_members) == 2


def test_exports_emit_visual_manifests(tmp_path: Path, report_metadata, sample_visual):
    chapter = {
        "title": "Manifest Chapter",
        "draft_text": "[Figure abcdef12: Dummy Visual]",
        "approved_visuals": [sample_visual],
        "references": [],
    }

    markdown_zip = build_markdown_report(
        [chapter],
        output_path=str(tmp_path / "manifest.md"),
        title="Manifest Report",
        report_metadata=report_metadata,
    )
    with zipfile.ZipFile(markdown_zip) as archive:
        manifest = json.loads(archive.read("visual_manifest.json").decode("utf-8"))

    assert len(manifest) == 1
    assert manifest[0]["caption"] == "Dummy Visual"
    assert manifest[0]["content_hash"]
    assert manifest[0]["text_reference_count"] == 1

    docx_path = build_final_report(
        [chapter],
        output_path=str(tmp_path / "manifest.docx"),
        title="Manifest Report",
        report_metadata=report_metadata,
    )
    manifest_path = Path(docx_path).with_name("manifest_visual_manifest.json")
    assert manifest_path.exists()
    docx_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert docx_manifest[0]["caption"] == "Dummy Visual"


def test_visual_manifest_marks_prepared_source_graph_refreshes_as_updated_graph(tmp_path: Path, report_metadata):
    updated_graph_path = tmp_path / "updated-graph.png"
    Image.new("RGB", (320, 240), color="royalblue").save(updated_graph_path)

    chapter = {
        "title": "Quantitative Analysis",
        "draft_text": "[Figure feed2023aa1111111111111111111111: Updated Enterprise AI Graph]",
        "approved_visuals": [
            {
                "id": "feed2023aa1111111111111111111111__line_linear",
                "marker_id": "feed2023aa1111111111111111111111",
                "original_asset_id": "feed2023aa1111111111111111111111",
                "type": "graph",
                "path": str(updated_graph_path),
                "title": "Updated Enterprise AI Graph",
                "short_caption": "Updated Enterprise AI Graph",
                "data_points": {
                    "labels": ["2020", "2021", "2022", "2023", "2024", "2025", "2026"],
                    "values": [42, 58, 79, 101, 120, 185, 260],
                    "unit": "Thousand Units",
                },
            }
        ],
        "references": [],
    }

    markdown_zip = build_markdown_report(
        [chapter],
        output_path=str(tmp_path / "updated-graph.md"),
        title="Updated Graph Report",
        report_metadata=report_metadata,
    )
    with zipfile.ZipFile(markdown_zip) as archive:
        manifest = json.loads(archive.read("visual_manifest.json").decode("utf-8"))

    assert len(manifest) == 1
    assert manifest[0]["source_type"] == "updated_graph"
    assert manifest[0]["original_asset_id"] == "feed2023aa1111111111111111111111"


def test_export_blocks_when_citation_normalization_would_drop_tokens(tmp_path: Path, report_metadata):
    chapter = {
        "title": "Broken Citations",
        "draft_text": "Updated claim [2].",
        "approved_visuals": [],
        "references": [
            {"index": 1, "title": "Only Source", "url": "https://example.com/source", "category": "Web"}
        ],
    }

    with pytest.raises(ExportValidationError, match="citation normalization would drop unresolved tokens"):
        build_markdown_report(
            [chapter],
            output_path=str(tmp_path / "broken.md"),
            title="Broken Report",
            report_metadata=report_metadata,
        )


def test_export_rejects_accidental_duplicate_visual_content_under_different_captions(
    tmp_path: Path,
    report_metadata,
    dummy_image_path: Path,
):
    chapter = {
        "title": "Duplicate Visuals",
        "draft_text": (
            "[Figure visualaa11: Adoption Curve]\n\n"
            "[Figure visualbb22: Lifecycle Diagram]"
        ),
        "approved_visuals": [
            {
                "id": "visualaa1111111111",
                "marker_id": "visualaa1111111111",
                "type": "image",
                "path": str(dummy_image_path),
                "title": "Adoption Curve",
                "short_caption": "Adoption Curve",
            },
            {
                "id": "visualbb2222222222",
                "marker_id": "visualbb2222222222",
                "type": "image",
                "path": str(dummy_image_path),
                "title": "Lifecycle Diagram",
                "short_caption": "Lifecycle Diagram",
            },
        ],
        "references": [],
    }

    with pytest.raises(ExportValidationError, match="Accidental duplicate visual content detected"):
        build_markdown_report(
            [chapter],
            output_path=str(tmp_path / "dupe.md"),
            title="Duplicate Report",
            report_metadata=report_metadata,
        )


def test_export_allows_explicit_visual_reuse_with_metadata(
    tmp_path: Path,
    report_metadata,
    dummy_image_path: Path,
):
    chapter = {
        "title": "Reused Visuals",
        "draft_text": (
            "[Figure visualaa11: Adoption Curve]\n\n"
            "[Figure visualbb22: Adoption Curve (repeat)]"
        ),
        "approved_visuals": [
            {
                "id": "visualaa1111111111",
                "marker_id": "visualaa1111111111",
                "type": "image",
                "path": str(dummy_image_path),
                "title": "Adoption Curve",
                "short_caption": "Adoption Curve",
                "source_asset_id": "visualaa1111111111",
            },
            {
                "id": "visualbb2222222222",
                "marker_id": "visualbb2222222222",
                "type": "image",
                "path": str(dummy_image_path),
                "title": "Adoption Curve (repeat)",
                "short_caption": "Adoption Curve (repeat)",
                "source_asset_id": "visualaa1111111111",
                "reuse_of_asset_id": "visualaa1111111111",
                "reuse_reason": "executive summary repeat",
                "is_reused_visual": True,
            },
        ],
        "references": [],
    }

    markdown_zip = build_markdown_report(
        [chapter],
        output_path=str(tmp_path / "reuse.md"),
        title="Reuse Report",
        report_metadata=report_metadata,
    )

    with zipfile.ZipFile(markdown_zip) as archive:
        manifest = json.loads(archive.read("visual_manifest.json").decode("utf-8"))

    assert len(manifest) == 2
    assert manifest[1]["is_reused_visual"] is True
    assert manifest[1]["reuse_of_asset_id"] == "visualaa1111111111"


def test_best_effort_markdown_export_continues_with_warnings(tmp_path: Path, report_metadata):
    chapter = {
        "title": "Best Effort Chapter",
        "draft_text": (
            "Updated claim [2].\n\n"
            "[Figure badc0ffe1111: Missing visual]"
        ),
        "approved_visuals": [],
        "references": [
            {"index": 1, "title": "Only Source", "url": "https://example.com/source", "category": "Web"}
        ],
    }

    warnings: list[str] = []
    markdown_zip = build_markdown_report(
        [chapter],
        output_path=str(tmp_path / "best-effort.md"),
        title="Best Effort Report",
        report_metadata=report_metadata,
        strict=False,
        export_warnings=warnings,
    )

    assert Path(markdown_zip).exists()
    assert warnings
    assert any("Citation normalization dropped unresolved tokens" in warning for warning in warnings)
    assert any("Best-effort Markdown export continued with visual issues" in warning for warning in warnings)
