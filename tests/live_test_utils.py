from __future__ import annotations

import json
from typing import Any

import pytest


def _to_searchable_text(payload: Any) -> str:
    if payload is None:
        return ""
    if isinstance(payload, str):
        return payload
    try:
        return json.dumps(payload, ensure_ascii=False)
    except TypeError:
        return str(payload)


def skip_if_live_quota_exhausted(*payloads: Any) -> None:
    combined = " ".join(_to_searchable_text(payload) for payload in payloads if payload is not None).lower()
    if not combined:
        return

    quota_signals = (
        "resource_exhausted",
        "quota exceeded",
        '"code": 429',
        "429 resource_exhausted",
        "generate_content_free_tier_requests",
    )
    if any(signal in combined for signal in quota_signals):
        pytest.skip("Live API quota is exhausted in the current environment.")
