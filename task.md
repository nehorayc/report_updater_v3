# Task: Report Updater v3 (Horizon/Elisha v1)

## Objective
Build a Streamlit application that modernizes legacy reports (PDF/DOCX). The app ingests a source document, filters source assets, plans research, generates a draft, allowing deep user refinement before final export.

## Detailed Checklist

### Phase 1: Foundation (Current State)
- [x] Environment Setup (.env, .gitignore, .venv)
- [x] Install Dependencies
- [x] App Skeleton (`app.py`)

### Phase 2: Directives (Layer 1)
- [x] Create `directives/research_chapter.md`: Define how to take a topic + context and output a researched draft with visual suggestions.
- [x] Create `directives/generate_visuals.md`: Define how to take a data point and generate python code for a graph.
- [x] Create `directives/doc_assembly.md`: Define how to merge text, images, and tables into a final DOCX.

### Phase 3: Execution Tools (Layer 3)
#### Ingestion
- [x] `execution/parse_pdf.py`: Function `extract_pdf_content(file_path)` returning `List[Chapter]` and `List[Asset]`.
- [x] `execution/parse_docx.py`: Function `extract_docx_content(file_path)` returning `List[Chapter]` and `List[Asset]`.
- [x] `execution/vision_service.py`: Function `transcribe_asset(image_bytes)` using Gemini Vision.

#### Research & Writing
- [x] `execution/research_agent.py`:
    - `search_web(query)`: DuckDuckGo wrapper.
    - `search_academic(query)`: OpenAlex/Arxiv wrapper.
    - `search_internal(query, docs)`: Local vector/keyword search on uploaded docs.
- [x] `execution/writer_agent.py`:
    - `write_chapter(context, blueprint)`: Main LLM call (Gemini).
    - Returns JSON: `{ "text_content": "...", "visual_suggestions": [...] }`

#### Visuals & Export
- [x] `execution/graph_generator.py`: `generate_graph_code(data, type)` and `execute_graph_code(code)`.
- [x] `execution/image_search.py`: `get_image_url(query)` and `download_image(url)`.
- [x] `execution/doc_builder.py`: `build_docx(chapters, assets, output_path)` using `python-docx`.

### Phase 4: Application Logic (Layer 2)
#### State 1: Upload & Extraction
- [x] UI: File Uploader.
- [x] Logic: Call `parse_pdf`/`parse_docx`.
- [x] Logic: Display extraction summary (page count, asset count).

#### State 2: Asset Selection
- [x] UI: Grid view of extracted images/tables.
- [x] Logic: Selection state management (`selected_asset_ids`).
- [x] Logic: Background job to transcribe selected assets (`vision_service`).

#### State 3: Research Planning
- [x] UI: Tabbed view per chapter.
- [x] UI: Editors for "Topic", "Timeframe", "Keywords".
- [x] UI: File uploader for "Reference Docs" per chapter.
- [x] Logic: Save Blueprint object to session state.

#### State 4: Draft Generation
- [x] UI: Progress bar and log console.
- [x] Logic: Serial processing of chapters.
- [x] Logic: Call `research_agent` -> `writer_agent`.
- [x] Logic: Store drafts and visual suggestions.

#### State 5: Verification
- [x] UI: Split view (Draft Text vs. Settings/Visuals).
- [x] UI: "Regenerate" button (re-runs State 4 for specific chapter).
- [x] UI: "Approve" checkbox for visual suggestions.

#### State 6: Final Assembly
- [x] Logic: Execute approved graph code -> save images.
- [x] Logic: Download approved web images.
- [x] Logic: Call `doc_builder` to assemble everything.
- [x] UI: Download button for final DOCX.

