import os
import sys
from PIL import Image

# Add execution directory to path to import doc_builder
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'execution'))
from doc_builder import build_final_report

def create_dummy_image(path, color, text="Dummy"):
    img = Image.new('RGB', (400, 300), color=color)
    img.save(path)
    return path

def main():
    print("Setting up test bench...")
    
    # Create temp directory for dummy images
    os.makedirs('.tmp', exist_ok=True)
    img1_path = create_dummy_image('.tmp/dummy1.png', 'red')
    img2_path = create_dummy_image('.tmp/dummy2.png', 'blue')
    
    id1 = "11111111"
    id2 = "22222222"
    
    visuals = [
        {
            'id': id1 + "abcd",
            'type': 'image',
            'path': img1_path,
            'title': 'Test Red Image'
        },
        {
            'original_asset_id': id2 + "efgh",
            'type': 'image',
            'path': img2_path,
            'title': 'Test Blue Image',
            'short_caption': 'Short cap'
        }
    ]
    
    references = [
        {
            "title": "A Study on Dummy Images",
            "url": "https://example.com/study",
            "category": "Academic"  # Academic & Scholarly Research
        },
        {
            "title": "State of AI 2026",
            "url": "https://example.com/ai-report"
            # Default "Web Sources & Industry Reports" if category missing
        },
        {
            "title": "Original Company Report Q1",
            "url": "Internal URL or None",
            "category": "Original"  # Original Report Documents
        },
        {
            "title": "External Data Source",
            "url": "",
            "category": "Uploaded"  # Uploaded Reference Materials
        }
    ]
    
    chapters = [
        {
            "title": "Welcome to the Test Bench",
            "draft_text": (
                "This is a test document to ensure images are embedded properly.\n\n"
                "Here is the first image:\n"
                f"[Figure {id1}: This is a dummy caption for the red image]\n\n"
                "As you can see above, the image should be embedded.\n\n"
                "And here is the second image:\n"
                f"[Asset: {id2}]\n\n"
                "End of test chapter."
            ),
            "approved_visuals": visuals,
            "references": references
        }
    ]
    
    import time
    out_path = f"test_images_report_{int(time.time())}.docx"
    print(f"Building report to {out_path}...")
    result_path = build_final_report(chapters, out_path)
    print(f"Successfully generated docx at: {result_path}")

if __name__ == "__main__":
    main()
