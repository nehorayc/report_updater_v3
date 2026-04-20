from __future__ import annotations

from typing import Any, Dict, Optional


_PRICE_PER_1M_TOKENS_USD: Dict[tuple[str, str], Dict[str, float | None]] = {
    ("openai", "gpt-5.4"): {
        "input": 2.50,
        "cached_input": 0.25,
        "output": 15.00,
    },
    ("openai", "gpt-5.4-mini"): {
        "input": 0.75,
        "cached_input": 0.075,
        "output": 4.50,
    },
    ("openai", "gpt-5.4-nano"): {
        "input": 0.20,
        "cached_input": 0.02,
        "output": 1.25,
    },
    ("gemini", "gemini-3-flash-preview"): {
        "input": 0.50,
        "cached_input": None,
        "output": 3.00,
    },
    ("gemini", "gemini-2.5-flash"): {
        "input": 0.30,
        "cached_input": 0.075,
        "output": 2.50,
    },
    ("gemini", "gemini-2.5-flash-lite"): {
        "input": 0.10,
        "cached_input": 0.025,
        "output": 0.40,
    },
    ("gemini", "gemini-2.0-flash"): {
        "input": 0.10,
        "cached_input": 0.025,
        "output": 0.40,
    },
}


def _normalize_model_name(model: str) -> str:
    normalized = str(model or "").strip().lower()
    if normalized.startswith("models/"):
        normalized = normalized.split("/", 1)[1]
    return normalized


def get_model_pricing(provider: str, model: str) -> Optional[Dict[str, float | None]]:
    return _PRICE_PER_1M_TOKENS_USD.get(
        (str(provider or "").strip().lower(), _normalize_model_name(model))
    )


def estimate_cost_usd(
    *,
    provider: str,
    model: str,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cached_input_tokens: int | None = None,
) -> float | None:
    pricing = get_model_pricing(provider, model)
    if pricing is None:
        return None

    billable_input = max(0, int(input_tokens or 0))
    cached_input = max(0, int(cached_input_tokens or 0))
    output = max(0, int(output_tokens or 0))

    if cached_input:
        billable_input = max(0, billable_input - cached_input)
        cached_rate = pricing.get("cached_input")
        if cached_rate is None:
            cached_input = 0

    cost = (billable_input / 1_000_000) * float(pricing.get("input") or 0)
    cost += (output / 1_000_000) * float(pricing.get("output") or 0)
    if cached_input:
        cost += (cached_input / 1_000_000) * float(pricing.get("cached_input") or 0)

    return round(cost, 8)


def format_cost(value: Any) -> str:
    if value is None:
        return "Unavailable"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "Unavailable"
    if numeric < 0.01:
        return f"${numeric:.4f}"
    return f"${numeric:.2f}"
