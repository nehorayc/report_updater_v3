import matplotlib
matplotlib.use('Agg')  # Non-interactive backend, must be set before pyplot import
import matplotlib.pyplot as plt
import os
import uuid
import base64
from io import BytesIO
from dotenv import load_dotenv
from gemini_client import generate_content as gemini_generate_content

load_dotenv()

from logger_config import setup_logger
import time

logger = setup_logger("GraphGenerator")

# Professional color palette for static fallback
_CORP_COLORS = ['#2563EB', '#16A34A', '#DC2626', '#D97706', '#7C3AED', '#0891B2']
_SUPPORTED_STATIC_CHART_TYPES = {'bar', 'line', 'pie'}

# Apply professional style to static charts
try:
    plt.style.use('seaborn-v0_8-whitegrid')
except OSError:
    plt.style.use('ggplot')  # Fallback if seaborn not available

# Builtins that are NOT safe to expose to LLM-generated code
_UNSAFE_BUILTINS = {
    'open', 'exec', 'eval', 'compile',
    'input', 'breakpoint', 'memoryview',
    '__loader__', '__spec__',
}

# Only these top-level module names may be imported by LLM-generated code
_ALLOWED_IMPORT_PREFIXES = {
    'matplotlib', 'numpy', 'math', 'statistics', 'collections',
    'itertools', 'functools', 'operator', 'textwrap', 'datetime',
    'random', 'io', 'colorsys', 'scipy', 'pandas',
}


def _safe_import(name, *args, **kwargs):
    """Wraps __import__ to only permit safe scientific/plotting modules."""
    top = name.split('.')[0]
    if top not in _ALLOWED_IMPORT_PREFIXES:
        raise ImportError(f"Import of '{name}' is not allowed in graph code sandbox.")
    return __import__(name, *args, **kwargs)


def _make_safe_globals() -> dict:
    """
    Returns a globals dict for exec() that allows all standard Python builtins
    EXCEPT those that could access the filesystem, network, or execute arbitrary code.
    __import__ is replaced with a sandboxed version that only allows safe modules.
    """
    import builtins
    safe_builtins = {
        k: v for k, v in vars(builtins).items()
        if k not in _UNSAFE_BUILTINS
    }
    # Replace __import__ with the sandboxed version
    safe_builtins['__import__'] = _safe_import
    return {"__builtins__": safe_builtins}


def _coerce_numeric_series(values, target_len: int) -> list[float]:
    """Normalize chart series length and convert missing/bad values to 0."""
    if isinstance(values, list):
        series = values[:target_len]
    else:
        series = [values]

    if len(series) < target_len:
        series = series + [0] * (target_len - len(series))

    normalized = []
    for value in series[:target_len]:
        try:
            normalized.append(float(value) if value is not None else 0.0)
        except (ValueError, TypeError):
            normalized.append(0.0)
    return normalized


def _should_use_static_first(visual_dict: dict) -> bool:
    data = visual_dict.get("data_points", {}) or {}
    labels = data.get("labels", [])
    values = data.get("values", [])
    chart_type = str(visual_dict.get("chart_type") or "bar").lower()

    if chart_type not in _SUPPORTED_STATIC_CHART_TYPES:
        return False
    if not isinstance(labels, list) or not labels:
        return False
    if isinstance(values, dict):
        return bool(values) and chart_type in {"bar", "line"}
    if isinstance(values, list):
        return bool(values)
    return values is not None


def generate_graph_with_llm(visual_dict: dict, output_dir: str = ".tmp/visuals") -> dict:
    """
    Uses Gemini to write a Matplotlib Python script for the given visual,
    then executes it safely. Returns {'path': ...} on success, {'error': ...} on failure.
    Includes one retry if the code runs but produces no file (path mismatch).
    """
    logger.info(f"Attempting LLM-based graph generation for: '{visual_dict.get('title')}'")
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.warning("GEMINI_API_KEY not found, skipping LLM graph generation.")
        return {"error": "No API key"}

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    filename = f"graph_{uuid.uuid4().hex}.png"
    output_path = os.path.abspath(os.path.join(output_dir, filename)).replace("\\", "/")

    title = visual_dict.get("title", "Data Visualization")
    description = visual_dict.get("description", "")
    data = visual_dict.get("data_points", {})
    chart_type = visual_dict.get("chart_type", "bar")

    def _build_prompt(previous_code: str = "") -> str:
        retry_note = ""
        if previous_code:
            retry_note = f"""
IMPORTANT: The previous attempt below ran without error but did NOT save a file to the expected path.
You MUST fix the save path. Do not change any other logic.

Previous (broken) code:
{previous_code}

"""
        return f"""{retry_note}Write a self-contained Python script using Matplotlib that creates a professional chart.

Chart details:
- Title: {title}
- Description: {description}
- Chart type (suggested): {chart_type}
- Data: {data}
- Output path: {output_path}

REQUIREMENTS:
1. Import all necessary libraries (matplotlib, numpy if needed).
2. Use plt.style.use('seaborn-v0_8-whitegrid') or 'ggplot' as fallback.
3. Use a professional color palette (e.g. #2563EB, #16A34A, #DC2626).
4. Set DPI=200, figure size=(12, 7).
5. Add clear title, axis labels with units if inferable, and a legend if multi-series.
6. Rotate x-tick labels 45 degrees if there are more than 4 categories.
7. Call plt.tight_layout() before saving.
8. Save to EXACTLY this path: {output_path}
9. Call plt.close() at the end.
10. Do NOT use plt.show().
11. Choose the best chart type for the data (line for trends, bar for comparisons, pie for proportions, etc.)

Respond with ONLY the executable Python code. No explanations, no markdown fences.
"""

    def _try_exec(prompt: str) -> tuple:
        """Returns (code, result_dict)."""
        start = time.time()
        response = gemini_generate_content(
            api_key=api_key,
            model='gemini-2.5-flash',
            contents=prompt,
        )
        logger.info(f"LLM code generated in {time.time()-start:.2f}s")

        code = response.text.strip()
        # Strip markdown fences if present despite instructions
        if code.startswith("```"):
            code = code.split("```")[1]
            if code.startswith("python"):
                code = code[6:]
            if "```" in code:
                code = code[:code.rfind("```")]
        code = code.strip()

        logger.debug(f"LLM generated code:\n{code[:500]}...")

        safe_globals = _make_safe_globals()
        exec(code, safe_globals)  # nosec

        if os.path.exists(output_path):
            logger.info(f"LLM-generated graph saved to: {output_path}")
            return code, {"path": output_path, "filename": filename}
        else:
            logger.warning(f"LLM code ran but no file found at: {output_path}")
            return code, {"error": "Code ran but no file was produced"}

    try:
        # First attempt
        code, result = _try_exec(_build_prompt())
        if "path" in result:
            return result

        # Bug 2 fix: one retry with explicit path correction prompt
        logger.info("Retrying with path-correction prompt...")
        _, result = _try_exec(_build_prompt(previous_code=code))
        if "path" in result:
            return result

        return {"error": "LLM code ran twice but no output file produced"}

    except Exception as e:
        logger.error(f"LLM graph generation failed: {e}", exc_info=True)
        return {"error": str(e)}


def _generate_static_graph(visual_dict: dict, output_dir: str = ".tmp/visuals") -> dict:
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    title = visual_dict.get("title", "Data Visualization")
    data = visual_dict.get("data_points", {})
    labels = data.get("labels", [])
    values = data.get("values", [])
    unit = data.get("unit", "")
    chart_type = visual_dict.get("chart_type", "bar").lower()

    if not labels or not values:
        logger.warning(f"Insufficient data for graph '{title}': labels={len(labels)}, values={len(values)}")
        return {"error": "No data points found for graph"}

    start_time = time.time()
    try:
        fig, ax = plt.subplots(figsize=(12, 7))
        x_positions = list(range(len(labels)))

        # --- Bug 6 fix: route by chart_type ---

        # Handle multi-series dict values (applies to bar and line)
        if isinstance(values, dict):
            import numpy as np
            x = np.arange(len(labels))
            num_series = max(len(values), 1)
            width = 0.8 / num_series
            multiplier = 0

            for idx, (attribute, measurement) in enumerate(values.items()):
                offset = width * multiplier
                color = _CORP_COLORS[idx % len(_CORP_COLORS)]

                if isinstance(measurement, dict):
                    aligned_data = []
                    for label in labels:
                        val = measurement.get(label) or measurement.get(str(label), 0)
                        aligned_data.append(val)
                    measurement = aligned_data

                if len(measurement) != len(labels):
                    logger.warning(f"Data mismatch for {attribute}: truncating/padding.")
                measurement = _coerce_numeric_series(measurement, len(labels))

                if chart_type == "line":
                    ax.plot(x, measurement, marker='o', label=attribute, color=color, linewidth=2)
                else:
                    ax.bar(x + offset, measurement, width, label=attribute, color=color)
                multiplier += 1

            ax.set_xticks(x + width * (num_series - 1) / 2 if chart_type != "line" else x)
            ax.set_xticklabels(labels, rotation=45, ha='right')
            ax.legend(loc='upper left')

        elif chart_type == "pie":
            # Pie chart: ignore labels/values mismatch gracefully
            float_vals = _coerce_numeric_series(values, len(labels))
            colors = _CORP_COLORS[:len(labels)]
            ax.pie(float_vals, labels=labels, colors=colors, autopct='%1.1f%%', startangle=90)
            ax.axis('equal')

        elif chart_type == "line":
            float_vals = _coerce_numeric_series(values, len(labels))
            ax.plot(x_positions, float_vals, marker='o', color=_CORP_COLORS[0], linewidth=2.5, markersize=6)
            ax.set_xticks(x_positions)
            ax.set_xticklabels(labels, rotation=45 if len(labels) > 4 else 0, ha='right')
            ax.fill_between(x_positions, float_vals, alpha=0.1, color=_CORP_COLORS[0])

        else:
            # Default: bar chart (single series)
            float_vals = _coerce_numeric_series(values, len(labels))
            colors = _CORP_COLORS[:len(labels)]
            ax.bar(x_positions, float_vals, color=colors)
            ax.set_xticks(x_positions)
            ax.set_xticklabels(labels, rotation=45 if len(labels) > 4 else 0, ha='right')

        ax.set_title(title, fontsize=14, fontweight='bold', pad=15)
        if unit and chart_type != "pie":
            ax.set_ylabel(unit)
        if chart_type != "pie":
            ax.grid(axis='y', linestyle='--', alpha=0.7)
        plt.tight_layout()

        filename = f"graph_{uuid.uuid4().hex}.png"
        path = os.path.join(output_dir, filename)
        plt.savefig(path, dpi=200)
        plt.close()

        logger.info(f"Static graph '{title}' ({chart_type}) generated in {time.time()-start_time:.2f}s at {path}")
        return {"path": path, "filename": filename}

    except Exception as e:
        logger.error(f"Error generating static graph '{title}': {e}", exc_info=True)
        plt.close()
        return {"error": str(e)}


def generate_graph(visual_dict: dict, output_dir: str = ".tmp/visuals") -> dict:
    """
    Generates a graph image. Uses deterministic local rendering first for simple
    structured charts, and falls back to the LLM path for complex or
    underspecified visuals.
    """
    logger.info(f"Starting graph generation: '{visual_dict.get('title')}'")

    if _should_use_static_first(visual_dict):
        logger.info("Using static graph renderer first for structured chart data.")
        static_result = _generate_static_graph(visual_dict, output_dir)
        if "path" in static_result:
            return static_result

        logger.warning(
            "Static-first graph generation failed (%s), trying LLM fallback.",
            static_result.get("error"),
        )
        llm_result = generate_graph_with_llm(visual_dict, output_dir)
        return llm_result if "path" in llm_result else static_result

    llm_result = generate_graph_with_llm(visual_dict, output_dir)
    if "path" in llm_result:
        return llm_result
    logger.warning(f"LLM graph failed ({llm_result.get('error')}), falling back to static chart.")
    return _generate_static_graph(visual_dict, output_dir)


if __name__ == "__main__":
    test_visual = {
        "title": "Projected AI Market Growth",
        "description": "Line chart showing AI market size in billions USD from 2022 to 2027",
        "chart_type": "line",
        "data_points": {
            "labels": ["2022", "2023", "2024", "2025", "2026", "2027"],
            "values": [100, 150, 220, 310, 420, 560],
            "unit": "USD Billions"
        }
    }
    result = generate_graph(test_visual)
    print(result)
