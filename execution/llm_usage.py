from __future__ import annotations

import csv
import json
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List

from llm_pricing import estimate_cost_usd


_USAGE_LOCK = threading.Lock()
_USAGE_ROWS: List[Dict[str, Any]] = []


def reset_usage() -> None:
    with _USAGE_LOCK:
        _USAGE_ROWS.clear()


def get_usage_rows() -> List[Dict[str, Any]]:
    with _USAGE_LOCK:
        return [dict(row) for row in _USAGE_ROWS]


def record_usage(
    *,
    provider: str,
    model: str,
    operation: str,
    success: bool,
    latency_seconds: float | None,
    input_tokens: int | None = None,
    cached_input_tokens: int | None = None,
    output_tokens: int | None = None,
    total_tokens: int | None = None,
    error: str | None = None,
) -> Dict[str, Any]:
    estimated_cost_usd = None
    has_token_counts = any(
        value is not None
        for value in (input_tokens, cached_input_tokens, output_tokens, total_tokens)
    )
    if success and has_token_counts:
        estimated_cost_usd = estimate_cost_usd(
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            cached_input_tokens=cached_input_tokens,
            output_tokens=output_tokens,
        )

    row = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "provider": str(provider or "").strip().lower(),
        "model": str(model or "").strip(),
        "operation": str(operation or "llm.generate_content").strip(),
        "success": bool(success),
        "latency_seconds": round(float(latency_seconds or 0), 3),
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "estimated_cost_usd": estimated_cost_usd,
        "error": str(error or "").strip()[:500],
    }

    with _USAGE_LOCK:
        _USAGE_ROWS.append(row)
    return dict(row)


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def summarize_usage(rows: Iterable[Dict[str, Any]] | None = None) -> Dict[str, Any]:
    usage_rows = list(rows) if rows is not None else get_usage_rows()
    total_cost = 0.0
    has_known_cost = False
    unknown_cost_calls = 0
    groups: Dict[tuple[str, str, str], Dict[str, Any]] = {}

    summary = {
        "calls": len(usage_rows),
        "successful_calls": sum(1 for row in usage_rows if row.get("success")),
        "failed_calls": sum(1 for row in usage_rows if not row.get("success")),
        "input_tokens": sum(_safe_int(row.get("input_tokens")) for row in usage_rows),
        "cached_input_tokens": sum(_safe_int(row.get("cached_input_tokens")) for row in usage_rows),
        "output_tokens": sum(_safe_int(row.get("output_tokens")) for row in usage_rows),
        "total_tokens": sum(_safe_int(row.get("total_tokens")) for row in usage_rows),
        "latency_seconds": round(sum(float(row.get("latency_seconds") or 0) for row in usage_rows), 3),
    }

    for row in usage_rows:
        if row.get("estimated_cost_usd") is None:
            if row.get("success"):
                unknown_cost_calls += 1
        else:
            total_cost += float(row["estimated_cost_usd"])

        key = (
            str(row.get("provider") or ""),
            str(row.get("model") or ""),
            str(row.get("operation") or ""),
        )
        grouped = groups.setdefault(
            key,
            {
                "provider": key[0],
                "model": key[1],
                "operation": key[2],
                "calls": 0,
                "successful_calls": 0,
                "failed_calls": 0,
                "input_tokens": 0,
                "cached_input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "latency_seconds": 0.0,
                "estimated_cost_usd": None,
                "unknown_cost_calls": 0,
            },
        )
        grouped["calls"] += 1
        grouped["successful_calls"] += 1 if row.get("success") else 0
        grouped["failed_calls"] += 0 if row.get("success") else 1
        grouped["input_tokens"] += _safe_int(row.get("input_tokens"))
        grouped["cached_input_tokens"] += _safe_int(row.get("cached_input_tokens"))
        grouped["output_tokens"] += _safe_int(row.get("output_tokens"))
        grouped["total_tokens"] += _safe_int(row.get("total_tokens"))
        grouped["latency_seconds"] = round(
            grouped["latency_seconds"] + float(row.get("latency_seconds") or 0),
            3,
        )
        if row.get("estimated_cost_usd") is None:
            if row.get("success"):
                grouped["unknown_cost_calls"] += 1
        else:
            has_known_cost = True
            if grouped["estimated_cost_usd"] is None:
                grouped["estimated_cost_usd"] = 0.0
            grouped["estimated_cost_usd"] = round(
                grouped["estimated_cost_usd"] + float(row["estimated_cost_usd"]),
                8,
            )

    summary["estimated_cost_usd"] = round(total_cost, 8) if has_known_cost or not unknown_cost_calls else None
    summary["unknown_cost_calls"] = unknown_cost_calls
    summary["by_group"] = sorted(
        groups.values(),
        key=lambda row: (row["provider"], row["model"], row["operation"]),
    )
    return summary


def export_usage_reports(base_path_without_ext: str) -> Dict[str, str]:
    rows = get_usage_rows()
    summary = summarize_usage(rows)
    base_path = os.path.abspath(base_path_without_ext)
    os.makedirs(os.path.dirname(base_path), exist_ok=True)

    json_path = f"{base_path}_llm_usage.json"
    csv_path = f"{base_path}_llm_usage.csv"

    with open(json_path, "w", encoding="utf-8") as file_obj:
        json.dump(
            {
                "summary": summary,
                "calls": rows,
            },
            file_obj,
            indent=2,
            ensure_ascii=False,
        )

    fieldnames = [
        "timestamp",
        "provider",
        "model",
        "operation",
        "success",
        "latency_seconds",
        "input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "total_tokens",
        "estimated_cost_usd",
        "error",
    ]
    with open(csv_path, "w", encoding="utf-8", newline="") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) for field in fieldnames})

    return {"json": json_path, "csv": csv_path}
