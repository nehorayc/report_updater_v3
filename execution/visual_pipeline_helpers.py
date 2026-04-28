from __future__ import annotations

import re
from typing import Callable

VISUAL_MARKER_PATTERN = re.compile(
    r"\[(?:Figure|Asset|Image|Figura|איור|תמונה)(?:\s+ID)?\s*:?\s*([A-Za-z0-9][A-Za-z0-9_-]{3,63})[:\s]*.*?\]",
    re.IGNORECASE,
)
RAW_VISUAL_TOKEN_PATTERN = re.compile(
    r"\[\s*visual\s*:\s*([A-Za-z0-9][A-Za-z0-9_-]{3,63})[^\]]*\]",
    re.IGNORECASE,
)
_VISUAL_TOKEN_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9%/-]{2,}")
_VISUAL_STOPWORDS = {
    "about",
    "after",
    "also",
    "analysis",
    "annual",
    "asset",
    "background",
    "below",
    "between",
    "both",
    "caption",
    "case",
    "chart",
    "comparison",
    "current",
    "data",
    "digital",
    "figure",
    "from",
    "graph",
    "high",
    "image",
    "into",
    "map",
    "overview",
    "professional",
    "query",
    "report",
    "resolution",
    "schematic",
    "shows",
    "storage",
    "study",
    "that",
    "their",
    "there",
    "these",
    "this",
    "through",
    "timeline",
    "updated",
    "use",
    "uses",
    "using",
    "visual",
    "with",
    "workflow",
}


def build_figure_marker(marker_id: str, caption: str) -> str:
    return f"[Figure {marker_id}: {caption}]"


def _clean_visual_context_text(value: str) -> str:
    cleaned = str(value or "")
    cleaned = VISUAL_MARKER_PATTERN.sub(" ", cleaned)
    cleaned = RAW_VISUAL_TOKEN_PATTERN.sub(" ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _keyword_tokens(*parts: str) -> list[str]:
    seen = set()
    keywords: list[str] = []
    for part in parts:
        cleaned = _clean_visual_context_text(part)
        for token in _VISUAL_TOKEN_PATTERN.findall(cleaned):
            normalized = token.lower().strip("-/")
            if normalized in _VISUAL_STOPWORDS:
                continue
            if normalized in seen:
                continue
            seen.add(normalized)
            keywords.append(normalized)
    return keywords


def _match_phrases(visual: dict) -> list[str]:
    phrases: list[str] = []
    seen = set()
    for key in (
        "query",
        "title",
        "short_caption",
        "description",
        "source_context_heading",
        "source_context_excerpt",
        "source_context_fallback",
    ):
        cleaned = _clean_visual_context_text(str(visual.get(key) or ""))
        if len(cleaned) < 12:
            continue
        lowered = cleaned.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        phrases.append(cleaned)
    return phrases


def _score_paragraph(paragraph: str, *, keywords: list[str], phrases: list[str]) -> int:
    cleaned = _clean_visual_context_text(paragraph)
    if not cleaned:
        return -1

    normalized = cleaned.lower()
    if VISUAL_MARKER_PATTERN.fullmatch(cleaned):
        return -1

    paragraph_tokens = {
        token.lower().strip("-/")
        for token in _VISUAL_TOKEN_PATTERN.findall(cleaned)
        if token
    }

    score = len(paragraph_tokens.intersection(keywords)) * 2
    for phrase in phrases:
        phrase_normalized = phrase.lower()
        if phrase_normalized in normalized:
            score += 5
            continue

        phrase_keywords = {
            token.lower().strip("-/")
            for token in _VISUAL_TOKEN_PATTERN.findall(phrase)
            if token
        }
        overlap = len(paragraph_tokens.intersection(phrase_keywords))
        if overlap >= 2:
            score += overlap

    if paragraph.lstrip().startswith("#"):
        score -= 1

    return score


def place_marker_near_relevant_paragraph(
    text: str,
    marker: str,
    visual: dict | None,
) -> tuple[str, str]:
    """
    Insert a visual marker near the most relevant paragraph.

    Returns the updated text plus a placement mode:
    - `contextual`: inserted near a scored paragraph
    - `chapter_end`: appended because no useful paragraph matched
    - `empty`: text was empty, so the marker became the full body
    """
    source_text = str(text or "").strip()
    if not source_text:
        return marker, "empty"

    paragraphs = [block.strip() for block in re.split(r"\n\s*\n", source_text) if block.strip()]
    if not paragraphs:
        return marker, "empty"

    visual = visual or {}
    keywords = _keyword_tokens(
        str(visual.get("title") or ""),
        str(visual.get("short_caption") or ""),
        str(visual.get("description") or ""),
        str(visual.get("query") or ""),
        str(visual.get("source_context_heading") or ""),
        str(visual.get("source_context_excerpt") or ""),
        str(visual.get("source_context_fallback") or ""),
    )
    phrases = _match_phrases(visual)

    best_index = -1
    best_score = 0
    for index, paragraph in enumerate(paragraphs):
        score = _score_paragraph(paragraph, keywords=keywords, phrases=phrases)
        if score > best_score:
            best_index = index
            best_score = score

    if best_index < 0 or best_score <= 0:
        return f"{source_text.rstrip()}\n\n{marker}\n", "chapter_end"

    insertion_index = best_index
    if paragraphs[insertion_index].lstrip().startswith("#") and insertion_index + 1 < len(paragraphs):
        insertion_index += 1

    paragraphs.insert(insertion_index + 1, marker)
    return "\n\n".join(paragraphs), "contextual"


def resolve_visual_for_export(
    visual: dict,
    *,
    generate_graph_fn: Callable[[dict], dict],
    search_image_fn: Callable[..., dict],
) -> dict:
    visual_type = str(visual.get("type", "")).strip().lower()
    if visual_type == "graph":
        return generate_graph_fn(visual)

    query = (
        str(visual.get("query") or "").strip()
        or str(visual.get("description") or "").strip()
        or str(visual.get("title") or "").strip()
        or str(visual.get("short_caption") or "").strip()
    )
    return search_image_fn(query, allow_placeholder_fallback=True)
