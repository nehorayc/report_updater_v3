from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from llm_client import (
    generate_content as gemini_generate_content,
    get_api_key,
    resolve_model,
)
from llm_json_utils import try_parse_json
from logger_config import setup_logger


YEAR_TOKEN_PATTERN = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")
_SINGLE_SERIES_KEY = "__single__"
GRAPH_UPDATE_STATUS_UPDATED = "updated"
GRAPH_UPDATE_STATUS_NO_NEW_DATA = "no_new_data"
GRAPH_UPDATE_STATUS_INVALID = "invalid"
_GRAPH_UPDATE_TYPE_TOKENS = {"chart", "graph"}
_UNIT_WORD_PATTERN = r"[A-Za-z$€£%][A-Za-z$€£%/\-]*(?:\s+(?!in\b|for\b|during\b|by\b)[A-Za-z$€£%][A-Za-z$€£%/\-]*){0,2}"
_VALUE_THEN_YEAR_PATTERN = re.compile(
    r"(?P<value>\d+(?:,\d{3})*(?:\.\d+)?)\s*(?P<scale>thousand|million|billion|trillion|%)?"
    rf"(?:\s+(?P<unit_word>{_UNIT_WORD_PATTERN}))?"
    r"[^.;:\n]{0,48}?\b(?:in|for|during|by)\s+(?P<year>(?:19|20)\d{2})\b",
    re.IGNORECASE,
)
_YEAR_THEN_VALUE_PATTERN = re.compile(
    r"\b(?:in|for|during|by)\s+(?P<year>(?:19|20)\d{2})\b[^.;:\n]{0,48}?"
    r"(?P<value>\d+(?:,\d{3})*(?:\.\d+)?)\s*(?P<scale>thousand|million|billion|trillion|%)?"
    rf"(?:\s+(?P<unit_word>{_UNIT_WORD_PATTERN}))?",
    re.IGNORECASE,
)
_GENERIC_UNIT_PATTERN = re.compile(
    r"\b(unit|units|shipment|shipments|server|servers|count|counts|article|articles|patent|patents)\b",
    re.IGNORECASE,
)

logger = setup_logger("GraphUpdateHelpers")


def normalize_marker_token(value: Any) -> str:
    token = str(value or "").strip().lower()
    if not token:
        return ""
    return re.sub(r"[^a-z0-9_-]", "", token)


def asset_has_update_plan(asset: Dict[str, Any]) -> bool:
    if not isinstance(asset, dict):
        return False
    return bool(asset.get("do_update") or asset.get("convert_to_text"))


def asset_requires_chart_refresh(asset: Dict[str, Any]) -> bool:
    if not isinstance(asset, dict):
        return False
    return bool(asset.get("do_update")) and str(asset.get("type", "")).strip().lower() in _GRAPH_UPDATE_TYPE_TOKENS


def visual_matches_asset_id(visual: Dict[str, Any], asset_id: Any) -> bool:
    normalized_asset_id = normalize_marker_token(asset_id)
    if not normalized_asset_id or not isinstance(visual, dict):
        return False

    candidate_tokens = {
        normalize_marker_token(visual.get(key))
        for key in ("source_asset_id", "original_asset_id", "marker_id", "id")
    }
    candidate_tokens.discard("")
    if normalized_asset_id in candidate_tokens:
        return True

    short_asset_id = normalized_asset_id[:8]
    return any(token[:8] == short_asset_id for token in candidate_tokens)


def unresolved_source_chart_updates(
    planned_assets: List[Dict[str, Any]] | None,
    approved_visuals: List[Dict[str, Any]] | None,
) -> List[Dict[str, str]]:
    unresolved: List[Dict[str, str]] = []

    for asset in planned_assets or []:
        if not asset_requires_chart_refresh(asset):
            continue

        asset_id = normalize_marker_token(asset.get("id"))
        matched_visuals = [
            visual
            for visual in approved_visuals or []
            if isinstance(visual, dict) and asset_id and visual_matches_asset_id(visual, asset_id)
        ]
        matched_graph = any(str(visual.get("type", "")).strip().lower() == "graph" for visual in matched_visuals)
        matched_original = any(str(visual.get("type", "")).strip().lower() != "graph" for visual in matched_visuals)
        graph_update_status = str(asset.get("graph_update_status", "")).strip().lower()

        if graph_update_status == GRAPH_UPDATE_STATUS_NO_NEW_DATA and matched_original:
            continue
        if matched_graph:
            continue

        unresolved.append(
            {
                "asset_id": asset_id or str(asset.get("id") or ""),
                "asset_type": str(asset.get("type", "visual")).strip().lower() or "visual",
                "short_caption": str(asset.get("short_caption") or asset.get("title") or "Source chart").strip(),
            }
        )

    return unresolved


def normalize_numeric_value(value: Any) -> Optional[int | float]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        numeric = float(value)
    else:
        text = str(value).strip().replace(",", "")
        if not text:
            return None
        if text.endswith("%"):
            text = text[:-1].strip()
        try:
            numeric = float(text)
        except ValueError:
            return None
    return int(numeric) if numeric.is_integer() else round(numeric, 4)


def series_label_key(label: Any) -> str:
    text = " ".join(str(label or "").split())
    if not text:
        return ""
    year_match = YEAR_TOKEN_PATTERN.search(text)
    if year_match:
        return year_match.group(0)
    return text.lower()


def extract_years_from_labels(labels: List[Any]) -> List[int]:
    years: List[int] = []
    for label in labels or []:
        match = YEAR_TOKEN_PATTERN.search(str(label or ""))
        if match:
            years.append(int(match.group(0)))
    return years


def _series_name_key(series_name: Any) -> str:
    return " ".join(str(series_name or "").split()).strip().lower() or "series"


def _normalize_labels(labels: Any) -> Optional[List[str]]:
    if not isinstance(labels, list) or not labels:
        return None

    normalized_labels: List[str] = []
    for label in labels:
        label_text = " ".join(str(label or "").split())
        if not label_text:
            return None
        normalized_labels.append(label_text)
    return normalized_labels


def _coerce_series_length(series_values: List[Any], target_len: int) -> List[Any]:
    coerced = list(series_values[:target_len])
    if len(coerced) < target_len:
        coerced.extend([0] * (target_len - len(coerced)))
    return coerced


def normalize_chart_series(
    data_points: Any,
) -> Optional[Tuple[List[str], Dict[str, List[int | float]], str, bool]]:
    if not isinstance(data_points, dict):
        return None

    labels = _normalize_labels(data_points.get("labels"))
    if not labels:
        return None

    values = data_points.get("values")
    datasets = data_points.get("datasets")
    unit = " ".join(str(data_points.get("unit", "") or "").split())

    if isinstance(values, list):
        values = _coerce_series_length(values, len(labels))
        normalized_values: List[int | float] = []
        for value in values:
            numeric = normalize_numeric_value(value)
            if numeric is None:
                return None
            normalized_values.append(numeric)
        return labels, {_SINGLE_SERIES_KEY: normalized_values}, unit, False

    if isinstance(values, dict) and values:
        normalized_values_by_series: Dict[str, List[int | float]] = {}
        for raw_series_name, series_values in values.items():
            normalized_series_name = " ".join(str(raw_series_name or "").split()).strip() or "Series"

            if isinstance(series_values, dict):
                aligned_series_values = []
                for label in labels:
                    label_value = series_values.get(label)
                    if label_value is None:
                        label_value = series_values.get(str(label))
                    aligned_series_values.append(label_value)
                series_values = aligned_series_values

            if not isinstance(series_values, list):
                return None
            series_values = _coerce_series_length(series_values, len(labels))

            normalized_series: List[int | float] = []
            for value in series_values:
                numeric = normalize_numeric_value(value)
                if numeric is None:
                    return None
                normalized_series.append(numeric)

            normalized_values_by_series[normalized_series_name] = normalized_series

        return labels, normalized_values_by_series, unit, True

    if isinstance(datasets, list) and datasets:
        normalized_values_by_series = {}
        dataset_units: List[str] = []

        for index, dataset in enumerate(datasets, start=1):
            if not isinstance(dataset, dict):
                return None

            raw_series_name = dataset.get("label") or dataset.get("name") or ""
            normalized_series_name = " ".join(str(raw_series_name or "").split()).strip()
            if not normalized_series_name:
                normalized_series_name = "Series" if len(datasets) == 1 else f"Series {index}"
            if normalized_series_name in normalized_values_by_series:
                normalized_series_name = f"{normalized_series_name} {index}"

            series_values = dataset.get("values")
            if series_values is None:
                series_values = dataset.get("data")

            if isinstance(series_values, dict):
                aligned_series_values = []
                for label in labels:
                    label_value = series_values.get(label)
                    if label_value is None:
                        label_value = series_values.get(str(label))
                    aligned_series_values.append(label_value)
                series_values = aligned_series_values

            if not isinstance(series_values, list):
                return None
            series_values = _coerce_series_length(series_values, len(labels))

            normalized_series: List[int | float] = []
            for value in series_values:
                numeric = normalize_numeric_value(value)
                if numeric is None:
                    return None
                normalized_series.append(numeric)

            normalized_values_by_series[normalized_series_name] = normalized_series

            dataset_unit = " ".join(str(dataset.get("unit", "") or "").split())
            if dataset_unit:
                dataset_units.append(dataset_unit)

        resolved_unit = unit
        if not resolved_unit and dataset_units and len(set(dataset_units)) == 1:
            resolved_unit = dataset_units[0]

        if len(normalized_values_by_series) == 1:
            only_series = next(iter(normalized_values_by_series.values()))
            return labels, {_SINGLE_SERIES_KEY: only_series}, resolved_unit, False

        return labels, normalized_values_by_series, resolved_unit, True

    return None


def denormalize_chart_series(
    labels: List[str],
    values_by_series: Dict[str, List[int | float]],
    unit: str = "",
    multi_series: bool = False,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"labels": list(labels)}
    if multi_series:
        payload["values"] = {
            series_name: list(series_values)
            for series_name, series_values in values_by_series.items()
        }
    else:
        payload["values"] = list(values_by_series.get(_SINGLE_SERIES_KEY, []))
    if unit:
        payload["unit"] = unit
    return payload


def canonicalize_chart_data_points(data_points: Any) -> Optional[Dict[str, Any]]:
    normalized = normalize_chart_series(data_points)
    if not normalized:
        return None

    labels, values_by_series, unit, multi_series = normalized
    return denormalize_chart_series(
        labels,
        values_by_series,
        unit=unit,
        multi_series=multi_series,
    )


def chart_has_mixed_dataset_units(data_points: Any) -> bool:
    if not isinstance(data_points, dict):
        return False

    units = {
        " ".join(str(dataset.get("unit", "") or "").split())
        for dataset in data_points.get("datasets") or []
        if isinstance(dataset, dict) and " ".join(str(dataset.get("unit", "") or "").split())
    }
    return len(units) > 1


def format_chart_data_points_for_prompt(extracted_data_points: Any) -> str:
    normalized = normalize_chart_series(extracted_data_points)
    if not normalized:
        return ""
    return _chart_payload_for_prompt(extracted_data_points)


def _reference_identity(ref: Dict[str, Any]) -> tuple:
    title = str(ref.get("title", "")).strip().lower()
    url = str(ref.get("url", "")).strip().lower()
    category = str(ref.get("category", "")).strip().lower()
    if url:
        return (title, url, category)
    return (title, category)


def _normalize_reference_category(raw_category: Any, source_hint: Any = None) -> str:
    category = str(raw_category or "").strip().lower()
    source_hint = str(source_hint or "").strip().lower()
    if category in {"academic", "web", "original", "uploaded"}:
        return category.title()
    if source_hint in {"academic", "paper", "journal", "openalex", "scholar"}:
        return "Academic"
    if source_hint in {"original"}:
        return "Original"
    if source_hint in {"uploaded", "internal", "reference_doc", "reference-doc"}:
        return "Uploaded"
    return "Web"


def _normalized_reference_entry(ref: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(ref, dict):
        return None

    title = " ".join(str(ref.get("title", "") or "").split()).strip()
    if not title:
        return None

    normalized = {
        "title": title,
        "category": _normalize_reference_category(
            ref.get("category"),
            ref.get("source_type") or ref.get("source"),
        ),
    }
    url = str(ref.get("url", "") or "").strip()
    if url.startswith("http"):
        normalized["url"] = url
    return normalized


def merge_graph_update_references(
    references: List[Dict[str, Any]] | None,
    assets_to_update: List[Dict[str, Any]] | None,
) -> List[Dict[str, Any]]:
    merged: List[Dict[str, Any]] = []
    seen: set[tuple] = set()

    for ref in references or []:
        normalized = _normalized_reference_entry(ref)
        if not normalized:
            continue
        key = _reference_identity(normalized)
        if key in seen:
            continue
        merged.append(normalized)
        seen.add(key)

    for asset in assets_to_update or []:
        if not isinstance(asset, dict):
            continue
        if str(asset.get("graph_update_status", "")).strip().lower() != GRAPH_UPDATE_STATUS_UPDATED:
            continue
        prepared_visual = asset.get("prepared_update_visual")
        if not isinstance(prepared_visual, dict):
            continue
        for ref in prepared_visual.get("graph_source_references", []) or []:
            normalized = _normalized_reference_entry(ref)
            if not normalized:
                continue
            key = _reference_identity(normalized)
            if key in seen:
                continue
            merged.append(normalized)
            seen.add(key)

    for index, ref in enumerate(merged, start=1):
        ref["index"] = index

    return merged


def merge_preserved_historical_data(
    extracted_data_points: Any,
    updated_data_points: Any,
) -> Optional[Dict[str, Any]]:
    extracted_series = normalize_chart_series(extracted_data_points)
    updated_series = normalize_chart_series(updated_data_points)
    if not extracted_series or not updated_series:
        return None

    extracted_labels, extracted_values_by_series, extracted_unit, extracted_multi_series = extracted_series
    updated_labels, updated_values_by_series, updated_unit, updated_multi_series = updated_series

    combined_labels = list(extracted_labels)
    combined_label_keys = [series_label_key(label) for label in combined_labels]
    updated_label_by_key = {
        series_label_key(label): label
        for label in updated_labels
        if series_label_key(label)
    }
    for label in updated_labels:
        key = series_label_key(label)
        if key and key not in combined_label_keys:
            combined_labels.append(updated_label_by_key.get(key, label))
            combined_label_keys.append(key)

    extracted_label_index = {
        series_label_key(label): index
        for index, label in enumerate(extracted_labels)
        if series_label_key(label)
    }
    updated_label_index = {
        series_label_key(label): index
        for index, label in enumerate(updated_labels)
        if series_label_key(label)
    }

    series_name_keys = {
        _series_name_key(series_name): series_name
        for series_name in extracted_values_by_series
    }
    for series_name in updated_values_by_series:
        series_name_keys.setdefault(_series_name_key(series_name), series_name)

    combined_values_by_series: Dict[str, List[int | float]] = {}
    for normalized_series_name, output_series_name in series_name_keys.items():
        extracted_series_name = next(
            (series_name for series_name in extracted_values_by_series if _series_name_key(series_name) == normalized_series_name),
            None,
        )
        updated_series_name = next(
            (series_name for series_name in updated_values_by_series if _series_name_key(series_name) == normalized_series_name),
            None,
        )

        combined_values: List[int | float] = []
        for label, label_key in zip(combined_labels, combined_label_keys):
            if label_key in extracted_label_index and extracted_series_name is not None:
                combined_values.append(
                    extracted_values_by_series[extracted_series_name][extracted_label_index[label_key]]
                )
                continue
            if label_key in updated_label_index and updated_series_name is not None:
                combined_values.append(
                    updated_values_by_series[updated_series_name][updated_label_index[label_key]]
                )
                continue
            combined_values.append(0)

        combined_values_by_series[output_series_name] = combined_values

    combined_labels, combined_values_by_series = _sort_chart_series_if_years(
        combined_labels,
        combined_values_by_series,
    )

    multi_series = extracted_multi_series or updated_multi_series or len(combined_values_by_series) > 1
    unit = updated_unit or extracted_unit
    return denormalize_chart_series(
        combined_labels,
        combined_values_by_series,
        unit=unit,
        multi_series=multi_series,
    )


def _sort_chart_series_if_years(
    labels: List[str],
    values_by_series: Dict[str, List[int | float]],
) -> Tuple[List[str], Dict[str, List[int | float]]]:
    year_pairs: List[Tuple[int, int, str]] = []
    for index, label in enumerate(labels):
        match = YEAR_TOKEN_PATTERN.search(label)
        if not match:
            return labels, values_by_series
        year_pairs.append((int(match.group(0)), index, label))

    year_pairs.sort(key=lambda item: (item[0], item[1]))
    sorted_indices = [item[1] for item in year_pairs]
    sorted_labels = [labels[index] for index in sorted_indices]
    sorted_values_by_series = {
        series_name: [series_values[index] for index in sorted_indices]
        for series_name, series_values in values_by_series.items()
    }
    return sorted_labels, sorted_values_by_series


def graph_has_plottable_data(data_points: Any) -> bool:
    normalized = normalize_chart_series(data_points)
    if not normalized:
        return False

    _, values_by_series, _, _ = normalized
    flattened = [value for series_values in values_by_series.values() for value in series_values]
    if not flattened:
        return False
    return any(abs(float(value)) > 1e-9 for value in flattened)


def graph_update_required_years(
    extracted_data_points: Any,
    update_end_year: Any,
) -> List[int]:
    normalized = normalize_chart_series(extracted_data_points)
    if not normalized:
        return []

    extracted_years = extract_years_from_labels(normalized[0])
    if not extracted_years:
        return []

    if isinstance(update_end_year, int):
        end_year = update_end_year
    else:
        match = YEAR_TOKEN_PATTERN.search(str(update_end_year or ""))
        end_year = int(match.group(0)) if match else None
    if not end_year:
        return []

    start_year = max(extracted_years) + 1
    if start_year > end_year:
        return []
    return list(range(start_year, end_year + 1))


def _load_sidecar_chart_data_points(asset_path: Any) -> Optional[Dict[str, Any]]:
    path_text = str(asset_path or "").strip()
    if not path_text:
        return None

    candidate = Path(path_text).with_suffix(".json")
    if not candidate.exists():
        return None

    try:
        parsed = json.loads(candidate.read_text(encoding="utf-8"))
    except Exception:
        return None

    if isinstance(parsed, dict):
        payload = parsed.get("data_points") if "data_points" in parsed else parsed.get("extracted_data_points") or parsed
    else:
        payload = None

    return _normalize_chart_payload_for_storage(payload)


def preferred_extracted_data_points(asset: Dict[str, Any]) -> Any:
    sidecar_data_points = _load_sidecar_chart_data_points(asset.get("path"))
    if sidecar_data_points is not None:
        return sidecar_data_points
    return copy.deepcopy(asset.get("extracted_data_points"))


def _default_chart_type_for_series(extracted_data_points: Any, asset: Dict[str, Any]) -> str:
    explicit = str(asset.get("chart_type", "")).strip().lower()
    if explicit in {"bar", "line", "pie", "horizontal_bar", "stacked_bar", "area"}:
        return explicit
    analysis_chart_type = str((asset.get("analysis") or {}).get("chart_type", "")).strip().lower()
    if analysis_chart_type in {"bar", "line", "pie", "horizontal_bar", "stacked_bar", "area"}:
        return analysis_chart_type

    normalized = normalize_chart_series(extracted_data_points)
    if normalized:
        labels, _, _, multi_series = normalized
        if extract_years_from_labels(labels):
            return "line"
        if multi_series:
            return "stacked_bar"
    return "bar"


def _normalize_chart_payload_for_storage(data_points: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(data_points, dict):
        return None

    labels = _normalize_labels(data_points.get("labels"))
    if not labels:
        return None

    datasets = data_points.get("datasets")
    if isinstance(datasets, list) and datasets:
        cleaned_datasets: List[Dict[str, Any]] = []
        used_names: set[str] = set()

        for index, dataset in enumerate(datasets, start=1):
            if not isinstance(dataset, dict):
                return None

            raw_series_name = dataset.get("label") or dataset.get("name") or ""
            series_name = " ".join(str(raw_series_name or "").split()).strip()
            if not series_name:
                series_name = "Series" if len(datasets) == 1 else f"Series {index}"
            if series_name in used_names:
                series_name = f"{series_name} {index}"
            used_names.add(series_name)

            series_values = dataset.get("values")
            if series_values is None:
                series_values = dataset.get("data")
            if isinstance(series_values, dict):
                aligned_series_values = []
                for label in labels:
                    label_value = series_values.get(label)
                    if label_value is None:
                        label_value = series_values.get(str(label))
                    aligned_series_values.append(label_value)
                series_values = aligned_series_values
            if not isinstance(series_values, list):
                return None
            series_values = _coerce_series_length(series_values, len(labels))

            normalized_values: List[int | float] = []
            for value in series_values:
                numeric = normalize_numeric_value(value)
                if numeric is None:
                    return None
                normalized_values.append(numeric)

            cleaned_dataset = {"label": series_name, "values": normalized_values}
            dataset_unit = " ".join(str(dataset.get("unit", "") or "").split())
            if dataset_unit:
                cleaned_dataset["unit"] = dataset_unit
            cleaned_datasets.append(cleaned_dataset)

        payload: Dict[str, Any] = {"labels": labels, "datasets": cleaned_datasets}
        top_level_unit = " ".join(str(data_points.get("unit", "") or "").split())
        if top_level_unit:
            payload["unit"] = top_level_unit
        return payload

    return canonicalize_chart_data_points(data_points)


def _series_units_by_name(data_points: Any) -> Dict[str, str]:
    normalized = normalize_chart_series(data_points)
    if not normalized:
        return {}

    _, values_by_series, unit, multi_series = normalized
    if not multi_series:
        return {_SINGLE_SERIES_KEY: unit}

    per_series_units: Dict[str, str] = {}
    if isinstance(data_points, dict):
        datasets = data_points.get("datasets")
        if isinstance(datasets, list):
            dataset_name_to_unit: Dict[str, str] = {}
            for index, dataset in enumerate(datasets, start=1):
                if not isinstance(dataset, dict):
                    continue
                raw_series_name = dataset.get("label") or dataset.get("name") or ""
                series_name = " ".join(str(raw_series_name or "").split()).strip()
                if not series_name:
                    series_name = "Series" if len(datasets) == 1 else f"Series {index}"
                dataset_name_to_unit[_series_name_key(series_name)] = " ".join(str(dataset.get("unit", "") or "").split())
            for series_name in values_by_series:
                per_series_units[series_name] = dataset_name_to_unit.get(_series_name_key(series_name), unit)
            return per_series_units

    return {series_name: unit for series_name in values_by_series}


def _expected_series_specs(extracted_data_points: Any) -> Tuple[List[Dict[str, str]], Dict[str, Dict[str, str]]]:
    normalized = normalize_chart_series(extracted_data_points)
    if not normalized:
        return [], {}

    _, values_by_series, _, multi_series = normalized
    units_by_name = _series_units_by_name(extracted_data_points)

    specs: List[Dict[str, str]] = []
    spec_lookup: Dict[str, Dict[str, str]] = {}
    for series_name in values_by_series:
        if multi_series:
            display_name = series_name
        else:
            display_name = "Value"
        spec = {
            "series_name": series_name,
            "display_name": display_name,
            "series_key": _series_name_key(series_name),
            "display_key": _series_name_key(display_name),
            "unit": units_by_name.get(series_name, ""),
        }
        specs.append(spec)
        spec_lookup[spec["display_key"]] = spec
        spec_lookup[spec["series_key"]] = spec

    return specs, spec_lookup


def _chart_payload_for_prompt(data_points: Any) -> str:
    normalized_payload = _normalize_chart_payload_for_storage(data_points)
    if normalized_payload is None:
        return json.dumps(data_points or {}, ensure_ascii=False)
    return json.dumps(normalized_payload, ensure_ascii=False)


def _finding_excerpt_for_graph_update(finding: Dict[str, Any], limit: int = 1200) -> str:
    excerpt = ""
    for key in ("snippet", "summary", "body", "content", "article_text"):
        text = " ".join(str(finding.get(key, "") or "").split())
        if text:
            excerpt = text
            break
    if len(excerpt) <= limit:
        return excerpt
    return excerpt[: limit - 1].rstrip() + "…"


def _source_context_prompt_section(asset: Dict[str, Any]) -> str:
    chapter_title = " ".join(str(asset.get("source_context_chapter_title", "") or "").split()).strip()
    heading = " ".join(str(asset.get("source_context_heading", "") or "").split()).strip()
    excerpt = " ".join(str(asset.get("source_context_excerpt", "") or "").split()).strip()
    fallback = " ".join(str(asset.get("source_context_fallback", "") or "").split()).strip()
    strategy = " ".join(str(asset.get("source_context_strategy", "") or "").split()).strip()
    page = asset.get("source_context_page")

    def _truncate(text: str, limit: int) -> str:
        if len(text) <= limit:
            return text
        return text[: limit - 1].rstrip() + "…"

    lines: List[str] = []
    if chapter_title:
        lines.append(f"- Chapter title: {_truncate(chapter_title, 180)}")
    if heading and heading != chapter_title:
        lines.append(f"- Local heading: {_truncate(heading, 180)}")
    if strategy:
        lines.append(f"- Context strategy: {strategy}")
    if page:
        lines.append(f"- Source page: {page}")
    if excerpt:
        lines.append(f"- Figure-local excerpt: {_truncate(excerpt, 900)}")
    if fallback and fallback != excerpt:
        lines.append(f"- Chapter fallback excerpt: {_truncate(fallback, 500)}")

    if not lines:
        return "- No original report context was available for this figure."
    return "\n".join(lines)


def _graph_update_source_catalog(
    research_findings: List[Dict[str, Any]] | None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    catalog: List[Dict[str, Any]] = []
    lookup: Dict[str, Dict[str, Any]] = {}

    for index, finding in enumerate(research_findings or [], start=1):
        if not isinstance(finding, dict):
            continue
        title = " ".join(str(finding.get("title", "") or "").split()).strip()
        excerpt = _finding_excerpt_for_graph_update(finding)
        url = str(finding.get("url", "") or "").strip()
        if not title and not excerpt:
            continue

        source_id = f"S{index}"
        source_payload = {
            "source_id": source_id,
            "title": title or f"Source {index}",
            "url": url,
            "category": _normalize_reference_category(
                finding.get("category"),
                finding.get("source_type") or finding.get("source"),
            ),
            "source_type": str(finding.get("source_type") or finding.get("source") or "web"),
            "published_date": str(finding.get("published_date") or ""),
            "approved_for_writing": bool(finding.get("approved_for_writing", True)),
            "excerpt": excerpt,
        }
        catalog.append(source_payload)
        lookup[source_id] = finding

    return catalog, lookup


def _is_quota_error(exc: Exception) -> bool:
    message = str(exc or "").lower()
    return any(token in message for token in ("quota", "rate limit", "resource exhausted", "429"))


def _normalize_source_id_list(value: Any) -> List[str]:
    if isinstance(value, list):
        candidates = value
    elif value is None:
        candidates = []
    else:
        candidates = [value]

    normalized: List[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        token = " ".join(str(candidate or "").split()).strip()
        if not token or token in seen:
            continue
        normalized.append(token)
        seen.add(token)
    return normalized


def _normalize_llm_graph_references(
    source_ids: List[str],
    source_lookup: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    references: List[Dict[str, Any]] = []
    seen: set[tuple] = set()
    for source_id in source_ids:
        finding = source_lookup.get(source_id)
        if not isinstance(finding, dict):
            continue
        normalized = _normalized_reference_entry(
            {
                "title": finding.get("title"),
                "url": finding.get("url"),
                "category": finding.get("category"),
                "source_type": finding.get("source_type") or finding.get("source"),
                "source": finding.get("source"),
            }
        )
        if not normalized:
            continue
        key = _reference_identity(normalized)
        if key in seen:
            continue
        references.append(normalized)
        seen.add(key)
    for index, ref in enumerate(references, start=1):
        ref["index"] = index
    return references


def _normalize_llm_datapoint_entries(
    new_datapoints: Any,
    *,
    required_years: List[int],
    series_specs: List[Dict[str, str]],
    spec_lookup: Dict[str, Dict[str, str]],
    source_lookup: Dict[str, Dict[str, Any]],
) -> Tuple[Dict[Tuple[str, int], Dict[str, Any]], List[str], List[str]]:
    if not isinstance(new_datapoints, list):
        return {}, [], ["The LLM graph updater did not return a 'new_datapoints' list."]

    errors: List[str] = []
    normalized_points: Dict[Tuple[str, int], Dict[str, Any]] = {}
    referenced_source_ids: List[str] = []
    seen_source_ids: set[str] = set()
    required_year_set = set(required_years)
    single_series = len(series_specs) == 1
    fallback_spec = series_specs[0] if series_specs else None

    for entry in new_datapoints:
        if not isinstance(entry, dict):
            errors.append("The LLM graph updater returned a malformed datapoint entry.")
            continue

        year_value = entry.get("year")
        if isinstance(year_value, int):
            year = year_value
        else:
            match = YEAR_TOKEN_PATTERN.search(str(year_value or ""))
            year = int(match.group(0)) if match else None
        if year is None or year not in required_year_set:
            errors.append("The LLM graph updater returned a datapoint outside the required update years.")
            continue

        raw_series = " ".join(str(entry.get("series", "") or "").split()).strip()
        if single_series and fallback_spec:
            spec = fallback_spec
        else:
            spec = spec_lookup.get(_series_name_key(raw_series))
        if spec is None:
            errors.append(
                f"The LLM graph updater returned an unknown series label '{raw_series or 'blank'}'."
            )
            continue

        unit_text = " ".join(str(entry.get("unit", "") or "").split()).strip()
        expected_unit = spec.get("unit", "")
        if unit_text and expected_unit:
            normalized_value, error = _normalize_value_to_expected_unit(
                entry.get("value"),
                scale_text="",
                unit_text=unit_text,
                expected_unit=expected_unit,
            )
        else:
            normalized_value = normalize_numeric_value(entry.get("value"))
            error = None if normalized_value is not None else "The refreshed graph contains a non-numeric datapoint."
        if error:
            errors.append(error)
            continue
        if normalized_value is None:
            errors.append("The refreshed graph contains a non-numeric datapoint.")
            continue

        source_ids = _normalize_source_id_list(entry.get("source_ids"))
        if not source_ids:
            errors.append(f"The LLM graph updater did not cite a source for {spec['display_name']} in {year}.")
            continue
        unknown_source_ids = [source_id for source_id in source_ids if source_id not in source_lookup]
        if unknown_source_ids:
            errors.append(
                "The LLM graph updater cited unknown source ids: " + ", ".join(unknown_source_ids[:4])
            )
            continue

        point_key = (spec["series_key"], year)
        prior_point = normalized_points.get(point_key)
        if prior_point is not None and float(prior_point["value"]) != float(normalized_value):
            errors.append(
                f"Conflicting refreshed datapoints were returned for {spec['display_name']} in {year}."
            )
            continue

        normalized_points[point_key] = {
            "display_name": spec["display_name"],
            "series_name": spec["series_name"],
            "value": normalized_value,
            "source_ids": source_ids,
        }
        for source_id in source_ids:
            if source_id in seen_source_ids:
                continue
            referenced_source_ids.append(source_id)
            seen_source_ids.add(source_id)

    expected_keys = {
        (spec["series_key"], year)
        for spec in series_specs
        for year in required_years
    }
    missing_keys = [
        (series_key, year)
        for series_key, year in sorted(expected_keys, key=lambda item: (item[1], item[0]))
        if (series_key, year) not in normalized_points
    ]
    if missing_keys:
        missing_labels = []
        for series_key, year in missing_keys[:8]:
            matching_spec = next(
                (spec for spec in series_specs if spec["series_key"] == series_key),
                None,
            )
            label = matching_spec["display_name"] if matching_spec else series_key
            missing_labels.append(f"{label} {year}")
        errors.append(
            "The LLM graph updater did not provide sourced datapoints for: " + ", ".join(missing_labels)
        )

    return normalized_points, referenced_source_ids, errors


def _validate_llm_chart_payload_against_datapoints(
    response_data_points: Any,
    *,
    expected_points: Dict[Tuple[str, int], Dict[str, Any]],
) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    cleaned_payload = _normalize_chart_payload_for_storage(response_data_points)
    if cleaned_payload is None:
        return None, ["The LLM graph updater returned invalid chart data."]

    normalized = normalize_chart_series(cleaned_payload)
    if not normalized:
        return None, ["The LLM graph updater returned invalid chart data."]

    labels, values_by_series, _, multi_series = normalized
    label_index = {
        series_label_key(label): index
        for index, label in enumerate(labels)
        if series_label_key(label)
    }
    if multi_series:
        series_lookup = {
            _series_name_key(series_name): series_name
            for series_name in values_by_series
        }
    else:
        series_lookup = {_SINGLE_SERIES_KEY: _SINGLE_SERIES_KEY}

    errors: List[str] = []
    for (series_key, year), point in expected_points.items():
        label_key = str(year)
        if label_key not in label_index:
            errors.append(f"The LLM graph updater omitted the required year {year} from the chart payload.")
            continue

        if multi_series:
            actual_series_name = series_lookup.get(series_key)
            if actual_series_name is None:
                errors.append(
                    f"The LLM graph updater omitted the series '{point['display_name']}' from the chart payload."
                )
                continue
        else:
            actual_series_name = _SINGLE_SERIES_KEY

        actual_value = values_by_series[actual_series_name][label_index[label_key]]
        if float(actual_value) != float(point["value"]):
            errors.append(
                f"The LLM graph updater returned inconsistent values for {point['display_name']} in {year}."
            )

    return cleaned_payload, errors


def _prepare_llm_source_graph_refresh(
    asset: Dict[str, Any],
    research_findings: List[Dict[str, Any]] | None,
    *,
    extracted_data_points: Any,
    required_years: List[int],
    update_end_year: Any = None,
) -> Optional[Dict[str, Any]]:
    api_key = get_api_key()
    if not api_key:
        logger.info("Skipping LLM graph refresh for %s because no API key is configured.", asset.get("id"))
        return None

    source_catalog, source_lookup = _graph_update_source_catalog(research_findings)
    if not source_catalog:
        logger.info("Skipping LLM graph refresh for %s because no research findings were available.", asset.get("id"))
        return None

    series_specs, spec_lookup = _expected_series_specs(extracted_data_points)
    if not series_specs:
        return None

    short_caption = str(asset.get("short_caption") or asset.get("title") or "Source chart").strip() or "Source chart"
    source_catalog_json = json.dumps(source_catalog, ensure_ascii=False, indent=2)
    expected_series_json = json.dumps(
        [
            {
                "series": spec["display_name"],
                "unit": spec["unit"],
            }
            for spec in series_specs
        ],
        ensure_ascii=False,
    )
    source_context_prompt = _source_context_prompt_section(asset)

    prompt = f"""
You are refreshing an existing source-report chart with NEW datapoints drawn ONLY from the approved source list below.

Return ONLY valid JSON in this exact shape:
{{
  "status": "updated" | "no_new_data" | "invalid",
  "reason": "short explanation",
  "new_datapoints": [
    {{
      "year": 2025,
      "series": "Value",
      "value": 123.4,
      "unit": "same unit as original series",
      "source_ids": ["S1"]
    }}
  ],
  "data_points": {{
    "labels": ["2014", "2015"],
    "values": [20, 30]
  }},
  "source_ids": ["S1"]
}}

Rules:
- Use ONLY the source_ids listed below. Never invent a new source id, title, URL, or datapoint.
- Preserve the original historical datapoints exactly. Do not revise pre-existing years.
- Only mark status="updated" if every required update year has an explicit numeric datapoint for every series.
- If any required year is missing or unsupported, return status="no_new_data".
- If the evidence conflicts or the units are incompatible, return status="invalid".
- Keep the same series names and the same unit scale as the original chart.
- For a single-series chart, use "Value" in the "series" field.
- The "data_points" object must contain the full refreshed chart from the first historical year through the final required year.
- Prefer a "datasets" payload when multiple series have different units.

Chart asset:
- Caption: {short_caption}
- Description: {str(asset.get("description") or asset.get("dataset_description") or short_caption).strip()}
- Required update years: {", ".join(str(year) for year in required_years)}
- Update through: {update_end_year}
- Series definitions: {expected_series_json}
- Original extracted datapoints (preserve these exactly): {_chart_payload_for_prompt(extracted_data_points)}

Original Report Context:
{source_context_prompt}

Approved source catalog:
{source_catalog_json}
"""

    try:
        response = gemini_generate_content(
            api_key=api_key,
            model=resolve_model("gemini-2.5-flash", role="graph"),
            contents=prompt,
            response_mime_type="application/json",
            temperature=0.0,
        )
        parsed = try_parse_json(response.text.strip())
    except Exception as exc:
        logger.warning("LLM graph refresh failed for %s: %s", asset.get("id"), exc)
        if _is_quota_error(exc):
            logger.warning("Graph refresh skipped due to LLM quota/rate-limit exhaustion.")
        return None

    status = str(parsed.get("status", "")).strip().lower()
    reason = " ".join(str(parsed.get("reason", "") or "").split()).strip()
    result: Dict[str, Any] = {
        "graph_update_status": GRAPH_UPDATE_STATUS_NO_NEW_DATA,
        "update_reason": reason,
        "required_years": list(required_years),
        "prepared_update_visual": None,
        "graph_update_validation_errors": [],
        "graph_update_references": [],
    }

    if status == GRAPH_UPDATE_STATUS_NO_NEW_DATA:
        result["update_reason"] = reason or (
            "The LLM graph updater did not find sourced numeric datapoints for every required update year."
        )
        return result

    if status == GRAPH_UPDATE_STATUS_INVALID:
        result["graph_update_status"] = GRAPH_UPDATE_STATUS_INVALID
        result["update_reason"] = reason or "The LLM graph updater reported conflicting or invalid evidence."
        result["graph_update_validation_errors"] = [result["update_reason"]]
        return result

    if status != GRAPH_UPDATE_STATUS_UPDATED:
        return None

    normalized_points, referenced_source_ids, point_errors = _normalize_llm_datapoint_entries(
        parsed.get("new_datapoints"),
        required_years=required_years,
        series_specs=series_specs,
        spec_lookup=spec_lookup,
        source_lookup=source_lookup,
    )
    if point_errors:
        result["graph_update_status"] = GRAPH_UPDATE_STATUS_INVALID
        result["update_reason"] = point_errors[0]
        result["graph_update_validation_errors"] = point_errors
        return result

    normalized_payload, payload_errors = _validate_llm_chart_payload_against_datapoints(
        parsed.get("data_points"),
        expected_points=normalized_points,
    )
    if payload_errors or normalized_payload is None:
        result["graph_update_status"] = GRAPH_UPDATE_STATUS_INVALID
        result["update_reason"] = payload_errors[0] if payload_errors else "The LLM graph updater returned invalid chart data."
        result["graph_update_validation_errors"] = payload_errors or [result["update_reason"]]
        return result

    explicit_source_ids = _normalize_source_id_list(parsed.get("source_ids"))
    if explicit_source_ids:
        unknown_source_ids = [source_id for source_id in explicit_source_ids if source_id not in source_lookup]
        if unknown_source_ids:
            result["graph_update_status"] = GRAPH_UPDATE_STATUS_INVALID
            result["update_reason"] = "The LLM graph updater cited unknown source ids: " + ", ".join(unknown_source_ids[:4])
            result["graph_update_validation_errors"] = [result["update_reason"]]
            return result
        referenced_source_ids = list(dict.fromkeys(referenced_source_ids + explicit_source_ids))

    graph_source_references = _normalize_llm_graph_references(referenced_source_ids, source_lookup)
    if not graph_source_references:
        result["graph_update_status"] = GRAPH_UPDATE_STATUS_INVALID
        result["update_reason"] = "The refreshed graph is missing usable source references for the bibliography."
        result["graph_update_validation_errors"] = [result["update_reason"]]
        return result

    prepared_visual = {
        "id": str(asset.get("id") or ""),
        "marker_id": str(asset.get("id") or ""),
        "original_asset_id": str(asset.get("id") or ""),
        "source_asset_id": str(asset.get("id") or ""),
        "action": "update",
        "type": "graph",
        "title": short_caption,
        "description": str(asset.get("description") or asset.get("dataset_description") or short_caption).strip(),
        "chart_type": _default_chart_type_for_series(extracted_data_points, asset),
        "data_points": normalized_payload,
        "extracted_data_points": copy.deepcopy(extracted_data_points),
        "update_end_date": str(update_end_year or ""),
        "update_reason": reason or (
            "Refreshed the source graph with sourced datapoints through "
            + ", ".join(str(year) for year in required_years)
            + " while preserving the historical series exactly."
        ),
        "graph_update_status": GRAPH_UPDATE_STATUS_UPDATED,
        "prepared_source_graph_refresh": True,
        "graph_source_references": graph_source_references,
        "graph_source_ids": referenced_source_ids,
        "graph_update_method": "llm",
    }

    validation_issues = graph_update_validation_issues(
        prepared_visual,
        update_end_year=update_end_year,
        extracted_data_points=extracted_data_points,
    )
    if validation_issues:
        result["graph_update_status"] = GRAPH_UPDATE_STATUS_INVALID
        result["update_reason"] = validation_issues[0]["message"]
        result["graph_update_validation_errors"] = [issue["message"] for issue in validation_issues]
        return result

    result["graph_update_status"] = GRAPH_UPDATE_STATUS_UPDATED
    result["update_reason"] = prepared_visual["update_reason"]
    result["prepared_update_visual"] = prepared_visual
    result["graph_update_references"] = graph_source_references
    return result


def _unit_scale_factor(text: str) -> float:
    lowered = str(text or "").lower()
    if "trillion" in lowered:
        return 1_000_000_000_000.0
    if "billion" in lowered:
        return 1_000_000_000.0
    if "million" in lowered:
        return 1_000_000.0
    if "thousand" in lowered:
        return 1_000.0
    return 1.0


def _unit_kind(text: str) -> str:
    lowered = str(text or "").lower()
    if "%" in lowered or "percent" in lowered:
        return "percent"
    if any(symbol in str(text or "") for symbol in ("$", "€", "£")) or any(
        token in lowered for token in ("usd", "eur", "gbp", "dollar", "euro", "pound")
    ):
        return "currency"
    return "generic"


def _normalize_value_to_expected_unit(
    raw_value: str,
    *,
    scale_text: str,
    unit_text: str,
    expected_unit: str,
) -> Tuple[Optional[int | float], Optional[str]]:
    numeric = normalize_numeric_value(raw_value)
    if numeric is None:
        return None, "The refreshed graph contains a non-numeric datapoint."

    candidate_text = " ".join(part for part in (scale_text, unit_text) if part).strip()
    expected_kind = _unit_kind(expected_unit)
    candidate_kind = _unit_kind(candidate_text)
    if candidate_kind and expected_kind and candidate_kind != expected_kind:
        return None, "The refreshed graph findings mix incompatible units."
    if expected_kind == "percent" and candidate_kind != "percent" and candidate_text:
        return None, "The refreshed graph findings use incompatible percentage units."
    if candidate_kind == "percent" and expected_kind != "percent":
        return None, "The refreshed graph findings use percentages for a non-percentage series."

    candidate_factor = _unit_scale_factor(candidate_text)
    expected_factor = _unit_scale_factor(expected_unit)
    normalized_value = float(numeric) * (candidate_factor / expected_factor)
    normalized_value = int(normalized_value) if normalized_value.is_integer() else round(normalized_value, 4)
    return normalized_value, None


def _finding_text_blocks(finding: Dict[str, Any]) -> List[str]:
    blocks: List[str] = []
    for key in ("snippet", "title", "body", "content", "article_text", "summary"):
        text = " ".join(str(finding.get(key, "") or "").split())
        if text and text not in blocks:
            blocks.append(text)
    return blocks


def _collect_required_year_candidates(
    finding_text: str,
    *,
    required_years: set[int],
    expected_unit: str,
) -> Tuple[Dict[int, int | float], List[str]]:
    candidates: Dict[int, int | float] = {}
    errors: List[str] = []
    for pattern in (_VALUE_THEN_YEAR_PATTERN, _YEAR_THEN_VALUE_PATTERN):
        for match in pattern.finditer(finding_text):
            year = int(match.group("year"))
            if year not in required_years:
                continue
            if pattern is _YEAR_THEN_VALUE_PATTERN and year in candidates:
                continue
            raw_value_text = str(match.group("value") or "").replace(",", "").strip()
            if pattern is _YEAR_THEN_VALUE_PATTERN and re.fullmatch(r"(?:19|20)\d{2}", raw_value_text):
                continue

            unit_word = " ".join(str(match.group("unit_word") or "").split())
            if unit_word and not _GENERIC_UNIT_PATTERN.search(unit_word) and _unit_kind(unit_word) == "generic":
                continue

            normalized_value, error = _normalize_value_to_expected_unit(
                match.group("value"),
                scale_text=str(match.group("scale") or ""),
                unit_text=unit_word,
                expected_unit=expected_unit,
            )
            if error:
                errors.append(error)
                continue
            if normalized_value is None:
                continue

            prior_value = candidates.get(year)
            if prior_value is not None and float(prior_value) != float(normalized_value):
                errors.append(f"Conflicting refreshed datapoints were found for {year}.")
                continue
            candidates[year] = normalized_value

    return candidates, errors


def _extract_required_year_updates(
    research_findings: List[Dict[str, Any]],
    *,
    required_years: List[int],
    expected_unit: str,
) -> Tuple[Dict[int, int | float], List[str]]:
    required_year_set = set(required_years)
    extracted_by_year: Dict[int, int | float] = {}
    errors: List[str] = []

    for finding in research_findings or []:
        if not isinstance(finding, dict):
            continue
        for block in _finding_text_blocks(finding):
            block_candidates, block_errors = _collect_required_year_candidates(
                block,
                required_years=required_year_set,
                expected_unit=expected_unit,
            )
            errors.extend(block_errors)
            for year, value in block_candidates.items():
                prior_value = extracted_by_year.get(year)
                if prior_value is not None and float(prior_value) != float(value):
                    errors.append(f"Conflicting refreshed datapoints were found for {year}.")
                    continue
                extracted_by_year[year] = value

    return extracted_by_year, errors


def prepare_source_graph_refresh(
    asset: Dict[str, Any],
    research_findings: List[Dict[str, Any]] | None,
    *,
    update_end_year: Any = None,
) -> Dict[str, Any]:
    extracted_data_points = preferred_extracted_data_points(asset)
    required_years = graph_update_required_years(extracted_data_points, update_end_year)
    short_caption = str(asset.get("short_caption") or asset.get("title") or "Source chart").strip() or "Source chart"

    result: Dict[str, Any] = {
        "graph_update_status": GRAPH_UPDATE_STATUS_NO_NEW_DATA,
        "update_reason": "",
        "required_years": required_years,
        "prepared_update_visual": None,
        "graph_update_validation_errors": [],
        "graph_update_references": [],
    }

    normalized_extracted = normalize_chart_series(extracted_data_points)
    if not normalized_extracted:
        result["graph_update_status"] = GRAPH_UPDATE_STATUS_INVALID
        result["update_reason"] = "The original chart does not contain usable extracted datapoints for a deterministic refresh."
        result["graph_update_validation_errors"] = [result["update_reason"]]
        return result

    labels, values_by_series, expected_unit, multi_series = normalized_extracted
    if not extract_years_from_labels(labels):
        result["update_reason"] = "The original chart is not a year-based series, so the refresh stage kept the original figure."
        return result

    if not required_years:
        result["update_reason"] = "The original chart already reaches the selected update window, so the existing figure was kept."
        return result

    llm_refresh_result = _prepare_llm_source_graph_refresh(
        asset,
        list(research_findings or []),
        extracted_data_points=extracted_data_points,
        required_years=required_years,
        update_end_year=update_end_year,
    )
    if llm_refresh_result is not None:
        return llm_refresh_result

    if multi_series:
        result["update_reason"] = (
            "No refreshed graph was approved because the chart has multiple series and the LLM refresh stage "
            "was unavailable or could not return a valid sourced update. The original figure was kept."
        )
        return result

    extracted_by_year, extraction_errors = _extract_required_year_updates(
        list(research_findings or []),
        required_years=required_years,
        expected_unit=expected_unit,
    )

    if extraction_errors:
        result["graph_update_status"] = GRAPH_UPDATE_STATUS_INVALID
        result["update_reason"] = extraction_errors[0]
        result["graph_update_validation_errors"] = extraction_errors
        return result

    missing_years = [year for year in required_years if year not in extracted_by_year]
    if missing_years:
        result["graph_update_status"] = GRAPH_UPDATE_STATUS_NO_NEW_DATA
        result["update_reason"] = (
            "No credible numeric datapoints were found for all required update years "
            + ", ".join(str(year) for year in missing_years)
            + ". The original figure was kept."
        )
        return result

    updated_data_points = {
        "labels": [str(year) for year in required_years],
        "values": [extracted_by_year[year] for year in required_years],
        "unit": expected_unit,
    }
    merged_data_points = merge_preserved_historical_data(extracted_data_points, updated_data_points)
    if merged_data_points is None:
        result["graph_update_status"] = GRAPH_UPDATE_STATUS_INVALID
        result["update_reason"] = "The refreshed datapoints could not be merged with the preserved source history."
        result["graph_update_validation_errors"] = [result["update_reason"]]
        return result

    prepared_visual = {
        "id": str(asset.get("id") or ""),
        "marker_id": str(asset.get("id") or ""),
        "original_asset_id": str(asset.get("id") or ""),
        "source_asset_id": str(asset.get("id") or ""),
        "action": "update",
        "type": "graph",
        "title": short_caption,
        "description": str(asset.get("description") or asset.get("dataset_description") or short_caption).strip(),
        "chart_type": _default_chart_type_for_series(extracted_data_points, asset),
        "data_points": merged_data_points,
        "extracted_data_points": copy.deepcopy(extracted_data_points),
        "update_end_date": str(update_end_year or ""),
        "update_reason": (
            "Preserved historical datapoints exactly and extended the source graph with validated "
            + ", ".join(str(year) for year in required_years)
            + " datapoints from targeted refresh research."
        ),
        "graph_update_status": GRAPH_UPDATE_STATUS_UPDATED,
        "prepared_source_graph_refresh": True,
        "graph_update_method": "deterministic",
    }

    validation_issues = graph_update_validation_issues(
        prepared_visual,
        update_end_year=update_end_year,
        extracted_data_points=extracted_data_points,
    )
    if validation_issues:
        result["graph_update_status"] = GRAPH_UPDATE_STATUS_INVALID
        result["update_reason"] = validation_issues[0]["message"]
        result["graph_update_validation_errors"] = [issue["message"] for issue in validation_issues]
        return result

    result["graph_update_status"] = GRAPH_UPDATE_STATUS_UPDATED
    result["update_reason"] = prepared_visual["update_reason"]
    result["prepared_update_visual"] = prepared_visual
    return result


def inject_prepared_source_graph_updates(
    visual_suggestions: List[Dict[str, Any]] | None,
    assets_to_update: List[Dict[str, Any]] | None,
) -> List[Dict[str, Any]]:
    prepared_by_asset: Dict[str, Dict[str, Any]] = {}
    suppressed_asset_ids: set[str] = set()
    for asset in assets_to_update or []:
        if not isinstance(asset, dict) or not asset_requires_chart_refresh(asset):
            continue
        asset_id = normalize_marker_token(asset.get("id"))
        if not asset_id:
            continue
        suppressed_asset_ids.add(asset_id)
        prepared_visual = asset.get("prepared_update_visual")
        if isinstance(prepared_visual, dict) and str(asset.get("graph_update_status", "")).strip().lower() == GRAPH_UPDATE_STATUS_UPDATED:
            prepared_by_asset[asset_id] = copy.deepcopy(prepared_visual)

    rewritten: List[Dict[str, Any]] = []
    inserted_asset_ids: set[str] = set()
    for visual in visual_suggestions or []:
        if not isinstance(visual, dict):
            rewritten.append(visual)
            continue

        candidate_asset_id = normalize_marker_token(
            visual.get("original_asset_id") or visual.get("marker_id") or visual.get("id")
        )
        if candidate_asset_id in suppressed_asset_ids and str(visual.get("type", "")).strip().lower() == "graph":
            if candidate_asset_id in prepared_by_asset and candidate_asset_id not in inserted_asset_ids:
                rewritten.append(copy.deepcopy(prepared_by_asset[candidate_asset_id]))
                inserted_asset_ids.add(candidate_asset_id)
            continue
        rewritten.append(visual)

    for asset_id, prepared_visual in prepared_by_asset.items():
        if asset_id in inserted_asset_ids:
            continue
        rewritten.append(copy.deepcopy(prepared_visual))

    return rewritten


def graph_update_validation_issues(
    visual: Dict[str, Any],
    *,
    update_end_year: Any = None,
    extracted_data_points: Any = None,
) -> List[Dict[str, str]]:
    if str(visual.get("type", "")).strip().lower() != "graph":
        return []

    issues: List[Dict[str, str]] = []
    if not str(visual.get("chart_type", "")).strip():
        issues.append(
            {
                "code": "graph_missing_chart_type",
                "message": "The graph update is missing a chart_type.",
            }
        )

    data_points = visual.get("data_points", {}) or {}
    normalized_visual_series = normalize_chart_series(data_points)
    if normalized_visual_series is None or not graph_has_plottable_data(data_points):
        issues.append(
            {
                "code": "graph_missing_data_points",
                "message": "The graph update does not contain plottable data points.",
            }
        )
        return issues

    visual_labels, visual_values_by_series, _, _ = normalized_visual_series
    extracted = extracted_data_points if extracted_data_points is not None else visual.get("extracted_data_points")
    normalized_extracted_series = normalize_chart_series(extracted)
    if normalized_extracted_series:
        extracted_labels, extracted_values_by_series, _, _ = normalized_extracted_series
        visual_label_index = {
            series_label_key(label): index
            for index, label in enumerate(visual_labels)
            if series_label_key(label)
        }
        extracted_label_index = {
            series_label_key(label): index
            for index, label in enumerate(extracted_labels)
            if series_label_key(label)
        }

        missing_historical_labels = [
            extracted_labels[index]
            for key, index in extracted_label_index.items()
            if key not in visual_label_index
        ]
        if missing_historical_labels:
            issues.append(
                {
                    "code": "graph_missing_historical_years",
                    "message": "The graph update dropped historical labels from the original chart: "
                    + ", ".join(missing_historical_labels[:6]),
                }
            )

        drifted_labels: List[str] = []
        for extracted_series_name, extracted_series_values in extracted_values_by_series.items():
            matching_visual_series_name = next(
                (
                    visual_series_name
                    for visual_series_name in visual_values_by_series
                    if _series_name_key(visual_series_name) == _series_name_key(extracted_series_name)
                ),
                None,
            )
            if matching_visual_series_name is None:
                issues.append(
                    {
                        "code": "graph_missing_historical_series",
                        "message": f"The graph update dropped the historical series '{extracted_series_name}'.",
                    }
                )
                continue

            visual_series_values = visual_values_by_series[matching_visual_series_name]
            for label in extracted_labels:
                label_key = series_label_key(label)
                if label_key not in extracted_label_index or label_key not in visual_label_index:
                    continue
                extracted_value = extracted_series_values[extracted_label_index[label_key]]
                visual_value = visual_series_values[visual_label_index[label_key]]
                if float(extracted_value) != float(visual_value):
                    drifted_labels.append(label)

        if drifted_labels:
            issues.append(
                {
                    "code": "graph_preserved_history_drift",
                    "message": "The graph update changed preserved historical values for: "
                    + ", ".join(drifted_labels[:6]),
                }
            )

    end_year: Optional[int]
    if isinstance(update_end_year, int):
        end_year = update_end_year
    else:
        match = YEAR_TOKEN_PATTERN.search(str(update_end_year or ""))
        end_year = int(match.group(0)) if match else None

    if end_year:
        visual_years = extract_years_from_labels(visual_labels)
        if visual_years and max(visual_years) < end_year:
            issues.append(
                {
                    "code": "graph_update_end_year_missing",
                    "message": f"The graph update stops at {max(visual_years)} and does not extend through {end_year}.",
                }
            )

    return issues


def apply_graph_update_contract(
    visual: Dict[str, Any],
    *,
    matched_asset: Optional[Dict[str, Any]] = None,
    update_end_year: Any = None,
) -> Dict[str, Any]:
    normalized = copy.deepcopy(visual)
    if str(normalized.get("type", "")).strip().lower() != "graph":
        return normalized

    matched_asset = matched_asset or {}
    if matched_asset.get("id"):
        normalized.setdefault("id", matched_asset.get("id"))
        normalized.setdefault("marker_id", matched_asset.get("id"))
        normalized["original_asset_id"] = matched_asset.get("id")
        normalized.setdefault("source_asset_id", matched_asset.get("id"))
        normalized["action"] = "update"

    normalized["chart_type"] = (
        str(normalized.get("chart_type", "")).strip()
        or str(matched_asset.get("chart_type", "")).strip()
        or str((matched_asset.get("analysis") or {}).get("chart_type", "")).strip()
        or "bar"
    )
    if update_end_year:
        normalized["update_end_date"] = str(update_end_year)

    extracted_data_points = matched_asset.get("extracted_data_points") or normalized.get("extracted_data_points")
    if extracted_data_points:
        normalized["extracted_data_points"] = copy.deepcopy(extracted_data_points)
        merged = merge_preserved_historical_data(extracted_data_points, normalized.get("data_points"))
        if merged is not None:
            normalized["data_points"] = merged

    issues = graph_update_validation_issues(
        normalized,
        update_end_year=update_end_year,
        extracted_data_points=extracted_data_points,
    )
    if issues:
        normalized["graph_validation_errors"] = issues
    else:
        normalized.pop("graph_validation_errors", None)

    return normalized
