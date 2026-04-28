from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Iterable, List

from dotenv import load_dotenv

import llm_client
from llm_json_utils import try_parse_json
from logger_config import setup_logger

load_dotenv()

logger = setup_logger("ReportChangeSummary")

_DEFAULT_GEMINI_CHANGE_SUMMARY_MODEL = "gemini-2.5-flash"
_EXCERPT_CHAR_LIMIT = 900


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_list(values: Any, *, limit: int | None = None) -> List[str]:
    if not isinstance(values, list):
        return []

    items: List[str] = []
    seen = set()
    for value in values:
        cleaned = _safe_text(value)
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        items.append(cleaned)
        if limit is not None and len(items) >= limit:
            break
    return items


def _normalize_whitespace(text: str) -> str:
    return " ".join(_safe_text(text).split())


def _truncate_chars(text: str, limit: int = _EXCERPT_CHAR_LIMIT) -> str:
    cleaned = _normalize_whitespace(text)
    if len(cleaned) <= limit:
        return cleaned
    truncated = cleaned[: max(0, limit - 3)].rstrip()
    return f"{truncated}..."


def _word_count(text: str) -> int:
    return len([token for token in _safe_text(text).split() if token])


def _chapter_changed(entry: Dict[str, Any]) -> bool:
    if entry.get("executive_takeaway"):
        return True
    if entry.get("updated_claims") or entry.get("new_claims") or entry.get("open_questions"):
        return True
    return _normalize_whitespace(entry.get("original_full_text", "")) != _normalize_whitespace(entry.get("draft_text", ""))


def selected_change_summary_model(provider: str | None = None) -> str:
    provider_name = provider or llm_client.get_provider()
    return llm_client.resolve_model(
        _DEFAULT_GEMINI_CHANGE_SUMMARY_MODEL,
        provider=provider_name,
    )


def compute_report_change_signature(
    chapters: Iterable[Dict[str, Any]],
    *,
    provider: str | None = None,
    model: str | None = None,
) -> str:
    provider_name = provider or llm_client.get_provider()
    model_name = model or selected_change_summary_model(provider_name)

    normalized_chapters = []
    for chapter in chapters:
        normalized_chapters.append(
            {
                "title": _safe_text(chapter.get("title")),
                "original_full_text": _normalize_whitespace(chapter.get("original_full_text", "")),
                "draft_text": _normalize_whitespace(chapter.get("draft_text", "")),
                "executive_takeaway": _safe_text(chapter.get("executive_takeaway")),
                "updated_claims": _normalize_list(chapter.get("updated_claims")),
                "new_claims": _normalize_list(chapter.get("new_claims")),
                "retained_claims": _normalize_list(chapter.get("retained_claims")),
                "open_questions": _normalize_list(chapter.get("open_questions")),
            }
        )

    payload = {
        "provider": provider_name,
        "model": model_name,
        "chapters": normalized_chapters,
    }
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    return digest.hexdigest()


def build_report_change_payload(chapters: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    chapter_entries: List[Dict[str, Any]] = []
    counts = {
        "total_chapters": 0,
        "changed_chapters": 0,
        "total_updated_claims": 0,
        "total_new_claims": 0,
        "total_retained_claims": 0,
        "total_open_questions": 0,
    }

    for raw_chapter in chapters:
        original_text = _safe_text(raw_chapter.get("original_full_text"))
        final_text = _safe_text(raw_chapter.get("draft_text"))
        updated_claims = _normalize_list(raw_chapter.get("updated_claims"), limit=6)
        new_claims = _normalize_list(raw_chapter.get("new_claims"), limit=6)
        retained_claims = _normalize_list(raw_chapter.get("retained_claims"), limit=6)
        open_questions = _normalize_list(raw_chapter.get("open_questions"), limit=5)
        entry = {
            "title": _safe_text(raw_chapter.get("title")) or "Untitled Chapter",
            "executive_takeaway": _safe_text(raw_chapter.get("executive_takeaway")),
            "updated_claims": updated_claims,
            "new_claims": new_claims,
            "retained_claims": retained_claims,
            "open_questions": open_questions,
            "original_word_count": _word_count(original_text),
            "final_word_count": _word_count(final_text),
            "original_excerpt": _truncate_chars(original_text),
            "final_excerpt": _truncate_chars(final_text),
            "original_full_text": original_text,
            "draft_text": final_text,
        }
        entry["changed"] = _chapter_changed(entry)
        chapter_entries.append(entry)

        counts["total_chapters"] += 1
        counts["changed_chapters"] += 1 if entry["changed"] else 0
        counts["total_updated_claims"] += len(updated_claims)
        counts["total_new_claims"] += len(new_claims)
        counts["total_retained_claims"] += len(retained_claims)
        counts["total_open_questions"] += len(open_questions)

    ai_chapters = [
        {
            "title": entry["title"],
            "executive_takeaway": entry["executive_takeaway"],
            "updated_claims": entry["updated_claims"],
            "new_claims": entry["new_claims"],
            "retained_claims": entry["retained_claims"],
            "open_questions": entry["open_questions"],
            "original_word_count": entry["original_word_count"],
            "final_word_count": entry["final_word_count"],
            "original_excerpt": entry["original_excerpt"],
            "final_excerpt": entry["final_excerpt"],
            "changed": entry["changed"],
        }
        for entry in chapter_entries
    ]

    for entry in chapter_entries:
        entry.pop("original_full_text", None)
        entry.pop("draft_text", None)

    return {
        "counts": counts,
        "chapters": chapter_entries,
        "ai_input": {
            "counts": counts,
            "chapters": ai_chapters,
        },
    }


def _normalize_change_items(values: Any, *, value_key: str) -> List[Dict[str, str]]:
    normalized: List[Dict[str, str]] = []
    if not isinstance(values, list):
        return normalized

    for item in values:
        chapter_title = ""
        value = ""
        if isinstance(item, dict):
            chapter_title = _safe_text(item.get("chapter_title") or item.get("chapter") or item.get("title"))
            value = _safe_text(item.get(value_key) or item.get("item") or item.get("summary") or item.get("text"))
        else:
            value = _safe_text(item)
        if not value:
            continue
        normalized.append(
            {
                "chapter_title": chapter_title,
                value_key: value,
            }
        )
    return normalized


def _normalize_ai_summary(parsed: Any) -> Dict[str, Any]:
    if not isinstance(parsed, dict):
        raise ValueError("AI change summary did not return a JSON object.")

    summary_bullets = _normalize_list(parsed.get("summary_bullets"), limit=5)
    important_changes = _normalize_change_items(parsed.get("important_changes"), value_key="change")[:8]
    open_questions = _normalize_change_items(parsed.get("notable_open_questions"), value_key="question")[:3]

    normalized = {
        "headline": _safe_text(parsed.get("headline")),
        "summary_bullets": summary_bullets[:5],
        "important_changes": important_changes,
        "notable_open_questions": open_questions,
    }
    if not normalized["headline"]:
        raise ValueError("AI change summary did not include a headline.")
    if len(normalized["summary_bullets"]) < 3:
        raise ValueError("AI change summary did not include enough summary bullets.")
    return normalized


def generate_ai_report_change_summary(change_payload: Dict[str, Any]) -> Dict[str, Any]:
    api_key = llm_client.get_api_key()
    if not api_key:
        return {"error": llm_client.missing_api_key_error()}

    provider = llm_client.get_provider()
    model = selected_change_summary_model(provider)
    ai_input = change_payload.get("ai_input") if isinstance(change_payload, dict) else None
    if not isinstance(ai_input, dict):
        return {"error": "Change payload is missing AI input data."}

    prompt = (
        "You are summarizing how an updated report differs from its source report.\n\n"
        "Return ONLY valid JSON with this exact schema:\n"
        "{\n"
        '  "headline": "short title",\n'
        '  "summary_bullets": ["3 to 5 concise bullets"],\n'
        '  "important_changes": [{"chapter_title": "Chapter name", "change": "short chapter-tagged change"}],\n'
        '  "notable_open_questions": [{"chapter_title": "Chapter name", "question": "optional unresolved question"}]\n'
        "}\n\n"
        "Rules:\n"
        "- Focus on what was updated, added, or materially clarified.\n"
        "- Keep each bullet short and concrete.\n"
        "- Use chapter titles when naming important changes and open questions.\n"
        "- Do not mention implementation details, prompts, or model behavior.\n"
        "- If there are no meaningful open questions, return an empty list for notable_open_questions.\n\n"
        f"Structured report change payload:\n{json.dumps(ai_input, ensure_ascii=False, indent=2)}"
    )

    try:
        response = llm_client.generate_content(
            api_key=api_key,
            model=model,
            contents=prompt,
            response_mime_type="application/json",
            temperature=0.1,
            operation="report_change_summary.generate_ai_report_change_summary",
        )
        parsed = try_parse_json(_safe_text(response.text))
        return _normalize_ai_summary(parsed)
    except Exception as exc:
        logger.warning("Unable to generate AI report change summary: %s", exc)
        return {"error": f"Unable to generate AI change summary: {exc}"}
