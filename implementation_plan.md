# Implementation Plan - Report Updater v3

## Phase 1: Environment & Foundation
- [x] Project Structure (directives/, execution/, .tmp/)
- [x] Initial Configuration (.env, .gitignore)
- [x] Install Dependencies (Update `requirements.txt` and install)
- [x] Create `app.py` skeleton (Streamlit State Machine Structure)

## Phase 2: Layer 1 - Directives (SOPs)
- [x] `directives/Layer_1.md` (Master Plan)
- [x] Create `directives/research_chapter.md`: logic for taking settings and generating text+visuals.
- [x] Create `directives/generate_visuals.md`: logic for code generation and image scraping.
- [x] Create `directives/doc_assembly.md`: standards for the final DOCX structure.

## Phase 3: Layer 3 - Execution (Tools & Scripts)
### Ingestion (Parsing)
- [x] `execution/parse_pdf.py`: Use `pdfplumber` for text/tables and `fitz` (PyMuPDF) for images.
- [x] `execution/parse_docx.py`: Use `python-docx` and XML parsing for text/images.
- [x] `execution/vision_service.py`: Wrapper for `google.generativeai` (Gemini Flash/Pro Vision).

### Research & Writing (Agents)
- [x] `execution/research_agent.py`:
    - Implement `DuckDuckGoSearchRun`.
    - Implement basic Academic search (optional for v1, maybe specific site search).
    - Implement file reader for internal uploaded docs.
- [x] `execution/writer_agent.py`:
    - Prompt engineering for "Research Report Chapter".
    - Structured Output Parser for JSON `{"text": "", "visuals": []}`.

### Visual Production (Media)
- [x] `execution/graph_generator.py`:
    - Sandboxed Python executor (e.g., using `exec` with restricted globals or a separate process).
    - Support `matplotlib` and `plotly`.
    - Return image bytes.
- [x] `execution/image_search.py`:
    - Wrapper for DDG Image Search.
    - Image downloader with timeout/headers.

### Final Export
- [x] `execution/doc_builder.py`:
    - Class `DocBuilder` that initializes a `Document()`.
    - Methods to add headings, text, and embed images (centering, captions).
    - Bibliography generator logic.

## Phase 4: Layer 2 - Orchestration (App Logic)
### State 1: Upload
- [x] `app.py`: `render_upload_extract()`
    - Handle file upload limits.
    - Display spinners during parsing.
    - Store `raw_chapters` (List[Dict]) in `st.session_state`.

### State 2: Selection
- [x] `app.py`: `render_asset_selection()`
    - Use `st.image` in columns for a gallery view.
    - Store `kept_asset_ids` in `st.session_state`.
    - Trigger `vision_service` on "Next" click.

### State 3: Planning
- [x] `app.py`: `render_research_planning()`
    - Iterate `session_state.chapters`.
    - `st.text_input` for Topic/Keywords.
    - `st.file_uploader` for specific reference docs.

### State 4: Generation
- [x] `app.py`: `render_draft_generation()`
    - `st.status` container to show live progress ("Researching...", "Writing...").
    - Call `writer_agent` per chapter.
    - Error handling (retry logic).

### State 5: Verification
- [x] `app.py`: `render_draft_verification()`
    - Two-column layout: Text Editor (Left) vs Settings/Visuals (Right).
    - "Regenerate" button logic (modifies specific chapter in state and re-runs).
    - "Add Visual" manual override.

### State 6: Export
- [x] `app.py`: `render_final_assembly()`
    - Run `graph_generator` for approved visuals.
    - Clean up temporary files.
    - Offer `st.download_button`.

