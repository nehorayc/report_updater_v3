import json
import os
from pathlib import Path
import time
from dotenv import load_dotenv
from typing import Any, Dict, List, Optional
from llm_client import (
    generate_content as gemini_generate_content,
    get_api_key,
    missing_api_key_error,
    provider_display_name,
    resolve_model,
)

load_dotenv()

from logger_config import setup_logger

logger = setup_logger("VisionService")

_RUNTIME_DIAGNOSTICS: List[Dict[str, str]] = []


def reset_runtime_diagnostics() -> None:
    _RUNTIME_DIAGNOSTICS.clear()


def consume_runtime_diagnostics() -> List[Dict[str, str]]:
    diagnostics = list(_RUNTIME_DIAGNOSTICS)
    _RUNTIME_DIAGNOSTICS.clear()
    return diagnostics


def _is_quota_error(exc: Exception) -> bool:
    message = str(exc or "").lower()
    return any(token in message for token in ("429", "quota", "resource_exhausted", "rate limit"))


def _record_runtime_diagnostic(level: str, message: str) -> None:
    normalized = " ".join(str(message or "").split())
    if not normalized:
        return
    diagnostic = {"level": level, "message": normalized}
    if diagnostic not in _RUNTIME_DIAGNOSTICS:
        _RUNTIME_DIAGNOSTICS.append(diagnostic)


def _image_mime_type(path: str) -> str:
    suffix = Path(path).suffix.lower()
    if suffix == ".png":
        return "image/png"
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".webp":
        return "image/webp"
    return "application/octet-stream"


def _normalize_numeric_value(value: Any) -> Optional[int | float]:
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


def _normalize_chart_data_points(payload: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(payload, dict):
        return None

    labels = payload.get("labels")
    values = payload.get("values")
    unit = " ".join(str(payload.get("unit", "") or "").split())

    if not isinstance(labels, list) or not labels:
        return None

    normalized_labels: List[str] = []
    for label in labels:
        text = " ".join(str(label or "").split())
        if not text:
            return None
        normalized_labels.append(text)

    if isinstance(values, list):
        if len(values) != len(normalized_labels):
            return None
        normalized_values: List[int | float] = []
        for value in values:
            numeric = _normalize_numeric_value(value)
            if numeric is None:
                return None
            normalized_values.append(numeric)
        result: Dict[str, Any] = {"labels": normalized_labels, "values": normalized_values}
        if unit:
            result["unit"] = unit
        return result

    if isinstance(values, dict) and values:
        normalized_values_by_series: Dict[str, List[int | float]] = {}
        for series_name, series_values in values.items():
            if not isinstance(series_values, list) or len(series_values) != len(normalized_labels):
                return None
            normalized_series: List[int | float] = []
            for value in series_values:
                numeric = _normalize_numeric_value(value)
                if numeric is None:
                    return None
                normalized_series.append(numeric)
            normalized_values_by_series[str(series_name).strip() or "Series"] = normalized_series
        result = {"labels": normalized_labels, "values": normalized_values_by_series}
        if unit:
            result["unit"] = unit
        return result

    return None


def _load_sidecar_chart_data_points(asset_path: str) -> Optional[Dict[str, Any]]:
    candidate = Path(asset_path).with_suffix(".json")
    if not candidate.exists():
        return None

    try:
        parsed = json.loads(candidate.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed to read chart datapoint sidecar '%s': %s", candidate, exc)
        return None

    if isinstance(parsed, dict):
        payload = parsed.get("data_points") if "data_points" in parsed else parsed.get("extracted_data_points") or parsed
    else:
        payload = None

    normalized = _normalize_chart_data_points(payload)
    if normalized:
        logger.info("Loaded chart datapoints from sidecar: %s", candidate)
    return normalized


def _focused_chart_update_query(result: Dict[str, Any]) -> str:
    short_caption = " ".join(str(result.get("short_caption", "") or "").split())
    description = " ".join(str(result.get("dataset_description", "") or "").split())
    seed = short_caption or description or "chart"
    return f"{seed} updated data recent years".strip()


def _asset_caption_fallback(asset: Dict[str, Any]) -> str:
    existing = " ".join(str(asset.get("short_caption", "") or "").split())
    if existing:
        return existing
    stem = Path(str(asset.get("path", ""))).stem.replace("_", " ").strip()
    return stem or f"Asset {asset.get('id', '')}"


def _extract_chart_data_points(
    *,
    asset: Dict[str, Any],
    api_key: str,
    result: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    path = asset.get("path")
    if not path:
        return None

    try:
        image_bytes = Path(path).read_bytes()
    except Exception as exc:
        logger.warning("Could not load chart image for datapoint extraction '%s': %s", path, exc)
        return None

    prompt = f"""
Extract the plotted data from this chart image.

Return ONLY JSON with this shape:
{{
  "labels": ["2020", "2021"],
  "values": [42, 58],
  "unit": "Thousand Units"
}}

Rules:
- Preserve label order exactly as shown in the chart.
- Return numeric values only. If they appear to be whole numbers, return integers.
- Do not invent extra labels or extra points.
- For a single-series chart, `values` must be a list.
- For a multi-series chart, `values` may be an object mapping series names to lists.
- If extraction is uncertain, return empty labels and values instead of guessing.

Context:
- Asset ID: {asset.get("id")}
- Caption: {result.get("short_caption", "")}
- Existing analysis: {result.get("dataset_description", "")}
"""

    start_time = time.time()
    try:
        response = gemini_generate_content(
            api_key=api_key,
            model=resolve_model("gemini-2.5-flash", role="vision"),
            contents=[
                prompt,
                {
                    "mime_type": _image_mime_type(path),
                    "data": image_bytes,
                },
            ],
            response_mime_type="application/json",
        )
        latency = time.time() - start_time
        logger.info("Focused chart datapoint extraction completed in %.2fs for %s", latency, asset.get("id"))

        payload = json.loads(response.text.strip())
        if isinstance(payload, dict) and "data_points" in payload:
            payload = payload["data_points"]
        return _normalize_chart_data_points(payload)
    except Exception as exc:
        logger.warning("Focused chart datapoint extraction failed for %s: %s", asset.get("id"), exc)
        return None


def _augment_analysis_result_with_chart_data(
    *,
    result: Dict[str, Any],
    asset_lookup: Dict[str, Dict[str, Any]],
    api_key: str,
) -> Dict[str, Any]:
    normalized = dict(result)
    asset = asset_lookup.get(str(normalized.get("id", "")))
    asset_type = str(normalized.get("type", "")).strip().lower()
    is_chart = asset_type in {"chart", "graph"}

    extracted = _normalize_chart_data_points(normalized.get("extracted_data_points"))

    if asset and is_chart:
        sidecar_data = _load_sidecar_chart_data_points(str(asset.get("path", "")))
        if extracted is None and sidecar_data is None:
            extracted = _extract_chart_data_points(asset=asset, api_key=api_key, result=normalized)
        if sidecar_data is not None:
            if extracted is not None and extracted != sidecar_data:
                logger.warning(
                    "Model-extracted chart datapoints differed from sidecar for %s; using sidecar values.",
                    asset.get("id"),
                )
            extracted = sidecar_data
        normalized["extracted_data_points"] = extracted
        if not normalized.get("suggested_update_query"):
            normalized["suggested_update_query"] = _focused_chart_update_query(normalized)
        if asset_type == "image" and extracted is not None:
            normalized["type"] = "chart"
    else:
        normalized["extracted_data_points"] = extracted if is_chart else None

    return normalized


def _fallback_result_for_failed_asset(asset: Dict[str, Any]) -> Dict[str, Any]:
    fallback = {
        "id": asset["id"],
        "type": "image",
        "short_caption": "Error analyzing image.",
        "dataset_description": "Analysis failed.",
        "suggested_update_query": None,
        "extracted_data_points": None,
    }

    sidecar_data = _load_sidecar_chart_data_points(str(asset.get("path", "")))
    if sidecar_data is not None:
        fallback["type"] = "chart"
        fallback["short_caption"] = _asset_caption_fallback(asset)
        fallback["dataset_description"] = (
            "Recovered chart analysis from local sidecar datapoints after live image analysis failed."
        )
        fallback["extracted_data_points"] = sidecar_data
        fallback["suggested_update_query"] = _focused_chart_update_query(fallback)

    return fallback

def analyze_batch_assets(assets: List[Dict]) -> List[Dict]:
    """
    Uses the selected multimodal LLM provider to analyze a batch of images.
    Expects assets to be a list of dicts with 'id' and 'path'.
    Returns a list of dicts with analysis results.
    """
    logger.info(f"Starting batch analysis for {len(assets)} assets.")
    api_key = get_api_key()
    if not api_key:
        logger.error("%s.", missing_api_key_error())
        _record_runtime_diagnostic(
            "error",
            f"{missing_api_key_error()} in environment, so the selected assets could not be analyzed.",
        )
        return []

    results = []
    
    # Process in chunks of 5 to avoid payload limits/complexity
    chunk_size = 5
    for i in range(0, len(assets), chunk_size):
        chunk = assets[i:i + chunk_size]
        logger.info(f"Processing chunk {i//chunk_size + 1} ({len(chunk)} images).")
        
        prompt_parts = [
            """
            Analyze these images from a professional report. I will provide them in order.
            For EACH image, output a JSON object with the following fields:
            - id: The ID provided for the image.
            - type: One of "chart", "image", "table".
            - short_caption: A very brief, 1-sentence summary of the content (for a quick caption).
            - table_markdown: If the type is "table", provide the full transcription of the data into a markdown table. Otherwise, leave null.
            - dataset_description: A DETAILED description of the data, axes, content, mood, logic, etc. needed to reconstruct it (if chart) or understand the table structure.
            - extracted_data_points: If the type is "chart", return structured plotted data when legible in the form {"labels": [...], "values": [...], "unit": "..."}. Otherwise, leave null.
            - suggested_update_query: If it is a chart/graph or table with a timeline (e.g., 2010-2020), provide a search query to find updated data (e.g., "Renewable energy adoption statistics 2020-2025"). Otherwise, leave null.
            
            Return a JSON LIST of these objects.
            """
        ]

        asset_lookup = {str(asset.get("id", "")): asset for asset in chunk if asset.get("id")}
        
        for asset in chunk:
            prompt_parts.append(f"Image ID: {asset['id']}")
            try:
                img_data = {
                    "mime_type": _image_mime_type(asset["path"]),
                    "data": open(asset['path'], "rb").read()
                }
                prompt_parts.append(img_data)
            except Exception as e:
                logger.error(f"Error loading image {asset['path']}: {e}")
                
        # Use JSON mode for guaranteed valid JSON output
        start_time = time.time()
        try:
            provider_name = provider_display_name()
            logger.debug("Sending request to %s for chunk %s...", provider_name, i//chunk_size + 1)
            response = gemini_generate_content(
                api_key=api_key,
                model=resolve_model('gemini-2.5-flash', role="vision"),
                contents=prompt_parts,
                response_mime_type="application/json",
            )
            latency = time.time() - start_time
            logger.info("%s response received for chunk %s in %.2fs.", provider_name, i//chunk_size + 1, latency)
            
            text = response.text.strip()
            logger.debug(f"Raw response: {text[:200]}...")

            parsed = json.loads(text)
            if isinstance(parsed, list):
                augmented = [
                    _augment_analysis_result_with_chart_data(
                        result=item,
                        asset_lookup=asset_lookup,
                        api_key=api_key,
                    )
                    if isinstance(item, dict)
                    else item
                    for item in parsed
                ]
                results.extend(augmented)
                logger.info(f"Successfully parsed {len(parsed)} results from chunk.")
            else:
                 # Fallback if model returns single object instead of list
                 if isinstance(parsed, dict):
                     parsed = _augment_analysis_result_with_chart_data(
                         result=parsed,
                         asset_lookup=asset_lookup,
                         api_key=api_key,
                     )
                 results.append(parsed)
                 logger.info("Successfully parsed 1 result from chunk (fallback).")
                 
        except Exception as e:
            logger.error(f"Error in batch analysis for chunk {i//chunk_size + 1}: {e}", exc_info=True)
            if _is_quota_error(e):
                _record_runtime_diagnostic(
                    "warning",
                    f"{provider_display_name()} quota was exhausted while analyzing selected assets. Captions and update suggestions may be incomplete for this run.",
                )
            else:
                _record_runtime_diagnostic(
                    "error",
                    "Asset analysis failed for one or more selected visuals. Placeholder captions were used instead.",
                )
            # Add placeholders for failed items
            for asset in chunk:
                results.append(_fallback_result_for_failed_asset(asset))

    logger.info(f"Batch analysis complete. Total results: {len(results)}")
    return results

if __name__ == "__main__":
    # Test
    pass
