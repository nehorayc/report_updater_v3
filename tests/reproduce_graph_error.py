import sys
import os

# Add parent directory to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'execution')))

from graph_generator import generate_graph
from logger_config import setup_logger

logger = setup_logger("TestGraph")

def test_nested_dict():
    logger.info("Testing nested dict structure...")
    visual = {
        "title": "Test Nested Dict",
        "data_points": {
            "labels": ["2021", "2022", "2023"],
            "values": {
                "Series A": {"2021": 10, "2022": 20, "2023": 30},
                "Series B": {"2021": 15, "2022": 25, "2023": 35}
            }
        }
    }
    result = generate_graph(visual, output_dir=".tmp/test_visuals")
    print(f"Result: {result}")

def test_list_values():
    logger.info("Testing list values structure...")
    visual = {
        "title": "Test List Values",
        "data_points": {
            "labels": ["A", "B", "C"],
            "values": [10, 20, 30]
        }
    }
    result = generate_graph(visual, output_dir=".tmp/test_visuals")
    print(f"Result: {result}")

if __name__ == "__main__":
    test_nested_dict()
    test_list_values()
