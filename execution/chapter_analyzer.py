import google.generativeai as genai
import os
import json
import re
from dotenv import load_dotenv
from typing import Dict, List, Any
from logger_config import setup_logger
import time
from llm_json_utils import salvage_ordered_json, try_parse_json

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

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-2.5-flash')

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

    generation_config = {"response_mime_type": "application/json"}

    start_time = time.time()
    try:
        response = model.generate_content(prompt, generation_config=generation_config)
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
