try:
    from ddgs import DDGS
except ImportError:  # pragma: no cover - compatibility fallback
    from duckduckgo_search import DDGS
import hashlib
import os
import time
import uuid
import warnings

import requests

from logger_config import setup_logger

logger = setup_logger("ImageSearch")


def _new_ddgs():
    original_warn = warnings.warn

    def _warn(message, *args, **kwargs):
        if "has been renamed to `ddgs`" in str(message):
            return None
        return original_warn(message, *args, **kwargs)

    warnings.warn = _warn
    try:
        return DDGS()
    finally:
        warnings.warn = original_warn


def _image_mime_type(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".png":
        return "image/png"
    if ext in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if ext == ".gif":
        return "image/gif"
    if ext == ".bmp":
        return "image/bmp"
    if ext == ".webp":
        return "image/webp"
    return "application/octet-stream"


def _aspect_ratio(width: int, height: int) -> float:
    if not width or not height:
        return 0.0
    return round(width / height, 4)


def _enrich_saved_image_metadata(
    *,
    path: str,
    filename: str,
    img_url: str,
    query: str,
    provider: str,
    selection_reason: str,
    width: int,
    height: int,
    img_data: bytes,
) -> dict:
    return {
        "path": path,
        "url": img_url,
        "source_url": img_url,
        "filename": filename,
        "provider": provider,
        "query": query,
        "selection_reason": selection_reason,
        "content_hash": hashlib.sha256(img_data).hexdigest(),
        "mime_type": _image_mime_type(path),
        "width": width,
        "height": height,
        "aspect_ratio": _aspect_ratio(width, height),
    }

def _query_variants(query: str) -> list[str]:
    cleaned = " ".join(str(query or "").split())
    if not cleaned:
        return []

    quality_suffix = "high resolution professional"
    variants = []
    enriched = cleaned if quality_suffix in cleaned.lower() else f"{cleaned} {quality_suffix}"
    for candidate in (enriched, cleaned):
        normalized = " ".join(candidate.split())
        if normalized and normalized not in variants:
            variants.append(normalized)
    return variants


def search_and_download_image(
    query: str,
    output_dir: str = ".tmp/visuals",
    *,
    allow_placeholder_fallback: bool = False,
) -> dict:
    """
    Search for an image and download the top result.
    Automatically enriches the query with quality keywords and
    filters out images smaller than 400x300 px.
    """
    logger.info(f"Starting image search for: '{query}'")
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    query_variants = _query_variants(query)
    if not query_variants:
        error = "Image search query is empty"
        logger.error(error)
        if allow_placeholder_fallback:
            placeholder = generate_placeholder_image(query or "Untitled visual", output_dir)
            placeholder["provider"] = "placeholder"
            placeholder["selection_reason"] = "empty_query_fallback"
            return placeholder
        return {"error": error}
    logger.info(f"Prepared image search queries: {query_variants}")

    MAX_RETRIES = 3
    retry_count = 0
    backoff = 2
    last_error = "Unknown image search failure"
    
    start_time = time.time()

    while retry_count < MAX_RETRIES:
        try:
            for variant in query_variants:
                with _new_ddgs() as ddgs:
                    results = ddgs.images(variant, max_results=5)
                    results_list = list(results)

                if not results_list:
                    logger.warning(f"No images found for query variant: '{variant}'")
                    last_error = f"No images found for query variant: {variant}"
                    continue

                for i, res in enumerate(results_list[:3]):  # Try top 3
                    img_url = res['image']
                    logger.info(f"Attempting to download result {i+1} for '{variant}': {img_url[:60]}...")

                    try:
                        download_start = time.time()
                        headers = {
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
                        }
                        response = requests.get(img_url, timeout=10, headers=headers)
                        response.raise_for_status()
                        img_data = response.content

                        from PIL import Image
                        from io import BytesIO
                        try:
                            img = Image.open(BytesIO(img_data))
                            img.verify()
                            img = Image.open(BytesIO(img_data))
                            width, height = img.size
                            if width < 400 or height < 300:
                                logger.warning(f"Result {i+1} too small ({width}x{height}), skipping.")
                                last_error = f"Image too small: {width}x{height}"
                                continue
                            logger.info(f"Successfully validated image from result {i+1} ({width}x{height})")
                        except Exception as ve:
                            logger.warning(f"Result {i+1} failed image validation: {ve}")
                            last_error = f"Image validation failed: {ve}"
                            continue

                        download_latency = time.time() - download_start
                        logger.debug(f"Image downloaded in {download_latency:.2f}s.")

                        ext = img_url.split('.')[-1].split('?')[0].lower()
                        if ext not in ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp']:
                            ext = "png"

                        filename = f"search_{uuid.uuid4().hex}.{ext}"
                        path = os.path.join(output_dir, filename)

                        with open(path, "wb") as f:
                            f.write(img_data)

                        latency = time.time() - start_time
                        logger.info(f"Image search and download complete in {latency:.2f}s. Saved to {path}")
                        return _enrich_saved_image_metadata(
                            path=path,
                            filename=filename,
                            img_url=img_url,
                            query=variant,
                            provider="ddgs",
                            selection_reason="validated_image_search_result",
                            width=width,
                            height=height,
                            img_data=img_data,
                        )
                    except Exception as de:
                        logger.warning(f"Failed to process result {i+1}: {de}")
                        last_error = str(de)
                        continue

            raise Exception(last_error or "Found results but none were valid images.")

        except Exception as e:
            retry_count += 1
            last_error = str(e)
            logger.warning(f"Image search attempt {retry_count}/{MAX_RETRIES} failed for '{query}': {e}")
            if retry_count >= MAX_RETRIES:
                logger.error(f"Max retries reached for image search '{query}'. Skipping visual.")
                if allow_placeholder_fallback:
                    placeholder = generate_placeholder_image(query, output_dir)
                    placeholder["provider"] = "placeholder"
                    placeholder["query"] = query
                    placeholder["selection_reason"] = "explicit_placeholder_fallback"
                    return placeholder
                return {"error": f"Image search failed after {MAX_RETRIES} attempts: {e}", "provider": "ddgs", "query": query}
            
            sleep_time = backoff * retry_count
            logger.info(f"Retrying in {sleep_time}s...")
            time.sleep(sleep_time)

    # Should not reach here, but guard against it
    if allow_placeholder_fallback:
        placeholder = generate_placeholder_image(query, output_dir)
        placeholder["provider"] = "placeholder"
        placeholder["query"] = query
        placeholder["selection_reason"] = "explicit_placeholder_fallback"
        return placeholder
    return {"error": "Image search exhausted all retries.", "provider": "ddgs", "query": query}

def generate_placeholder_image(query: str, output_dir: str) -> dict:
    """
    Generates a simple placeholder image with text using matplotlib.
    """
    try:
        import matplotlib.pyplot as plt
        import textwrap
        from PIL import Image
        
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        filename = f"placeholder_{uuid.uuid4().hex}.png"
        path = os.path.join(output_dir, filename)
        
        plt.figure(figsize=(10, 6))
        plt.text(0.5, 0.5, f"Image Not Found\n\nQuery: {textwrap.fill(query, 30)}", 
                 ha='center', va='center', fontsize=20, color='gray')
        plt.axis('off')
        plt.savefig(path, bbox_inches='tight', pad_inches=0.5)
        plt.close()
        
        logger.info(f"Generated placeholder image at {path}")
        with Image.open(path) as placeholder_image:
            width, height = placeholder_image.size
        return {
            "path": path,
            "url": "placeholder",
            "source_url": "placeholder",
            "filename": filename,
            "mime_type": _image_mime_type(path),
            "width": width,
            "height": height,
            "aspect_ratio": _aspect_ratio(width, height),
        }
    except Exception as e:
        logger.error(f"Failed to generate placeholder: {e}")
        return {"error": "Failed to generate placeholder"}

if __name__ == "__main__":
    import sys
    q = sys.argv[1] if len(sys.argv) > 1 else "clean energy turbine"
    print(search_and_download_image(q))
