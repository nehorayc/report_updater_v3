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
from writer_agent import write_chapter


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "graph_update"


def _load_fixture_json(name: str) -> dict | list:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _load_fixture_text(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8").strip()


def _years_from_labels(labels: list[object]) -> set[int]:
    years: set[int] = set()
    for label in labels:
        for match in re.findall(r"(?<!\d)(?:19|20)\d{2}(?!\d)", str(label)):
            years.add(int(match))
    return years


def test_graph_update_fixtures_stop_at_2023_and_expect_refresh_through_2026():
    baseline_asset = _load_fixture_json("baseline_asset.json")
    baseline_graph = _load_fixture_json("baseline_data_2020_2023.json")
    source_text = _load_fixture_text("baseline_source_chapter.md")
    update_findings = _load_fixture_json("update_findings_2024_2026.json")

    baseline_labels = baseline_graph["data_points"]["labels"]
    baseline_years = _years_from_labels(baseline_labels)
    expected_updated_years = set(baseline_asset["expected_updated_years"])

    assert baseline_asset["id"] in source_text
    assert baseline_years == {2020, 2021, 2022, 2023}
    assert max(baseline_years) == 2023
    assert expected_updated_years == {2024, 2025, 2026}
    assert min(expected_updated_years) > max(baseline_years)
    assert len(update_findings) >= 2
    assert all("snippet" in finding and str(finding["snippet"]).strip() for finding in update_findings)

    baseline_image = REPO_ROOT / baseline_asset["path"]
    assert baseline_image.exists() and baseline_image.stat().st_size > 0

    with Image.open(baseline_image) as image:
        image.verify()


@pytest.mark.live_api
@pytest.mark.network
@pytest.mark.slow
def test_live_graph_updater_can_run_independently(tmp_path: Path, report_metadata: dict[str, str]):
    if os.getenv("RUN_LIVE_API_TESTS") != "1":
        pytest.skip("Set RUN_LIVE_API_TESTS=1 to run live Gemini graph updater tests.")

    load_dotenv(REPO_ROOT / ".env")
    if not os.getenv("GEMINI_API_KEY"):
        pytest.skip("GEMINI_API_KEY is required for live Gemini graph updater tests.")

    baseline_asset = dict(_load_fixture_json("baseline_asset.json"))
    baseline_asset["path"] = str((REPO_ROOT / baseline_asset["path"]).resolve())
    original_text = _load_fixture_text("baseline_source_chapter.md")
    graph_update_findings = _load_fixture_json("update_findings_2024_2026.json")

    baseline_years = set(baseline_asset["baseline_years"])
    expected_updated_years = set(baseline_asset["expected_updated_years"])
    original_asset_id = str(baseline_asset["id"])

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
            "Refresh the existing figure with new annual shipment data. "
            "The original source graph stops at 2023. "
            "The updated graph must include recent years through 2026. "
            "Keep the prose report-like, and prefer a bar or line chart for the updated visual."
        ),
    }

    writer_result = write_chapter(
        original_text=original_text,
        research_findings=graph_update_findings,
        blueprint=blueprint,
        writing_style="Professional",
        assets_to_update=[baseline_asset],
        prior_chapter_context=[],
        target_word_count=325,
        temperature=0.2,
    )

    skip_if_live_quota_exhausted(writer_result)
    assert "error" not in writer_result, writer_result.get("raw_content", "")
    assert original_asset_id in writer_result.get("text_content", "")

    visuals = [
        visual
        for visual in writer_result.get("visual_suggestions", [])
        if isinstance(visual, dict) and str(visual.get("type", "")).lower() == "graph"
    ]
    assert visuals, writer_result

    update_visuals = [
        visual
        for visual in visuals
        if str(visual.get("action", "")).lower() == "update"
        and str(visual.get("original_asset_id", "")) == original_asset_id
    ]
    assert update_visuals, writer_result

    update_visual = update_visuals[0]
    data_points = update_visual.get("data_points", {})
    assert isinstance(data_points, dict), update_visual
    assert isinstance(data_points.get("labels"), list) and len(data_points["labels"]) >= 2, update_visual
    assert data_points.get("values") not in (None, [], {}), update_visual

    updated_years = _years_from_labels(data_points["labels"])
    assert updated_years, update_visual
    assert max(updated_years) >= 2026, update_visual
    assert expected_updated_years.issubset(updated_years), update_visual
    assert max(updated_years) > max(baseline_years), update_visual
    assert not updated_years.issubset(baseline_years), update_visual

    render_result = generate_graph(update_visual, output_dir=str(tmp_path))
    assert "path" in render_result, {
        "writer_result": writer_result,
        "render_result": render_result,
    }

    rendered_path = Path(render_result["path"])
    assert rendered_path.exists() and rendered_path.stat().st_size > 0

    with Image.open(rendered_path) as rendered_image:
        rendered_image.verify()
