from __future__ import annotations

import json

from llm_pricing import estimate_cost_usd, format_cost
from llm_usage import export_usage_reports, record_usage, reset_usage, summarize_usage


def test_cost_estimate_uses_cached_input_discount():
    cost = estimate_cost_usd(
        provider="openai",
        model="gpt-5.4-mini",
        input_tokens=1_000_000,
        cached_input_tokens=200_000,
        output_tokens=100_000,
    )

    expected = (800_000 / 1_000_000 * 0.75) + (200_000 / 1_000_000 * 0.075) + (100_000 / 1_000_000 * 4.50)
    assert cost == round(expected, 8)


def test_unknown_model_cost_is_unavailable():
    assert estimate_cost_usd(
        provider="openai",
        model="unknown-model",
        input_tokens=100,
        output_tokens=50,
    ) is None
    assert format_cost(None) == "Unavailable"


def test_dated_model_name_uses_base_pricing():
    cost = estimate_cost_usd(
        provider="openai",
        model="gpt-5.4-mini-2026-03-17",
        input_tokens=1_000_000,
        output_tokens=100_000,
    )

    expected = (1_000_000 / 1_000_000 * 0.75) + (100_000 / 1_000_000 * 4.50)
    assert cost == round(expected, 8)


def test_usage_summary_and_export(tmp_path):
    reset_usage()
    record_usage(
        provider="openai",
        model="gpt-5.4-mini",
        operation="writer",
        success=True,
        latency_seconds=1.25,
        input_tokens=100,
        cached_input_tokens=10,
        output_tokens=50,
        total_tokens=150,
    )
    record_usage(
        provider="openai",
        model="unknown-model",
        operation="writer",
        success=True,
        latency_seconds=0.75,
        input_tokens=20,
        output_tokens=10,
        total_tokens=30,
    )

    summary = summarize_usage()
    assert summary["calls"] == 2
    assert summary["input_tokens"] == 120
    assert summary["output_tokens"] == 60
    assert summary["unknown_cost_calls"] == 1
    assert summary["estimated_cost_usd"] > 0
    assert len(summary["by_group"]) == 2

    paths = export_usage_reports(str(tmp_path / "report"))
    assert paths["json"].endswith("_llm_usage.json")
    assert paths["csv"].endswith("_llm_usage.csv")

    payload = json.loads((tmp_path / "report_llm_usage.json").read_text(encoding="utf-8"))
    assert payload["summary"]["calls"] == 2
    assert len(payload["calls"]) == 2


def test_usage_summary_marks_all_unknown_costs_as_unavailable():
    reset_usage()
    record_usage(
        provider="openai",
        model="unknown-model",
        operation="writer",
        success=True,
        latency_seconds=0.75,
        input_tokens=20,
        output_tokens=10,
        total_tokens=30,
    )

    summary = summarize_usage()

    assert summary["unknown_cost_calls"] == 1
    assert summary["estimated_cost_usd"] is None
    assert summary["by_group"][0]["estimated_cost_usd"] is None
