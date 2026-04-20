from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest
from dotenv import load_dotenv
from PIL import Image

from graph_generator import generate_graph
from live_test_utils import skip_if_live_quota_exhausted
from vision_service import analyze_batch_assets
from writer_agent import write_chapter


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "graph_update"


def _load_fixture_json(name: str) -> dict | list:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _load_fixture_text(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8").strip()


def _years_from_labels(labels: list[object]) -> list[int]:
    years: list[int] = []
    for label in labels:
        for match in re.findall(r"(?<!\d)(?:19|20)\d{2}(?!\d)", str(label)):
            years.append(int(match))
    return years


def _year_to_value_map(labels: list[object], values: object) -> dict[int, float]:
    if not isinstance(values, list):
        return {}

    mapping: dict[int, float] = {}
    for label, value in zip(labels, values):
        matches = _years_from_labels([label])
        if not matches:
            continue
        try:
            mapping[matches[0]] = float(value)
        except (TypeError, ValueError):
            continue
    return mapping


@pytest.mark.live_api
@pytest.mark.network
@pytest.mark.slow
def test_live_graph_upgrade_flow_preserves_historical_data_and_extends_to_2026(
    tmp_path: Path,
    report_metadata: dict[str, str],
):
    if os.getenv("RUN_LIVE_API_TESTS") != "1":
        pytest.skip("Set RUN_LIVE_API_TESTS=1 to run live graph upgrade flow tests.")

    load_dotenv(REPO_ROOT / ".env")
    if not os.getenv("GEMINI_API_KEY"):
        pytest.skip("GEMINI_API_KEY is required for live graph upgrade flow tests.")

    baseline_asset = dict(_load_fixture_json("baseline_asset.json"))
    baseline_asset["path"] = str((REPO_ROOT / baseline_asset["path"]).resolve())
    original_text = _load_fixture_text("baseline_source_chapter.md")
    update_findings = _load_fixture_json("update_findings_2024_2026.json")
    expected_merged = _load_fixture_json("expected_merged_data_2020_2026.json")

    baseline_graph = _load_fixture_json("baseline_data_2020_2023.json")
    baseline_labels = baseline_graph["data_points"]["labels"]
    baseline_values = baseline_graph["data_points"]["values"]
    expected_labels = expected_merged["data_points"]["labels"]
    expected_values = expected_merged["data_points"]["values"]

    analysis_results = analyze_batch_assets(
        [{"id": baseline_asset["id"], "path": baseline_asset["path"]}]
    )

    skip_if_live_quota_exhausted(analysis_results)
    assert len(analysis_results) == 1, analysis_results
    analysis = analysis_results[0]
    assert str(analysis.get("type", "")).lower() in {"chart", "graph"}, analysis
    assert str(analysis.get("suggested_update_query", "")).strip(), analysis

    extracted_data_points = analysis.get("extracted_data_points")
    assert isinstance(extracted_data_points, dict), analysis
    assert extracted_data_points.get("labels") == baseline_labels, analysis
    assert extracted_data_points.get("values") == baseline_values, analysis

    baseline_asset["description"] = analysis.get("dataset_description", baseline_asset.get("description", ""))
    baseline_asset["update_query"] = analysis.get("suggested_update_query", baseline_asset.get("update_query"))
    baseline_asset["extracted_data_points"] = extracted_data_points

    blueprint = {
        "topic": "Enterprise AI infrastructure capacity and deployment trends",
        "timeframe": "2024-2026",
        "baseline_summary": "A chapter on enterprise AI infrastructure demand, hardware capacity, and deployment readiness.",
        "baseline_claims": [
            "Enterprise AI programs were increasing hardware requirements.",
            "Capacity planning and deployment readiness mattered for adoption.",
        ],
        "source_chapter_title": "Enterprise AI Infrastructure",
        "chapter_role": "body",
        "original_report_date": report_metadata["original_report_date"],
        "update_start_date": report_metadata["update_start_date"],
        "update_end_date": report_metadata["update_end_date"],
        "target_audience": report_metadata["target_audience"],
        "output_language": report_metadata["output_language"],
        "edition_title": "Enterprise AI Update",
        "report_subject": "Enterprise AI",
        "preserve_original_voice": True,
        "instructions": (
            "Refresh the existing figure with new annual shipment data through 2026. "
            "Preserve the historical datapoints extracted from the original chart exactly. "
            "Only extend the series with the new years required by the update window."
        ),
    }

    writer_result = write_chapter(
        original_text=original_text,
        research_findings=update_findings,
        blueprint=blueprint,
        writing_style="Professional",
        assets_to_update=[baseline_asset],
        prior_chapter_context=[],
        target_word_count=325,
        temperature=0.2,
    )

    skip_if_live_quota_exhausted(writer_result)
    assert "error" not in writer_result, writer_result.get("raw_content", "")
    visuals = [
        visual
        for visual in writer_result.get("visual_suggestions", [])
        if isinstance(visual, dict)
        and str(visual.get("type", "")).lower() == "graph"
        and str(visual.get("action", "")).lower() == "update"
        and str(visual.get("original_asset_id", "")) == str(baseline_asset["id"])
    ]
    assert visuals, writer_result

    update_visual = visuals[0]
    data_points = update_visual.get("data_points", {})
    assert isinstance(data_points, dict), update_visual

    labels = data_points.get("labels")
    values = data_points.get("values")
    assert labels == expected_labels, update_visual

    actual_map = _year_to_value_map(labels, values)
    expected_map = _year_to_value_map(expected_labels, expected_values)
    assert actual_map == expected_map, update_visual

    render_result = generate_graph(update_visual, output_dir=str(tmp_path))
    assert "path" in render_result, {
        "analysis": analysis,
        "writer_result": writer_result,
        "render_result": render_result,
    }

    rendered_path = Path(render_result["path"])
    assert rendered_path.exists() and rendered_path.stat().st_size > 0

    with Image.open(rendered_path) as rendered_image:
        rendered_image.verify()
