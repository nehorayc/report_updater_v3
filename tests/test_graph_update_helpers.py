from __future__ import annotations

from graph_update_helpers import (
    apply_graph_update_contract,
    canonicalize_chart_data_points,
    graph_update_validation_issues,
    merge_preserved_historical_data,
)


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
