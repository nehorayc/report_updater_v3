from ddgs import DDGS
import os
import re
import requests
import time
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from typing import List, Dict

from logger_config import setup_logger

logger = setup_logger("ResearchAgent")

_FETCH_TIMEOUT = 5  # seconds per article fetch
_ARTICLE_MAX_CHARS = 2500
_DDG_DELAY = 1.2   # seconds between DDG queries to avoid rate limiting
_TRANSLATION_CACHE = {}  # module-level cache: Hebrew -> English


def _is_hebrew(text: str) -> bool:
    """Returns True if text contains Hebrew characters."""
    return bool(re.search(r'[\u0590-\u05FF]', text))


def _translate_to_english(text: str) -> str:
    """
    Translates Hebrew text to English using Gemini.
    Falls back to returning the original text on any error.
    Uses a module-level cache to avoid re-translating the same string.
    """
    if not text or not _is_hebrew(text):
        return text
    if text in _TRANSLATION_CACHE:
        return _TRANSLATION_CACHE[text]
    try:
        import google.generativeai as genai
        from dotenv import load_dotenv
        load_dotenv()
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            return text
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.0-flash')
        response = model.generate_content(
            f"Translate the following text to English. Return ONLY the translation, no explanations:\n\n{text}"
        )
        translated = response.text.strip()
        _TRANSLATION_CACHE[text] = translated
        logger.info(f"Translated '{text[:40]}...' -> '{translated[:40]}...'")
        return translated
    except Exception as e:
        logger.warning(f"Translation failed for '{text[:40]}': {e}")
        return text


def _gemini_research_fallback(topic: str, keywords: List[str]) -> List[Dict]:
    """
    Uses Gemini's internal knowledge to synthesize research findings
    when DDG returns 0 results. Returns a list of finding dicts.
    """
    logger.info(f"DDG yielded 0 results — using Gemini research fallback for: '{topic}'")
    try:
        import google.generativeai as genai
        from dotenv import load_dotenv
        load_dotenv()
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            return []
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.5-flash')

        kw_str = ", ".join(keywords[:6]) if keywords else topic
        prompt = f"""You are a research assistant. Provide 5 factual, specific, and up-to-date research findings about: "{topic}".
Key aspects to cover: {kw_str}

For each finding, provide:
- A clear, descriptive title
- 2-3 sentences of specific facts, statistics, and named sources (companies, reports, dates)

Format as a numbered list. Be specific — include real numbers, percentages, organizations, and years.
Focus on developments from 2023-2025."""

        response = model.generate_content(prompt)
        raw = response.text.strip()

        # Parse numbered list into findings
        findings = []
        # Split on numbered list items
        items = re.split(r'\n\s*\d+[\.\)]\s+', raw)
        for item in items:
            item = item.strip()
            if not item:
                continue
            # First line is the title, rest is snippet
            lines = item.split('\n', 1)
            title = lines[0].strip().lstrip('**').rstrip('**').strip()
            snippet = lines[1].strip() if len(lines) > 1 else title
            if title:
                findings.append({
                    "title": title,
                    "snippet": snippet,
                    "url": None,
                    "source": "gemini"
                })

        logger.info(f"Gemini fallback produced {len(findings)} findings.")
        return findings[:5]

    except Exception as e:
        logger.error(f"Gemini research fallback failed: {e}", exc_info=True)
        return []


def _fetch_article_text(url: str) -> str:
    """
    Fetches a URL and returns up to _ARTICLE_MAX_CHARS of visible text.
    Strips HTML tags. Returns empty string on any failure.
    """
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        resp = requests.get(url, timeout=_FETCH_TIMEOUT, headers=headers)
        resp.raise_for_status()
        # Strip HTML tags
        text = re.sub(r'<[^>]+>', ' ', resp.text)
        # Collapse whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        return text[:_ARTICLE_MAX_CHARS]
    except Exception:
        return ""

def search_web(query: str, max_results: int = 5) -> List[Dict[str, str]]:
    """
    Performs a web search using DuckDuckGo, then fetches full article text
    for each result in parallel (with timeout). Falls back to snippet if fetch fails.
    """
    logger.info(f"Performing web search for: '{query}' (max_results={max_results})")
    raw_results = []
    start_time = time.time()
    try:
        with DDGS() as ddgs:
            ddgs_gen = ddgs.text(query, max_results=max_results)
            for r in ddgs_gen:
                raw_results.append({
                    "title": r.get('title', ''),
                    "url": r.get('href', ''),
                    "snippet": r.get('body', ''),
                    "source": "web"
                })
        logger.info(f"DDG search returned {len(raw_results)} results in {time.time()-start_time:.2f}s. Fetching article bodies...")
    except Exception as e:
        logger.error(f"Web search error for query '{query}': {e}", exc_info=True)
        return raw_results

    # Enrich results with full article text in parallel
    urls = [r['url'] for r in raw_results]
    fetched: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_url = {executor.submit(_fetch_article_text, url): url for url in urls if url}
        for future in as_completed(future_to_url, timeout=_FETCH_TIMEOUT + 2):
            url = future_to_url[future]
            try:
                fetched[url] = future.result()
            except Exception:
                fetched[url] = ""

    results = []
    for r in raw_results:
        article_body = fetched.get(r['url'], "")
        # Use full body if we got meaningful content, otherwise fall back to snippet
        content = article_body if len(article_body) > len(r['snippet']) else r['snippet']
        results.append({
            "title": r['title'],
            "url": r['url'],
            "snippet": content,
            "source": "web"
        })

    logger.info(f"Web search+fetch complete. Total time: {time.time()-start_time:.2f}s.")
    return results

def search_internal(query: str, reference_docs: List[str]) -> List[Dict[str, str]]:
    """
    Searches uploaded reference docs and returns the top matching paragraphs
    (not just the filename). A paragraph is any text block separated by blank lines.
    """
    logger.info(f"Performing internal search for: '{query}' in {len(reference_docs)} docs.")
    results = []
    query_lower = query.lower()
    query_words = set(query_lower.split())

    for doc_path in reference_docs:
        if not os.path.exists(doc_path):
            continue
        try:
            with open(doc_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

            # Split into paragraphs (blank-line separated)
            paragraphs = [p.strip() for p in re.split(r'\n\s*\n', content) if p.strip()]

            # Score each paragraph by how many query words it contains
            scored = []
            for para in paragraphs:
                para_lower = para.lower()
                score = sum(1 for w in query_words if w in para_lower)
                if score > 0:
                    scored.append((score, para))

            # Return top 3 matching paragraphs from this doc
            scored.sort(key=lambda x: x[0], reverse=True)
            for score, para in scored[:3]:
                results.append({
                    "title": os.path.basename(doc_path),
                    "snippet": para[:1500],  # cap length
                    "source": "internal"
                })
                logger.debug(f"Internal match (score={score}) in '{os.path.basename(doc_path)}'")

        except Exception as e:
            logger.error(f"Error reading doc {doc_path}: {e}")

    logger.info(f"Internal search complete. Found {len(results)} paragraph matches.")
    return results

def perform_comprehensive_research(blueprint: Dict) -> List[Dict]:
    """
    Combines web and internal research based on keywords.
    Translates Hebrew keywords to English before searching.
    Falls back to Gemini synthesized findings if DDG returns nothing.
    """
    topic = blueprint.get("topic", "")
    keywords = blueprint.get("keywords", [])
    ref_paths = blueprint.get("ref_paths", [])

    logger.info(f"Orchestrating comprehensive research for topic: '{topic}'")
    all_findings = []

    # 1. Internal Search (if reference docs exist)
    if ref_paths:
        for kw in keywords[:3]:
            all_findings.extend(search_internal(kw, ref_paths))

    # 2. Translate topic + keywords to English if Hebrew
    en_topic = _translate_to_english(topic)
    en_keywords = [_translate_to_english(kw) for kw in keywords]

    # 3. Web Search — build query list
    generic_topics = ["introduction", "conclusion", "summary", "abstract", "foreword", "appendix"]
    queries = []

    if en_topic.lower().strip() not in generic_topics and len(en_topic.split()) > 1:
        queries.append(en_topic)

    for kw in en_keywords:
        if kw not in queries:
            queries.append(kw)

    # Limit to top 4 queries total to avoid rate limiting
    final_queries = queries[:4]
    if not final_queries and en_topic:
        final_queries = [en_topic]

    ddg_total = 0
    for i, q in enumerate(final_queries):
        if i > 0:
            time.sleep(_DDG_DELAY)  # avoid rate limiting between queries
        res = search_web(q)
        if res:
            all_findings.extend(res)
            ddg_total += len(res)
        else:
            # Try a slightly broader version if 0 results
            if len(q.split()) > 2:
                broad_q = " ".join(q.split()[:2])
                logger.info(f"Retrying with broader query: {broad_q}")
                time.sleep(_DDG_DELAY)
                broad_res = search_web(broad_q, max_results=3)
                all_findings.extend(broad_res)
                ddg_total += len(broad_res)

    # 4. Gemini fallback if DDG returned nothing at all
    if ddg_total == 0:
        logger.warning(f"All DDG queries returned 0 results for topic '{en_topic}'. Activating Gemini research fallback.")
        gemini_findings = _gemini_research_fallback(en_topic, en_keywords)
        all_findings.extend(gemini_findings)

    logger.info(f"Comprehensive research complete. Total findings: {len(all_findings)}")
    unique_findings = []
    seen_urls = set()
    for f in all_findings:
        if f.get('url') and f['url'] not in seen_urls:
            unique_findings.append(f)
            seen_urls.add(f['url'])
        elif not f.get('url'):  # Internal docs, Gemini findings (no URL)
            unique_findings.append(f)

    return unique_findings[:15]  # Return top 15 results


if __name__ == "__main__":
    test_blueprint = {"topic": "AI in healthcare trends 2024", "keywords": ["Mayo Clinic AI", "FDA approved AI 2024"]}
    findings = perform_comprehensive_research(test_blueprint)
    for f in findings:
        print(f"[{f['source']}] {f['title']}: {f.get('url', 'N/A')}")
