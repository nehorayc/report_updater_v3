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

    deduped.sort(
        key=lambda item: (
            item.get('source_quality', 0),
            item.get('freshness_score', 0),
            item.get('relevance_score', 0),
        ),
        reverse=True,
    )

    trimmed = deduped[:15]
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
