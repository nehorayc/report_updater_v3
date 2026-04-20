from __future__ import annotations

import copy
import re
from typing import Any, Dict, Iterable, List, Optional

from graph_update_helpers import (
    canonicalize_chart_data_points,
    extract_years_from_labels,
    graph_has_plottable_data,
    graph_update_validation_issues,
    normalize_chart_series,
)
from logger_config import setup_logger


logger = setup_logger("GraphRanking")

_TOKEN_PATTERN = re.compile(r"[a-z0-9]{3,}")
_STOPWORDS = {
    "about",
    "across",
    "after",
    "against",
    "among",
    "annual",
    "and",
    "are",
    "between",
    "chart",
    "comparison",
    "data",
    "figure",
    "for",
    "from",
    "graph",
    "growth",
    "has",
    "have",
    "how",
    "into",
    "its",
    "new",
    "over",
    "report",
    "section",
    "shows",
    "showing",
    "than",
    "that",
    "the",
    "their",
    "this",
    "through",
    "update",
    "updated",
    "with",
    "year",
    "years",
}
_SHORTLIST_SIZE = 3
_AUTO_SELECT_THRESHOLD = 0.84
_REVIEW_THRESHOLD = 0.68
_SCORE_WEIGHTS = {
    "text_relevance": 0.25,
    "analytical_help": 0.20,
    "readability": 0.20,
    "data_faithfulness": 0.15,
    "evidence_strength": 0.10,
    "distinctiveness": 0.05,
    "production_robustness": 0.05,
}


def _clamp_score(value: float) -> float:
    return max(0.0, min(1.0, round(value, 4)))


def _normalize_marker_token(value: Any) -> str:
    token = str(value or "").strip().lower()
    if not token:
        return ""
    return re.sub(r"[^a-z0-9_-]", "", token)


def _canonical_slot_id(visual: Dict[str, Any]) -> str:
    for key in ("marker_id", "original_asset_id", "id"):
        token = _normalize_marker_token(visual.get(key))
        if token:
            return token
    fallback_title = re.sub(r"[^a-z0-9]+", "-", str(visual.get("title") or "graph").lower()).strip("-")
    return fallback_title or "graph-slot"


def _tokenize(text: str) -> set[str]:
    return {
        token
        for token in _TOKEN_PATTERN.findall(str(text or "").lower())
        if token not in _STOPWORDS
    }


def _extract_local_context(draft_text: str, marker_id: str) -> str:
    text = str(draft_text or "")
    if not text:
        return ""

    normalized_marker = _normalize_marker_token(marker_id)
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    for index, paragraph in enumerate(paragraphs):
        if normalized_marker and normalized_marker in _normalize_marker_token(paragraph):
            context_parts = []
            if index > 0:
                context_parts.append(paragraphs[index - 1])
            context_parts.append(paragraph)
            if index + 1 < len(paragraphs):
                context_parts.append(paragraphs[index + 1])
            return "\n\n".join(context_parts)

    if normalized_marker:
        raw_index = text.lower().find(normalized_marker[:8])
        if raw_index >= 0:
            start = max(0, raw_index - 320)
            end = min(len(text), raw_index + 320)
            return text[start:end].strip()

    return text[:640].strip()


def _question_token_overlap(visual_text: str, question: Dict[str, Any]) -> float:
    visual_tokens = _tokenize(visual_text)
    question_tokens = _tokenize(
        " ".join(
            part
            for part in (
                question.get("question_text"),
                question.get("candidate_metric"),
                question.get("target_claim_text"),
                question.get("nearby_text_excerpt"),
            )
            if part
        )
    )
    if not visual_tokens or not question_tokens:
        return 0.0
    return len(visual_tokens & question_tokens) / max(3, min(len(question_tokens), 8))


def _question_chart_preference(question: Dict[str, Any], labels: List[str]) -> str:
    families = [
        str(family).strip().lower()
        for family in question.get("preferred_chart_families", []) or []
        if str(family).strip()
    ]
    for family in families:
        if family in {"bar", "line", "pie"}:
            return family
    question_type = str(question.get("question_type") or "").strip().lower()
    if question_type == "trend":
        return "line"
    if question_type == "composition":
        return "pie" if 2 <= len(labels) <= 5 else "bar"
    return "bar"


def _match_visual_to_graph_question(visual: Dict[str, Any], graphable_questions: List[Dict[str, Any]]) -> tuple[Optional[Dict[str, Any]], float]:
    if not graphable_questions:
        return None, 0.0

    explicit_question_id = str(visual.get("graph_question_id") or "").strip()
    normalized = normalize_chart_series((visual or {}).get("data_points"))
    labels = normalized[0] if normalized else []
    visual_text = " ".join(
        part
        for part in (
            visual.get("title"),
            visual.get("description"),
            " ".join(str(label) for label in labels),
        )
        if part
    )

    best_question: Optional[Dict[str, Any]] = None
    best_score = 0.0
    for question in graphable_questions:
        if not isinstance(question, dict):
            continue
        if explicit_question_id and explicit_question_id == str(question.get("graph_question_id") or "").strip():
            return question, 1.0

        score = _question_token_overlap(visual_text, question)
        question_type = str(question.get("question_type") or "").strip().lower()
        if question_type == "trend" and _looks_like_year_series(labels):
            score += 0.18
        elif question_type in {"comparison", "composition"} and labels and not _looks_like_year_series(labels):
            score += 0.12
        if visual.get("original_asset_id"):
            score += 0.05

        if score > best_score:
            best_question = question
            best_score = score

    if best_score < 0.16:
        return None, round(best_score, 4)
    return best_question, round(best_score, 4)


def build_graph_brief(
    visual: Dict[str, Any],
    *,
    chapter_title: str = "",
    draft_text: str = "",
    chapter_role: str = "",
    graphable_questions: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    slot_id = _canonical_slot_id(visual)
    local_context = _extract_local_context(draft_text, slot_id)
    normalized = normalize_chart_series((visual or {}).get("data_points"))
    labels = normalized[0] if normalized else []
    matched_question, question_match_score = _match_visual_to_graph_question(visual, graphable_questions or [])
    return {
        "slot_id": slot_id,
        "title": str(visual.get("title") or visual.get("description") or "Graph").strip(),
        "description": str(visual.get("description") or "").strip(),
        "chapter_title": str(chapter_title or "").strip(),
        "chapter_role": str(chapter_role or "").strip(),
        "local_context": local_context,
        "labels": labels,
        "years": extract_years_from_labels(labels),
        "graph_question_id": str((matched_question or {}).get("graph_question_id") or "").strip(),
        "target_question_text": str((matched_question or {}).get("question_text") or "").strip(),
        "question_type": str((matched_question or {}).get("question_type") or "").strip(),
        "preferred_chart_families": list((matched_question or {}).get("preferred_chart_families") or []),
        "question_match_score": question_match_score,
        "graph_question_required": bool(graphable_questions) and not visual.get("original_asset_id"),
    }


def _looks_like_year_series(labels: List[str]) -> bool:
    years = extract_years_from_labels(labels)
    return bool(labels) and len(years) >= max(2, len(labels) - 1)


def _flatten_values(values_by_series: Dict[str, List[int | float]]) -> List[float]:
    return [float(value) for series_values in values_by_series.values() for value in series_values]


def _positive_ratio(values: Iterable[float]) -> float:
    positives = sorted(value for value in values if value > 0)
    if len(positives) < 2:
        return 1.0
    smallest = positives[0]
    if smallest <= 0:
        return 1.0
    return round(positives[-1] / smallest, 4)


def _normalize_chart_type(
    visual: Dict[str, Any],
    labels: List[str],
    multi_series: bool,
    *,
    question_type: str = "",
    preferred_chart_families: Optional[List[str]] = None,
) -> str:
    chart_type = str(visual.get("chart_type") or "").strip().lower()
    if chart_type in {"bar", "line", "pie"}:
        return chart_type
    families = [
        str(family).strip().lower()
        for family in preferred_chart_families or []
        if str(family).strip()
    ]
    for family in families:
        if family in {"bar", "line", "pie"}:
            return family
    if question_type == "trend":
        return "line"
    if question_type == "composition":
        return "pie" if 2 <= len(labels) <= 5 else "bar"
    if _looks_like_year_series(labels):
        return "line"
    if not multi_series and 2 <= len(labels) <= 5:
        return "bar"
    return "bar"


def _supports_pie(labels: List[str], flattened_values: List[float], multi_series: bool) -> bool:
    return (
        not multi_series
        and 2 <= len(labels) <= 5
        and flattened_values
        and all(value >= 0 for value in flattened_values)
        and any(value > 0 for value in flattened_values)
    )


def _variant_specs(
    visual: Dict[str, Any],
    *,
    question_type: str = "",
    preferred_chart_families: Optional[List[str]] = None,
) -> List[tuple[str, str]]:
    normalized = normalize_chart_series((visual or {}).get("data_points"))
    if not normalized:
        chart_type = str(visual.get("chart_type") or "bar").strip().lower() or "bar"
        return [(chart_type if chart_type in {"bar", "line", "pie"} else "bar", "linear")]

    labels, values_by_series, _, multi_series = normalized
    flattened_values = _flatten_values(values_by_series)
    base_chart_type = _normalize_chart_type(
        visual,
        labels,
        multi_series,
        question_type=question_type,
        preferred_chart_families=preferred_chart_families,
    )
    preferred_chart_type = _question_chart_preference(
        {
            "question_type": question_type,
            "preferred_chart_families": preferred_chart_families or [],
        },
        labels,
    )
    if not preferred_chart_type:
        preferred_chart_type = "line" if _looks_like_year_series(labels) else "bar"
    use_log_variant = (
        base_chart_type in {"bar", "line"} or preferred_chart_type in {"bar", "line"}
    ) and all(value > 0 for value in flattened_values) and _positive_ratio(flattened_values) >= 100

    specs: List[tuple[str, str]] = [(base_chart_type, "linear")]
    if preferred_chart_type != base_chart_type:
        specs.append((preferred_chart_type, "linear"))
    if _supports_pie(labels, flattened_values, multi_series):
        specs.append(("pie", "linear"))
    if use_log_variant:
        specs.append((preferred_chart_type, "log"))
        if base_chart_type in {"bar", "line"} and base_chart_type != preferred_chart_type:
            specs.append((base_chart_type, "log"))

    deduped: List[tuple[str, str]] = []
    seen = set()
    for spec in specs:
        if spec in seen:
            continue
        seen.add(spec)
        deduped.append(spec)
    return deduped


def _variant_label(chart_type: str, y_axis_scale: str) -> str:
    chart_label = {
        "bar": "Bar chart",
        "line": "Line chart",
        "pie": "Pie chart",
    }.get(chart_type, chart_type.title())
    if y_axis_scale == "log":
        return f"{chart_label} (log scale)"
    return chart_label


def _build_candidate(visual: Dict[str, Any], *, slot_id: str, chart_type: str, y_axis_scale: str) -> Dict[str, Any]:
    candidate = copy.deepcopy(visual)
    base_identifier = _normalize_marker_token(candidate.get("id")) or slot_id
    candidate["slot_id"] = slot_id
    candidate["marker_id"] = slot_id
    candidate["chart_type"] = chart_type
    candidate["id"] = f"{base_identifier}__{chart_type}_{y_axis_scale}"
    candidate["variant_key"] = f"{chart_type}_{y_axis_scale}"
    candidate["variant_label"] = _variant_label(chart_type, y_axis_scale)
    if y_axis_scale == "log":
        candidate["y_axis_scale"] = "log"
    else:
        candidate.pop("y_axis_scale", None)

    canonical_data_points = canonicalize_chart_data_points(candidate.get("data_points"))
    if canonical_data_points:
        candidate["data_points"] = canonical_data_points
    return candidate


def _score_text_relevance(candidate: Dict[str, Any], brief: Dict[str, Any], chart_type: str) -> float:
    candidate_text = " ".join(
        part
        for part in (
            candidate.get("title"),
            candidate.get("description"),
            candidate.get("variant_label"),
        )
        if part
    )
    context_text = " ".join(
        part
        for part in (
            brief.get("chapter_title"),
            brief.get("chapter_role"),
            brief.get("local_context"),
            brief.get("target_question_text"),
        )
        if part
    )
    candidate_tokens = _tokenize(candidate_text)
    context_tokens = _tokenize(context_text)
    overlap = len(candidate_tokens & context_tokens)
    denominator = max(4, min(len(candidate_tokens) or 1, 8))
    score = 0.45 + min(0.35, overlap / denominator)

    lowered_context = context_text.lower()
    question_type = str(brief.get("question_type") or "").strip().lower()
    if chart_type == "line" and (
        question_type == "trend"
        or any(token in lowered_context for token in ("trend", "trajectory", "over time", "annual", "growth"))
    ):
        score += 0.12
    if chart_type == "bar" and (
        question_type in {"comparison", "before_after"}
        or any(token in lowered_context for token in ("compare", "comparison", "versus", " vs ", "relative", "density"))
    ):
        score += 0.12
    if chart_type == "pie" and (
        question_type == "composition"
        or any(token in lowered_context for token in ("share", "mix", "composition", "portion"))
    ):
        score += 0.12
    if question_type and not brief.get("graph_question_id"):
        score -= 0.15
    if brief.get("graph_question_id"):
        score += min(0.12, float(brief.get("question_match_score", 0.0)) * 0.2)

    return _clamp_score(score)


def _score_analytical_help(
    *,
    chart_type: str,
    y_axis_scale: str,
    labels: List[str],
    multi_series: bool,
    ratio: float,
    question_type: str = "",
) -> float:
    score = 0.5
    if question_type == "trend" and chart_type == "line":
        score += 0.3
    elif question_type == "comparison" and chart_type == "bar":
        score += 0.24
    elif question_type == "composition" and chart_type == "pie":
        score += 0.18
    elif _looks_like_year_series(labels) and chart_type == "line":
        score += 0.28
    elif not _looks_like_year_series(labels) and chart_type == "bar":
        score += 0.2
    elif chart_type == "pie":
        score += 0.05

    if multi_series and chart_type in {"bar", "line"}:
        score += 0.08

    if ratio >= 100 and y_axis_scale == "log":
        score += 0.22
    elif ratio >= 100 and chart_type in {"bar", "line"}:
        score -= 0.2

    if len(labels) <= 1:
        score -= 0.35

    return _clamp_score(score)


def _score_readability(
    *,
    chart_type: str,
    y_axis_scale: str,
    labels: List[str],
    flattened_values: List[float],
    multi_series: bool,
    ratio: float,
) -> float:
    score = 0.72
    long_label_count = sum(1 for label in labels if len(str(label)) > 18)

    if chart_type == "pie":
        if multi_series or len(labels) > 6:
            score -= 0.5
        if any(value < 0 for value in flattened_values):
            score -= 0.6
    if chart_type == "bar" and len(labels) > 8:
        score -= 0.1
    if chart_type == "line" and len(labels) > 12:
        score -= 0.08
    if long_label_count:
        score -= min(0.18, long_label_count * 0.03)

    if ratio >= 100 and chart_type in {"bar", "line"} and y_axis_scale != "log":
        score -= 0.42
    if ratio >= 100 and y_axis_scale == "log":
        score += 0.18

    return _clamp_score(score)


def _score_data_faithfulness(validation_issues: List[Dict[str, str]], candidate: Dict[str, Any]) -> float:
    score = 0.95
    if validation_issues:
        score -= min(0.75, 0.25 * len(validation_issues))
    if candidate.get("extracted_data_points"):
        score += 0.03
    return _clamp_score(score)


def _score_evidence_strength(candidate: Dict[str, Any]) -> float:
    score = 0.58
    if candidate.get("original_asset_id"):
        score += 0.2
    if candidate.get("extracted_data_points"):
        score += 0.15
    if candidate.get("source_asset_id"):
        score += 0.05
    return _clamp_score(score)


def _score_distinctiveness(candidate: Dict[str, Any], base_chart_type: str, base_scale: str) -> float:
    score = 0.72
    if candidate.get("chart_type") != base_chart_type:
        score += 0.14
    if str(candidate.get("y_axis_scale") or "linear") != base_scale:
        score += 0.14
    return _clamp_score(score)


def _score_production_robustness(
    *,
    chart_type: str,
    labels: List[str],
    flattened_values: List[float],
    multi_series: bool,
) -> float:
    score = 0.92
    if not labels or not flattened_values:
        score -= 0.85
    if chart_type not in {"bar", "line", "pie"}:
        score -= 0.5
    if chart_type == "pie" and (multi_series or any(value < 0 for value in flattened_values)):
        score -= 0.5
    return _clamp_score(score)


def _quality_band(overall_score: float, blocked: bool) -> str:
    if blocked:
        return "Blocked"
    if overall_score >= 0.82:
        return "Strong"
    if overall_score >= 0.68:
        return "Medium"
    return "Weak"


def _decision_reasons(
    *,
    candidate: Dict[str, Any],
    brief: Dict[str, Any],
    ratio: float,
    validation_issues: List[Dict[str, str]],
    blocked_reasons: List[str],
    chart_type: str,
    y_axis_scale: str,
    labels: List[str],
) -> List[str]:
    reasons: List[str] = []
    if blocked_reasons:
        return blocked_reasons
    if validation_issues:
        reasons.append(validation_issues[0]["message"])
    if brief.get("target_question_text"):
        reasons.append(f"Matches vetted question: {brief['target_question_text']}")
    if _looks_like_year_series(labels) and chart_type == "line":
        reasons.append("Matches a time-series trend.")
    if ratio >= 100 and y_axis_scale == "log":
        reasons.append("Uses log scale so smaller values stay visible.")
    elif ratio >= 100 and chart_type in {"bar", "line"}:
        reasons.append("Linear scale compresses smaller values.")
    if candidate.get("original_asset_id"):
        reasons.append("Preserves the original figure slot and update metadata.")
    if brief.get("local_context"):
        reasons.append("Scored against the nearby chapter text instead of only the title.")
    return reasons[:4]


def _score_candidate(candidate: Dict[str, Any], brief: Dict[str, Any], *, base_chart_type: str, base_scale: str) -> Dict[str, Any]:
    normalized = normalize_chart_series(candidate.get("data_points"))
    blocked_reasons: List[str] = []

    if not normalized or not graph_has_plottable_data(candidate.get("data_points")):
        blocked_reasons.append("No plottable data points were found for this graph.")
        normalized = None

    if normalized:
        labels, values_by_series, _, multi_series = normalized
        flattened_values = _flatten_values(values_by_series)
    else:
        labels, values_by_series, multi_series, flattened_values = [], {}, False, []

    chart_type = str(candidate.get("chart_type") or "bar").strip().lower() or "bar"
    y_axis_scale = str(candidate.get("y_axis_scale") or "linear").strip().lower() or "linear"
    ratio = _positive_ratio(flattened_values)

    validation_issues = [
        issue
        for issue in graph_update_validation_issues(
            candidate,
            update_end_year=candidate.get("update_end_date"),
            extracted_data_points=candidate.get("extracted_data_points"),
        )
        if issue.get("code") != "graph_missing_chart_type"
    ]
    blocked_reasons.extend(issue["message"] for issue in validation_issues)

    if brief.get("graph_question_required") and not brief.get("graph_question_id"):
        blocked_reasons.append("This graph does not match any vetted graphable question for the chapter.")

    if chart_type == "pie" and normalized and multi_series:
        blocked_reasons.append("Pie charts cannot represent multiple series cleanly.")
    if chart_type == "pie" and any(value < 0 for value in flattened_values):
        blocked_reasons.append("Pie charts cannot be rendered with negative values.")
    if y_axis_scale == "log" and any(value <= 0 for value in flattened_values):
        blocked_reasons.append("Log scale requires all plotted values to be positive.")

    blocked = bool(blocked_reasons)

    text_relevance = _score_text_relevance(candidate, brief, chart_type)
    analytical_help = _score_analytical_help(
        chart_type=chart_type,
        y_axis_scale=y_axis_scale,
        labels=labels,
        multi_series=multi_series,
        ratio=ratio,
        question_type=str(brief.get("question_type") or "").strip().lower(),
    )
    readability = _score_readability(
        chart_type=chart_type,
        y_axis_scale=y_axis_scale,
        labels=labels,
        flattened_values=flattened_values,
        multi_series=multi_series,
        ratio=ratio,
    )
    data_faithfulness = _score_data_faithfulness(validation_issues, candidate)
    evidence_strength = _score_evidence_strength(candidate)
    distinctiveness = _score_distinctiveness(candidate, base_chart_type, base_scale)
    production_robustness = _score_production_robustness(
        chart_type=chart_type,
        labels=labels,
        flattened_values=flattened_values,
        multi_series=multi_series,
    )

    overall_score = sum(
        _SCORE_WEIGHTS[name] * value
        for name, value in (
            ("text_relevance", text_relevance),
            ("analytical_help", analytical_help),
            ("readability", readability),
            ("data_faithfulness", data_faithfulness),
            ("evidence_strength", evidence_strength),
            ("distinctiveness", distinctiveness),
            ("production_robustness", production_robustness),
        )
    )
    if blocked:
        overall_score = min(overall_score, 0.24)

    overall_score = _clamp_score(overall_score)
    quality_band = _quality_band(overall_score, blocked)
    reasons = _decision_reasons(
        candidate=candidate,
        brief=brief,
        ratio=ratio,
        validation_issues=validation_issues,
        blocked_reasons=blocked_reasons,
        chart_type=chart_type,
        y_axis_scale=y_axis_scale,
        labels=labels,
    )

    scorecard = {
        "text_relevance": text_relevance,
        "analytical_help": analytical_help,
        "readability": readability,
        "data_faithfulness": data_faithfulness,
        "evidence_strength": evidence_strength,
        "distinctiveness": distinctiveness,
        "production_robustness": production_robustness,
        "overall_score": overall_score,
        "quality_band": quality_band,
    }
    candidate["scorecard"] = scorecard
    candidate["quality_band"] = quality_band
    candidate["blocked"] = blocked
    candidate["blocked_reasons"] = blocked_reasons
    candidate["ranking_reasons"] = reasons
    return candidate


def build_ranked_graph_candidate_group(
    visual: Dict[str, Any],
    *,
    chapter_title: str = "",
    draft_text: str = "",
    chapter_role: str = "",
    graphable_questions: Optional[List[Dict[str, Any]]] = None,
    shortlist_size: int = _SHORTLIST_SIZE,
) -> Optional[Dict[str, Any]]:
    if str((visual or {}).get("type", "")).strip().lower() != "graph":
        return None

    brief = build_graph_brief(
        visual,
        chapter_title=chapter_title,
        draft_text=draft_text,
        chapter_role=chapter_role,
        graphable_questions=graphable_questions,
    )
    slot_id = brief["slot_id"]
    normalized = normalize_chart_series((visual or {}).get("data_points"))
    labels = normalized[0] if normalized else []
    multi_series = normalized[3] if normalized else False
    base_chart_type = _normalize_chart_type(
        visual,
        labels,
        multi_series,
        question_type=str(brief.get("question_type") or "").strip().lower(),
        preferred_chart_families=brief.get("preferred_chart_families"),
    )
    base_scale = str(visual.get("y_axis_scale") or "linear").strip().lower() or "linear"

    candidates = [
        _build_candidate(visual, slot_id=slot_id, chart_type=chart_type, y_axis_scale=y_axis_scale)
        for chart_type, y_axis_scale in _variant_specs(
            visual,
            question_type=str(brief.get("question_type") or "").strip().lower(),
            preferred_chart_families=brief.get("preferred_chart_families"),
        )
    ]

    ranked_candidates = [
        _score_candidate(candidate, brief, base_chart_type=base_chart_type, base_scale=base_scale)
        for candidate in candidates
    ]
    ranked_candidates.sort(
        key=lambda item: (
            item.get("blocked", False),
            -(item.get("scorecard") or {}).get("overall_score", 0.0),
            item.get("variant_label", ""),
        )
    )

    for index, candidate in enumerate(ranked_candidates, start=1):
        candidate["rank"] = index

    shortlist = [
        candidate
        for candidate in ranked_candidates
        if not candidate.get("blocked")
    ][:max(1, shortlist_size)]
    if not shortlist:
        shortlist = ranked_candidates[:1]

    recommended = shortlist[0] if shortlist else ranked_candidates[0]
    top_score = (recommended.get("scorecard") or {}).get("overall_score", 0.0)

    if recommended.get("blocked"):
        selection_mode = "skip"
        auto_select_candidate_id = ""
    elif top_score >= _AUTO_SELECT_THRESHOLD:
        selection_mode = "auto"
        auto_select_candidate_id = recommended["id"]
    elif top_score >= _REVIEW_THRESHOLD:
        selection_mode = "manual"
        auto_select_candidate_id = recommended["id"]
    else:
        selection_mode = "review"
        auto_select_candidate_id = ""

    return {
        "slot_id": slot_id,
        "marker_id": slot_id,
        "type": "graph",
        "title": brief["title"],
        "description": brief["description"],
        "graph_question_id": brief.get("graph_question_id", ""),
        "target_question_text": brief.get("target_question_text", ""),
        "question_type": brief.get("question_type", ""),
        "brief": brief,
        "selection_mode": selection_mode,
        "recommended_candidate_id": recommended["id"] if recommended else "",
        "auto_select_candidate_id": auto_select_candidate_id,
        "top_score": top_score,
        "quality_band": recommended.get("quality_band", "Blocked") if recommended else "Blocked",
        "candidates": ranked_candidates,
        "shortlist": shortlist,
    }


def build_ranked_graph_candidate_groups(
    visuals: List[Dict[str, Any]],
    *,
    chapter_title: str = "",
    draft_text: str = "",
    chapter_role: str = "",
    graphable_questions: Optional[List[Dict[str, Any]]] = None,
    shortlist_size: int = _SHORTLIST_SIZE,
) -> List[Dict[str, Any]]:
    groups: List[Dict[str, Any]] = []
    for visual in visuals or []:
        group = build_ranked_graph_candidate_group(
            visual,
            chapter_title=chapter_title,
            draft_text=draft_text,
            chapter_role=chapter_role,
            graphable_questions=graphable_questions,
            shortlist_size=shortlist_size,
        )
        if group:
            groups.append(group)

    groups.sort(
        key=lambda item: (
            -float(item.get("top_score", 0.0)),
            str(item.get("title") or ""),
        )
    )
    logger.info("Prepared %s ranked graph candidate group(s).", len(groups))
    return groups
