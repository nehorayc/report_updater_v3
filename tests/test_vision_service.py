from __future__ import annotations

import json
from pathlib import Path

import vision_service


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "graph_update"


def test_analyze_batch_assets_uses_chart_sidecar_data_points(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    class FakeResponse:
        text = json.dumps(
            [
                {
                    "id": "feed2023aa1111111111111111111111",
                    "type": "chart",
                    "short_caption": "Enterprise AI server shipments by year",
                    "dataset_description": "Bar chart showing annual enterprise AI server shipments.",
                    "suggested_update_query": "enterprise AI server shipments 2024 2025 2026",
                    "extracted_data_points": None,
                }
            ]
        )

    monkeypatch.setattr(vision_service, "gemini_generate_content", lambda **kwargs: FakeResponse())

    asset_path = FIXTURE_DIR / "enterprise_ai_server_shipments_2020_2023.png"
    results = vision_service.analyze_batch_assets(
        [{"id": "feed2023aa1111111111111111111111", "path": str(asset_path)}]
    )

    assert len(results) == 1
    extracted = results[0]["extracted_data_points"]
    assert extracted["labels"] == ["2020", "2021", "2022", "2023"]
    assert extracted["values"] == [42, 58, 79, 101]
    assert extracted["unit"] == "Thousand Units"


def test_analyze_batch_assets_unwraps_provider_object_and_fills_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    vision_service.reset_runtime_diagnostics()

    class FakeResponse:
        text = json.dumps(
            {
                "analysis": [
                    {
                        "id": "asset-one_chart42",
                        "type": "image",
                        "short_caption": "First selected source visual",
                        "dataset_description": "A valid analysis for the first selected visual.",
                        "suggested_update_query": None,
                        "extracted_data_points": None,
                    }
                ]
            }
        )

    monkeypatch.setattr(vision_service, "gemini_generate_content", lambda **kwargs: FakeResponse())

    asset_path = tmp_path / "source_visual.png"
    asset_path.write_bytes((FIXTURE_DIR / "enterprise_ai_server_shipments_2020_2023.png").read_bytes())
    results = vision_service.analyze_batch_assets(
        [
            {"id": "asset-one", "path": str(asset_path)},
            {"id": "asset-two", "path": str(asset_path)},
        ]
    )

    assert [result["id"] for result in results] == ["asset-one", "asset-two"]
    assert results[0]["short_caption"] == "First selected source visual"
    assert results[1]["short_caption"] == "Error analyzing image."
    diagnostics = vision_service.consume_runtime_diagnostics()
    assert any("fewer usable asset results" in item["message"] for item in diagnostics)
