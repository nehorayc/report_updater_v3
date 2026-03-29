import os
import json
import re
from dotenv import load_dotenv
from typing import Dict, List, Any
from logger_config import setup_logger
import time
from llm_json_utils import salvage_ordered_json, try_parse_json
from gemini_client import generate_content as gemini_generate_content

load_dotenv()
logger = setup_logger("ChapterAnalyzer")

ANALYSIS_SCHEMA = {
    "summary": "string",
    "keywords": "string_list",
    "core_claims": "string_list",
    "dated_facts": "string_list",
    "named_entities": "string_list",
    "stats": "string_list",
    "original_citations": "string_list",
    "original_figures": "string_list",
    "chapter_role": "string",
    "language": "string",
}

_BATCH_CHAPTER_TEXT_LIMIT = 8000
_BATCH_MAX_CHARS = 70000
_BATCH_MAX_CHAPTERS = 10


def _detect_language(text: str) -> str:
    return "Hebrew" if re.search(r'[\u0590-\u05FF]', text or "") else "English"


def _unique_preserve_order(items: List[str], limit: int = 10) -> List[str]:
    seen = set()
    results = []
    for item in items:
        clean = str(item).strip()
        if not clean:
            continue
        key = clean.lower()
        if key in seen:
            continue
        seen.add(key)
        results.append(clean)
        if len(results) >= limit:
            break
    return results


def _extract_sentences(text: str) -> List[str]:
    raw_sentences = re.split(r'(?<=[.!?])\s+|\n+', text or "")
    sentences = []
    for sentence in raw_sentences:
        clean = sentence.strip()
        if len(clean) >= 40:
            sentences.append(clean)
    return sentences


def _infer_chapter_role(title: str) -> str:
    lowered = (title or "").strip().lower()
    if any(token in lowered for token in ["introduction", "overview", "background", "executive summary"]):
        return "introduction"
    if any(token in lowered for token in ["conclusion", "summary", "outlook", "recommendations"]):
        return "conclusion"
    if any(token in lowered for token in ["appendix", "methodology", "references"]):
        return "appendix"
    return "body"


def _fallback_analysis(title: str, text: str) -> Dict[str, Any]:
    sentences = _extract_sentences(text)
    summary_sentences = sentences[:3] or [text[:500].strip()]
    dated_facts = [s for s in sentences if re.search(r'\b(?:19|20)\d{2}\b', s)][:5]
    stats = re.findall(r'(?:[$€£]\s?\d[\d,\.]*\s*(?:million|billion|trillion)?|\b\d+(?:\.\d+)?%|\b\d+[\d,\.]*\s*(?:million|billion|trillion))', text or "")
    named_entities = re.findall(r'\b(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+|[A-Z]{2,})\b', text or "")
    original_citations = re.findall(r'\[(\d+)\]', text or "")
    original_figures = re.findall(r'\[(?:Figure|Asset|Image|Figura):?\s*([^\]]+)\]', text or "", flags=re.IGNORECASE)

    return {
        "summary": " ".join(summary_sentences[:2]).strip(),
        "keywords": _unique_preserve_order((title or "").split() + re.findall(r'\b[A-Za-z][A-Za-z0-9\-]{3,}\b', text or ""), limit=8),
        "core_claims": _unique_preserve_order(summary_sentences, limit=5),
        "dated_facts": _unique_preserve_order(dated_facts, limit=5),
        "named_entities": _unique_preserve_order(named_entities, limit=10),
        "stats": _unique_preserve_order(stats, limit=8),
        "original_citations": _unique_preserve_order(original_citations, limit=10),
        "original_figures": _unique_preserve_order(original_figures, limit=10),
        "chapter_role": _infer_chapter_role(title),
        "language": _detect_language(text),
    }


def _is_quota_or_rate_limit_error(exc: Exception) -> bool:
    message = str(exc or "").upper()
    if "RESOURCE_EXHAUSTED" in message:
        return True
    if "429" not in message:
        return False
    return any(
        token in message
        for token in (
            "QUOTA",
            "RATE LIMIT",
            "GENERATEREQUESTSPERDAYPERPROJECTPERMODEL",
            "GENERATIVELANGUAGE.GOOGLEAPIS.COM/GENERATE_CONTENT",
        )
    )


def _normalize_result(result: Dict[str, Any], title: str, text: str) -> Dict[str, Any]:
    fallback = _fallback_analysis(title, text)
    normalized = {
        "summary": str(result.get("summary") or fallback["summary"]).strip(),
        "keywords": _unique_preserve_order(result.get("keywords") or fallback["keywords"], limit=8),
        "core_claims": _unique_preserve_order(result.get("core_claims") or fallback["core_claims"], limit=5),
        "dated_facts": _unique_preserve_order(result.get("dated_facts") or fallback["dated_facts"], limit=5),
        "named_entities": _unique_preserve_order(result.get("named_entities") or fallback["named_entities"], limit=10),
        "stats": _unique_preserve_order(result.get("stats") or fallback["stats"], limit=8),
        "original_citations": _unique_preserve_order(result.get("original_citations") or fallback["original_citations"], limit=10),
        "original_figures": _unique_preserve_order(result.get("original_figures") or fallback["original_figures"], limit=10),
        "chapter_role": str(result.get("chapter_role") or fallback["chapter_role"]).strip() or "body",
        "language": str(result.get("language") or fallback["language"]).strip() or _detect_language(text),
    }
    return normalized


def _truncate_for_batch(text: str, limit: int = _BATCH_CHAPTER_TEXT_LIMIT) -> str:
    if len(text or "") <= limit:
        return text or ""
    return f"{(text or '')[:limit]}\n\n(Text truncated for batch analysis)"


def _chunk_chapters_for_batch(
    chapters: List[Dict[str, Any]],
    max_chars: int = _BATCH_MAX_CHARS,
    max_chapters: int = _BATCH_MAX_CHAPTERS,
) -> List[List[Dict[str, Any]]]:
    chunks: List[List[Dict[str, Any]]] = []
    current_chunk: List[Dict[str, Any]] = []
    current_chars = 0

    for index, chapter in enumerate(chapters):
        prepared = {
            "id": str(chapter.get("id") or f"chapter_{index + 1}"),
            "title": str(chapter.get("title", "")).strip(),
            "content": str(chapter.get("content", "")),
            "batch_text": _truncate_for_batch(str(chapter.get("content", ""))),
        }
        estimated_chars = len(prepared["title"]) + len(prepared["batch_text"]) + 300

        should_flush = (
            current_chunk
            and (
                len(current_chunk) >= max_chapters
                or current_chars + estimated_chars > max_chars
            )
        )
        if should_flush:
            chunks.append(current_chunk)
            current_chunk = []
            current_chars = 0

        current_chunk.append(prepared)
        current_chars += estimated_chars

    if current_chunk:
        chunks.append(current_chunk)
    return chunks


def _extract_batch_items(parsed: Any) -> List[Dict[str, Any]]:
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    if isinstance(parsed, dict):
        chapters = parsed.get("chapters")
        if isinstance(chapters, list):
            return [item for item in chapters if isinstance(item, dict)]
        for value in parsed.values():
            if isinstance(value, list) and all(isinstance(item, dict) for item in value):
                return value
    return []


def _build_batch_prompt(chapters: List[Dict[str, Any]]) -> str:
    chapter_blocks = []
    for chapter in chapters:
        chapter_blocks.append(
            f"""
CHAPTER ID:
{chapter['id']}

CHAPTER TITLE:
{chapter['title']}

CHAPTER TEXT:
---
{chapter['batch_text']}
---
"""
        )

    return f"""
You are an expert report editor preparing legacy chapters for a future edition update.

You will receive multiple chapters. For EACH chapter, return one JSON object with:
- id: the exact chapter ID provided
- summary: concise 1-2 paragraph chapter summary in the same language as the chapter
- keywords: 5-8 strong research keywords for updating this chapter
- core_claims: up to 5 major claims or takeaways from the original chapter
- dated_facts: up to 5 original facts/statements that contain dates, years, or timeline-sensitive information
- named_entities: up to 10 important organizations, products, institutions, or people mentioned
- stats: up to 8 important numbers, percentages, or financial/statistical values from the original text
- original_citations: citation markers or source markers explicitly present in the original text
- original_figures: figure, table, image, or asset references explicitly present in the original text
- chapter_role: one of introduction, body, conclusion, appendix
- language: detected language of the chapter

Return ONLY valid JSON in this format:
{{
  "chapters": [
    {{
      "id": "chapter-id",
      "summary": "...",
      "keywords": ["..."],
      "core_claims": ["..."],
      "dated_facts": ["..."],
      "named_entities": ["..."],
      "stats": ["..."],
      "original_citations": ["..."],
      "original_figures": ["..."],
      "chapter_role": "body",
      "language": "English"
    }}
  ]
}}

Every input chapter must produce exactly one output item. Do not omit IDs. Keep the output faithful to each chapter and do not invent facts.

CHAPTERS:
{"".join(chapter_blocks)}
"""


def _analyze_chunk_with_batch_model(api_key: str, chapters: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    prompt = _build_batch_prompt(chapters)

    start_time = time.time()
    response = gemini_generate_content(
        api_key=api_key,
        model='gemini-2.5-flash',
        contents=prompt,
        response_mime_type="application/json",
    )
    text_resp = response.text.strip()
    parsed = try_parse_json(text_resp)
    items = _extract_batch_items(parsed)
    if not items:
        raise ValueError("Batch analyzer returned no chapter items.")

    results_by_id: Dict[str, Dict[str, Any]] = {}
    for item in items:
        chapter_id = str(item.get("id", "")).strip()
        if not chapter_id:
            continue
        results_by_id[chapter_id] = item

    logger.info(
        "Batch chapter analysis complete for %s chapter(s) in %.2fs.",
        len(chapters),
        time.time() - start_time,
    )
    return results_by_id


def analyze_chapters_batch(
    chapters: List[Dict[str, Any]],
    max_chars: int = _BATCH_MAX_CHARS,
    max_chapters: int = _BATCH_MAX_CHAPTERS,
) -> Dict[str, Dict[str, Any]]:
    """
    Analyzes multiple chapters in batched Gemini calls and returns a mapping of
    chapter_id -> normalized analysis. If a batch response is malformed or
    incomplete, the missing chapters automatically fall back to single-chapter
    analysis to preserve behavior.
    """
    if not chapters:
        return {}

    logger.info("Starting batched analysis for %s chapter(s).", len(chapters))
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.error("GEMINI_API_KEY missing.")
        return {
            str(chapter.get("id") or f"chapter_{index + 1}"): _fallback_analysis(
                str(chapter.get("title", "")),
                str(chapter.get("content", "")),
            )
            for index, chapter in enumerate(chapters)
        }

    normalized_results: Dict[str, Dict[str, Any]] = {}
    chunks = _chunk_chapters_for_batch(chapters, max_chars=max_chars, max_chapters=max_chapters)

    skip_remote_analysis = False

    for chunk_index, chunk in enumerate(chunks, start=1):
        logger.info(
            "Analyzing chunk %s/%s with %s chapter(s).",
            chunk_index,
            len(chunks),
            len(chunk),
        )

        if skip_remote_analysis:
            logger.warning(
                "Skipping Gemini batch analysis for chunk %s/%s because a prior chunk hit quota/rate limits. Using local fallback analysis.",
                chunk_index,
                len(chunks),
            )
            for chapter in chunk:
                chapter_id = chapter["id"]
                normalized_results[chapter_id] = _fallback_analysis(chapter["title"], chapter["content"])
            continue

        chunk_results: Dict[str, Dict[str, Any]] = {}
        chunk_hit_quota_limit = False
        try:
            chunk_results = _analyze_chunk_with_batch_model(api_key, chunk)
        except Exception as exc:
            chunk_hit_quota_limit = _is_quota_or_rate_limit_error(exc)
            if chunk_hit_quota_limit:
                skip_remote_analysis = True
                logger.warning(
                    "Batch analysis hit quota/rate limits for chunk %s/%s: %s. Using local fallback analysis for this chunk and remaining chunks.",
                    chunk_index,
                    len(chunks),
                    exc,
                    exc_info=True,
                )
            else:
                logger.warning(
                    "Batch analysis failed for chunk %s/%s: %s. Falling back to single-chapter analysis.",
                    chunk_index,
                    len(chunks),
                    exc,
                    exc_info=True,
                )

        for chapter in chunk:
            chapter_id = chapter["id"]
            raw_result = chunk_results.get(chapter_id)
            if raw_result is None:
                if chunk_hit_quota_limit:
                    normalized_results[chapter_id] = _fallback_analysis(chapter["title"], chapter["content"])
                    continue
                logger.warning(
                    "Missing batch analysis result for chapter '%s' (%s). Falling back to single-chapter analysis.",
                    chapter.get("title", "Untitled Chapter"),
                    chapter_id,
                )
                normalized_results[chapter_id] = analyze_chapter_content(chapter["title"], chapter["content"])
                continue

            normalized_results[chapter_id] = _normalize_result(raw_result, chapter["title"], chapter["content"])

    return normalized_results


def analyze_chapter_content(title: str, text: str) -> Dict[str, Any]:
    """
    Analyzes raw chapter text to generate a structured baseline used to update
    the chapter into a new edition.
    """
    logger.info(f"Starting analysis for chapter: '{title}' (Length: {len(text)})")

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.error("GEMINI_API_KEY missing.")
        return _fallback_analysis(title, text)

    prompt = f"""
    You are an expert report editor preparing a legacy chapter for a future edition update.

    CHAPTER TITLE:
    {title}

    CHAPTER TEXT:
    ---
    {text[:12000]}
    ---
    (Text truncated for analysis if too long)

    TASK:
    Produce a structured baseline of this chapter.

    Return valid JSON with these fields:
    - summary: concise 1-2 paragraph chapter summary in the same language as the chapter
    - keywords: 5-8 strong research keywords for updating this chapter
    - core_claims: up to 5 major claims or takeaways from the original chapter
    - dated_facts: up to 5 original facts/statements that contain dates, years, or timeline-sensitive information
    - named_entities: up to 10 important organizations, products, institutions, or people mentioned
    - stats: up to 8 important numbers, percentages, or financial/statistical values from the original text
    - original_citations: citation markers or source markers explicitly present in the original text
    - original_figures: figure, table, image, or asset references explicitly present in the original text
    - chapter_role: one of introduction, body, conclusion, appendix
    - language: detected language of the chapter

    Keep the output faithful to the original text. Do not invent facts.
    """

    start_time = time.time()
    try:
        response = gemini_generate_content(
            api_key=api_key,
            model='gemini-2.5-flash',
            contents=prompt,
            response_mime_type="application/json",
        )
        text_resp = response.text.strip()
        try:
            result = try_parse_json(text_resp)
        except json.JSONDecodeError:
            logger.warning("Chapter analysis JSON decode failed, attempting ordered salvage.")
            result = salvage_ordered_json(text_resp, ANALYSIS_SCHEMA)
        normalized = _normalize_result(result, title, text)
        logger.info(f"Chapter analysis complete in {time.time() - start_time:.2f}s")
        return normalized
    except Exception as e:
        logger.error(f"Error analyzing chapter '{title}': {e}", exc_info=True)
        return _fallback_analysis(title, text)


if __name__ == "__main__":
    sample_text = "The global AI market is expected to reach $1 trillion by 2030. Key drivers include generative AI and automation."
    print(json.dumps(analyze_chapter_content("AI Market Outlook", sample_text), indent=2))
