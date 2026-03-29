import fitz  # PyMuPDF
import hashlib
import os
import re
import time
from collections import Counter
from typing import Any, Dict

from logger_config import setup_logger

logger = setup_logger("PDFParser")

RAW_TOC_TITLE_PATTERNS = (
    "table of contents",
    "contents",
    "toc",
    "\u05ea\u05d5\u05db\u05df",
    "\u05ea\u05d5\u05db\u05df \u05e2\u05e0\u05d9\u05d9\u05e0\u05d9\u05dd",
)
RUN_DATE_PATTERN = re.compile(r"^\s*run date\s*:", re.IGNORECASE)
PAGE_MARKER_PATTERN = re.compile(r"^\s*(?:page\s+)?\d+\s*(?:/|of)\s*\d+\s*$", re.IGNORECASE)
NUMBERED_HEADING_PREFIX_PATTERN = re.compile(r"^\s*\d+(?:\.\d+)*(?:[.)])?\s+")
BULLET_PREFIX_PATTERN = re.compile(r"^\s*(?:[\u2022*-]|\d+[.)])\s+")
HEADING_HINT_PATTERNS = [
    re.compile(r"^(?:Executive Summary|Key Findings|Overview|Introduction|Background|Conclusion)$", re.IGNORECASE),
]


def _normalize_heading_text(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip().strip(":")
    cleaned = re.sub(r"^[#\-\*\u2022]+\s*", "", cleaned)
    return cleaned.lower()


TOC_TITLE_PATTERNS = {_normalize_heading_text(value) for value in RAW_TOC_TITLE_PATTERNS}


def _is_page_marker_text(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return False
    if PAGE_MARKER_PATTERN.match(stripped):
        return True
    compact = re.sub(r"[\s:]+", "", stripped)
    return bool(re.fullmatch(r"\d+/\d+", compact))


def _starts_with_bullet(text: str) -> bool:
    return bool(BULLET_PREFIX_PATTERN.match(str(text or "")))


def _is_internal_heading_line(text: str) -> bool:
    stripped = str(text or "").strip().strip(":")
    if not stripped:
        return False
    if _is_page_marker_text(stripped):
        return False
    if stripped.startswith("["):
        return False

    heading_candidate = NUMBERED_HEADING_PREFIX_PATTERN.sub("", stripped).strip().strip(":")
    if not heading_candidate:
        return False
    if not re.match(r"^[A-Za-z\u0590-\u05FF]", heading_candidate):
        return False
    if heading_candidate.endswith((".", ",", ";")):
        return False

    words = heading_candidate.split()
    if len(words) > 7 or len(heading_candidate) > 80:
        return False
    if any(pattern.match(heading_candidate) for pattern in HEADING_HINT_PATTERNS):
        return True
    if re.search(r'[.,;!?()\[\]/"\'`]', heading_candidate):
        return False

    alpha_chars = sum(1 for char in heading_candidate if char.isalpha())
    if re.search(r"\d", heading_candidate):
        return False
    return alpha_chars >= 4 and len(words) <= 4


def _structure_single_chapter_text(text: str) -> str:
    lines = [line.strip() for line in str(text or "").splitlines()]
    if not lines:
        return ""

    cleaned_lines = []
    for line in lines:
        if not line or _is_page_marker_text(line):
            continue
        if _is_internal_heading_line(line):
            normalized_heading = NUMBERED_HEADING_PREFIX_PATTERN.sub("", line).strip().strip(":")
            if cleaned_lines and cleaned_lines[-1] != "":
                cleaned_lines.append("")
            cleaned_lines.append(f"## {normalized_heading or line}")
            cleaned_lines.append("")
        else:
            cleaned_lines.append(line)

    cleaned_text = "\n".join(cleaned_lines)
    cleaned_text = re.sub(r"\n{3,}", "\n\n", cleaned_text).strip()
    return cleaned_text


def _estimate_average_font_size(doc: fitz.Document) -> float:
    all_sizes = []
    for page in doc:
        for block in page.get_text("dict")["blocks"]:
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    all_sizes.append(span["size"])
    return (sum(all_sizes) / len(all_sizes)) if all_sizes else 10.0


def _extract_text_blocks(doc: fitz.Document, avg_size: float) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for page_index, page in enumerate(doc):
        page_num = page_index + 1
        page_height = page.rect.height
        page_width = page.rect.width
        for raw_block in page.get_text("dict")["blocks"]:
            if raw_block.get("type") != 0:
                continue

            line_texts = []
            max_size_in_block = 0.0
            spans = []
            for line in raw_block.get("lines", []):
                text = "".join(span["text"] for span in line.get("spans", []))
                if text.strip():
                    line_texts.append(text.strip())
                spans.extend(line.get("spans", []))
                for span in line.get("spans", []):
                    max_size_in_block = max(max_size_in_block, span["size"])

            block_text = " ".join(line_texts).strip()
            if not block_text:
                continue

            y0 = raw_block["bbox"][1]
            y1 = raw_block["bbox"][3]
            is_margin = (y0 < page_height * 0.08) or (y1 > page_height * 0.92)
            is_small = max_size_in_block <= (avg_size * 1.05)
            is_page_num = re.match(r"^\s*(Page\s+)?-?\s*\d+\s*-?\s*(of\s+\d+)?\s*$", block_text, re.IGNORECASE)
            if (is_margin and is_small) or is_page_num or _is_page_marker_text(block_text):
                logger.debug("Skipping header/footer/page num block: '%s'", block_text[:50])
                continue

            x0 = raw_block["bbox"][0]
            x1 = raw_block["bbox"][2]
            center_x = (x0 + x1) / 2.0
            blocks.append(
                {
                    "index": len(blocks),
                    "text": block_text,
                    "normalized": _normalize_heading_text(block_text),
                    "page_num": page_num,
                    "bbox": raw_block["bbox"],
                    "max_size": max_size_in_block,
                    "is_bold": any(span.get("flags", 0) & 2**4 for span in spans),
                    "word_count": len(block_text.split()),
                    "starts_with_bullet": _starts_with_bullet(block_text),
                    "is_numbered": bool(re.match(r"^\d+(?:\.\d+)*\s+", block_text)),
                    "centered": abs(center_x - (page_width / 2.0)) < (page_width * 0.12),
                }
            )
    return blocks


def _looks_like_heading_candidate(block: dict[str, Any], avg_size: float) -> bool:
    text = str(block.get("text", "")).strip()
    if not text or _is_page_marker_text(text):
        return False
    if block.get("starts_with_bullet"):
        return False
    if RUN_DATE_PATTERN.match(text):
        return False
    if block.get("word_count", 0) > 12:
        return False
    if len(text) > 120:
        return False
    if sum(1 for char in text if char.isalpha()) < 3:
        return False
    if re.search(r"https?://|www\.", text, re.IGNORECASE):
        return False
    if text.endswith((".", ";", "?", "!")) and block.get("word_count", 0) > 4:
        return False

    size_signal = block.get("max_size", 0) > avg_size * 1.18
    bold_signal = block.get("is_bold") and block.get("max_size", 0) > avg_size * 1.02
    numbered_signal = block.get("is_numbered") and block.get("max_size", 0) > avg_size * 0.95
    centered_signal = block.get("centered") and block.get("max_size", 0) > avg_size * 1.3 and block.get("word_count", 0) <= 8
    return bool(size_signal or bold_signal or numbered_signal or centered_signal)


def _next_block_on_same_page(blocks: list[dict[str, Any]], index: int) -> dict[str, Any] | None:
    page_num = blocks[index]["page_num"]
    for next_index in range(index + 1, len(blocks)):
        candidate = blocks[next_index]
        if candidate["page_num"] != page_num:
            return None
        return candidate
    return None


def _looks_like_body_start_after_toc(
    block: dict[str, Any],
    next_block: dict[str, Any] | None,
    avg_size: float,
    found_titles: int,
) -> bool:
    if found_titles < 2:
        return False
    if not _looks_like_heading_candidate(block, avg_size):
        return False
    if next_block and next_block.get("starts_with_bullet"):
        return False
    return block.get("max_size", 0) > avg_size * 1.4


def _looks_like_toc_entry(block: dict[str, Any], next_block: dict[str, Any] | None, avg_size: float) -> bool:
    if block.get("normalized") in TOC_TITLE_PATTERNS:
        return False
    if block.get("word_count", 0) > 8:
        return False
    if not next_block or not next_block.get("starts_with_bullet"):
        return False
    return bool(
        block.get("is_bold")
        or block.get("centered")
        or block.get("max_size", 0) >= avg_size * 0.9
    )


def _extract_outline_titles(doc: fitz.Document) -> list[str]:
    try:
        outline = doc.get_toc(simple=True)
    except Exception:
        return []

    titles = []
    seen = set()
    for item in outline:
        if len(item) < 2:
            continue
        level, title = item[0], str(item[1]).strip()
        normalized = _normalize_heading_text(title)
        if level != 1 or not normalized or normalized in TOC_TITLE_PATTERNS or normalized in seen:
            continue
        seen.add(normalized)
        titles.append(title)
    return titles


def _extract_printed_toc_metadata(blocks: list[dict[str, Any]], avg_size: float) -> tuple[list[str], set[int]]:
    start_index = next((block["index"] for block in blocks if block["normalized"] in TOC_TITLE_PATTERNS), None)
    if start_index is None:
        return [], set()

    start_page = blocks[start_index]["page_num"]
    toc_titles = []
    seen_titles = set()
    skip_indices: set[int] = set()

    for index in range(start_index, len(blocks)):
        block = blocks[index]
        if block["page_num"] > start_page + 2:
            break

        next_block = _next_block_on_same_page(blocks, index)
        if _looks_like_body_start_after_toc(block, next_block, avg_size, len(toc_titles)):
            break

        skip_indices.add(index)
        if _looks_like_toc_entry(block, next_block, avg_size):
            normalized = block["normalized"]
            if normalized not in seen_titles:
                seen_titles.add(normalized)
                toc_titles.append(block["text"].strip())

    if len(toc_titles) < 2:
        return [], set()
    return toc_titles, skip_indices


def _derive_heading_size_bands(
    blocks: list[dict[str, Any]],
    avg_size: float,
    skip_indices: set[int],
) -> dict[str, float]:
    candidates = [
        block
        for block in blocks
        if block["index"] not in skip_indices and _looks_like_heading_candidate(block, avg_size)
    ]
    if not candidates:
        return {
            "top_level_threshold": avg_size * 1.6,
            "secondary_threshold": avg_size * 1.25,
            "top_size": avg_size * 1.6,
        }

    size_counts = Counter(
        round(block["max_size"], 2)
        for block in candidates
        if block["max_size"] > avg_size * 1.08
    )
    ordered_sizes = sorted(size_counts, reverse=True)
    if len(ordered_sizes) > 1 and size_counts[ordered_sizes[0]] == 1 and ordered_sizes[0] > ordered_sizes[1] * 1.6:
        ordered_sizes = ordered_sizes[1:]
    if not ordered_sizes:
        ordered_sizes = [round(max(block["max_size"] for block in candidates), 2)]

    top_size = ordered_sizes[0]
    second_size = ordered_sizes[1] if len(ordered_sizes) > 1 else max(avg_size * 1.18, top_size * 0.82)
    third_size = ordered_sizes[2] if len(ordered_sizes) > 2 else max(avg_size * 1.08, second_size * 0.9)

    return {
        "top_level_threshold": ((top_size + second_size) / 2.0) if len(ordered_sizes) > 1 else top_size - 0.01,
        "secondary_threshold": ((second_size + third_size) / 2.0) if len(ordered_sizes) > 2 else second_size - 0.01,
        "top_size": top_size,
    }


def _detect_heading_level(
    block: dict[str, Any],
    avg_size: float,
    top_level_titles: set[str],
    size_bands: dict[str, float],
) -> int:
    normalized = block.get("normalized", "")
    if top_level_titles:
        if normalized in top_level_titles and (
            _looks_like_heading_candidate(block, avg_size) or block.get("max_size", 0) >= avg_size * 1.3
        ):
            return 1
        if (
            block.get("word_count", 0) <= 8
            and not block.get("starts_with_bullet")
            and sum(1 for char in block.get("text", "") if char.isalpha()) >= 3
            and block.get("max_size", 0) >= avg_size * 1.1
        ):
            if block.get("max_size", 0) >= size_bands["secondary_threshold"]:
                return 2
            return 3
        if not _looks_like_heading_candidate(block, avg_size):
            return 0
        if block.get("max_size", 0) >= size_bands["secondary_threshold"]:
            return 2
        return 3

    if not _looks_like_heading_candidate(block, avg_size):
        return 0

    if block.get("max_size", 0) >= size_bands["top_level_threshold"]:
        if block.get("centered") or block.get("max_size", 0) >= size_bands["top_size"] - 0.05 or block.get("word_count", 0) <= 3:
            return 1
    if block.get("max_size", 0) >= size_bands["secondary_threshold"]:
        return 2
    return 3


def _start_chapter(title: str, page_num: int) -> dict[str, Any]:
    return {
        "title": title.strip() or "Untitled Chapter",
        "normalized_title": _normalize_heading_text(title),
        "content_lines": [],
        "pages": [page_num],
    }


def _ensure_chapter_page(chapter: dict[str, Any], page_num: int) -> None:
    if page_num not in chapter["pages"]:
        chapter["pages"].append(page_num)


def _append_paragraph(chapter: dict[str, Any], text: str) -> None:
    cleaned = str(text or "").strip()
    if not cleaned:
        return
    chapter["content_lines"].append(cleaned)


def _append_internal_heading(chapter: dict[str, Any], text: str, level: int) -> None:
    cleaned = str(text or "").strip()
    if not cleaned:
        return
    marker = "##" if level == 2 else "###"
    if chapter["content_lines"] and chapter["content_lines"][-1] != "":
        chapter["content_lines"].append("")
    chapter["content_lines"].append(f"{marker} {cleaned}")
    chapter["content_lines"].append("")


def _finalize_chapter(chapter: dict[str, Any]) -> dict[str, Any]:
    content = "\n".join(chapter.pop("content_lines", []))
    content = re.sub(r"\n{3,}", "\n\n", content).strip()
    chapter.pop("normalized_title", None)
    return {
        "title": chapter["title"],
        "content": content,
        "pages": chapter["pages"],
    }


def _extract_pdf_image_payload(doc: fitz.Document, image_info: tuple[Any, ...]) -> tuple[bytes, str]:
    xref = image_info[0]
    smask = image_info[1] if len(image_info) > 1 else 0

    if smask:
        try:
            base_pix = fitz.Pixmap(doc, xref)
            mask_pix = fitz.Pixmap(doc, smask)

            if (base_pix.width, base_pix.height) == (mask_pix.width, mask_pix.height):
                merged_pix = fitz.Pixmap(base_pix, mask_pix)
                return merged_pix.tobytes("png"), "png"

            logger.warning(
                "Skipping soft-mask merge for xref %s because base image %sx%s "
                "does not match mask %sx%s.",
                xref,
                base_pix.width,
                base_pix.height,
                mask_pix.width,
                mask_pix.height,
            )
        except Exception as exc:
            logger.warning(
                "Failed to merge soft mask %s for image xref %s. Falling back to raw extraction. Error: %s",
                smask,
                xref,
                exc,
            )

    base_image = doc.extract_image(xref)
    return base_image["image"], base_image["ext"]


def extract_pdf_content(file_path: str, output_dir: str = ".tmp/assets") -> Dict[str, Any]:
    """
    Extracts text and images from a PDF file.
    Uses PDF outlines or printed TOC entries to infer top-level chapters, and
    keeps smaller headings inside the chapter body as markdown headings.
    """
    logger.info("Starting PDF extraction for: %s", file_path)
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    results = {
        "chapters": [],
        "assets": [],
    }

    start_time = time.time()
    doc = fitz.open(file_path)

    avg_size = _estimate_average_font_size(doc)
    logger.info("Average font size estimated: %.2f", avg_size)

    blocks = _extract_text_blocks(doc, avg_size)
    outline_titles = _extract_outline_titles(doc)
    printed_toc_titles, toc_skip_indices = _extract_printed_toc_metadata(blocks, avg_size)
    top_level_title_list = outline_titles or printed_toc_titles
    top_level_titles = {_normalize_heading_text(title) for title in top_level_title_list}
    size_bands = _derive_heading_size_bands(blocks, avg_size, toc_skip_indices)

    current_chapter: dict[str, Any] | None = None
    for block in blocks:
        if block["index"] in toc_skip_indices:
            continue

        heading_level = _detect_heading_level(block, avg_size, top_level_titles, size_bands)
        page_num = block["page_num"]

        if heading_level == 1:
            normalized_title = block["normalized"]
            if (
                current_chapter is not None
                and current_chapter.get("normalized_title") == normalized_title
                and not current_chapter.get("content_lines")
            ):
                _ensure_chapter_page(current_chapter, page_num)
                continue
            if current_chapter is not None:
                results["chapters"].append(_finalize_chapter(current_chapter))
            current_chapter = _start_chapter(block["text"], page_num)
            continue

        if current_chapter is None:
            if top_level_titles:
                continue
            current_chapter = _start_chapter("Introduction", page_num)

        _ensure_chapter_page(current_chapter, page_num)
        if heading_level >= 2:
            _append_internal_heading(current_chapter, block["text"], heading_level)
        else:
            _append_paragraph(current_chapter, block["text"])

    if current_chapter is not None:
        results["chapters"].append(_finalize_chapter(current_chapter))

    for chapter in results["chapters"]:
        content = chapter.get("content", "")
        if len(results["chapters"]) == 1 or len(content.splitlines()) > 120:
            chapter["content"] = _structure_single_chapter_text(content)

    text_latency = time.time() - start_time
    logger.info("Text extraction complete. Found %s chapters in %.2fs.", len(results["chapters"]), text_latency)

    asset_start_time = time.time()
    distinct_assets = {}

    for page_index in range(len(doc)):
        page_num = page_index + 1
        image_list = doc[page_index].get_images(full=True)

        for img in image_list:
            xref = img[0]
            try:
                image_bytes, ext = _extract_pdf_image_payload(doc, img)

                asset_id = hashlib.md5(image_bytes).hexdigest()
                if asset_id not in distinct_assets:
                    filename = f"asset_{asset_id}.{ext}"
                    saved_path = os.path.join(output_dir, filename)
                    with open(saved_path, "wb") as handle:
                        handle.write(image_bytes)

                    distinct_assets[asset_id] = {
                        "id": asset_id,
                        "type": "image",
                        "path": saved_path,
                    }

                for chapter in results["chapters"]:
                    if page_num in chapter.get("pages", []):
                        if "asset_ids" not in chapter:
                            chapter["asset_ids"] = []
                        if asset_id not in chapter["asset_ids"]:
                            chapter["asset_ids"].append(asset_id)
                            chapter["content"] += f" [Asset: {asset_id[:8]}] "
            except Exception as exc:
                logger.error("Error extracting image xref %s on page %s: %s", xref, page_num, exc)

    results["assets"] = list(distinct_assets.values())
    asset_latency = time.time() - asset_start_time
    logger.info("Asset extraction complete. Found %s distinct assets in %.2fs.", len(results["assets"]), asset_latency)
    return results


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        path = sys.argv[1]
        data = extract_pdf_content(path)
        print(f"Extracted {len(data['chapters'])} chapters and {len(data['assets'])} images.")
