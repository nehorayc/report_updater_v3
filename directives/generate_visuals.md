# Directive: Visual Production Logic (State 6)

## Goal
To produce high-quality, relevant media (graphs and images) for the final report based on approved suggestions from State 5.

## Part A: Graph Generation (Python Code)

### 1. Code Generation Requirements
- Use **Matplotlib** or **Plotly**.
- The code must be self-contained (imports included).
- Use a professional "Corporate/Financial" theme (e.g., specific color palettes, clean fonts).
- Output must be saved to a buffer or a specific `.png` path in `.tmp/`.

### 2. Formatting Standards
- Clear titles and legend.
- Labeled axes with units.
- High resolution (DPI=300).
- Transparent background if possible, or a neutral light gray/white.

### 3. Fail-Safe
- If the code execution fails, the system must automatically generate a **Markdown Table** as a fallback.

---

## Part B: Image Sourcing & Search

### 1. Search Strategy
- Use DuckDuckGo Image Search.
- Use high-quality keywords (e.g., adding "professional photography", "diagram", "4k").

### 2. Selection & Validation
- Preference for authoritative sources (Unsplash, Pexels, or News outlets).
- Download images and verify they are valid byte-streams (not 404s or HTML wrappers).

---

## Part C: Final Asset Mapping

### 1. Placeholder Logic
The final text in `State 6` will contain markers like `{{VISUAL_ID_123}}`. 
The assembly script must:
1. Identify the marker.
2. Fetch the corresponding asset (Source Asset, Generated Graph, or Searched Image).
3. Insert into the DOCX with the prescribed caption.

### 2. Branding
- All generated visuals should follow the same aesthetic: Consistent font sizes and monochromatic or complementary color schemes.
