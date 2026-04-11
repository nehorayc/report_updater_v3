# Directive: Visual Production Logic (State 7)

## Goal
To produce high-quality, relevant media (graphs and images) for the final report based on approved suggestions from State 6.

## Part A: Graph Generation (LLM Code)

### 1. Primary Method: LLM-Generated Matplotlib Code
- Pass the `visual_dict` (title, description, data_points, chart_type) to `generate_graph_with_llm()`.
- The function asks Gemini (`gemini-2.5-flash`) to write a self-contained Matplotlib script.
- The code is `exec()`-ed in a restricted globals sandbox (only matplotlib, numpy, builtins).
- Output file is saved to `.tmp/visuals/` at DPI=150.
- **Advantage:** Any chart type (line, bar, pie, scatter), professional styling auto-chosen by the model.

### 2. Fallback: Static Professional Bar Chart
- If LLM code generation or execution fails, `generate_graph()` falls back to a built-in bar chart.
- Uses **corporate color palette** (`#2563EB`, `#16A34A`, `#DC2626`, …).
- Uses `seaborn-v0_8-whitegrid` or `ggplot` style, DPI=150.
- Supports single-series and multi-series (grouped bar) data.

---

## Part B: Image Sourcing & Search

### 1. Search Strategy
- Use DuckDuckGo Image Search.
- The query is **automatically enriched** with `high resolution professional` before searching.

### 2. Selection & Validation
- Try the top 3 results per search.
- Use PIL to verify each image is a valid byte-stream (not a 404 or HTML wrapper).
- **Filter by minimum size**: discard any image smaller than **400×300 px** (avoids icons/thumbnails).
- Preference for authoritative sources when possible (Unsplash, Pexels, News outlets).

---

## Part C: Final Asset Mapping

### 1. Placeholder Logic
The final text in `State 7` will contain markers like `{{VISUAL_ID_123}}`. 
The assembly script must:
1. Identify the marker.
2. Fetch the corresponding asset (Source Asset, Generated Graph, or Searched Image).
3. Insert into the DOCX with the prescribed caption.

### 2. Branding
- All generated visuals should follow the same aesthetic: Consistent font sizes and monochromatic or complementary color schemes.
