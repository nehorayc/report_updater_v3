import os
import google.generativeai as genai
from typing import Dict, List
import json
from dotenv import load_dotenv

load_dotenv()

from logger_config import setup_logger
import time

logger = setup_logger("Translator")

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

    genai.configure(api_key=api_key)
    # Using gemini-2.5-flash for consistent performance across the app
    model = genai.GenerativeModel('gemini-2.5-flash')

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
        response = model.generate_content(prompt)
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
