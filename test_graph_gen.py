import sys
import os
import json

# Add execution directory to path so we can import modules
sys.path.append(os.path.abspath("execution"))

try:
    from graph_generator import generate_graph
except ImportError:
    # Try alternate path if running from within execution dir
    sys.path.append(os.path.abspath("."))
    from graph_generator import generate_graph

# Output directory
output_dir = ".tmp/visuals"
if not os.path.exists(output_dir):
    os.makedirs(output_dir)

# Test Case 1: Single Series Bar Chart (Old format)
print("Testing Single Series...")
visual_single = {
    "title": "Single Series Test",
    "data_points": {
        "labels": ["A", "B", "C"],
        "values": [10, 20, 30],
        "unit": "Units"
    }
}
res_single = generate_graph(visual_single, output_dir)
print(f"Single Series Result: {res_single}")

# Test Case 2: Multi-Series Bar Chart (New problematic format)
print("\nTesting Multi-Series...")
visual_multi = {
    "title": "Multi Series Test",
    "data_points": {
        "labels": ["Q1", "Q2", "Q3"],
        "values": {
            "Series X": [10, 15, 12],
            "Series Y": [8, 12, 14],
            "Series Z": [5, 9, 11]
        },
        "unit": "Revenue"
    }
}
res_multi = generate_graph(visual_multi, output_dir)
print(f"Multi Series Result: {res_multi}")

# Test Case 3: Mismatched Data Lengths (Robustness check)
print("\nTesting Mismatched Lengths...")
visual_mismatch = {
    "title": "Mismatch Test",
    "data_points": {
        "labels": ["Q1", "Q2", "Q3"],
        "values": {
            "Short": [10, 15], # Missing one
            "Long": [8, 12, 14, 20] # Extra one
        }
    }
}
res_mismatch = generate_graph(visual_mismatch, output_dir)
print(f"Mismatch Result: {res_mismatch}")
