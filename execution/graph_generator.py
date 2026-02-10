import matplotlib.pyplot as plt
import os
import uuid
import base64
from io import BytesIO

from logger_config import setup_logger
import time

logger = setup_logger("GraphGenerator")

def generate_graph(visual_dict: dict, output_dir: str = ".tmp/visuals") -> dict:
    """
    Generated a graph image using matplotlib based on a visual suggestion.
    """
    logger.info(f"Starting graph generation: '{visual_dict.get('title')}'")
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    title = visual_dict.get("title", "Data Visualization")
    data = visual_dict.get("data_points", {})
    labels = data.get("labels", [])
    values = data.get("values", [])

    if not labels or not values:
        logger.warning(f"Insufficient data for graph '{title}': labels={len(labels)}, values={len(values)}")
        return {"error": "No data points found for graph"}

    start_time = time.time()
    try:
        plt.figure(figsize=(10, 6))
        
        # Handle cases where values is a dict (multi-series)
        if isinstance(values, dict):
            # Create a simple multi-bar chart or line chart
            # For simplicity, if we have multiple series, we'll plot them
            import numpy as np
            x = np.arange(len(labels))
            # Protect against empty values dict to avoid division by zero
            num_series = len(values) if len(values) > 0 else 1
            width = 0.8 / num_series
            multiplier = 0

            for attribute, measurement in values.items():
                offset = width * multiplier
                
                # Handle nested dicts (e.g. {"Series A": {"2021": 10, ...}})
                if isinstance(measurement, dict):
                    # Align with labels
                    aligned_data = []
                    for label in labels:
                        # Try exact match or string match
                        val = measurement.get(label)
                        if val is None:
                            val = measurement.get(str(label), 0)
                        aligned_data.append(val)
                    measurement = aligned_data

                # Ensure measurement matches labels length
                if len(measurement) != len(labels):
                    logger.warning(f"Data mismatch for {attribute}: {len(measurement)} values vs {len(labels)} labels. Truncating/Padding.")
                    # Ensure measurement is a list before slicing/padding
                    if not isinstance(measurement, list):
                        measurement = [measurement]
                    measurement = measurement[:len(labels)] + [0]*(len(labels)-len(measurement))
                
                # Ensure all values are numeric
                try:
                    measurement = [float(x) if x is not None else 0 for x in measurement]
                except (ValueError, TypeError):
                    logger.warning(f"Non-numeric data in {attribute}, coercing to 0.")
                    measurement = [0] * len(labels)

                plt.bar(x + offset, measurement, width, label=attribute)
                multiplier += 1

            plt.xticks(x + width * (num_series - 1) / 2, labels, rotation=45, ha='right')
            plt.legend(loc='upper left', ncols=3)
        
        else:
            # Standard single series bar chart
            plt.bar(labels, values, color='skyblue')
            plt.xticks(rotation=45, ha='right')

        plt.title(title)
        plt.grid(axis='y', linestyle='--', alpha=0.7)
        plt.tight_layout()
        
        filename = f"graph_{uuid.uuid4().hex}.png"
        path = os.path.join(output_dir, filename)
        plt.savefig(path)
        plt.close()

        latency = time.time() - start_time
        logger.info(f"Graph '{title}' generated successfully in {latency:.2f}s at {path}")
        return {
            "path": path,
            "filename": filename
        }
    except Exception as e:
        logger.error(f"Error generating graph '{title}': {e}", exc_info=True)
        return {"error": str(e)}

# Note: In a more advanced version, we would use an LLM to generate the code 
# and then execute it in a sandbox. For v1, we'll use a standardized bar chart.

if __name__ == "__main__":
    test_visual = {
        "title": "Projected Growth",
        "data_points": {"labels": ["2022", "2023", "2024"], "values": [100, 150, 220]}
    }
    print(generate_graph(test_visual))
