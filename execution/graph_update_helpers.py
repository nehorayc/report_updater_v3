from __future__ import annotations

import copy
import json
import re
from typing import Any, Dict, List, Optional, Tuple


YEAR_TOKEN_PATTERN = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")
_SINGLE_SERIES_KEY = "__single__"


def normalize_marker_token(value: Any) -> str:
    token = str(value or "").strip().lower()
    if not token:
        return ""
    return re.sub(r"[^a-z0-9_-]", "", token)


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


def format_chart_data_points_for_prompt(extracted_data_points: Any) -> str:
    normalized = normalize_chart_series(extracted_data_points)
    if not normalized:
        return ""

    labels, values_by_series, unit, multi_series = normalized
    payload = denormalize_chart_series(labels, values_by_series, unit=unit, multi_series=multi_series)
    return json.dumps(payload, ensure_ascii=False)


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
