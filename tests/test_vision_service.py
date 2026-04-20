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
