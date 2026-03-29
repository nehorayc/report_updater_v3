import os
from typing import Any, Dict, List
import json
from dotenv import load_dotenv
from llm_json_utils import try_parse_json
from gemini_client import generate_content as gemini_generate_content

load_dotenv()

from logger_config import setup_logger
import time

logger = setup_logger("Translator")

_TRANSLATION_BATCH_MAX_ITEMS = 8
_TRANSLATION_BATCH_MAX_CHARS = 32000


def _build_translation_prompt(items: List[Dict[str, str]], target_lang: str, preserve_markdown: bool) -> str:
    format_rules = (
        "Maintain EXACT Markdown formatting, tables, and [Figure XXXXXXXX] or [Asset: XXXXXXXX] markers."
        if preserve_markdown
        else "Return clean translated plain text for each item with no markdown fences or extra commentary."
    )
    item_blocks = "\n".join(
        f'ID: {item["id"]}\nTEXT:\n---\n{item["text"]}\n---'
        for item in items
    )
    return f"""
You are a professional technical translator.
Translate each item into {target_lang}.

CRITICAL INSTRUCTIONS:
1. {format_rules}
2. Preserve the professional tone of the original.
3. If the source contains Hebrew that looks reversed or garbled, correct it naturally in translation.
4. Do NOT include page numbers, headers, or footers from the original text.
5. Return ONLY valid JSON in this format:
{{
  "translations": [
    {{"id": "0", "text": "translated text"}}
  ]
}}

ITEMS:
{item_blocks}
"""


def _chunk_translation_items(texts: List[str]) -> List[List[Dict[str, str]]]:
    chunks: List[List[Dict[str, str]]] = []
    current_chunk: List[Dict[str, str]] = []
    current_chars = 0

    for index, text in enumerate(texts):
        item = {"id": str(index), "text": str(text or "")}
        estimated_chars = len(item["text"]) + 200
        should_flush = (
            current_chunk
            and (
                len(current_chunk) >= _TRANSLATION_BATCH_MAX_ITEMS
                or current_chars + estimated_chars > _TRANSLATION_BATCH_MAX_CHARS
            )
        )
        if should_flush:
            chunks.append(current_chunk)
            current_chunk = []
            current_chars = 0

        current_chunk.append(item)
        current_chars += estimated_chars

    if current_chunk:
        chunks.append(current_chunk)
    return chunks


def _extract_batch_translations(parsed: Any) -> Dict[str, str]:
    if isinstance(parsed, dict):
        parsed = parsed.get("translations", parsed)
    if not isinstance(parsed, list):
        return {}

    translations: Dict[str, str] = {}
    for item in parsed:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id", "")).strip()
        text = str(item.get("text", "")).strip()
        if item_id:
            translations[item_id] = text
    return translations


def translate_texts_batch(texts: List[str], target_lang: str, preserve_markdown: bool = True) -> List[str]:
    """
    Translates multiple texts in batched Gemini calls and returns them in the
    same order. Missing batch items fall back to single-item translation.
    """
    if not texts:
        return []

    logger.info("Starting batched translation to %s for %s item(s).", target_lang, len(texts))
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.error("GEMINI_API_KEY not found in environment.")
        return list(texts)

    translated_by_index: Dict[int, str] = {}

    for chunk in _chunk_translation_items(texts):
        prompt = _build_translation_prompt(chunk, target_lang, preserve_markdown=preserve_markdown)
        try:
            response = gemini_generate_content(
                api_key=api_key,
                model='gemini-2.5-flash',
                contents=prompt,
                response_mime_type="application/json",
            )
            mapped = _extract_batch_translations(try_parse_json(response.text.strip()))
        except Exception as exc:
            logger.error("Batched translation error for %s: %s", target_lang, exc, exc_info=True)
            mapped = {}

        for item in chunk:
            index = int(item["id"])
            translated = mapped.get(item["id"])
            if translated:
                translated_by_index[index] = translated.strip()
            else:
                translated_by_index[index] = translate_content(item["text"], target_lang).strip()

    return [translated_by_index.get(index, str(texts[index] or "")) for index in range(len(texts))]

def translate_content(text: str, target_lang: str) -> str:
    """
    Translates report content into the target language using Gemini.
    Preserves markdown formatting, tables, and [Figure ID] markers.
    """
    logger.info(f"Starting translation to {target_lang}. Text length: {len(text)}")
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.error("GEMINI_API_KEY not found in environment.")
        return text # Fallback

    prompt = f"""
    You are a professional technical translator. 
    Translate the following report chapter into {target_lang}.
    
    CRITICAL INSTRUCTIONS:
    1. Maintain EXACT Markdown formatting (headers, bold, lists).
    2. DO NOT translate technical identifiers like [Figure XXXXXXXX] or [Asset: XXXXXXXX]. Leave them exactly as they are.
    3. Maintain the professional tone of the original.
    4. If the text contains Hebrew and it looks reversed or garbled, correct it for natural reading order in the translation.
    5. Translate tables carefully, maintaining the markdown structure.
    6. DO NOT include page numbers, headers, or footers from the original text in the translation.
    
    TEXT TO TRANSLATE:
    ---
    {text}
    ---
    
    OUTPUT: Provide ONLY the translated text.
    """

    logger.debug(f"Translation prompt (truncated): {prompt[:500]}...")
    start_time = time.time()
    try:
        response = gemini_generate_content(
            api_key=api_key,
            model='gemini-2.5-flash',
            contents=prompt,
        )
        latency = time.time() - start_time
        logger.info(f"Translation to {target_lang} complete in {latency:.2f}s.")
        
        translated_text = response.text.strip()
        logger.debug(f"Translated text (truncated): {translated_text[:500]}...")
        return translated_text
    except Exception as e:
        logger.error(f"Translation Error for language {target_lang}: {e}", exc_info=True)
        return f"Translation Error: {str(e)}\n\nOriginal Text:\n{text}"

def translate_chapter_batch(chapter: Dict, target_langs: List[str]) -> Dict[str, str]:
    """
    Translates a single chapter into multiple languages.
    Returns a dict: { 'Hebrew': '...', 'Spanish': '...' }
    """
    translations = {}
    for lang in target_langs:
        translations[lang] = translate_content(chapter['draft_text'], lang)
    return translations
