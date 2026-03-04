import os
import sys
import time
import uuid

# Add execution directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'execution'))
from doc_builder import build_final_report
from graph_generator import generate_graph

def main():
    print("Testing Graph Generator and Document Builder Integration...")
    
    # 1. Generate a graph directly from graph_generator
    test_visual = {
        "title": "Projected Growth (Generated)",
        "data_points": {
            "labels": ["2024", "2025", "2026", "2027"], 
            "values": [5.2, 8.4, 12.1, 15.6]
        }
    }
    
    print(f"Generating graph titled '{test_visual['title']}'...")
    result = generate_graph(test_visual)
    
    if "error" in result:
        print(f"Failed to generate graph: {result['error']}")
        return
        
    graph_path = result.get("path")
    print(f"Graph generated successfully: {graph_path}")
    
    # 2. Embed the generated graph into a report
    asset_id = uuid.uuid4().hex[:8]
    
    visuals = [
        {
            'original_asset_id': asset_id,
            'type': 'image',
            'path': graph_path,
            'title': test_visual['title'],
            'short_caption': 'A dynamic graph'
        }
    ]
    
    chapters = [
        {
            "title": "LLM Image Generation Test",
            "draft_text": (
                "This report tests the dynamic generation of graphs via Python code "
                "and embedding them into a Word Document.\n\n"
                "Here is the generated graph:\n"
                f"[Asset: {asset_id}]\n\n"
                "The graph should be visible above this text."
            ),
            "approved_visuals": visuals,
            "references": []
        }
    ]
    
    out_path = f"test_graph_report_{int(time.time())}.docx"
    print(f"Building report to {out_path}...")
    result_path = build_final_report(chapters, out_path)
    print(f"Successfully generated docx at: {result_path}")

if __name__ == "__main__":
    main()
