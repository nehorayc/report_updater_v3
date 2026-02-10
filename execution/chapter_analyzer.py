import google.generativeai as genai
import os
import json
from dotenv import load_dotenv
from typing import Dict, List, Any
from logger_config import setup_logger
import time

load_dotenv()
logger = setup_logger("ChapterAnalyzer")

def analyze_chapter_content(title: str, text: str) -> Dict[str, Any]:
    """
    Analyzes raw chapter text to generate a concise summary and search keywords.
    """
    logger.info(f"Starting analysis for chapter: '{title}' (Length: {len(text)})")
    
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.error("GEMINI_API_KEY missing.")
        return {
            "summary": text[:500] + "...", # Fallback
            "keywords": title.split()
        }

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-2.5-flash')

    prompt = f"""
    You are an expert content strategist. Analyze the following chapter text from a report.
    
    CHAPTER TITLE: {title}
    
    CHAPTER TEXT:
    ---
    {text[:10000]} 
    ---
    (Text truncated for analysis if too long)

    TASK:
    1. SUMMARY: Write a concise summary (1-2 paragraphs) of the key points, arguments, and data in this chapter. This summary will be used by a researcher to find updated information.
    2. KEYWORDS: Extract 5-10 specific, high-value search keywords or short phrases that would help a researcher find UPDATED information on this topic (e.g., instead of "Market", use "AI Market Size 2025").

    OUTPUT FORMAT (MANDATORY JSON):
    {{
      "summary": "The summary text...",
      "keywords": ["Keyword 1", "Keyword 2", "Keyword 3"]
    }}
    """
    
    start_time = time.time()
    try:
        response = model.generate_content(prompt)
        text_resp = response.text
        
        # Clean JSON
        if "```json" in text_resp:
            text_resp = text_resp.split("```json")[1].split("```")[0].strip()
        elif "```" in text_resp:
            text_resp = text_resp.split("```")[1].split("```")[0].strip()
            
        result = json.loads(text_resp)
        logger.info(f"Chapter analysis complete in {time.time() - start_time:.2f}s")
        return result
        
    except Exception as e:
        logger.error(f"Error analyzing chapter '{title}': {e}", exc_info=True)
        return {
            "summary": text[:500] + "...",
            "keywords": title.split()
        }

if __name__ == "__main__":
    # Test
    sample_text = "The global AI market is expected to reach $1 trillion by 2030. Key drivers include generative AI and automation."
    print(analyze_chapter_content("AI Market Outlook", sample_text))
