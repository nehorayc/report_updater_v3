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
