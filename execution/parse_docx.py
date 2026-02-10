from docx import Document
import os
import hashlib
from typing import List, Dict, Any

from logger_config import setup_logger
import time

logger = setup_logger("DocxParser")

def extract_docx_content(file_path: str, output_dir: str = ".tmp/assets") -> Dict[str, Any]:
    """
    Extracts text and images from a DOCX file.
    Uses Word Styles (Heading 1, etc.) to detect chapters.
    """
    logger.info(f"Starting DOCX extraction for: {file_path}")
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    start_time = time.time()
    doc = Document(file_path)
    results = {
        "chapters": [],
        "assets": []
    }

    # 1. Combined Extraction: Extract Text and link Images to Chapters
    current_chapter = {"title": "Introduction", "content": "", "asset_ids": []}
    
    # Helper to save image
    def save_image(image_bytes, ext):
        asset_id = hashlib.md5(image_bytes).hexdigest()
        filename = f"asset_{asset_id}.{ext}"
        saved_path = os.path.join(output_dir, filename)
        if not os.path.exists(saved_path):
            with open(saved_path, "wb") as f:
                f.write(image_bytes)
        return asset_id, saved_path

    # Track distinct assets globally
    distinct_assets = {}

    for para_idx, para in enumerate(doc.paragraphs):
        # Check for heading
        if para.style.name.startswith('Heading') or para.style.name == 'Title':
            if current_chapter["content"].strip() or current_chapter["asset_ids"]:
                results["chapters"].append(current_chapter)
                logger.debug(f"Detected chapter split on स्टाइल '{para.style.name}': '{para.text[:50]}...'")
            current_chapter = {"title": para.text, "content": "", "asset_ids": []}
        else:
            current_chapter["content"] += para.text + "\n"
        
        # Check for images in this paragraph
        for run in para.runs:
            if 'drawing' in run.element.xml:
                # Use low-level XML to find the blip relationship ID
                import re
                rIds = re.findall(r'r:embed="([^"]+)"', run.element.xml)
                for rId in rIds:
                    if rId in doc.part.rels:
                        image_part = doc.part.rels[rId].target_part
                        if "image" in image_part.content_type:
                            ext = image_part.content_type.split('/')[-1]
                            asset_id, saved_path = save_image(image_part.blob, ext)
                            
                            if asset_id not in current_chapter["asset_ids"]:
                                logger.info(f"Found image {asset_id[:8]} in paragraph {para_idx}.")
                                current_chapter["asset_ids"].append(asset_id)
                                # Add marker to content
                                current_chapter["content"] += f" [Asset: {asset_id[:8]}] "
                            
                            distinct_assets[asset_id] = {
                                "id": asset_id,
                                "type": "image",
                                "path": saved_path
                            }

    # Add the last chapter
    if current_chapter["content"].strip() or current_chapter["asset_ids"]:
        results["chapters"].append(current_chapter)

    results["assets"] = list(distinct_assets.values())
    latency = time.time() - start_time
    logger.info(f"DOCX extraction complete in {latency:.2f}s. Found {len(results['chapters'])} chapters and {len(results['assets'])} assets.")
    return results

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        path = sys.argv[1]
        data = extract_docx_content(path)
        print(f"Extracted {len(data['chapters'])} chapters and {len(data['assets'])} images.")
