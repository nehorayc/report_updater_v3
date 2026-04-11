
---

# Layer 1: Directive (Master Plan)

## 1. Project Overview & Goals
**Project Name:** Report Updater (Horizon/Elisha v1)
**Goal:** Build a Streamlit application that modernizes legacy reports. It ingests a source document, filters source assets, plans research, generates a draft, and allows deep user refinement before final export.
**Key Workflow:** Ingest $\rightarrow$ Filter Source Assets $\rightarrow$ Plan Source Visual Updates $\rightarrow$ Plan Research $\rightarrow$ Generate Draft $\rightarrow$ **Review Draft & Approve Visuals** $\rightarrow$ Final Export.

---

## 2. Architecture: The 7-Step State Machine
The application logic follows a linear state machine in `app.py`, with a feedback loop at Step 6.

### **State 1: UPLOAD SOURCE REPORT**
*   **Input:** User uploads **Source Report** (PDF/DOCX).
*   **Action:**
    *   **File Parsing:** Split document into chapters.
    *   **Asset Extraction:** Extract *all* images and tables (blindly).
    *   **Initial Metadata:** Store raw text and asset thumbnails.
*   **Output:** Session state populated with `raw_chapters` and `detected_assets`.

### **State 2: SOURCE ASSET SELECTION**
*   **Goal:** User decides which *original* images/tables to keep.
*   **UI:** Gallery of extracted assets.
*   **User Action:** Checkbox selection `[x] Include`.
*   **System Action (On Transition):**
    *   **Vision Analysis:** Transcribe selected Graph/Table data via Gemini Vision.
    *   **Text Analysis:** Analyze chapters to determine initial Topic, Timeframe, and Keywords.

### **State 3: SOURCE VISUAL UPDATE PLANNING**
*   **Goal:** User decides which retained source charts/tables should stay as-is, be refreshed, or be converted.
*   **UI:** Dedicated gallery/cards for selected charts and tables.
*   **User Action:**
    *   **Keep Original:** Preserve the source visual as-is.
    *   **Refresh with Updated Data:** Provide or edit a research query for a rebuilt chart/table.
    *   **Convert Table to Editable Text:** Turn a retained source table into markdown text for the draft.
*   **System Action:** Save `do_update`, `convert_to_text`, and `update_query` decisions on the selected source assets.

### **State 4: RESEARCH PLANNING (Metadata Editor)**
*   **Goal:** User defines *how* the research should be conducted.
*   **UI:** List of chapters with editable settings.
*   **User Action:**
    *   **Edit Topic:** (e.g., change "AI" to "GenAI in Finance").
    *   **Edit Timeframe:** (e.g., set "2024-2025").
    *   **Edit Keywords:** Refine search queries.
    *   **Upload Reference Docs:** Add internal PDFs/DOCXs (mapped to chapters via keywords).
*   **System Action:** Save the "Research Blueprint" for each chapter.

### **State 5: DRAFT GENERATION (The Engine)**
*   **Action:** Iterate through chapters (or a single chapter if regenerating).
    1.  **Research:** Execute Web (DuckDuckGo), Academic (OpenAlex), and Internal (uploaded doc) searches based on the Blueprint.
    2.  **Writing:** Generate the new chapter text.
    3.  **Visual Ideation (New):**
        *   Based on the *newly written text*, the AI must return a list of **Suggested Visuals**.
        *   *Example output:* `{"type": "graph", "title": "Market Growth", "description": "Bar chart showing 5% growth", "location": "after_paragraph_2"}`.
    4.  **No Rendering Yet:** Do *not* generate the actual graph images yet. Just store the text text/code suggestions.

### **State 6: DRAFT REVIEW & VISUAL APPROVAL (The Loop)**
*   **Goal:** User reviews the draft, adjusts settings if needed, and approves both updated source visuals and new visuals.
*   **UI Structure (Per Chapter):**
    1.  **Draft Preview:** Show the rewritten text.
    2.  **Settings Used:** Display Topic, Timeframe, Keywords.
        *   *Action:* If User changes these settings $\rightarrow$ Button: **"Regenerate Chapter Text"** (Triggers State 5 logic again for this chapter).
    3.  **Visual Suggestions:**
        *   Display the AI's proposed graphs/images descriptions.
        *   *Action:* User checks `[x] Approve`.
*   **Transition to Final:** User clicks "Finalize Report".

### **State 7: FINAL ASSEMBLY (Render & Export)**
*   **Action:**
    1.  **Visual Production:**
        *   **Graphs:** Execute Python code (Matplotlib/Plotly) for *Approved* graphs.
        *   **Images:** Search DuckDuckGo Images for *Approved* image requests.
    2.  **Document Construction:**
        *   Combine rewritten text.
        *   Embed **Selected Source Assets** (from State 2).
        *   Embed **Newly Generated Visuals** (from State 7).
    3.  **Bibliography:** Consolidate references (Internal/Web/Academic).
*   **Output:** Download Buttons (.md / .docx).

---

## 3. Data & File Handling SOPs

### **A. Multimodal Parsing**
*   **Tools:** `pdfplumber`, `fitz`, `python-docx`.
*   **Logic:** Extract text and raw asset bytes.
*   **Data Structure (Chapter Object):**
    ```python
    class Chapter:
        # Settings
        title: str, topic: str, timeframe: str, keywords: list
        # Content
        draft_text: str
        # Assets
        source_assets_to_keep: list[id]
        suggested_visuals: list[dict] # AI suggestions
        approved_visuals: list[dict]  # User approved list
    ```

### **B. Reference Material**
*   **Logic:** Loaded in State 4. Filtered during State 5 (Research) based on keyword matching.

---

## 4. Writing & Research Logic (State 5)

### **A. The Prompt Strategy (Two-Part Output)**
*   **Input:** Research Findings + Original Text + User Blueprint.
*   **Instructions:**
    1.  Rewrite text focusing on Topic/Timeframe.
    2.  Identify data points in your new text that deserve a visual.
    3.  **Output Format:** JSON or XML structure containing `text_content` AND `visual_suggestions`.

### **B. Regeneration Logic**
*   In **State 6**, if "Regenerate" is clicked:
    *   Clear `draft_text` and `suggested_visuals` for that chapter.
    *   Re-run the Research & Write function using the *newly edited* Blueprint settings.
    *   Update the UI with the new version.

---

## 5. Visual Production Logic (State 7)

### **A. Graph Generation**
*   **Input:** The "Visual Suggestion" (which contains data points and chart type).
*   **Process:**
    *   Pass the data to a specialized "Code Generator" LLM call.
    *   Prompt: "Write a Python function using Matplotlib to plot this data. Return only code."
    *   Execute code safely.
    *   Save resulting plot as image bytes.
*   **Fallback:** If code fails, generate a formatted Markdown table instead.

### **B. Image Sourcing**
*   **Input:** "Search for an image of a Solar Farm".
*   **Process:** Use DuckDuckGo Image Search API. Get top result URL. Download bytes.

---

## 6. Export Strategy

### **DOCX Construction**
*   **Library:** `python-docx`.
*   **Placement Logic:**
    *   The Draft Text will contain placeholders like `[INSERT_VISUAL_ID_123]`.
    *   During DOCX generation, replace that string with the actual image (Source Asset OR New Generated Asset).
    *   Ensure proper captions are added below images.

### **Bibliography**
*   Parse the `---REFERENCES---` block from the draft text.
*   Sort by Type (Internal/Web/Academic).
*   Append as the final section of the DOCX.
