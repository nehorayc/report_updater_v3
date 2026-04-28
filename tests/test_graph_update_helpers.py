from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from graph_update_helpers import (
    GRAPH_UPDATE_STATUS_INVALID,
    GRAPH_UPDATE_STATUS_NO_NEW_DATA,
    GRAPH_UPDATE_STATUS_UPDATED,
    asset_has_update_plan,
    apply_graph_update_contract,
    canonicalize_chart_data_points,
    inject_prepared_source_graph_updates,
    graph_update_validation_issues,
    merge_preserved_historical_data,
    merge_graph_update_references,
    prepare_source_graph_refresh,
    unresolved_source_chart_updates,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "graph_update"


def _load_fixture_json(name: str) -> dict | list:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def test_merge_preserved_historical_data_keeps_original_values_and_appends_new_years():
    extracted = {
        "labels": ["2020", "2021", "2022", "2023"],
        "values": [42, 58, 79, 101],
        "unit": "Thousand Units",
    }
    updated = {
        "labels": ["2020", "2021", "2022", "2023", "2024", "2025", "2026"],
        "values": [45, 55, 70, 90, 120, 185, 260],
        "unit": "Thousand Units",
    }

    merged = merge_preserved_historical_data(extracted, updated)

    assert merged == {
        "labels": ["2020", "2021", "2022", "2023", "2024", "2025", "2026"],
        "values": [42, 58, 79, 101, 120, 185, 260],
        "unit": "Thousand Units",
    }


def test_apply_graph_update_contract_sets_update_fields_and_clears_valid_graph_errors():
    visual = {
        "id": "feed2023aa1111111111111111111111",
        "type": "graph",
        "title": "Updated chart",
        "data_points": {
            "labels": ["2020", "2021", "2022", "2023", "2024", "2025", "2026"],
            "values": [45, 55, 70, 90, 120, 185, 260],
            "unit": "Thousand Units",
        },
    }
    matched_asset = {
        "id": "feed2023aa1111111111111111111111",
        "extracted_data_points": {
            "labels": ["2020", "2021", "2022", "2023"],
            "values": [42, 58, 79, 101],
            "unit": "Thousand Units",
        },
    }

    normalized = apply_graph_update_contract(
        visual,
        matched_asset=matched_asset,
        update_end_year="2026-03-22",
    )

    assert normalized["marker_id"] == matched_asset["id"]
    assert normalized["original_asset_id"] == matched_asset["id"]
    assert normalized["source_asset_id"] == matched_asset["id"]
    assert normalized["chart_type"] == "bar"
    assert normalized["update_end_date"] == "2026-03-22"
    assert normalized["data_points"]["values"] == [42, 58, 79, 101, 120, 185, 260]
    assert "graph_validation_errors" not in normalized


def test_graph_update_validation_issues_flag_history_drift_and_missing_end_year():
    visual = {
        "type": "graph",
        "chart_type": "bar",
        "original_asset_id": "feed2023aa1111111111111111111111",
        "data_points": {
            "labels": ["2020", "2021", "2022", "2023", "2024", "2025"],
            "values": [45, 58, 79, 101, 120, 185],
            "unit": "Thousand Units",
        },
    }
    extracted = {
        "labels": ["2020", "2021", "2022", "2023"],
        "values": [42, 58, 79, 101],
        "unit": "Thousand Units",
    }

    issues = graph_update_validation_issues(
        visual,
        update_end_year="2026-03-22",
        extracted_data_points=extracted,
    )
    codes = {issue["code"] for issue in issues}

    assert "graph_preserved_history_drift" in codes
    assert "graph_update_end_year_missing" in codes


def test_asset_has_update_plan_detects_refresh_and_convert_to_text():
    assert asset_has_update_plan({"do_update": True}) is True
    assert asset_has_update_plan({"convert_to_text": True}) is True
    assert asset_has_update_plan({"do_update": False, "convert_to_text": False}) is False


def test_unresolved_source_chart_updates_flags_planned_refresh_without_replacement():
    unresolved = unresolved_source_chart_updates(
        [
            {
                "id": "feed2023aa1111111111111111111111",
                "type": "chart",
                "short_caption": "Annual shipments",
                "do_update": True,
            }
        ],
        approved_visuals=[],
    )

    assert unresolved == [
        {
            "asset_id": "feed2023aa1111111111111111111111",
            "asset_type": "chart",
            "short_caption": "Annual shipments",
        }
    ]


def test_unresolved_source_chart_updates_accept_matching_update_graph():
    unresolved = unresolved_source_chart_updates(
        [
            {
                "id": "feed2023aa1111111111111111111111",
                "type": "chart",
                "short_caption": "Annual shipments",
                "do_update": True,
            }
        ],
        approved_visuals=[
            {
                "id": "feed2023aa1111111111111111111111__line_linear",
                "marker_id": "feed2023aa1111111111111111111111",
                "original_asset_id": "feed2023aa1111111111111111111111",
                "type": "graph",
            }
        ],
    )

    assert unresolved == []


def test_prepare_source_graph_refresh_merges_preserved_history_with_required_new_years():
    asset = dict(_load_fixture_json("baseline_asset.json"))
    asset["path"] = str((REPO_ROOT / asset["path"]).resolve())
    findings = _load_fixture_json("update_findings_2024_2026.json")
    expected = _load_fixture_json("expected_merged_data_2020_2026.json")

    result = prepare_source_graph_refresh(
        asset,
        findings,
        update_end_year="2026-03-22",
    )

    assert result["graph_update_status"] == GRAPH_UPDATE_STATUS_UPDATED
    assert result["prepared_update_visual"]["type"] == "graph"
    assert result["prepared_update_visual"]["original_asset_id"] == asset["id"]
    assert result["prepared_update_visual"]["data_points"] == expected["data_points"]


def test_prepare_source_graph_refresh_returns_no_new_data_when_numeric_years_are_missing():
    asset = dict(_load_fixture_json("baseline_asset.json"))
    asset["path"] = str((REPO_ROOT / asset["path"]).resolve())
    findings = [
        {
            "title": "Topical but non-numeric note",
            "snippet": (
                "Enterprise AI server demand remained elevated through 2025 and 2026, "
                "but the source did not publish shipment totals."
            ),
        }
    ]

    result = prepare_source_graph_refresh(
        asset,
        findings,
        update_end_year="2026-03-22",
    )

    assert result["graph_update_status"] == GRAPH_UPDATE_STATUS_NO_NEW_DATA
    assert result["prepared_update_visual"] is None
    assert "original figure was kept" in result["update_reason"].lower()


def test_prepare_source_graph_refresh_returns_invalid_on_conflicting_required_year_values():
    asset = dict(_load_fixture_json("baseline_asset.json"))
    asset["path"] = str((REPO_ROOT / asset["path"]).resolve())
    findings = [
        {
            "title": "First source",
            "snippet": "Enterprise AI server shipments reached 120 thousand units in 2024, 185 thousand units in 2025, and 260 thousand units in 2026.",
        },
        {
            "title": "Conflicting source",
            "snippet": "Enterprise AI server shipments reached 140 thousand units in 2024 as enterprise demand accelerated.",
        },
    ]

    result = prepare_source_graph_refresh(
        asset,
        findings,
        update_end_year="2026-03-22",
    )

    assert result["graph_update_status"] == GRAPH_UPDATE_STATUS_INVALID
    assert result["prepared_update_visual"] is None
    assert any("conflicting refreshed datapoints" in error.lower() for error in result["graph_update_validation_errors"])


def test_prepare_source_graph_refresh_can_use_llm_sourced_updates(monkeypatch):
    asset = dict(_load_fixture_json("baseline_asset.json"))
    asset["path"] = str((REPO_ROOT / asset["path"]).resolve())
    asset["source_context_heading"] = "Annual Shipments"
    asset["source_context_excerpt"] = "The original figure tracked enterprise AI server shipments and emphasized capacity planning."
    asset["source_context_fallback"] = "The chapter linked shipment growth to deployment readiness and infrastructure demand."
    asset["source_context_chapter_title"] = "Enterprise AI Infrastructure"
    findings = [
        {
            "title": "Enterprise AI server shipments update",
            "url": "https://example.com/shipments-update",
            "source_type": "web",
            "approved_for_writing": True,
            "snippet": "Enterprise AI server shipments reached 120 thousand units in 2024, 185 thousand units in 2025, and 260 thousand units in 2026.",
        }
    ]
    expected = _load_fixture_json("expected_merged_data_2020_2026.json")
    captured = {}

    monkeypatch.setattr("graph_update_helpers.get_api_key", lambda: "test-key")
    def fake_generate_content(**kwargs):
        captured["prompt"] = kwargs["contents"]
        return SimpleNamespace(
            text=json.dumps(
                {
                    "status": "updated",
                    "reason": "Found sourced shipment totals through 2026.",
                    "new_datapoints": [
                        {"year": 2024, "series": "Value", "value": 120, "unit": "Thousand Units", "source_ids": ["S1"]},
                        {"year": 2025, "series": "Value", "value": 185, "unit": "Thousand Units", "source_ids": ["S1"]},
                        {"year": 2026, "series": "Value", "value": 260, "unit": "Thousand Units", "source_ids": ["S1"]},
                    ],
                    "data_points": expected["data_points"],
                    "source_ids": ["S1"],
                }
            )
        )

    monkeypatch.setattr("graph_update_helpers.gemini_generate_content", fake_generate_content)

    result = prepare_source_graph_refresh(
        asset,
        findings,
        update_end_year="2026-03-22",
    )

    assert result["graph_update_status"] == GRAPH_UPDATE_STATUS_UPDATED
    assert result["prepared_update_visual"]["data_points"] == expected["data_points"]
    assert result["prepared_update_visual"]["graph_update_method"] == "llm"
    assert result["prepared_update_visual"]["graph_source_references"] == [
        {
            "index": 1,
            "title": "Enterprise AI server shipments update",
            "url": "https://example.com/shipments-update",
            "category": "Web",
        }
    ]
    assert "Original Report Context" in captured["prompt"]
    assert "Enterprise AI Infrastructure" in captured["prompt"]
    assert "capacity planning" in captured["prompt"]


def test_prepare_source_graph_refresh_allows_llm_multi_series_updates_with_mixed_units(monkeypatch):
    asset = {
        "id": "200f4bb779682bba74f01f32ae38d06e",
        "type": "chart",
        "short_caption": "Annual articles and share of field total, 2014-2024",
        "description": "A dual-axis line chart with article counts and field-share percentages.",
        "analysis": {"chart_type": "line"},
        "extracted_data_points": {
            "labels": ["2023", "2024"],
            "datasets": [
                {"label": "Count", "values": [320, 388], "unit": "Count"},
                {"label": "% of field annual total", "values": [0.15, 0.225], "unit": "%"},
            ],
        },
    }
    findings = [
        {
            "title": "Updated bibliometrics release",
            "url": "https://example.com/dna-bibliometrics",
            "source_type": "web",
            "approved_for_writing": True,
            "snippet": "The bibliometrics release reported 410 articles and a 0.24 field share in 2025, rising to 438 articles and a 0.255 field share in 2026.",
        }
    ]

    monkeypatch.setattr("graph_update_helpers.get_api_key", lambda: "test-key")
    monkeypatch.setattr(
        "graph_update_helpers.gemini_generate_content",
        lambda **kwargs: SimpleNamespace(
            text=json.dumps(
                {
                    "status": "updated",
                    "reason": "Found article-count and share updates through 2026.",
                    "new_datapoints": [
                        {"year": 2025, "series": "Count", "value": 410, "unit": "Count", "source_ids": ["S1"]},
                        {"year": 2025, "series": "% of field annual total", "value": 0.24, "unit": "%", "source_ids": ["S1"]},
                        {"year": 2026, "series": "Count", "value": 438, "unit": "Count", "source_ids": ["S1"]},
                        {"year": 2026, "series": "% of field annual total", "value": 0.255, "unit": "%", "source_ids": ["S1"]},
                    ],
                    "data_points": {
                        "labels": ["2023", "2024", "2025", "2026"],
                        "datasets": [
                            {"label": "Count", "values": [320, 388, 410, 438], "unit": "Count"},
                            {"label": "% of field annual total", "values": [0.15, 0.225, 0.24, 0.255], "unit": "%"},
                        ],
                    },
                    "source_ids": ["S1"],
                }
            )
        ),
    )

    result = prepare_source_graph_refresh(
        asset,
        findings,
        update_end_year="2026-03-22",
    )

    assert result["graph_update_status"] == GRAPH_UPDATE_STATUS_UPDATED
    assert "datasets" in result["prepared_update_visual"]["data_points"]
    assert result["prepared_update_visual"]["graph_source_references"][0]["title"] == "Updated bibliometrics release"


def test_merge_graph_update_references_appends_unique_graph_sources():
    merged = merge_graph_update_references(
        [
            {"index": 1, "title": "Writer Source", "url": "https://example.com/writer", "category": "Web"},
            {"index": 2, "title": "Updated bibliometrics release", "url": "https://example.com/dna-bibliometrics", "category": "Web"},
        ],
        [
            {
                "graph_update_status": GRAPH_UPDATE_STATUS_UPDATED,
                "prepared_update_visual": {
                    "graph_source_references": [
                        {
                            "index": 1,
                            "title": "Updated bibliometrics release",
                            "url": "https://example.com/dna-bibliometrics",
                            "category": "Web",
                        },
                        {
                            "index": 2,
                            "title": "Archive dataset",
                            "url": "https://example.com/archive-dataset",
                            "category": "Academic",
                        },
                    ]
                },
            }
        ],
    )

    assert merged == [
        {"index": 1, "title": "Writer Source", "url": "https://example.com/writer", "category": "Web"},
        {"index": 2, "title": "Updated bibliometrics release", "url": "https://example.com/dna-bibliometrics", "category": "Web"},
        {"index": 3, "title": "Archive dataset", "url": "https://example.com/archive-dataset", "category": "Academic"},
    ]


def test_inject_prepared_source_graph_updates_replaces_writer_generated_update_graph():
    asset = dict(_load_fixture_json("baseline_asset.json"))
    asset["path"] = str((REPO_ROOT / asset["path"]).resolve())
    findings = _load_fixture_json("update_findings_2024_2026.json")
    expected = _load_fixture_json("expected_merged_data_2020_2026.json")
    refresh_result = prepare_source_graph_refresh(
        asset,
        findings,
        update_end_year="2026-03-22",
    )
    asset.update(refresh_result)

    rewritten = inject_prepared_source_graph_updates(
        [
            {
                "id": asset["id"],
                "marker_id": asset["id"],
                "original_asset_id": asset["id"],
                "type": "graph",
                "title": "Writer-generated graph",
                "chart_type": "bar",
                "data_points": {
                    "labels": ["2024", "2025", "2026"],
                    "values": [99, 111, 222],
                    "unit": "Thousand Units",
                },
            }
        ],
        [asset],
    )

    assert len(rewritten) == 1
    assert rewritten[0]["prepared_source_graph_refresh"] is True
    assert rewritten[0]["data_points"] == expected["data_points"]


def test_unresolved_source_chart_updates_accept_no_new_data_when_original_asset_is_retained():
    unresolved = unresolved_source_chart_updates(
        [
            {
                "id": "feed2023aa1111111111111111111111",
                "type": "graph",
                "short_caption": "Annual shipments",
                "do_update": True,
                "graph_update_status": GRAPH_UPDATE_STATUS_NO_NEW_DATA,
            }
        ],
        approved_visuals=[
            {
                "original_asset_id": "feed2023aa1111111111111111111111",
                "type": "image",
            }
        ],
    )

    assert unresolved == []


def test_unresolved_source_chart_updates_keep_invalid_refreshes_blocking_even_if_original_is_present():
    unresolved = unresolved_source_chart_updates(
        [
            {
                "id": "feed2023aa1111111111111111111111",
                "type": "graph",
                "short_caption": "Annual shipments",
                "do_update": True,
                "graph_update_status": GRAPH_UPDATE_STATUS_INVALID,
            }
        ],
        approved_visuals=[
            {
                "original_asset_id": "feed2023aa1111111111111111111111",
                "type": "image",
            }
        ],
    )

    assert len(unresolved) == 1


def test_canonicalize_chart_data_points_supports_dataset_payloads():
    canonical = canonicalize_chart_data_points(
        {
            "labels": ["2024", "2025", "2026"],
            "datasets": [
                {"label": "Articles", "values": [120, 155, 190], "unit": "Count"},
                {"label": "Patents", "data": [14, 19, 28], "unit": "Count"},
            ],
        }
    )

    assert canonical == {
        "labels": ["2024", "2025", "2026"],
        "values": {
            "Articles": [120, 155, 190],
            "Patents": [14, 19, 28],
        },
        "unit": "Count",
    }
