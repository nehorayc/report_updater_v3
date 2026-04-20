from __future__ import annotations

from pathlib import Path
import warnings

import pytest

import graph_generator
from graph_generator import _make_safe_globals, _safe_import, generate_graph


def test_safe_graph_sandbox_blocks_unsafe_imports():
    safe_globals = _make_safe_globals()

    assert "open" not in safe_globals["__builtins__"]
    with pytest.raises(ImportError):
        _safe_import("os")


def test_generate_graph_falls_back_to_static_single_series(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(graph_generator, "generate_graph_with_llm", lambda *args, **kwargs: {"error": "skip"})

    result = generate_graph(
        {
            "title": "Single Series",
            "data_points": {"labels": ["A", "B", "C"], "values": [1, 2, 3]},
        },
        output_dir=str(tmp_path),
    )

    assert "path" in result
    assert Path(result["path"]).exists()


def test_generate_graph_handles_multi_series_and_nested_dicts(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(graph_generator, "generate_graph_with_llm", lambda *args, **kwargs: {"error": "skip"})

    result = generate_graph(
        {
            "title": "Multi Series",
            "chart_type": "line",
            "data_points": {
                "labels": ["2024", "2025", "2026"],
                "values": {
                    "Series A": {"2024": 10, "2025": 20, "2026": 30},
                    "Series B": [12, 18, 25],
                },
            },
        },
        output_dir=str(tmp_path),
    )

    assert "path" in result
    assert Path(result["path"]).exists()


def test_generate_graph_handles_dataset_style_series(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(graph_generator, "generate_graph_with_llm", lambda *args, **kwargs: {"error": "skip"})

    result = generate_graph(
        {
            "title": "Dataset Style",
            "chart_type": "line",
            "data_points": {
                "labels": ["2024", "2025", "2026"],
                "datasets": [
                    {"label": "Articles", "values": [120, 155, 190], "unit": "Count"},
                    {"label": "Patents", "data": [14, 19, 28], "unit": "Count"},
                ],
            },
        },
        output_dir=str(tmp_path),
    )

    assert "path" in result
    assert Path(result["path"]).exists()


def test_generate_graph_returns_error_for_missing_data(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(graph_generator, "generate_graph_with_llm", lambda *args, **kwargs: {"error": "skip"})

    result = generate_graph(
        {
            "title": "Missing Data",
            "data_points": {"labels": [], "values": []},
        },
        output_dir=str(tmp_path),
    )

    assert result["error"] == "No data points found for graph"


def test_generate_graph_short_circuits_all_zero_series_without_llm(monkeypatch, tmp_path: Path):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("LLM path should not be used when graph data is empty/all-zero")

    monkeypatch.setattr(graph_generator, "generate_graph_with_llm", fail_if_called)

    result = generate_graph(
        {
            "title": "All Zero Series",
            "chart_type": "line",
            "data_points": {"labels": ["2024", "2025", "2026"], "values": [0, 0, 0]},
        },
        output_dir=str(tmp_path),
    )

    assert result["error"] == "No data points found for graph"


def test_generate_graph_handles_single_series_length_mismatch(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(graph_generator, "generate_graph_with_llm", lambda *args, **kwargs: {"error": "skip"})

    result = generate_graph(
        {
            "title": "Length Mismatch",
            "chart_type": "bar",
            "data_points": {"labels": ["A", "B", "C", "D"], "values": [1, 2]},
        },
        output_dir=str(tmp_path),
    )

    assert "path" in result
    assert Path(result["path"]).exists()


def test_generate_graph_single_series_line_avoids_ticklabel_warning(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(graph_generator, "generate_graph_with_llm", lambda *args, **kwargs: {"error": "skip"})

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = generate_graph(
            {
                "title": "Quiet Line",
                "chart_type": "line",
                "data_points": {"labels": ["2024", "2025", "2026"], "values": [10, 20, 30]},
            },
            output_dir=str(tmp_path),
        )

    assert "path" in result
    assert Path(result["path"]).exists()
    assert not any("set_ticklabels()" in str(warning.message) for warning in caught)


def test_generate_graph_skips_llm_for_simple_structured_chart(monkeypatch, tmp_path: Path):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("LLM path should not be used for simple structured charts")

    monkeypatch.setattr(graph_generator, "generate_graph_with_llm", fail_if_called)

    result = generate_graph(
        {
            "title": "Static First",
            "chart_type": "bar",
            "data_points": {"labels": ["A", "B"], "values": [3, 5]},
        },
        output_dir=str(tmp_path),
    )

    assert "path" in result
    assert Path(result["path"]).exists()


def test_generate_graph_uses_llm_first_for_complex_chart(monkeypatch, tmp_path: Path):
    calls = {"llm": 0}
    llm_path = tmp_path / "llm_graph.png"
    llm_path.write_bytes(b"png")

    def fake_llm(*args, **kwargs):
        calls["llm"] += 1
        return {"path": str(llm_path), "filename": llm_path.name}

    monkeypatch.setattr(graph_generator, "generate_graph_with_llm", fake_llm)

    result = generate_graph(
        {
            "title": "Complex Scatter",
            "chart_type": "scatter",
            "data_points": {"labels": ["A", "B"], "values": [3, 5]},
        },
        output_dir=str(tmp_path),
    )

    assert calls["llm"] == 1
    assert result["path"] == str(llm_path)


def test_generate_graph_rejects_update_graphs_with_history_drift_or_missing_end_year(monkeypatch, tmp_path: Path):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("Renderer should not run when update-graph validation already failed")

    monkeypatch.setattr(graph_generator, "generate_graph_with_llm", fail_if_called)

    result = generate_graph(
        {
            "title": "Invalid Updated Graph",
            "type": "graph",
            "chart_type": "bar",
            "original_asset_id": "feed2023aa1111111111111111111111",
            "update_end_date": "2026-03-22",
            "extracted_data_points": {
                "labels": ["2020", "2021", "2022", "2023"],
                "values": [42, 58, 79, 101],
                "unit": "Thousand Units",
            },
            "data_points": {
                "labels": ["2020", "2021", "2022", "2023", "2024", "2025"],
                "values": [45, 58, 79, 101, 120, 185],
                "unit": "Thousand Units",
            },
        },
        output_dir=str(tmp_path),
    )

    assert "error" in result
    assert "Graph update validation failed" in result["error"]


def test_generate_graph_uses_log_scale_variant_without_llm(monkeypatch, tmp_path: Path):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("LLM path should not be used for static log-scale graphs")

    monkeypatch.setattr(graph_generator, "generate_graph_with_llm", fail_if_called)

    result = generate_graph(
        {
            "title": "Extreme Ratio",
            "chart_type": "bar",
            "y_axis_scale": "log",
            "data_points": {
                "labels": ["Synthetic DNA", "LTO-9 Tape"],
                "values": [215000000, 45],
                "unit": "TB per gram",
            },
        },
        output_dir=str(tmp_path),
    )

    assert "path" in result
    assert Path(result["path"]).exists()
