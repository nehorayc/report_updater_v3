from duckduckgo_search import DDGS
import requests
import os
import uuid

from logger_config import setup_logger
import time

logger = setup_logger("ImageSearch")

def search_and_download_image(query: str, output_dir: str = ".tmp/visuals") -> dict:
    """
    Search for an image and download the top result.
    Automatically enriches the query with quality keywords and
    filters out images smaller than 400x300 px.
    """
    logger.info(f"Starting image search for: '{query}'")
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # Enrich query with quality keywords if not already present
    quality_suffix = "high resolution professional"
    if quality_suffix not in query.lower():
        enriched_query = f"{query} {quality_suffix}"
    else:
        enriched_query = query
    logger.info(f"Enriched query: '{enriched_query}'")

    MAX_RETRIES = 3
    retry_count = 0
    backoff = 2
    
    start_time = time.time()

    while retry_count < MAX_RETRIES:
        try:
            with DDGS() as ddgs:
                # Get a few results so we can fallback if the top one is invalid
                results = ddgs.images(enriched_query, max_results=5)
                results_list = list(results)
                
                if not results_list:
                    logger.warning(f"No images found for query: '{query}'")
                    return {"error": "No images found"}
                
                success = False
                for i, res in enumerate(results_list[:3]): # Try top 3
                    img_url = res['image']
                    logger.info(f"Attempting to download result {i+1}: {img_url[:60]}...")
                    
                    try:
                        download_start = time.time()
                        # Use a realistic User-Agent to avoid some blocks
                        headers = {
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
                        }
                        response = requests.get(img_url, timeout=10, headers=headers)
                        response.raise_for_status()
                        img_data = response.content
                        
                        # Validate image data using PIL
                        from PIL import Image
                        from io import BytesIO
                        try:
                            img = Image.open(BytesIO(img_data))
                            img.verify() 
                            # Re-open after verify() since it closes the file
                            img = Image.open(BytesIO(img_data))
                            width, height = img.size
                            if width < 400 or height < 300:
                                logger.warning(f"Result {i+1} too small ({width}x{height}), skipping.")
                                continue
                            logger.info(f"Successfully validated image from result {i+1} ({width}x{height})")
                        except Exception as ve:
                            logger.warning(f"Result {i+1} failed image validation: {ve}")
                            continue

                        download_latency = time.time() - download_start
                        logger.debug(f"Image downloaded in {download_latency:.2f}s.")
                        
                        # Detect extension from URL or use png/jpg based on what PIL says?
                        ext = img_url.split('.')[-1].split('?')[0].lower()
                        if ext not in ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp']:
                            ext = "png"
                            
                        filename = f"search_{uuid.uuid4().hex}.{ext}"
                        path = os.path.join(output_dir, filename)
                        
                        with open(path, "wb") as f:
                            f.write(img_data)
                        
                        latency = time.time() - start_time
                        logger.info(f"Image search and download complete in {latency:.2f}s. Saved to {path}")
                        return {
                            "path": path,
                            "url": img_url,
                            "filename": filename
                        }
                    except Exception as de:
                        logger.warning(f"Failed to process result {i+1}: {de}")
                        continue
                
                # If we reach here, we didn't return from the loop
                raise Exception("Found results but none were valid images.")

        except Exception as e:
            retry_count += 1
            logger.warning(f"Image search attempt {retry_count}/{MAX_RETRIES} failed for '{query}': {e}")
            if retry_count >= MAX_RETRIES:
                logger.error(f"Max retries reached for image search '{query}'. Skipping visual.")
                return {"error": f"Image search failed after {MAX_RETRIES} attempts: {e}"}
            
            sleep_time = backoff * retry_count
            logger.info(f"Retrying in {sleep_time}s...")
            time.sleep(sleep_time)

    # Should not reach here, but guard against it
    return {"error": "Image search exhausted all retries."}

def generate_placeholder_image(query: str, output_dir: str) -> dict:
    """
    Generates a simple placeholder image with text using matplotlib.
    """
    try:
        import matplotlib.pyplot as plt
        import textwrap
        
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
        return {
            "path": path,
            "url": "placeholder",
            "filename": filename
        }
    except Exception as e:
        logger.error(f"Failed to generate placeholder: {e}")
        return {"error": "Failed to generate placeholder"}

if __name__ == "__main__":
    import sys
    q = sys.argv[1] if len(sys.argv) > 1 else "clean energy turbine"
    print(search_and_download_image(q))
