import google.generativeai as genai
import os
import json
from dotenv import load_dotenv
from typing import List, Dict

load_dotenv()

from logger_config import setup_logger
import time

logger = setup_logger("WriterAgent")

def write_chapter(original_text: str, research_findings: List[Dict], blueprint: Dict, writing_style: str = "Professional", assets_to_update: List[Dict] = [], target_word_count: int = 500) -> Dict:
    """
    Uses Gemini to rewrite a chapter based on research and original text.
    Returns a dictionary with text content and visual suggestions.
    """
    logger.info(f"Starting chapter generation for topic: {blueprint.get('topic')} (Target: {target_word_count} words)")
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.error("GEMINI_API_KEY not found in environment.")
        return {"error": "GEMINI_API_KEY not found"}

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-2.5-flash')

    # Prepare research context
    findings_str = "\n".join([f"- {f['title']}: {f['snippet']} (Source: {f.get('url', 'Internal')})" for f in research_findings])

    # Prepare asset update context
    update_instructions = ""
    if assets_to_update:
        logger.info(f"Preparing update instructions for {len(assets_to_update)} assets.")
        update_instructions = "MANDATORY VISUAL/TABLE UPDATES:\n"
        for a in assets_to_update:
            if a.get('type') == 'table' and a.get('convert_to_text'):
                update_instructions += f"- CONVERT TO TEXT: Replace Figure '{a.get('short_caption')}' (ID: {a['id']}) with this markdown table: {a.get('analysis', {}).get('table_markdown')}. Integrate it into the text flow.\n"
            elif a.get('type') == 'table' and a.get('do_update'):
                 update_instructions += f"- UPDATE TABLE: Recreate Figure '{a.get('short_caption')}' (ID: {a['id']}) as a Markdown table using NEW data from research. Original structure: {a.get('description')}\n"
            else:
                update_instructions += f"- RECREATE GRAPH: Recreate Figure '{a.get('short_caption')}' (Original ID: {a['id']}) using NEW data from research (extending to Present). Description: {a.get('description')}\n"
        update_instructions += "For each of these items, you MUST include a [Figure ID] marker in the appropriate place in 'text_content' (using the ID provided) so it appears in the final report.\n"

    prompt = f"""
    Original Report Chapter Text:
    ---
    {original_text}
    ---

    Recent Research Findings:
    ---
    {findings_str}
    ---

    User Objective (Blueprint):
    - Topic: {blueprint.get('topic')}
    - Timeframe: {blueprint.get('timeframe')}
    - Additional Instructions: {blueprint.get('instructions', 'None')}
    - Writing Style: {writing_style}
    - TARGET LENGTH: Approximately {target_word_count} words.

    TASK:
    Rewrite the chapter to be modern, accurate, and professional, adhering strictly to the '{writing_style}' style.
    1. Update facts and statistics using the research findings.
    2. Maintain the core message but adjust the tone to match the requested style.
    3. Include inline citations like [Source: Name].
    4. {update_instructions}
    
    CRITICAL - VISUAL MARKERS:
    - The original text contains markers like [Figure XXXXXXXX: Caption]. 
    - You MUST preserve these markers in the appropriate context within your 'text_content'.
    - If you suggest a NEW visual or update an existing one, you MUST insert a marker like [Figure XXXXXXXX] in the 'text_content'.

    5. MANDATORY: Suggest at least 2 NEW visuals (graphs or search-based images) to enhance understanding.
    6. BIBLIOGRAPHY (MANDATORY): 
       - Provide a list of AT LEAST 5 references used in this chapter.
       - Ensure a mix of categories:
         - "Academic": For research papers, journals, or scholarly articles (if found in research).
         - "Web": For news articles, reports, and websites (from research findings).
         - "Original": For the original report content/data.
         - "Uploaded": For information from recently uploaded reference documents.
       - IMPORTANT: If a URL was provided in the research findings, you MUST include it in the reference.

    OUTPUT FORMAT (MANDATORY JSON):
    {{
      "text_content": "The markdown-formatted text...",
      "visual_suggestions": [ ... ],
      "references": [
        {{
          "title": "Exact Title of Source", 
          "url": "http://...", 
          "category": "Web" 
        }}
      ]
    }}
    """

    # Use JSON mode for guaranteed valid JSON output
    generation_config = {"response_mime_type": "application/json"}

    logger.debug(f"Prompt sent to Gemini (truncated): {prompt[:500]}...")
    start_time = time.time()
    try:
        response = model.generate_content(prompt, generation_config=generation_config)
        latency = time.time() - start_time
        logger.info(f"Gemini response received in {latency:.2f}s.")
        
        text = response.text
        # Log FULL response for debugging persistent issues
        logger.debug(f"FULL Gemini Response:\n{text}")
        
        # In JSON mode, we shouldn't get markdown fences, but safety first
        text = text.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
        
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("JSON decode failed, attempting to repair...")
            # Simple repair: sometimes there are trailing commas or unescaped quotes
            import re
            # Remove trailing commas in arrays/objects
            text = re.sub(r',\s*([\]}])', r'\1', text)
            try:
                parsed = json.loads(text)
            except:
                 logger.error("JSON repair failed.")
                 # Fallback: if we have text but bad JSON, try to salvage text_content
                 if '"text_content":' in text:
                     # Heuristic extraction
                     start = text.find('"text_content":') + 15
                     # Try to find the end of the text_content string (risky if content has escaped quotes)
                     # Better heuristic: split by unique key that follows, e.g. "visual_suggestions"
                     if '"visual_suggestions"' in text:
                         end = text.find('"visual_suggestions"')
                         # Backtrack to find the comma and quote
                         # This is very rough, but better than nothing
                         raw_content = text[start:end].strip().strip(',').strip('"')
                         parsed = {"text_content": raw_content.replace('\\n', '\n').replace('\\"', '"'), "visual_suggestions": [], "references": []}
                     else:
                         # Fallback to previous simple split
                         parsed = {"text_content": text[start:].split('",\n')[0].strip('"').replace('\\n', '\n'), "visual_suggestions": [], "references": []}
                 else:
                     raise

        logger.info(f"Successfully generated chapter. Text length: {len(parsed.get('text_content', ''))}")
        return parsed
    except Exception as e:
        logger.error(f"Failed to generate chapter: {e}", exc_info=True)
        return {"error": f"Failed to generate chapter: {str(e)}", "raw_content": response.text if 'response' in locals() else ""}

if __name__ == "__main__":
    # Test call
    res = write_chapter("AI is growing.", [{"title": "AI in 2025", "snippet": "Market grew by 40% in 2024.", "url": "example.com"}], {"topic": "AI Trends"})
    print(json.dumps(res, indent=2))
