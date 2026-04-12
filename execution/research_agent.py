from collections import Counter
from duckduckgo_search import DDGS
import os
import re
import requests
import time
from copy import deepcopy
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from logger_config import setup_logger
from llm_json_utils import try_parse_json
from gemini_client import generate_content as gemini_generate_content

logger = setup_logger("ResearchAgent")

_FETCH_TIMEOUT = 5
_ARTICLE_MAX_CHARS = 2500
_DDG_DELAY = 1.2
_TRANSLATION_CACHE: Dict[str, str] = {}
_REFERENCE_TEXT_CACHE: Dict[Tuple[str, float], str] = {}
_ARTICLE_TEXT_CACHE: Dict[str, str] = {}
_WEB_SEARCH_CACHE: Dict[Tuple[str, int, Optional[int], Optional[int]], List[Dict[str, Any]]] = {}
_ACADEMIC_SEARCH_CACHE: Dict[Tuple[str, int, Optional[int], Optional[int]], List[Dict[str, Any]]] = {}
_RESEARCH_RESULT_CACHE: Dict[Tuple[Any, ...], List[Dict[str, Any]]] = {}
_GENERIC_TOPICS = {"introduction", "conclusion", "summary", "abstract", "foreword", "appendix"}
_RUNTIME_DIAGNOSTICS: List[Dict[str, str]] = []
_TRANSLATION_BATCH_MAX_ITEMS = 12
_GENERIC_WEB_PATH_TERMS = {
    "topic", "topics", "tag", "tags", "category", "categories", "archive", "archives",
    "all-posts", "latest-news", "top-stories", "news", "posts",
}
_GENERIC_WEB_TITLE_PATTERN = re.compile(
    r"^(?:news archives|all posts|latest news archives|top stories archives|thema:\s*news|news|latest news)(?:\b|[\s\-:|])",
    re.IGNORECASE,
)
_TOPIC_WORD_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9\-]{2,}|[\u0590-\u05FF]{2,}")
_TOPIC_STOPWORDS = {
    "about",
    "analysis",
    "and",
    "background",
    "chapter",
    "current",
    "data",
    "digital",
    "field",
    "for",
    "from",
    "future",
    "impact",
    "industry",
    "information",
    "introduction",
    "market",
    "model",
    "overview",
    "policy",
    "report",
    "review",
    "risk",
    "risks",
    "section",
    "study",
    "technology",
    "technologies",
    "trend",
    "trends",
    "update",
    "with",
}
_DEFAULT_RESEARCH_RANKER_MODEL = "gemini-2.5-flash"


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
    normalized = re.sub(r"\s+", " ", str(message or "")).strip()
    if not normalized:
        return
    diagnostic = {"level": level, "message": normalized}
    if diagnostic not in _RUNTIME_DIAGNOSTICS:
        _RUNTIME_DIAGNOSTICS.append(diagnostic)


def _is_hebrew(text: str) -> bool:
    return bool(re.search(r'[\u0590-\u05FF]', text or ""))


def _clone_findings(findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return deepcopy(findings)


def _translate_to_english(text: str) -> str:
    if not text or not _is_hebrew(text):
        return text
    if text in _TRANSLATION_CACHE:
        return _TRANSLATION_CACHE[text]
    try:
        from dotenv import load_dotenv
        load_dotenv()
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            return text
        response = gemini_generate_content(
            api_key=api_key,
            model='gemini-2.0-flash',
            contents=f"Translate the following text to English. Return ONLY the translation, no explanations:\n\n{text}",
        )
        translated = response.text.strip()
        _TRANSLATION_CACHE[text] = translated
        logger.info(f"Translated '{text[:40]}...' -> '{translated[:40]}...'")
        return translated
    except Exception as e:
        logger.warning(f"Translation failed for '{text[:40]}': {e}")
        if _is_quota_error(e):
            _record_runtime_diagnostic(
                "warning",
                "Gemini quota was exhausted while translating research terms. The app continued with the original wording, so search coverage may be weaker until the quota resets.",
            )
        return text


def _chunk_items(items: List[str], chunk_size: int) -> List[List[str]]:
    if chunk_size <= 0:
        return [items]
    return [items[index:index + chunk_size] for index in range(0, len(items), chunk_size)]


def _extract_translation_map(parsed: Any) -> Dict[str, str]:
    if isinstance(parsed, dict):
        items = parsed.get("translations")
        if isinstance(items, list):
            parsed = items
    if not isinstance(parsed, list):
        return {}

    translated: Dict[str, str] = {}
    for item in parsed:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source", "")).strip()
        translation = str(item.get("translation", "")).strip()
        if source and translation:
            translated[source] = translation
    return translated


def _translate_terms_to_english(texts: List[str]) -> Dict[str, str]:
    translations: Dict[str, str] = {}
    pending: List[str] = []
    seen = set()

    for text in texts:
        normalized = str(text or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        if not _is_hebrew(normalized):
            translations[normalized] = normalized
        elif normalized in _TRANSLATION_CACHE:
            translations[normalized] = _TRANSLATION_CACHE[normalized]
        else:
            pending.append(normalized)

    if not pending:
        return translations

    try:
        from dotenv import load_dotenv
        load_dotenv()
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            for text in pending:
                translations[text] = text
            return translations

        for chunk in _chunk_items(pending, _TRANSLATION_BATCH_MAX_ITEMS):
            prompt = f"""
Translate each Hebrew term below to concise natural English.
Return ONLY valid JSON in this format:
{{
  "translations": [
    {{"source": "original text", "translation": "english translation"}}
  ]
}}

Preserve meaning faithfully. Do not add commentary.

TERMS:
{chr(10).join(f"- {item}" for item in chunk)}
"""

            try:
                response = gemini_generate_content(
                    api_key=api_key,
                    model='gemini-2.0-flash',
                    contents=prompt,
                    response_mime_type="application/json",
                )
                parsed = try_parse_json(response.text.strip())
                mapped = _extract_translation_map(parsed)
            except Exception as exc:
                logger.warning("Batched term translation failed: %s", exc)
                mapped = {}
                if _is_quota_error(exc):
                    _record_runtime_diagnostic(
                        "warning",
                        "Gemini quota was exhausted while translating research terms. The app continued with the original wording, so search coverage may be weaker until the quota resets.",
                    )

            for source in chunk:
                translated = mapped.get(source)
                if translated:
                    _TRANSLATION_CACHE[source] = translated
                    translations[source] = translated
                else:
                    translations[source] = _translate_to_english(source)

    except Exception as exc:
        logger.warning("Unable to initialize batched term translation: %s", exc)
        for text in pending:
            translations[text] = _translate_to_english(text)

    return translations


def _extract_year(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    match = re.search(r'\b(19\d{2}|20\d{2})\b', str(value))
    return int(match.group(1)) if match else None


def _infer_time_window(blueprint: Dict) -> Dict[str, Optional[int]]:
    metadata = blueprint.get("report_metadata", {}) or {}
    original_report_date = blueprint.get("original_report_date") or metadata.get("original_report_date")
    update_start_date = blueprint.get("update_start_date") or metadata.get("update_start_date") or original_report_date
    update_end_date = blueprint.get("update_end_date") or metadata.get("update_end_date")

    original_year = _extract_year(original_report_date)
    start_year = _extract_year(update_start_date) or original_year
    end_year = _extract_year(update_end_date) or datetime.now().year

    if start_year and end_year and start_year > end_year:
        start_year, end_year = end_year, start_year

    return {
        "original_year": original_year,
        "start_year": start_year,
        "end_year": end_year,
    }


def _extract_years(text: str) -> List[int]:
    years = {int(year) for year in re.findall(r'\b(19\d{2}|20\d{2})\b', text or "")}
    return sorted(years)


def _compute_freshness_score(text: str, start_year: Optional[int], end_year: Optional[int]) -> float:
    years = _extract_years(text)
    if not years:
        return 0.35
    if start_year and end_year and any(start_year <= year <= end_year for year in years):
        return 1.0
    if end_year and max(years) >= end_year - 1:
        return 0.75
    if start_year and max(years) >= start_year:
        return 0.6
    return 0.2


def _compute_relevance_score(text: str, topic: str, keywords: List[str]) -> float:
    haystack = (text or "").lower()
    score = 0.0
    if topic and topic.lower() in haystack:
        score += 1.0
    for keyword in keywords:
        lowered = keyword.lower().strip()
        if not lowered:
            continue
        if lowered in haystack:
            score += 0.5
        else:
            overlap = sum(1 for token in lowered.split() if token in haystack)
            score += min(0.4, overlap * 0.1)
    return round(score, 2)


def _dedupe_preserve_order(values: List[str], *, limit: Optional[int] = None) -> List[str]:
    results: List[str] = []
    seen = set()
    for value in values:
        normalized = re.sub(r"\s+", " ", str(value or "")).strip()
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        results.append(normalized)
        if limit is not None and len(results) >= limit:
            break
    return results


def _meaningful_topic_terms(texts: List[str], *, limit: int = 24) -> List[str]:
    counts: Counter[str] = Counter()
    for text in texts:
        for token in _TOPIC_WORD_PATTERN.findall(str(text or "").lower()):
            if token in _TOPIC_STOPWORDS or len(token) < 3:
                continue
            counts[token] += 1
    return [token for token, _ in counts.most_common(limit)]


def _build_topic_profile(blueprint: Dict, topic: str, keywords: List[str]) -> Dict[str, Any]:
    source_chapter_title = str(blueprint.get("source_chapter_title") or blueprint.get("title") or "").strip()
    report_subject = str(blueprint.get("report_subject") or blueprint.get("edition_title") or "").strip()
    baseline_summary = str(blueprint.get("baseline_summary") or "").strip()
    baseline_claims = [
        str(item).strip()
        for item in blueprint.get("baseline_claims", [])[:4]
        if str(item).strip()
    ]

    phrase_pool = _dedupe_preserve_order(
        [topic, source_chapter_title, report_subject, *keywords[:6]],
        limit=12,
    )
    priority_terms = _meaningful_topic_terms([topic, source_chapter_title, report_subject], limit=12)
    if not priority_terms:
        priority_terms = _meaningful_topic_terms(phrase_pool, limit=12)
    context_terms = _meaningful_topic_terms(
        [*phrase_pool, baseline_summary, *baseline_claims],
        limit=24,
    )
    subject_anchor_terms = _meaningful_topic_terms([report_subject], limit=10)
    if not subject_anchor_terms:
        subject_anchor_terms = _meaningful_topic_terms([topic, source_chapter_title], limit=10)
    return {
        "topic": topic,
        "source_chapter_title": source_chapter_title,
        "report_subject": report_subject,
        "phrases": phrase_pool,
        "priority_terms": priority_terms,
        "context_terms": context_terms,
        "subject_anchor_terms": subject_anchor_terms,
    }


def _contains_topic_token(haystack: str, token: str) -> bool:
    return bool(re.search(rf"(?<!\w){re.escape(token.lower())}(?!\w)", haystack))


def _deterministic_topic_match(finding: Dict[str, Any], topic_profile: Dict[str, Any]) -> Dict[str, Any]:
    title = str(finding.get("title", "")).strip()
    snippet = str(finding.get("snippet", "")).strip()
    haystack = re.sub(r"\s+", " ", f"{title} {snippet}".lower())
    source_type = str(finding.get("source_type") or finding.get("source") or "web").lower()

    priority_hits = [token for token in topic_profile["priority_terms"] if _contains_topic_token(haystack, token)]
    context_hits = [token for token in topic_profile["context_terms"] if _contains_topic_token(haystack, token)]
    subject_anchor_hits = [
        token for token in topic_profile.get("subject_anchor_terms", [])
        if _contains_topic_token(haystack, token)
    ]
    phrase_hits = [
        phrase
        for phrase in topic_profile["phrases"]
        if len(phrase) >= 6 and phrase.lower() in haystack
    ]

    score = (
        (len(priority_hits) * 1.3)
        + (len(phrase_hits) * 1.5)
        + (len(subject_anchor_hits) * 1.6)
        + (len(context_hits) * 0.35)
        + float(finding.get("relevance_score", 0.0)) * 0.2
        + float(finding.get("source_quality", 0.0)) * 0.1
    )

    passes_subject_anchor = (
        source_type in {"uploaded", "internal"}
        or not topic_profile.get("subject_anchor_terms")
        or bool(subject_anchor_hits)
    )

    passes = False
    if not passes_subject_anchor:
        passes = False
    elif source_type in {"uploaded", "internal"}:
        passes = True
    elif priority_hits or phrase_hits:
        passes = True
    elif len(context_hits) >= (2 if source_type == "academic" else 3):
        passes = True

    return {
        "priority_topic_hits": priority_hits,
        "context_topic_hits": context_hits,
        "topic_phrase_hits": phrase_hits,
        "report_subject_hits": subject_anchor_hits,
        "passes_subject_anchor": passes_subject_anchor,
        "deterministic_topic_score": round(score, 3),
        "passes_topic_prefilter": passes,
    }


def _prefilter_findings_for_topic(
    findings: List[Dict[str, Any]],
    blueprint: Dict[str, Any],
    topic: str,
    keywords: List[str],
) -> List[Dict[str, Any]]:
    topic_profile = _build_topic_profile(blueprint, topic, keywords)
    kept: List[Dict[str, Any]] = []
    dropped = 0

    for finding in findings:
        enriched = dict(finding)
        enriched.update(_deterministic_topic_match(enriched, topic_profile))
        if not enriched.get("passes_topic_prefilter"):
            dropped += 1
            logger.info(
                "Dropping off-topic finding before LLM rerank: %s",
                enriched.get("title", "Untitled finding"),
            )
            continue
        kept.append(enriched)

    kept.sort(
        key=lambda item: (
            item.get("deterministic_topic_score", 0.0),
            item.get("source_quality", 0.0),
            item.get("freshness_score", 0.0),
            item.get("relevance_score", 0.0),
        ),
        reverse=True,
    )

    if dropped:
        _record_runtime_diagnostic(
            "warning",
            f"Filtered out {dropped} off-topic research candidates before writing for '{topic or blueprint.get('source_chapter_title', 'this chapter')}'.",
        )

    return kept[:24]


def _normalize_rerank_response(parsed: Any) -> Dict[str, Dict[str, Any]]:
    if isinstance(parsed, dict):
        parsed = parsed.get("sources")
    if not isinstance(parsed, list):
        return {}

    normalized: Dict[str, Dict[str, Any]] = {}
    for item in parsed:
        if not isinstance(item, dict):
            continue
        source_id = str(item.get("id", "")).strip()
        if not source_id:
            continue
        try:
            relevance_score = float(item.get("relevance_score", 0.0))
        except (TypeError, ValueError):
            relevance_score = 0.0
        normalized[source_id] = {
            "relevance_score": max(0.0, min(1.0, relevance_score)),
            "directly_on_topic": bool(item.get("directly_on_topic")),
            "background_only": bool(item.get("background_only")),
            "cross_domain_analogy": bool(item.get("cross_domain_analogy")),
            "keep": bool(item.get("keep")),
            "reason": str(item.get("reason", "")).strip(),
        }
    return normalized


def _apply_deterministic_approval(findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    approved: List[Dict[str, Any]] = []
    for finding in findings:
        candidate = dict(finding)
        direct = bool(candidate.get("priority_topic_hits") or candidate.get("topic_phrase_hits"))
        passes_subject_anchor = bool(candidate.get("passes_subject_anchor", True))
        source_type = str(candidate.get("source_type", candidate.get("source", ""))).lower()
        candidate["llm_relevance_score"] = min(1.0, candidate.get("deterministic_topic_score", 0.0) / 4.0)
        candidate["directly_on_topic"] = direct
        candidate["background_only"] = False
        candidate["cross_domain_analogy"] = False
        candidate["approved_for_writing"] = source_type in {"uploaded", "internal"} or (direct and passes_subject_anchor)
        candidate["approval_strategy"] = "deterministic"
        approved.append(candidate)
    return approved


def _llm_rerank_findings_for_topic(
    findings: List[Dict[str, Any]],
    blueprint: Dict[str, Any],
    topic: str,
    keywords: List[str],
) -> List[Dict[str, Any]]:
    if not findings:
        return []

    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:
        pass

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return _apply_deterministic_approval(findings)

    if len(findings) == 1:
        return _apply_deterministic_approval(findings)

    model = os.getenv("RESEARCH_RANKER_MODEL", _DEFAULT_RESEARCH_RANKER_MODEL).strip() or _DEFAULT_RESEARCH_RANKER_MODEL
    source_chapter_title = str(blueprint.get("source_chapter_title") or blueprint.get("title") or "").strip()
    report_subject = str(blueprint.get("report_subject") or blueprint.get("edition_title") or "").strip()
    baseline_summary = str(blueprint.get("baseline_summary") or "").strip()
    baseline_claims = [
        str(item).strip()
        for item in blueprint.get("baseline_claims", [])[:4]
        if str(item).strip()
    ]

    candidate_lines = []
    for index, finding in enumerate(findings, start=1):
        candidate_lines.append(
            f"- id: {index}\n"
            f"  title: {finding.get('title', 'Untitled')}\n"
            f"  source_type: {finding.get('source_type', finding.get('source', 'web'))}\n"
            f"  published_date: {finding.get('published_date', 'Unknown')}\n"
            f"  url: {finding.get('url', 'N/A')}\n"
            f"  deterministic_hits: priority={','.join(finding.get('priority_topic_hits', [])) or 'none'}; "
            f"phrases={','.join(finding.get('topic_phrase_hits', [])) or 'none'}; "
            f"context={','.join(finding.get('context_topic_hits', [])[:6]) or 'none'}\n"
            f"  report_subject_hits: {','.join(finding.get('report_subject_hits', [])) or 'none'}\n"
            f"  abstract_or_snippet: {str(finding.get('snippet', '')).strip()[:700]}"
        )

    prompt = f"""
You are reranking candidate sources for a single report chapter.

Return ONLY valid JSON in this format:
{{
  "sources": [
    {{
      "id": "1",
      "relevance_score": 0.0,
      "directly_on_topic": true,
      "background_only": false,
      "cross_domain_analogy": false,
      "keep": true,
      "reason": "short explanation"
    }}
  ]
}}

Chapter topic: {topic}
Source chapter title: {source_chapter_title}
Report subject: {report_subject}
Chapter keywords: {", ".join(keywords[:8])}
Baseline summary: {baseline_summary or "N/A"}
Baseline claims:
{chr(10).join(f"- {claim}" for claim in baseline_claims) or "- None supplied"}

Decision rules:
- Keep only sources that are directly relevant to this chapter's subject and can support factual claims in the rewritten chapter.
- A source must connect to the report subject itself, not just a neighboring application area or analogy.
- Mark `background_only=true` for broad context or analogy sources that are not safe as primary evidence.
- Mark `cross_domain_analogy=true` for sources from other sectors or disciplines that only resemble the topic superficially.
- If a source is mainly about a different domain, set `keep=false`.
- Prefer sources that match the source chapter title, report subject, and chapter keywords simultaneously.

Candidate sources:
{chr(10).join(candidate_lines)}
"""

    try:
        response = gemini_generate_content(
            api_key=api_key,
            model=model,
            contents=prompt,
            response_mime_type="application/json",
            temperature=0.0,
        )
        ranked = _normalize_rerank_response(try_parse_json(response.text.strip()))
    except Exception as exc:
        logger.warning("Research reranker failed: %s", exc)
        if _is_quota_error(exc):
            _record_runtime_diagnostic(
                "warning",
                "Gemini quota was exhausted while reranking research sources. The app fell back to deterministic topic filtering.",
            )
        return _apply_deterministic_approval(findings)

    approved: List[Dict[str, Any]] = []
    for index, finding in enumerate(findings, start=1):
        candidate = dict(finding)
        rating = ranked.get(str(index), {})
        direct = bool(rating.get("directly_on_topic"))
        background_only = bool(rating.get("background_only"))
        cross_domain = bool(rating.get("cross_domain_analogy"))
        keep = bool(rating.get("keep"))
        source_type = str(candidate.get("source_type", candidate.get("source", "web"))).lower()
        passes_subject_anchor = bool(candidate.get("passes_subject_anchor", True))

        candidate["llm_relevance_score"] = float(rating.get("relevance_score", 0.0))
        candidate["directly_on_topic"] = direct
        candidate["background_only"] = background_only
        candidate["cross_domain_analogy"] = cross_domain
        candidate["passes_subject_anchor"] = passes_subject_anchor
        candidate["approval_strategy"] = "llm_rerank"
        candidate["relevance_reason"] = str(rating.get("reason", "")).strip()
        candidate["approved_for_writing"] = (
            source_type in {"uploaded", "internal"}
            or (keep and direct and not background_only and not cross_domain and passes_subject_anchor)
        )
        approved.append(candidate)

    approved_for_writing = [item for item in approved if item.get("approved_for_writing")]
    if not approved_for_writing:
        fallback = _apply_deterministic_approval(findings[:8])
        for item in fallback:
            item["approval_strategy"] = "deterministic_fallback"
            item["approved_for_writing"] = True
        _record_runtime_diagnostic(
            "warning",
            f"LLM reranking rejected all candidate sources for '{topic or source_chapter_title or 'this chapter'}'. Falling back to deterministic topic matches.",
        )
        return fallback

    return approved


def _source_quality(source: str) -> float:
    mapping = {
        "academic": 1.0,
        "uploaded": 0.85,
        "internal": 0.85,
        "web": 0.7,
        "gemini": 0.35,
    }
    return mapping.get((source or "").lower(), 0.5)


def _assess_web_source(title: str, url: str, snippet: str) -> Tuple[float, bool, str]:
    title = str(title or "").strip()
    url = str(url or "").strip()
    snippet = str(snippet or "").strip()
    parsed = urlparse(url) if url else None
    path_segments = [segment.lower() for segment in (parsed.path.split('/') if parsed else []) if segment]

    penalty = 0.0
    reasons: List[str] = []

    if any(segment in _GENERIC_WEB_PATH_TERMS for segment in path_segments):
        penalty += 0.35
        reasons.append("generic_path")

    if path_segments and all(segment in _GENERIC_WEB_PATH_TERMS for segment in path_segments[-2:]):
        penalty += 0.25
        reasons.append("archive_like_path")

    if _GENERIC_WEB_TITLE_PATTERN.search(title):
        penalty += 0.35
        reasons.append("generic_title")

    if len(snippet) < 120:
        penalty += 0.1
        reasons.append("thin_snippet")

    if not re.search(r"\b(19|20)\d{2}\b", f"{title} {snippet}"):
        penalty += 0.05
        reasons.append("no_explicit_year")

    quality = max(0.1, 0.7 - penalty)
    is_credible = penalty < 0.55
    return quality, is_credible, ",".join(reasons)


def _enrich_finding(finding: Dict, topic: str, keywords: List[str], start_year: Optional[int], end_year: Optional[int]) -> Dict:
    source = finding.get("source") or finding.get("source_type") or "web"
    combined_text = " ".join([
        str(finding.get("title", "")),
        str(finding.get("snippet", "")),
        str(finding.get("published_date", "")),
    ])
    finding["source_type"] = source
    finding["source_quality"] = _source_quality(source)
    finding["freshness_score"] = _compute_freshness_score(combined_text, start_year, end_year)
    finding["relevance_score"] = _compute_relevance_score(combined_text, topic, keywords)
    finding["source_credible"] = True
    if str(source).lower() == "web":
        quality, is_credible, reason = _assess_web_source(
            finding.get("title", ""),
            finding.get("url", ""),
            finding.get("snippet", ""),
        )
        finding["source_quality"] = round(quality, 2)
        finding["source_credible"] = is_credible
        if reason:
            finding["quality_notes"] = reason
    return finding


def _filter_low_value_findings(findings: List[Dict]) -> List[Dict]:
    filtered = []
    for finding in findings:
        if finding.get("source_type") == "web" and not finding.get("source_credible", True):
            logger.info(
                "Dropping low-value web finding: %s | %s | %s",
                finding.get("title", "Untitled finding"),
                finding.get("url", ""),
                finding.get("quality_notes", ""),
            )
            continue
        filtered.append(finding)
    return filtered


def _normalize_reference_text(text: str) -> str:
    text = re.sub(r'\[(?:Figure|Asset|Image|Figura):?\s*[^\]]+\]', ' ', text or "", flags=re.IGNORECASE)
    text = text.replace('\x00', ' ')
    text = re.sub(r'\r\n?', '\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _load_reference_text(doc_path: str) -> str:
    if not os.path.exists(doc_path):
        return ""

    cache_key = (doc_path, os.path.getmtime(doc_path))
    if cache_key in _REFERENCE_TEXT_CACHE:
        return _REFERENCE_TEXT_CACHE[cache_key]

    ext = os.path.splitext(doc_path)[1].lower()
    text = ""
    try:
        if ext == ".txt":
            with open(doc_path, 'r', encoding='utf-8', errors='ignore') as file_obj:
                text = file_obj.read()
        elif ext == ".pdf":
            from parse_pdf import extract_pdf_content
            parsed = extract_pdf_content(doc_path, output_dir=os.path.join('.tmp', 'ref_assets'))
            text = "\n\n".join(
                f"{chapter.get('title', '')}\n{chapter.get('content', '')}".strip()
                for chapter in parsed.get('chapters', [])
                if chapter.get('content') or chapter.get('title')
            )
        elif ext == ".docx":
            from parse_docx import extract_docx_content
            parsed = extract_docx_content(doc_path, output_dir=os.path.join('.tmp', 'ref_assets'))
            text = "\n\n".join(
                f"{chapter.get('title', '')}\n{chapter.get('content', '')}".strip()
                for chapter in parsed.get('chapters', [])
                if chapter.get('content') or chapter.get('title')
            )
        else:
            logger.warning(f"Unsupported reference doc type for internal search: {doc_path}")
    except Exception as exc:
        logger.error(f"Error extracting text from reference doc {doc_path}: {exc}")
        text = ""

    text = _normalize_reference_text(text)
    _REFERENCE_TEXT_CACHE[cache_key] = text
    return text

def _split_reference_paragraphs(text: str) -> List[str]:
    paragraphs = [part.strip() for part in re.split(r'\n\s*\n', text or "") if part.strip()]
    if len(paragraphs) > 1:
        return paragraphs
    return [part.strip() for part in re.split(r'(?<=[.!?])\s+', text or "") if len(part.strip()) >= 60]


def _gemini_research_fallback(topic: str, keywords: List[str], start_year: Optional[int], end_year: Optional[int]) -> List[Dict]:
    logger.info(f"DDG yielded 0 results - using Gemini research fallback for: '{topic}'")
    try:
        from dotenv import load_dotenv
        load_dotenv()
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            return []

        kw_str = ", ".join(keywords[:6]) if keywords else topic
        year_window = f"{start_year}-{end_year}" if start_year and end_year else "the requested update window"
        prompt = f"""You are a research assistant. Provide 5 factual, specific, and up-to-date research findings about: "{topic}".
Key aspects to cover: {kw_str}
Time window to prioritize: {year_window}

For each finding, provide:
- A clear, descriptive title
- 2-3 sentences of specific facts, statistics, and named sources (companies, reports, dates)

Format as a numbered list. Be specific. Include real numbers, percentages, organizations, and years when possible.
"""

        response = gemini_generate_content(
            api_key=api_key,
            model='gemini-2.5-flash',
            contents=prompt,
        )
        raw = response.text.strip()

        findings = []
        items = re.split(r'\n\s*\d+[\.\)]\s+', raw)
        for item in items:
            item = item.strip()
            if not item:
                continue
            lines = item.split('\n', 1)
            title = lines[0].strip().lstrip('**').rstrip('**').strip()
            snippet = lines[1].strip() if len(lines) > 1 else title
            if title:
                findings.append({
                    "title": title,
                    "snippet": snippet,
                    "url": None,
                    "source": "gemini",
                    "published_date": None,
                })

        logger.info(f"Gemini fallback produced {len(findings)} findings.")
        return findings[:5]
    except Exception as e:
        logger.error(f"Gemini research fallback failed: {e}", exc_info=True)
        if _is_quota_error(e):
            _record_runtime_diagnostic(
                "warning",
                "Gemini quota was exhausted during fallback research. No fallback findings were added for this chapter.",
            )
        return []


def _fetch_article_text(url: str) -> str:
    if url in _ARTICLE_TEXT_CACHE:
        return _ARTICLE_TEXT_CACHE[url]
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        resp = requests.get(url, timeout=_FETCH_TIMEOUT, headers=headers)
        resp.raise_for_status()
        text = re.sub(r'<[^>]+>', ' ', resp.text)
        text = re.sub(r'\s+', ' ', text).strip()
        article = text[:_ARTICLE_MAX_CHARS]
        _ARTICLE_TEXT_CACHE[url] = article
        return article
    except Exception:
        _ARTICLE_TEXT_CACHE[url] = ""
        return ""


def search_web(query: str, max_results: int = 5, start_year: Optional[int] = None, end_year: Optional[int] = None) -> List[Dict[str, str]]:
    cache_key = (str(query or "").strip().lower(), max_results, start_year, end_year)
    if cache_key in _WEB_SEARCH_CACHE:
        logger.info("Returning cached web search for: '%s'", query)
        return _clone_findings(_WEB_SEARCH_CACHE[cache_key])

    logger.info(f"Performing web search for: '{query}' (max_results={max_results})")
    raw_results = []
    start_time = time.time()
    try:
        with DDGS() as ddgs:
            ddgs_gen = ddgs.text(query, max_results=max_results)
            for result in ddgs_gen:
                raw_results.append({
                    "title": result.get('title', ''),
                    "url": result.get('href', ''),
                    "snippet": result.get('body', ''),
                    "source": "web",
                    "published_date": result.get('date'),
                })
        logger.info(f"DDG search returned {len(raw_results)} results in {time.time() - start_time:.2f}s. Fetching article bodies...")
    except Exception as e:
        logger.error(f"Web search error for query '{query}': {e}", exc_info=True)
        return raw_results

    urls = [item['url'] for item in raw_results]
    fetched: Dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_url = {executor.submit(_fetch_article_text, url): url for url in urls if url}
        for future in as_completed(future_to_url, timeout=_FETCH_TIMEOUT + 2):
            url = future_to_url[future]
            try:
                fetched[url] = future.result()
            except Exception:
                fetched[url] = ""

    results = []
    for item in raw_results:
        article_body = fetched.get(item['url'], "")
        content = article_body if len(article_body) > len(item['snippet']) else item['snippet']
        item['snippet'] = content
        item['freshness_score'] = _compute_freshness_score(
            f"{item.get('published_date', '')} {item.get('title', '')} {content}", start_year, end_year
        )
        results.append(item)

    logger.info(f"Web search+fetch complete. Total time: {time.time() - start_time:.2f}s.")
    _WEB_SEARCH_CACHE[cache_key] = _clone_findings(results)
    return _clone_findings(results)


def _openalex_abstract(work: Dict) -> str:
    inverted = work.get('abstract_inverted_index') or {}
    if not inverted:
        return ""
    positioned_words = []
    for word, positions in inverted.items():
        for position in positions:
            positioned_words.append((position, word))
    positioned_words.sort(key=lambda item: item[0])
    return " ".join(word for _, word in positioned_words)


def search_academic(query: str, max_results: int = 3, start_year: Optional[int] = None, end_year: Optional[int] = None) -> List[Dict[str, str]]:
    cache_key = (str(query or "").strip().lower(), max_results, start_year, end_year)
    if cache_key in _ACADEMIC_SEARCH_CACHE:
        logger.info("Returning cached academic search for: '%s'", query)
        return _clone_findings(_ACADEMIC_SEARCH_CACHE[cache_key])

    logger.info(f"Performing academic search for: '{query}'")
    params = {
        "search": query,
        "per-page": max_results,
    }
    if start_year and end_year:
        params["filter"] = f"from_publication_date:{start_year}-01-01,to_publication_date:{end_year}-12-31"

    try:
        response = requests.get("https://api.openalex.org/works", params=params, timeout=10)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        logger.warning(f"Academic search failed for '{query}': {exc}")
        return []

    findings = []
    for work in payload.get('results', []):
        title = work.get('display_name') or 'Untitled academic source'
        publication_year = work.get('publication_year')
        source_name = (((work.get('primary_location') or {}).get('source') or {}).get('display_name')) or ''
        abstract = _openalex_abstract(work)
        snippet_parts = [part for part in [abstract, source_name, f"Publication year: {publication_year}" if publication_year else ""] if part]
        findings.append({
            "title": title,
            "url": work.get('id') or work.get('doi'),
            "snippet": " | ".join(snippet_parts)[:_ARTICLE_MAX_CHARS] or title,
            "source": "academic",
            "published_date": str(publication_year) if publication_year else None,
        })
    _ACADEMIC_SEARCH_CACHE[cache_key] = _clone_findings(findings)
    return _clone_findings(findings)


def search_internal(query: str, reference_docs: List[str]) -> List[Dict[str, str]]:
    logger.info(f"Performing internal search for: '{query}' in {len(reference_docs)} docs.")
    results = []
    query_words = {word for word in re.findall(r'\w+', (query or '').lower()) if len(word) > 2}

    for doc_path in reference_docs:
        if not os.path.exists(doc_path):
            continue
        try:
            content = _load_reference_text(doc_path)
            paragraphs = _split_reference_paragraphs(content)
            scored = []
            for paragraph in paragraphs:
                lowered = paragraph.lower()
                score = sum(1 for word in query_words if word in lowered)
                if score > 0:
                    scored.append((score, paragraph))

            scored.sort(key=lambda item: item[0], reverse=True)
            for score, paragraph in scored[:3]:
                results.append({
                    "title": os.path.basename(doc_path),
                    "snippet": paragraph[:1500],
                    "source": "uploaded",
                    "published_date": None,
                    "source_quality": 0.85,
                    "relevance_score": float(score),
                    "freshness_score": 0.5,
                })
                logger.debug(f"Internal match (score={score}) in '{os.path.basename(doc_path)}'")
        except Exception as exc:
            logger.error(f"Error reading doc {doc_path}: {exc}")

    logger.info(f"Internal search complete. Found {len(results)} paragraph matches.")
    return results

def _build_queries(topic: str, keywords: List[str], blueprint: Dict) -> List[str]:
    window = _infer_time_window(blueprint)
    original_year = window.get('original_year')
    start_year = window.get('start_year')
    end_year = window.get('end_year')

    queries: List[str] = []
    if topic and topic.lower().strip() not in _GENERIC_TOPICS:
        if start_year and end_year:
            queries.append(f"{topic} {start_year} {end_year}")
            queries.append(f"{topic} latest {end_year}")
        queries.append(topic)
        if original_year and end_year and original_year != end_year:
            queries.append(f"{topic} since {original_year}")

    for keyword in keywords:
        clean = keyword.strip()
        if not clean:
            continue
        if start_year and end_year:
            queries.append(f"{clean} {start_year} {end_year}")
        queries.append(clean)

    final_queries = []
    seen = set()
    for query in queries:
        normalized = query.lower().strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        final_queries.append(query)
        if len(final_queries) >= 4:
            break
    return final_queries


def _reference_cache_key(reference_docs: List[str]) -> Tuple[Tuple[str, float], ...]:
    entries = []
    for doc_path in reference_docs or []:
        if not os.path.exists(doc_path):
            continue
        entries.append((doc_path, os.path.getmtime(doc_path)))
    return tuple(sorted(entries))


def _build_research_cache_key(blueprint: Dict, window: Dict[str, Optional[int]]) -> Tuple[Any, ...]:
    topic = str(blueprint.get("topic", "")).strip().lower()
    keywords = tuple(
        sorted(str(keyword).strip().lower() for keyword in blueprint.get("keywords", []) if str(keyword).strip())
    )
    return (
        topic,
        str(blueprint.get("source_chapter_title", "")).strip().lower(),
        str(blueprint.get("report_subject", "")).strip().lower(),
        keywords,
        window.get("original_year"),
        window.get("start_year"),
        window.get("end_year"),
        _reference_cache_key(blueprint.get("ref_paths", [])),
    )


def perform_comprehensive_research(blueprint: Dict) -> List[Dict]:
    topic = blueprint.get("topic", "")
    keywords = blueprint.get("keywords", [])
    ref_paths = blueprint.get("ref_paths", [])
    window = _infer_time_window(blueprint)
    research_cache_key = _build_research_cache_key(blueprint, window)

    if research_cache_key in _RESEARCH_RESULT_CACHE:
        logger.info("Returning cached comprehensive research for topic: '%s'", topic)
        return _clone_findings(_RESEARCH_RESULT_CACHE[research_cache_key])

    logger.info(f"Orchestrating comprehensive research for topic: '{topic}'")
    all_findings: List[Dict] = []

    internal_queries = keywords[:3] or ([topic] if topic else [])
    if ref_paths:
        for query in internal_queries:
            all_findings.extend(search_internal(query, ref_paths))

    translated_terms = _translate_terms_to_english([topic, *keywords])
    en_topic = translated_terms.get(str(topic).strip(), topic)
    en_keywords = [translated_terms.get(str(keyword).strip(), keyword) for keyword in keywords]

    final_queries = _build_queries(en_topic, en_keywords, blueprint)
    if not final_queries and en_topic:
        final_queries = [en_topic]

    external_total = 0
    for index, query in enumerate(final_queries):
        if index > 0:
            time.sleep(_DDG_DELAY)

        web_results = search_web(query, start_year=window.get('start_year'), end_year=window.get('end_year'))
        academic_results = search_academic(query, start_year=window.get('start_year'), end_year=window.get('end_year'))

        if web_results:
            all_findings.extend(web_results)
            external_total += len(web_results)
        elif len(query.split()) > 2:
            broader_query = " ".join(query.split()[:2])
            logger.info(f"Retrying with broader query: {broader_query}")
            time.sleep(_DDG_DELAY)
            broader_results = search_web(broader_query, max_results=3, start_year=window.get('start_year'), end_year=window.get('end_year'))
            all_findings.extend(broader_results)
            external_total += len(broader_results)

        if academic_results:
            all_findings.extend(academic_results)
            external_total += len(academic_results)

    if external_total == 0:
        logger.warning(f"All external queries returned 0 results for topic '{en_topic}'. Activating Gemini research fallback.")
        all_findings.extend(_gemini_research_fallback(en_topic, en_keywords, window.get('start_year'), window.get('end_year')))

    logger.info(f"Comprehensive research complete. Total findings: {len(all_findings)}")

    enriched = [
        _enrich_finding(finding, en_topic, en_keywords, window.get('start_year'), window.get('end_year'))
        for finding in all_findings
    ]
    enriched = _filter_low_value_findings(enriched)

    deduped: List[Dict] = []
    seen_keys = set()
    for finding in enriched:
        dedupe_key = finding.get('url') or f"{finding.get('title', '').strip().lower()}::{finding.get('snippet', '')[:120].strip().lower()}"
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)
        deduped.append(finding)

    prefiltered = _prefilter_findings_for_topic(deduped, blueprint, en_topic, en_keywords)
    reranked = _llm_rerank_findings_for_topic(prefiltered, blueprint, en_topic, en_keywords)
    reranked.sort(
        key=lambda item: (
            bool(item.get("approved_for_writing")),
            bool(item.get("directly_on_topic")),
            item.get("llm_relevance_score", 0.0),
            item.get("deterministic_topic_score", 0.0),
            item.get("source_quality", 0.0),
            item.get("freshness_score", 0.0),
            item.get("relevance_score", 0.0),
        ),
        reverse=True,
    )

    trimmed = [item for item in reranked if item.get("approved_for_writing")][:12]
    if not trimmed:
        trimmed = reranked[:8]
    _RESEARCH_RESULT_CACHE[research_cache_key] = _clone_findings(trimmed)
    return _clone_findings(trimmed)


if __name__ == "__main__":
    test_blueprint = {
        "topic": "AI in healthcare trends",
        "keywords": ["Mayo Clinic AI", "FDA approved AI"],
        "original_report_date": "2023-01-01",
        "update_start_date": "2023-01-01",
        "update_end_date": "2026-03-22",
    }
    findings = perform_comprehensive_research(test_blueprint)
    for finding in findings:
        print(f"[{finding['source']}] {finding['title']}: {finding.get('url', 'N/A')}")
