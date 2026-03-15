import pdfplumber
import fitz  # PyMuPDF
import os
import hashlib
from typing import List, Dict, Any

from logger_config import setup_logger
import time

logger = setup_logger("PDFParser")

def extract_pdf_content(file_path: str, output_dir: str = ".tmp/assets") -> Dict[str, Any]:
    """
    Extracts text and images from a PDF file.
    Attempts to group text by headings/chapters.
    """
    logger.info(f"Starting PDF extraction for: {file_path}")
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    results = {
        "chapters": [],
        "assets": []
    }

    start_time = time.time()
    # 1. Extract Text and track Chapter Page Ranges using fitz (PyMuPDF)
    doc = fitz.open(file_path)
    current_chapter = {"title": "Introduction", "content": "", "pages": []}
    
    # Estimate average font size for heading detection
    all_sizes = []
    for page in doc:
        blocks = page.get_text("dict")["blocks"]
        for b in blocks:
            if b["type"] == 0: # text
                for l in b["lines"]:
                    for s in l["spans"]:
                        all_sizes.append(s["size"])
    
    avg_size = sum(all_sizes) / len(all_sizes) if all_sizes else 10
    logger.info(f"Average font size estimated: {avg_size:.2f}")
    
    import re
    
    for i, page in enumerate(doc):
        page_num = i + 1
        page_height = page.rect.height
        blocks_dict = page.get_text("dict")["blocks"]
        
        for b in blocks_dict:
            if b["type"] != 0: continue # Skip images
            
            # Combine spans into line text
            block_text = ""
            max_size_in_block = 0
            for l in b["lines"]:
                line_text = ""
                for s in l["spans"]:
                    line_text += s["text"]
                    max_size_in_block = max(max_size_in_block, s["size"])
                block_text += line_text + " "
            
            block_text = block_text.strip()
            if not block_text: continue
            
            # ----- Header / Footer / Page Number Filtering -----
            y0 = b["bbox"][1] # top coordinate 
            y1 = b["bbox"][3] # bottom coordinate
            
            # 1. Coordinate check: Is it in the top 8% or bottom 8% of the page?
            is_margin = (y0 < page_height * 0.08) or (y1 > page_height * 0.92)
            
            # 2. Size check: Headers/Footers are almost always average size or smaller.
            is_small = max_size_in_block <= (avg_size * 1.05)
            
            # 3. Pattern check: Catch common page numbers (e.g. "12", "Page 12", "- 12 -", "12 of 20")
            is_page_num = re.match(r'^\s*(Page\s+)?-?\s*\d+\s*-?\s*(of\s+\d+)?\s*$', block_text, re.IGNORECASE)
            
            if (is_margin and is_small) or is_page_num:
                logger.debug(f"Skipping header/footer/page num block: '{block_text[:50]}'")
                continue
            # ---------------------------------------------------

            # Heuristics for heading
            is_numbered = re.match(r'^\d+(\.\d+)*\s+', block_text)
            
            # Check for bold spans
            is_bold = any(s.get("flags", 0) & 2**4 for l in b["lines"] for s in l["spans"]) # 2^4 = bold in MuPDF
            
            # Size threshold - headers are usually larger, but maybe not by 40%
            is_large = max_size_in_block > avg_size * 1.2
            is_short = len(block_text.split()) < 10
            
            # A block is likely a heading if it's short, and either:
            # 1. Much larger than average
            # 2. Slightly larger and bold
            # 3. Numbered and bold
            potential_heading = is_short and (
                (max_size_in_block > avg_size * 1.4) or
                (is_large and is_bold) or
                (is_numbered and is_bold)
            )

            if potential_heading:
                if current_chapter["content"].strip():
                    results["chapters"].append(current_chapter)
                    logger.debug(f"Detected chapter split: '{block_text[:50]}...'")
                current_chapter = {"title": block_text, "content": "", "pages": [page_num]}
            else:
                current_chapter["content"] += block_text + "\n"
                if page_num not in current_chapter["pages"]:
                    current_chapter["pages"].append(page_num)

    if current_chapter["content"].strip():
        results["chapters"].append(current_chapter)

    text_latency = time.time() - start_time
    logger.info(f"Text extraction complete. Found {len(results['chapters'])} chapters in {text_latency:.2f}s.")

    # 2. Extract Images and associate with chapters
    asset_start_time = time.time()
    distinct_assets = {}
    
    for i in range(len(doc)):
        page_num = i + 1
        image_list = doc[i].get_images(full=True)
        
        for img in image_list:
            xref = img[0]
            try:
                base_image = doc.extract_image(xref)
                image_bytes = base_image["image"]
                ext = base_image["ext"]
                
                asset_id = hashlib.md5(image_bytes).hexdigest()
                if asset_id not in distinct_assets:
                    filename = f"asset_{asset_id}.{ext}"
                    saved_path = os.path.join(output_dir, filename)
                    with open(saved_path, "wb") as f:
                        f.write(image_bytes)
                    
                    distinct_assets[asset_id] = {
                        "id": asset_id,
                        "type": "image",
                        "path": saved_path
                    }
                
                # Link this asset_id to chapters covering this page
                for chapter in results["chapters"]:
                    if page_num in chapter.get("pages", []):
                        if "asset_ids" not in chapter:
                            chapter["asset_ids"] = []
                        if asset_id not in chapter["asset_ids"]:
                            chapter["asset_ids"].append(asset_id)
                            # Add marker to chapter summary
                            chapter["content"] += f" [Asset: {asset_id[:8]}] "
            except Exception as e:
                logger.error(f"Error extracting image xref {xref} on page {page_num}: {e}")

    results["assets"] = list(distinct_assets.values())
    asset_latency = time.time() - asset_start_time
    logger.info(f"Asset extraction complete. Found {len(results['assets'])} distinct assets in {asset_latency:.2f}s.")
    return results

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        path = sys.argv[1]
        data = extract_pdf_content(path)
        print(f"Extracted {len(data['chapters'])} chapters and {len(data['assets'])} images.")
