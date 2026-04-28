from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Tuple


_YEAR_PATTERN = re.compile(r"\b(19\d{2}|20\d{2})\b")
_PERCENT_PATTERN = re.compile(r"\b\d+(?:\.\d+)?\s*%")
_NUMBER_PATTERN = re.compile(r"(?<![A-Za-z])(?:[$€£]\s*)?\d+(?:,\d{3})*(?:\.\d+)?(?:\s*%|x)?")
_GRAPH_QUESTION_TOKEN_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9\-]{2,}|[\u0590-\u05FF]{2,}")
_GRAPH_QUESTION_STOPWORDS = {
    "about",
    "across",
    "after",
    "among",
    "analysis",
    "and",
    "annual",
    "are",
    "between",
    "chapter",
    "compare",
    "comparison",
    "data",
    "figure",
    "finding",
    "for",
    "from",
    "graph",
    "growth",
    "how",
    "into",
    "latest",
    "market",
    "overview",
    "report",
    "research",
    "section",
    "shows",
    "since",
    "storage",
    "study",
    "that",
    "the",
    "their",
    "this",
    "through",
    "update",
    "updated",
    "using",
    "what",
    "with",
}
_TREND_TERMS = {
    "annual",
    "annually",
    "change",
    "grew",
    "growth",
    "over time",
    "timeline",
    "trend",
    "trajectory",
    "yearly",
}
_COMPARISON_TERMS = {
    "benchmark",
    "compared",
    "comparison",
    "density",
    "relative",
    "versus",
    "vs",
}
_COMPOSITION_TERMS = {
    "breakdown",
    "composition",
    "distribution",
    "mix",
    "portion",
    "share",
}
_BEFORE_AFTER_TERMS = {
    "before",
    "after",
    "change",
    "delta",
    "increase",
    "decrease",
}


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _strip_visual_prefix(text: str) -> str:
    return re.sub(r"^\[For Figure [^\]]+\]\s*", "", _normalize_text(text), flags=re.IGNORECASE)


def _tokenize(text: str) -> List[str]:
    tokens = []
    for token in _GRAPH_QUESTION_TOKEN_PATTERN.findall(str(text or "").lower()):
        if token in _GRAPH_QUESTION_STOPWORDS or len(token) < 3:
            continue
        tokens.append(token)
    return tokens


def _metric_phrase(title: str, blueprint: Dict[str, Any]) -> str:
    cleaned = _strip_visual_prefix(title)
    cleaned = re.sub(r"\((?:19|20)\d{2}(?:\s*[-–]\s*(?:19|20)\d{2})?\)", "", cleaned).strip(" -:")
    if cleaned:
        return cleaned
    return _normalize_text(
        blueprint.get("source_chapter_title")
        or blueprint.get("topic")
        or blueprint.get("report_subject")
        or "this chapter metric"
    )


def _extract_years(text: str) -> List[int]:
    return sorted({int(year) for year in _YEAR_PATTERN.findall(str(text or ""))})


def _extract_numeric_tokens(text: str) -> List[str]:
    return [token.strip() for token in _NUMBER_PATTERN.findall(str(text or "")) if token.strip()]


def _extract_percent_tokens(text: str) -> List[str]:
    return [token.strip() for token in _PERCENT_PATTERN.findall(str(text or "")) if token.strip()]


def _infer_unit(text: str) -> str:
    lowered = str(text or "").lower()
    if "%" in lowered or "percent" in lowered:
        return "%"
    if "$" in str(text or "") or any(symbol in lowered for symbol in ("usd", "eur", "gbp")):
        return "currency"
    if "tb" in lowered or "gb" in lowered or "pb" in lowered:
        return "storage"
    if any(term in lowered for term in ("count", "filings", "articles", "patents", "projects")):
        return "count"
    return ""


def _question_type_from_text(text: str, years: List[int], numeric_count: int, percent_count: int) -> Optional[str]:
    lowered = str(text or "").lower()

    if any(term in lowered for term in _COMPOSITION_TERMS) and max(percent_count, numeric_count) >= 3:
        return "composition"
    if any(term in lowered for term in _COMPARISON_TERMS) and max(2, numeric_count) >= 2:
        return "comparison"
    if len(years) >= 4 and (any(term in lowered for term in _TREND_TERMS) or numeric_count >= 4):
        return "trend"
    if len(years) >= 2 and any(term in lowered for term in _BEFORE_AFTER_TERMS):
        return "before_after"
    if len(years) >= 4:
        return "trend"
    if percent_count >= 3:
        return "composition"
    if numeric_count >= 3 and any(term in lowered for term in ("compare", "comparison", "relative", "density")):
        return "comparison"
    if len(years) >= 2 and numeric_count >= 2:
        return "before_after"
    return None


def _preferred_chart_families(question_type: str) -> List[str]:
    if question_type == "trend":
        return ["line", "area", "bar"]
    if question_type == "comparison":
        return ["horizontal_bar", "bar", "line"]
    if question_type == "composition":
        return ["stacked_bar", "pie", "bar"]
    return ["bar", "line"]


def _data_point_count(
    question_type: str,
    years: List[int],
    numeric_tokens: List[str],
    percent_tokens: List[str],
) -> int:
    if question_type == "trend":
        return len(years)
    if question_type == "composition":
        return max(len(percent_tokens), len(numeric_tokens))
    return len(numeric_tokens)


def _question_text(question_type: str, metric_phrase: str, years: List[int]) -> str:
    if question_type == "trend" and years:
        return f"How has {metric_phrase} changed from {min(years)} to {max(years)}?"
    if question_type == "comparison":
        return f"How does {metric_phrase} compare across the entities supported by the chapter research?"
    if question_type == "composition":
        return f"How is {metric_phrase} distributed across the categories identified in the chapter research?"
    if question_type == "before_after" and len(years) >= 2:
        return f"How did {metric_phrase} change between {years[0]} and {years[-1]}?"
    return f"What graph would best explain {metric_phrase}?"


def _provenance_strength(finding: Dict[str, Any]) -> float:
    quality = float(finding.get("source_quality", 0.0) or 0.0)
    freshness = float(finding.get("freshness_score", 0.0) or 0.0)
    relevance = float(
        finding.get("llm_relevance_score")
        if finding.get("llm_relevance_score") is not None
        else finding.get("relevance_score", 0.0)
    )
    return round((quality * 0.45) + (freshness * 0.2) + (relevance * 0.35), 4)


def _question_rejection_reason(
    *,
    question_type: Optional[str],
    data_point_count: int,
    unit: str,
    provenance_strength: float,
) -> str:
    if not question_type:
        return "No graphable question pattern was detected in the finding."
    if question_type == "trend" and data_point_count < 4:
        return "Trend questions need at least four ordered time points."
    if question_type == "comparison" and data_point_count < 2:
        return "Comparison questions need at least two comparable values."
    if question_type == "composition" and data_point_count < 3:
        return "Composition questions need at least three categories or shares."
    if question_type == "before_after" and data_point_count < 2:
        return "Before/after questions need two comparable periods."
    if not unit and question_type in {"comparison", "composition", "before_after"}:
        return "The metric unit is too unclear to support a trustworthy graph."
    if provenance_strength < 0.42:
        return "The supporting evidence is too weak to justify a graph."
    return ""


def _graphable_reason_summary(question_type: str, data_point_count: int, years: List[int]) -> List[str]:
    reasons: List[str] = []
    if question_type == "trend" and years:
        reasons.append(f"Has {len(years)} ordered time points.")
    elif question_type == "comparison":
        reasons.append(f"Includes {data_point_count} comparable values.")
    elif question_type == "composition":
        reasons.append(f"Includes {data_point_count} share or category datapoints.")
    elif question_type == "before_after" and years:
        reasons.append(f"Compares periods from {years[0]} to {years[-1]}.")
    return reasons


def _candidate_score(candidate: Dict[str, Any]) -> float:
    return round(
        (1.25 if candidate.get("graphable") else 0.0)
        + min(1.2, float(candidate.get("provenance_strength", 0.0)) * 1.5)
        + min(1.0, float(candidate.get("data_point_count", 0)) / 4.0)
        + min(0.6, len(candidate.get("candidate_years", [])) / 6.0),
        4,
    )


def _dedupe_candidates(candidates: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    deduped: List[Dict[str, Any]] = []
    seen = set()
    for candidate in candidates:
        key = (
            str(candidate.get("question_type") or ""),
            " ".join(_tokenize(candidate.get("candidate_metric") or candidate.get("question_text") or ""))[:80],
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped


def evaluate_graphable_question_candidates(
    findings: List[Dict[str, Any]],
    blueprint: Dict[str, Any],
) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    chapter_id = _normalize_text(blueprint.get("chapter_id") or blueprint.get("id"))

    for index, finding in enumerate(findings or [], start=1):
        if not isinstance(finding, dict):
            continue
        if finding.get("approved_for_writing") is False:
            continue
        if str(finding.get("source_type") or finding.get("source") or "").lower() == "web" and not finding.get("source_credible", True):
            continue

        title = _strip_visual_prefix(finding.get("title", ""))
        snippet = _normalize_text(finding.get("snippet", ""))
        combined_text = _normalize_text(f"{title}. {snippet}")
        if not combined_text:
            continue

        source_finding_id = str(finding.get("id") or f"finding_{index}")
        years = _extract_years(combined_text)
        numeric_tokens = _extract_numeric_tokens(combined_text)
        percent_tokens = _extract_percent_tokens(combined_text)
        metric_phrase = _metric_phrase(title, blueprint)
        question_type = _question_type_from_text(
            combined_text,
            years,
            len(numeric_tokens),
            len(percent_tokens),
        )
        data_point_count = _data_point_count(question_type or "", years, numeric_tokens, percent_tokens) if question_type else 0
        unit = _infer_unit(combined_text)
        provenance_strength = _provenance_strength(finding)
        rejected_reason = _question_rejection_reason(
            question_type=question_type,
            data_point_count=data_point_count,
            unit=unit,
            provenance_strength=provenance_strength,
        )
        graphable = not rejected_reason
        question_text = _question_text(question_type or "comparison", metric_phrase, years)

        candidate = {
            "graph_question_id": f"gq_{index}",
            "chapter_id": chapter_id,
            "source_finding_ids": [source_finding_id],
            "question_text": question_text,
            "question_type": question_type or "",
            "target_claim_text": title or metric_phrase,
            "nearby_text_excerpt": snippet[:320],
            "candidate_metric": metric_phrase,
            "candidate_unit": unit,
            "candidate_entities": [],
            "candidate_years": years,
            "data_point_count": data_point_count,
            "provenance_strength": provenance_strength,
            "graphable": graphable,
            "graphable_reasons": _graphable_reason_summary(question_type or "", data_point_count, years),
            "preferred_chart_families": _preferred_chart_families(question_type) if question_type else [],
            "rejected_reason": rejected_reason,
        }
        candidate["_score"] = _candidate_score(candidate)
        candidates.append(candidate)

    deduped = _dedupe_candidates(candidates)
    deduped.sort(
        key=lambda item: (
            bool(item.get("graphable")),
            float(item.get("_score", 0.0)),
            float(item.get("provenance_strength", 0.0)),
            int(item.get("data_point_count", 0)),
        ),
        reverse=True,
    )
    return deduped


def discover_graphable_questions(
    findings: List[Dict[str, Any]],
    blueprint: Dict[str, Any],
    *,
    max_questions: int = 3,
) -> List[Dict[str, Any]]:
    viable = [
        dict(candidate)
        for candidate in evaluate_graphable_question_candidates(findings, blueprint)
        if candidate.get("graphable")
    ]

    for candidate in viable:
        candidate.pop("_score", None)

    return viable[:max(1, max_questions)]
