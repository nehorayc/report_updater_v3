from __future__ import annotations

import re
from typing import Any, Dict, List


_REPORT_PREFIX_PATTERN = re.compile(r"^(?:report|ai report)\s*[-_: ]*", re.IGNORECASE)
_SEPARATOR_PATTERN = re.compile(r"[_\-]+")
_MULTISPACE_PATTERN = re.compile(r"\s+")
_GENERIC_SUBJECTS = {"report", "ai report", "updated edition", "modernized report"}
_ANALYSIS_TERMS = (
    "analysis",
    "assessment",
    "outlook",
    "review",
    "forecast",
    "adoption",
    "impact",
    "risk",
    "trajectory",
)
_INTRO_TERMS = {"background", "overview", "introduction", "context"}


def _clean_label(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"\.[A-Za-z0-9]{2,5}$", "", text)
    text = _REPORT_PREFIX_PATTERN.sub("", text)
    text = _SEPARATOR_PATTERN.sub(" ", text)
    text = _MULTISPACE_PATTERN.sub(" ", text)
    return text.strip(" -_:")


def _unique(items: List[str], limit: int = 10) -> List[str]:
    seen = set()
    results: List[str] = []
    for item in items:
        text = _MULTISPACE_PATTERN.sub(" ", str(item or "").strip())
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        results.append(text)
        if len(results) >= limit:
            break
    return results


def infer_report_subject(report_title: str = "", report_metadata: Dict[str, Any] | None = None) -> str:
    report_metadata = report_metadata or {}
    candidates = [
        report_metadata.get("edition_title", ""),
        report_title,
    ]
    for candidate in candidates:
        cleaned = _clean_label(candidate)
        if cleaned and cleaned.lower() not in _GENERIC_SUBJECTS:
            return cleaned
    return ""


def build_source_anchored_topic(chapter_title: str, report_subject: str, chapter_role: str = "body") -> str:
    title = _clean_label(chapter_title)
    subject = _clean_label(report_subject)
    if not title:
        return subject
    if not subject:
        return title

    lowered_title = title.lower()
    lowered_subject = subject.lower()
    if lowered_subject in lowered_title:
        return title

    if lowered_title in _INTRO_TERMS or chapter_role == "introduction":
        return f"{title} of {subject}"
    if any(term in lowered_title for term in _ANALYSIS_TERMS):
        return f"{title} of {subject}"
    return f"{title} for {subject}"


def build_chapter_blueprint_defaults(
    chapter: Dict[str, Any],
    report_metadata: Dict[str, Any] | None = None,
    report_title: str = "",
) -> Dict[str, Any]:
    report_metadata = report_metadata or {}
    baseline = chapter.get("baseline", {}) or {}
    source_title = str(chapter.get("source_title") or chapter.get("title") or "").strip()
    chapter_role = str(baseline.get("chapter_role") or "body").strip() or "body"
    report_subject = infer_report_subject(report_title, report_metadata)
    topic = build_source_anchored_topic(source_title, report_subject, chapter_role=chapter_role)

    baseline_keywords = baseline.get("keywords", []) if isinstance(baseline.get("keywords"), list) else []
    baseline_entities = baseline.get("named_entities", []) if isinstance(baseline.get("named_entities"), list) else []
    baseline_claims = baseline.get("core_claims", []) if isinstance(baseline.get("core_claims"), list) else []

    keyword_pool: List[str] = []
    if topic:
        keyword_pool.append(topic)
    if source_title:
        keyword_pool.append(source_title)
    if report_subject:
        keyword_pool.append(report_subject)
    keyword_pool.extend(str(item) for item in baseline_keywords[:6])
    keyword_pool.extend(str(item) for item in baseline_entities[:3])
    keyword_pool.extend(str(item) for item in baseline_claims[:2])

    return {
        "topic": topic or source_title,
        "keywords": _unique(keyword_pool, limit=10),
        "report_subject": report_subject,
        "source_chapter_title": source_title,
    }


def _first_meaningful_paragraph(text: Any, limit: int = 280) -> str:
    for block in re.split(r"\n\s*\n", str(text or "")):
        candidate = block.strip()
        if not candidate:
            continue
        if candidate.startswith("#"):
            continue
        if len(candidate.split()) < 6:
            continue
        candidate = _MULTISPACE_PATTERN.sub(" ", candidate)
        if len(candidate) <= limit:
            return candidate
        return candidate[: limit - 3] + "..."
    return ""


def build_prior_chapter_context(
    chapters: List[Dict[str, Any]],
    current_index: int,
    limit: int = 3,
) -> List[Dict[str, Any]]:
    if current_index <= 0:
        return []

    start_index = max(0, current_index - limit)
    selected = chapters[start_index:current_index]
    context_items: List[Dict[str, Any]] = []

    for chapter in selected:
        if "draft_text" not in chapter:
            continue

        summary = str(chapter.get("executive_takeaway") or "").strip()
        if not summary:
            summary = _first_meaningful_paragraph(chapter.get("draft_text", ""))
        if not summary:
            summary = _first_meaningful_paragraph(chapter.get("content", ""))

        key_points = _unique(
            list(chapter.get("updated_claims", []) or [])
            + list(chapter.get("new_claims", []) or [])
            + list(chapter.get("retained_claims", []) or []),
            limit=3,
        )
        open_questions = _unique(list(chapter.get("open_questions", []) or []), limit=2)

        if not summary and not key_points and not open_questions:
            continue

        context_items.append(
            {
                "title": str(chapter.get("title", "Untitled Chapter")).strip() or "Untitled Chapter",
                "summary": summary,
                "key_points": key_points,
                "open_questions": open_questions,
            }
        )

    return context_items

