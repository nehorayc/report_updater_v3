import json
import re
from typing import Any, Dict, Iterable


def strip_code_fences(text: str) -> str:
    cleaned = str(text or "").strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    return cleaned.strip()


def try_parse_json(text: str) -> Any:
    cleaned = strip_code_fences(text)
    if not cleaned:
        raise json.JSONDecodeError("Empty JSON content", cleaned, 0)

    stripped = cleaned.strip()
    if stripped.startswith("{"):
        closing = stripped.rfind("}")
        candidate = stripped[: closing + 1] if closing != -1 else stripped
    elif stripped.startswith("["):
        closing = stripped.rfind("]")
        candidate = stripped[: closing + 1] if closing != -1 else stripped
    else:
        object_start = cleaned.find("{")
        object_end = cleaned.rfind("}")
        array_start = cleaned.find("[")
        array_end = cleaned.rfind("]")
        if object_start != -1 and object_end != -1 and object_end > object_start:
            candidate = cleaned[object_start : object_end + 1]
        elif array_start != -1 and array_end != -1 and array_end > array_start:
            candidate = cleaned[array_start : array_end + 1]
        else:
            candidate = cleaned
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        repaired = re.sub(r",\s*([\]}])", r"\1", candidate)
        return json.loads(repaired)


def _extract_field_block(text: str, key: str, next_keys: Iterable[str]) -> str | None:
    start_match = re.search(rf'"{re.escape(key)}"\s*:\s*', text)
    if not start_match:
        return None

    start = start_match.end()
    next_patterns = [rf',\s*"{re.escape(next_key)}"\s*:' for next_key in next_keys]
    end = len(text)
    for pattern in next_patterns:
        match = re.search(pattern, text[start:], flags=re.DOTALL)
        if match:
            end = min(end, start + match.start())

    raw = text[start:end].strip()
    if raw.endswith(","):
        raw = raw[:-1].rstrip()
    return raw


def _decode_string(raw: str) -> str:
    raw = str(raw or "").strip()
    if not raw:
        return ""
    try:
        decoded = json.loads(raw)
        return decoded if isinstance(decoded, str) else str(decoded)
    except Exception:
        if raw.startswith('"') and raw.endswith('"') and len(raw) >= 2:
            raw = raw[1:-1]
        return (
            raw.replace("\\n", "\n")
            .replace("\\r", "\r")
            .replace("\\t", "\t")
            .replace('\\"', '"')
            .replace("\\\\", "\\")
            .strip()
        )


def _decode_string_list(raw: str) -> list[str]:
    raw = str(raw or "").strip()
    if not raw:
        return []
    try:
        decoded = json.loads(raw)
        if isinstance(decoded, list):
            return [str(item).strip() for item in decoded if str(item).strip()]
    except Exception:
        pass

    matches = re.findall(r'"((?:\\.|[^"\\])*)"', raw, flags=re.DOTALL)
    results = []
    for match in matches:
        item = _decode_string(f'"{match}"')
        if item:
            results.append(item)
    return results


def _decode_json_value(raw: str) -> Any:
    raw = str(raw or "").strip()
    if not raw:
        return None
    try:
        return try_parse_json(raw)
    except Exception:
        try:
            repaired = re.sub(r",\s*([\]}])", r"\1", raw)
            return json.loads(repaired)
        except Exception:
            return None


def salvage_ordered_json(text: str, field_types: Dict[str, str]) -> Dict[str, Any]:
    cleaned = strip_code_fences(text)
    keys = list(field_types.keys())
    result: Dict[str, Any] = {}

    for index, key in enumerate(keys):
        raw = _extract_field_block(cleaned, key, keys[index + 1 :])
        if raw is None:
            continue

        field_type = field_types[key]
        if field_type == "string":
            result[key] = _decode_string(raw)
        elif field_type == "string_list":
            result[key] = _decode_string_list(raw)
        elif field_type == "json":
            decoded = _decode_json_value(raw)
            if decoded is not None:
                result[key] = decoded
        else:
            result[key] = raw

    return result
