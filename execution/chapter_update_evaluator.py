from __future__ import annotations

import os
import re
from collections import Counter
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

from gemini_client import generate_content as gemini_generate_content
from llm_json_utils import try_parse_json
from logger_config import setup_logger

load_dotenv()

logger = setup_logger("ChapterUpdateEvaluator")

_COMMON_STOPWORDS = {
    "about",
    "after",
    "against",
    "among",
    "around",
    "because",
    "before",
    "between",
    "business",
    "chapter",
    "companies",
    "company",
    "current",
    "data",
    "during",
    "each",
    "enterprise",
    "from",
    "governance",
    "industry",
    "information",
    "into",
    "market",
    "report",
    "section",
    "their",
    "there",
    "these",
    "through",
    "update",
    "updated",
    "using",
    "were",
    "while",
    "with",
    "within",
    "would",
    "years",
}
_WORD_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9\-]{3,}|[\u0590-\u05FF]{2,}")
_HEADING_PATTERN = re.compile(r"^\s*#{1,6}\s+(.+?)\s*$", re.MULTILINE)
_BULLET_PATTERN = re.compile(r"^\s*[-*]\s+", re.MULTILINE)
_CITATION_PATTERN = re.compile(r"\[(\d+)\]")
_METRIC_PATTERN = re.compile(
    r"(?:[$€£]\s?\d[\d,\.]*\s*(?:million|billion|trillion)?|\b\d+(?:\.\d+)?%|\b\d[\d,\.]*\s*(?:million|billion|trillion|thousand)\b)",
    re.IGNORECASE,
)
_ENTITY_PATTERN = re.compile(r"\b(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+|[A-Z]{2,}(?:\s+[A-Z]{2,})*)\b")
_SOURCE_REINTERPRETATION_PATTERN = re.compile(
    r"(original report'?s statement|requires clarification from previous reports|original report noted the heading|provided snippets|overly optimistic outlier)",
    re.IGNORECASE,
)
_DEFAULT_CHAPTER_JUDGE_MODEL = "gemini-3-flash-preview"


def _issue(severity: str, code: str, message: str, *, context: str = "") -> Dict[str, Any]:
    issue = {
        "severity": severity,
        "code": code,
        "message": message,
    }
    if context:
        issue["context"] = context
    return issue


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _detect_language(text: str) -> str:
    return "Hebrew" if re.search(r"[\u0590-\u05FF]", text or "") else "English"


def _extract_headings(text: str) -> List[str]:
    headings: List[str] = []
    seen = set()
    for heading in _HEADING_PATTERN.findall(text or ""):
        cleaned = re.sub(r"\s+", " ", heading).strip().strip(":").lower()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            headings.append(cleaned)
    return headings


def _split_paragraphs(text: str) -> List[str]:
    return [part.strip() for part in re.split(r"\n\s*\n", text or "") if part.strip()]


def _bullet_ratio(text: str) -> float:
    lines = [line for line in (text or "").splitlines() if line.strip()]
    if not lines:
        return 0.0
    return sum(1 for line in lines if _BULLET_PATTERN.match(line)) / len(lines)


def _extract_years(text: str) -> set[int]:
    return {int(year) for year in re.findall(r"\b(19\d{2}|20\d{2})\b", text or "")}


def _extract_metrics(text: str) -> set[str]:
    return {match.strip().lower() for match in _METRIC_PATTERN.findall(text or "")}


def _extract_entities(text: str, limit: int = 20) -> set[str]:
    entities: List[str] = []
    seen = set()
    for entity in _ENTITY_PATTERN.findall(text or ""):
        cleaned = re.sub(r"\s+", " ", entity).strip()
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        entities.append(cleaned)
        if len(entities) >= limit:
            break
    return {entity.lower() for entity in entities}


def _content_words(text: str, limit: int = 40) -> List[str]:
    counts: Counter[str] = Counter()
    for token in _WORD_PATTERN.findall((text or "").lower()):
        if token in _COMMON_STOPWORDS or len(token) < 4:
            continue
        counts[token] += 1
    return [token for token, _ in counts.most_common(limit)]


def _normalize_reference_value(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def _chapter_judge_model_name() -> str:
    configured = os.getenv("CHAPTER_UPDATE_JUDGE_MODEL", _DEFAULT_CHAPTER_JUDGE_MODEL)
    return str(configured or "").strip() or _DEFAULT_CHAPTER_JUDGE_MODEL


def _context_window(text: str, pattern: re.Pattern[str], radius: int = 180) -> str:
    match = pattern.search(text or "")
    if not match:
        return ""
    start = max(0, match.start() - radius)
    end = min(len(text or ""), match.end() + radius)
    return re.sub(r"\s+", " ", str(text or "")[start:end]).strip()


def _extract_time_window(blueprint: Optional[Dict[str, Any]]) -> tuple[Optional[int], Optional[int]]:
    blueprint = blueprint or {}

    def _extract(value: Any) -> Optional[int]:
        match = re.search(r"\b(19\d{2}|20\d{2})\b", str(value or ""))
        return int(match.group(1)) if match else None

    start_year = _extract(blueprint.get("update_start_date"))
    end_year = _extract(blueprint.get("update_end_date"))
    if start_year and end_year and start_year > end_year:
        start_year, end_year = end_year, start_year
    return start_year, end_year


def _score_ratio(value: float, ideal_min: float, ideal_max: float) -> float:
    if ideal_min <= value <= ideal_max:
        return 1.0
    if value < ideal_min and ideal_min > 0:
        return max(0.0, value / ideal_min)
    if value > ideal_max and value > 0:
        return max(0.0, ideal_max / value)
    return 0.0


def _aggregate_finding_signals(research_findings: List[Dict[str, Any]]) -> Dict[str, set[Any]]:
    finding_terms: set[str] = set()
    finding_entities: set[str] = set()
    finding_years: set[int] = set()
    finding_metrics: set[str] = set()

    for finding in research_findings[:10]:
        blob = " ".join(
            str(finding.get(key, "")).strip()
            for key in ("title", "snippet")
            if str(finding.get(key, "")).strip()
        )
        finding_terms.update(_content_words(blob, limit=16))
        finding_entities.update(_extract_entities(blob))
        finding_years.update(_extract_years(blob))
        finding_metrics.update(_extract_metrics(blob))

    return {
        "terms": finding_terms,
        "entities": finding_entities,
        "years": finding_years,
        "metrics": finding_metrics,
    }


def _matched_reference_ratio(references: List[Dict[str, Any]], research_findings: List[Dict[str, Any]]) -> float:
    relevant_refs = [
        ref
        for ref in references
        if str(ref.get("category", "")).strip().lower() != "original"
    ]
    if not relevant_refs:
        return 0.0

    finding_titles = {_normalize_reference_value(item.get("title")) for item in research_findings}
    finding_urls = {_normalize_reference_value(item.get("url")) for item in research_findings if item.get("url")}

    matches = 0
    for ref in relevant_refs:
        title = _normalize_reference_value(ref.get("title"))
        url = _normalize_reference_value(ref.get("url"))
        if (title and title in finding_titles) or (url and url in finding_urls):
            matches += 1

    return matches / len(relevant_refs)


def _finding_lookup(research_findings: List[Dict[str, Any]]) -> tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    by_title: Dict[str, Dict[str, Any]] = {}
    by_url: Dict[str, Dict[str, Any]] = {}
    for finding in research_findings:
        title = _normalize_reference_value(finding.get("title"))
        url = _normalize_reference_value(finding.get("url"))
        if title and title not in by_title:
            by_title[title] = finding
        if url and url not in by_url:
            by_url[url] = finding
    return by_title, by_url


def _match_finding_for_reference(
    ref: Dict[str, Any],
    finding_titles: Dict[str, Dict[str, Any]],
    finding_urls: Dict[str, Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    title = _normalize_reference_value(ref.get("title"))
    url = _normalize_reference_value(ref.get("url"))
    if url and url in finding_urls:
        return finding_urls[url]
    if title and title in finding_titles:
        return finding_titles[title]
    return None


def _finding_is_directly_relevant(finding: Optional[Dict[str, Any]]) -> bool:
    if not finding:
        return False
    if "approved_for_writing" in finding and not _coerce_bool(finding.get("approved_for_writing")):
        return False
    if _coerce_bool(finding.get("background_only")):
        return False
    if _coerce_bool(finding.get("cross_domain_analogy")):
        return False
    if "directly_on_topic" in finding and not _coerce_bool(finding.get("directly_on_topic")):
        return False
    return True


def _approved_reference_ratio(references: List[Dict[str, Any]], research_findings: List[Dict[str, Any]]) -> float:
    relevant_refs = [
        ref
        for ref in references
        if str(ref.get("category", "")).strip().lower() != "original"
    ]
    if not relevant_refs:
        return 0.0

    finding_titles, finding_urls = _finding_lookup(research_findings)
    approved_count = 0
    for ref in relevant_refs:
        finding = _match_finding_for_reference(ref, finding_titles, finding_urls)
        if _finding_is_directly_relevant(finding):
            approved_count += 1
    return approved_count / len(relevant_refs)


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    return text in {"true", "1", "yes"}


def _coerce_score(value: Any) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, score))


def judge_chapter_update_with_llm(
    *,
    original_text: str,
    generated_text: str,
    research_findings: List[Dict[str, Any]],
    blueprint: Optional[Dict[str, Any]] = None,
    references: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return {"error": "GEMINI_API_KEY not found"}

    blueprint = blueprint or {}
    references = references or []

    findings_lines = []
    for index, finding in enumerate(research_findings[:8], start=1):
        findings_lines.append(
            f"- [{index}] {finding.get('title', 'Untitled')} | {finding.get('published_date', 'Unknown')} | "
            f"{finding.get('url', 'N/A')} | {finding.get('snippet', '')}"
        )
    references_lines = []
    for ref in references:
        references_lines.append(
            f"- [{ref.get('index', '?')}] {ref.get('title', 'Untitled')} | {ref.get('url', 'N/A')} | {ref.get('category', '')}"
        )

    prompt = f"""
You are evaluating whether a rewritten report chapter genuinely updates the original chapter while preserving its style and scope.

Return ONLY valid JSON with these fields:
{{
  "freshness_score": 0.0,
  "style_preservation_score": 0.0,
  "scope_preservation_score": 0.0,
  "evidence_grounding_score": 0.0,
  "contains_meaningful_new_information": true,
  "preserves_original_style": true,
  "preserves_original_scope": true,
  "is_well_grounded_in_findings": true,
  "reasoning_summary": "short paragraph",
  "strengths": ["..."],
  "failures": ["..."]
}}

Evaluation rules:
- "Meaningful new information" means the chapter uses concrete recent facts, developments, dates, organizations, or metrics that were not already present in the original chapter.
- "Preserves original style" means it keeps the original language, broad tone, structural feel, and narrative form. It should not turn prose into a bullet memo unless the source did that.
- "Preserves original scope" means it stays on the same chapter subject rather than drifting into a generic overview.
- "Well grounded" means the important updated claims are supported by the supplied research findings and references.

Blueprint topic: {blueprint.get('topic', '')}
Source chapter title: {blueprint.get('source_chapter_title', '')}
Update window: {blueprint.get('update_start_date', '')} to {blueprint.get('update_end_date', '')}

Original chapter:
---
{original_text}
---

Research findings:
---
{chr(10).join(findings_lines)}
---

Generated chapter:
---
{generated_text}
---

References:
---
{chr(10).join(references_lines)}
---
"""

    response = gemini_generate_content(
        api_key=api_key,
        model=_chapter_judge_model_name(),
        contents=prompt,
        response_mime_type="application/json",
        temperature=0.0,
    )
    parsed = try_parse_json(response.text.strip())
    if not isinstance(parsed, dict):
        raise ValueError("LLM judge did not return a JSON object.")

    normalized = {
        "freshness_score": _coerce_score(parsed.get("freshness_score")),
        "style_preservation_score": _coerce_score(parsed.get("style_preservation_score")),
        "scope_preservation_score": _coerce_score(parsed.get("scope_preservation_score")),
        "evidence_grounding_score": _coerce_score(parsed.get("evidence_grounding_score")),
        "contains_meaningful_new_information": _coerce_bool(parsed.get("contains_meaningful_new_information")),
        "preserves_original_style": _coerce_bool(parsed.get("preserves_original_style")),
        "preserves_original_scope": _coerce_bool(parsed.get("preserves_original_scope")),
        "is_well_grounded_in_findings": _coerce_bool(parsed.get("is_well_grounded_in_findings")),
        "reasoning_summary": str(parsed.get("reasoning_summary", "")).strip(),
        "strengths": [str(item).strip() for item in parsed.get("strengths", []) if str(item).strip()],
        "failures": [str(item).strip() for item in parsed.get("failures", []) if str(item).strip()],
    }
    normalized["passes"] = all(
        (
            normalized["contains_meaningful_new_information"],
            normalized["preserves_original_style"],
            normalized["preserves_original_scope"],
            normalized["is_well_grounded_in_findings"],
        )
    )
    return normalized


def evaluate_chapter_update(
    *,
    original_text: str,
    generated_text: str,
    research_findings: List[Dict[str, Any]],
    blueprint: Optional[Dict[str, Any]] = None,
    references: Optional[List[Dict[str, Any]]] = None,
    use_llm_judge: bool = False,
) -> Dict[str, Any]:
    blueprint = blueprint or {}
    references = references or []
    issues: List[Dict[str, Any]] = []

    normalized_original = _normalize_text(original_text)
    normalized_generated = _normalize_text(generated_text)
    original_language = _detect_language(original_text)
    generated_language = _detect_language(generated_text)

    original_headings = _extract_headings(original_text)
    generated_headings = _extract_headings(generated_text)
    heading_overlap = 1.0
    if original_headings:
        matched_headings = sum(1 for heading in original_headings if heading in generated_headings)
        heading_overlap = matched_headings / len(original_headings)

    original_paragraphs = _split_paragraphs(original_text)
    generated_paragraphs = _split_paragraphs(generated_text)
    paragraph_ratio = (
        len(generated_paragraphs) / max(len(original_paragraphs), 1)
        if original_paragraphs or generated_paragraphs
        else 1.0
    )

    original_bullet_ratio = _bullet_ratio(original_text)
    generated_bullet_ratio = _bullet_ratio(generated_text)
    bullet_style_score = max(0.0, 1.0 - abs(generated_bullet_ratio - original_bullet_ratio) * 2.0)
    length_ratio = len(normalized_generated) / max(len(normalized_original), 1)
    length_score = _score_ratio(length_ratio, 0.55, 1.9)
    copy_similarity = SequenceMatcher(None, normalized_original.lower(), normalized_generated.lower()).ratio()

    original_terms = set(_content_words(original_text, limit=24))
    generated_terms = set(_content_words(generated_text, limit=28))
    topic_terms = set(_content_words(" ".join(str(blueprint.get(key, "")) for key in ("topic", "source_chapter_title", "report_subject")), limit=16))

    original_entities = _extract_entities(original_text)
    generated_entities = _extract_entities(generated_text)
    original_years = _extract_years(original_text)
    generated_years = _extract_years(generated_text)
    original_metrics = _extract_metrics(original_text)
    generated_metrics = _extract_metrics(generated_text)
    finding_signals = _aggregate_finding_signals(research_findings)

    new_finding_terms = sorted((generated_terms & finding_signals["terms"]) - original_terms)
    new_finding_entities = sorted((generated_entities & finding_signals["entities"]) - original_entities)
    new_finding_metrics = sorted((generated_metrics & finding_signals["metrics"]) - original_metrics)

    start_year, end_year = _extract_time_window(blueprint)
    new_update_window_years = sorted(
        year
        for year in (generated_years & finding_signals["years"]) - original_years
        if (start_year is None or year >= start_year) and (end_year is None or year <= end_year)
    )

    fresh_signal_count = (
        min(len(new_finding_terms), 4)
        + min(len(new_finding_entities), 3)
        + min(len(new_finding_metrics), 2)
        + min(len(new_update_window_years), 2)
    )
    freshness_score = min(1.0, fresh_signal_count / 6.0)
    if copy_similarity > 0.9:
        freshness_score *= 0.55
    elif copy_similarity > 0.82:
        freshness_score *= 0.8

    original_scope_terms = original_terms | topic_terms
    scope_overlap = len(generated_terms & original_scope_terms) / max(len(original_scope_terms), 1)
    scope_preservation_score = min(1.0, (scope_overlap * 2.6) + (heading_overlap * 0.35))
    matched_reference_ratio = _matched_reference_ratio(references, research_findings)
    approved_reference_ratio = _approved_reference_ratio(references, research_findings)
    finding_support_score = min(1.0, fresh_signal_count / 5.0)
    evidence_grounding_score = min(
        1.0,
        (matched_reference_ratio * 0.45)
        + (finding_support_score * 0.35)
        + (approved_reference_ratio * 0.20),
    )

    if _SOURCE_REINTERPRETATION_PATTERN.search(generated_text):
        issues.append(
            _issue(
                "error",
                "source_reinterpretation_drift",
                "Generated chapter appears to reinterpret the original report in speculative or meta-report language instead of staying in chapter prose.",
                context=_context_window(generated_text, _SOURCE_REINTERPRETATION_PATTERN),
            )
        )

    finding_titles, finding_urls = _finding_lookup(research_findings)
    off_topic_titles: List[str] = []
    for ref in references:
        if str(ref.get("category", "")).strip().lower() == "original":
            continue
        finding = _match_finding_for_reference(ref, finding_titles, finding_urls)
        if finding and not _finding_is_directly_relevant(finding):
            off_topic_titles.append(str(ref.get("title", "Untitled source")).strip() or "Untitled source")
    if off_topic_titles:
        issues.append(
            _issue(
                "error",
                "off_topic_citation",
                "Generated chapter cites research findings that were flagged as off-topic, background-only, or cross-domain analogies.",
                context=", ".join(off_topic_titles[:3]),
            )
        )

    language_score = 1.0 if original_language == generated_language else 0.0
    style_preservation_score = min(
        1.0,
        (language_score * 0.35)
        + (heading_overlap * 0.25)
        + (bullet_style_score * 0.15)
        + (length_score * 0.15)
        + (max(0.0, 1.0 - abs(paragraph_ratio - 1.0)) * 0.10),
    )

    if original_language != generated_language:
        issues.append(
            _issue(
                "error",
                "style_language_mismatch",
                f"Generated chapter language ({generated_language}) does not match the original ({original_language}).",
            )
        )

    if heading_overlap < 0.5 and original_headings:
        issues.append(
            _issue(
                "warning",
                "style_structure_drift",
                "Generated chapter no longer preserves enough of the original heading structure.",
                context=", ".join(original_headings),
            )
        )

    if freshness_score < 0.45:
        issues.append(
            _issue(
                "error",
                "insufficient_new_information",
                "Generated chapter does not appear to add enough concrete new information from the research findings.",
            )
        )

    if copy_similarity > 0.9:
        issues.append(
            _issue(
                "warning",
                "too_similar_to_original",
                "Generated chapter appears very close to the original chapter and may not be sufficiently refreshed.",
            )
        )

    if scope_preservation_score < 0.45:
        issues.append(
            _issue(
                "error",
                "scope_drift",
                "Generated chapter appears to drift away from the original chapter subject or source title.",
            )
        )

    if evidence_grounding_score < 0.45:
        issues.append(
            _issue(
                "error",
                "weak_research_grounding",
                "Generated chapter is weakly grounded in the supplied research findings or references.",
            )
        )

    freshness_pass = freshness_score >= 0.45 and any(
        (
            new_update_window_years,
            new_finding_metrics,
            len(new_finding_terms) >= 3,
            len(new_finding_entities) >= 2,
        )
    )
    style_preservation_pass = original_language == generated_language and style_preservation_score >= 0.6
    scope_preservation_pass = scope_preservation_score >= 0.45
    grounding_pass = evidence_grounding_score >= 0.45

    llm_judge: Optional[Dict[str, Any]] = None
    if use_llm_judge:
        try:
            llm_judge = judge_chapter_update_with_llm(
                original_text=original_text,
                generated_text=generated_text,
                research_findings=research_findings,
                blueprint=blueprint,
                references=references,
            )
            if llm_judge.get("error"):
                issues.append(
                    _issue(
                        "warning",
                        "llm_judge_unavailable",
                        str(llm_judge["error"]),
                    )
                )
            elif not llm_judge.get("passes", False):
                issues.append(
                    _issue(
                        "error",
                        "llm_judge_failed",
                        "LLM judge concluded that the chapter update does not sufficiently preserve style, scope, freshness, or grounding.",
                        context=llm_judge.get("reasoning_summary", ""),
                    )
                )
        except Exception as exc:
            logger.warning("LLM chapter update judge failed: %s", exc)
            llm_judge = {"error": str(exc)}
            issues.append(
                _issue(
                    "warning",
                    "llm_judge_unavailable",
                    f"LLM judge could not evaluate the chapter update: {exc}",
                )
            )

    error_count = sum(1 for issue in issues if issue["severity"] == "error")
    warning_count = sum(1 for issue in issues if issue["severity"] == "warning")

    summary = {
        "blocking": error_count > 0,
        "passes": error_count == 0,
        "freshness_pass": freshness_pass,
        "style_preservation_pass": style_preservation_pass,
        "scope_preservation_pass": scope_preservation_pass,
        "grounding_pass": grounding_pass,
        "error_count": error_count,
        "warning_count": warning_count,
    }
    if llm_judge and not llm_judge.get("error"):
        summary["llm_judge_pass"] = bool(llm_judge.get("passes"))

    return {
        "summary": summary,
        "scores": {
            "freshness_score": round(freshness_score, 3),
            "style_preservation_score": round(style_preservation_score, 3),
            "scope_preservation_score": round(scope_preservation_score, 3),
            "evidence_grounding_score": round(evidence_grounding_score, 3),
            "copy_similarity": round(copy_similarity, 3),
            "heading_overlap": round(heading_overlap, 3),
            "matched_reference_ratio": round(matched_reference_ratio, 3),
            "approved_reference_ratio": round(approved_reference_ratio, 3),
        },
        "signals": {
            "new_update_window_years": new_update_window_years,
            "new_finding_terms": new_finding_terms[:10],
            "new_finding_entities": new_finding_entities[:10],
            "new_finding_metrics": sorted(new_finding_metrics)[:10],
            "original_headings": original_headings,
            "generated_headings": generated_headings,
        },
        "issues": issues,
        "llm_judge": llm_judge,
    }
