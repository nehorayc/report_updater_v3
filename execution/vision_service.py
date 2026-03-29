import os
import json
from dotenv import load_dotenv
from typing import List, Dict
from gemini_client import generate_content as gemini_generate_content

load_dotenv()

from logger_config import setup_logger
import time

logger = setup_logger("VisionService")

_RUNTIME_DIAGNOSTICS: List[Dict[str, str]] = []


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
    normalized = " ".join(str(message or "").split())
    if not normalized:
        return
    diagnostic = {"level": level, "message": normalized}
    if diagnostic not in _RUNTIME_DIAGNOSTICS:
        _RUNTIME_DIAGNOSTICS.append(diagnostic)

def analyze_batch_assets(assets: List[Dict]) -> List[Dict]:
    """
    Uses Gemini Vision to analyze a batch of images.
    Expects assets to be a list of dicts with 'id' and 'path'.
    Returns a list of dicts with analysis results.
    """
    logger.info(f"Starting batch analysis for {len(assets)} assets.")
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.error("GEMINI_API_KEY not found in environment.")
        _record_runtime_diagnostic(
            "error",
            "Gemini API key is missing, so the selected assets could not be analyzed.",
        )
        return []

    results = []
    
    # Process in chunks of 5 to avoid payload limits/complexity
    chunk_size = 5
    for i in range(0, len(assets), chunk_size):
        chunk = assets[i:i + chunk_size]
        logger.info(f"Processing chunk {i//chunk_size + 1} ({len(chunk)} images).")
        
        prompt_parts = [
            """
            Analyze these images from a professional report. I will provide them in order.
            For EACH image, output a JSON object with the following fields:
            - id: The ID provided for the image.
            - type: One of "chart", "image", "table".
            - short_caption: A very brief, 1-sentence summary of the content (for a quick caption).
            - table_markdown: If the type is "table", provide the full transcription of the data into a markdown table. Otherwise, leave null.
            - dataset_description: A DETAILED description of the data, axes, content, mood, logic, etc. needed to reconstruct it (if chart) or understand the table structure.
            - suggested_update_query: If it is a chart/graph or table with a timeline (e.g., 2010-2020), provide a search query to find updated data (e.g., "Renewable energy adoption statistics 2020-2025"). Otherwise, leave null.
            
            Return a JSON LIST of these objects.
            """
        ]
        
        for asset in chunk:
            prompt_parts.append(f"Image ID: {asset['id']}")
            try:
                img_data = {
                    "mime_type": "image/png", # Assuming png/jpg, API handles detection usually
                    "data": open(asset['path'], "rb").read()
                }
                prompt_parts.append(img_data)
            except Exception as e:
                logger.error(f"Error loading image {asset['path']}: {e}")
                
        # Use JSON mode for guaranteed valid JSON output
        start_time = time.time()
        try:
            logger.debug(f"Sending request to Gemini for chunk {i//chunk_size + 1}...")
            response = gemini_generate_content(
                api_key=api_key,
                model='gemini-2.5-flash',
                contents=prompt_parts,
                response_mime_type="application/json",
            )
            latency = time.time() - start_time
            logger.info(f"Gemini response received for chunk {i//chunk_size + 1} in {latency:.2f}s.")
            
            text = response.text.strip()
            logger.debug(f"Raw response: {text[:200]}...")

            parsed = json.loads(text)
            if isinstance(parsed, list):
                results.extend(parsed)
                logger.info(f"Successfully parsed {len(parsed)} results from chunk.")
            else:
                 # Fallback if model returns single object instead of list
                 results.append(parsed)
                 logger.info("Successfully parsed 1 result from chunk (fallback).")
                 
        except Exception as e:
            logger.error(f"Error in batch analysis for chunk {i//chunk_size + 1}: {e}", exc_info=True)
            if _is_quota_error(e):
                _record_runtime_diagnostic(
                    "warning",
                    "Gemini quota was exhausted while analyzing selected assets. Captions and update suggestions may be incomplete for this run.",
                )
            else:
                _record_runtime_diagnostic(
                    "error",
                    "Asset analysis failed for one or more selected visuals. Placeholder captions were used instead.",
                )
            # Add placeholders for failed items
            for asset in chunk:
                results.append({
                    "id": asset['id'],
                    "type": "image",
                    "short_caption": "Error analyzing image.",
                    "dataset_description": "Analysis failed.",
                    "suggested_update_query": None
                })

    logger.info(f"Batch analysis complete. Total results: {len(results)}")
    return results

if __name__ == "__main__":
    # Test
    pass
