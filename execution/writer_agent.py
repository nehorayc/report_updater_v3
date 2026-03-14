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

    THINK STEP BY STEP (do not output this reasoning, just follow the process):
    Step 1 — Identify every outdated claim, statistic, or date in the original text.
    Step 2 — For each outdated item, find the best replacement fact from the Research Findings above.
    Step 3 — Only then write the new chapter text, integrating those replacements naturally.

    CRITICAL WRITING STYLE RULES:
    - You are the ORIGINAL AUTHOR updating your own report with newer data.
    - MATCH the original text's writing style, structure, tone, and formatting exactly.
    - Do NOT explain how the chapter differs from the previous version.
    - Do NOT write phrases like "this section has been updated", "unlike the previous version", "compared to the earlier report", or "in the previous edition".
    - Simply write the updated chapter as if it were the current, authoritative version. The reader should NOT notice it was rewritten.
    - Mirror the original text's paragraph structure, heading style, and level of detail.

    TASK:
    Rewrite the chapter to be modern, accurate, and professional, adhering strictly to the '{writing_style}' style.
    1. Update facts and statistics using the research findings.
    2. Maintain the core message, structure, and tone of the original text.
    3. Be specific: cite exact numbers, percentages, named organizations, and years. Avoid generic claims like "the market is growing" — always quantify.
    4. Use numbered inline citations: [1], [2], [3], etc. Each number must correspond to the index in the "references" list you provide (1-indexed). Every factual claim from research must have a citation.
    5. {update_instructions}
    
    CRITICAL - VISUAL MARKERS:
    - The original text may contain existing figure markers with real hex IDs (e.g. [Figure 4a1b2c3d: Caption]).
    - You MUST preserve those existing markers in the appropriate context within your 'text_content'.
    - If you are UPDATING or RECREATING an existing visual, insert a marker using ONLY the real ID provided in the update instructions above (e.g. [Figure <actual_id>: Caption]).
    - Do NOT invent IDs. Do NOT use placeholder text like "XXXXXXXX". Only use IDs explicitly listed in the update instructions.
    - For BRAND-NEW visual suggestions, do NOT insert a marker in text_content — just add the suggestion to the 'visual_suggestions' list.

    6. MANDATORY: Suggest at least 2 NEW visuals. Each must be EITHER a 'graph' (data chart) OR an 'image' (stock photo/diagram).
       Use 'graph' when you have or can estimate specific numerical data.
       Use 'image' for conceptual illustrations, photos, or diagrams without hard numbers.
       CRITICAL: use EXACTLY "graph" or "image" as the type value — no other strings.
    7. BIBLIOGRAPHY (MANDATORY): 
       - Provide an ORDERED list of references. The order MUST match the numbered inline citations [1], [2], etc. in the text.
       - Include an "index" field with the reference number (1, 2, 3, ...).
       - Ensure a mix of categories:
         - "Academic": For research papers, journals, or scholarly articles (if found in research).
         - "Web": For news articles, reports, and websites (from research findings).
         - "Original": For the original report content/data.
         - "Uploaded": For information from recently uploaded reference documents.
       - ANTI-HALLUCINATION RULE (CRITICAL): You MUST NOT invent URLs. Only include a `url` field if the exact URL appears verbatim in the Research Findings section above. If no URL is available for a source, omit the `url` field entirely or set it to null.

    OUTPUT FORMAT (MANDATORY JSON):
    {{
      "text_content": "The markdown-formatted text with [1], [2] citations...",
      "visual_suggestions": [
        {{
          "type": "graph",
          "title": "Short descriptive title",
          "description": "What this graph shows and why it is relevant",
          "chart_type": "bar",
          "data_points": {{
            "labels": ["Label A", "Label B"],
            "values": [10, 20],
            "unit": "USD Billions"
          }}
        }},
        {{
          "type": "image",
          "title": "Short descriptive title",
          "description": "What this image should show",
          "query": "specific English DuckDuckGo search query for the image"
        }}
      ],
      "references": [
        {{
          "index": 1,
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
