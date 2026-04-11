# Project Overview

## What this project does

Report Updater v3 is a Streamlit application that takes a legacy report in PDF or DOCX form and produces an updated edition.

The system:
- extracts chapters and embedded visuals from the source report
- lets the user choose which original visuals to keep
- lets the user decide which retained charts and tables should be updated or converted before drafting
- analyzes selected visuals with Gemini Vision
- infers chapter metadata and update settings
- performs fresh research from web, academic, and uploaded internal sources
- rewrites each chapter as a new edition with inline citations
- suggests or regenerates visuals
- runs a quality gate before export
- exports a polished DOCX and Markdown version
- can optionally translate the final report into additional languages

This is not just a parser or summarizer. It is a report modernization pipeline.

## Primary user workflow

The app is organized as a 7-step state machine in `app.py`.

1. Upload source report
   - User uploads a PDF or DOCX.
   - The app extracts chapters, text, and embedded visuals after confirmation.
   - It also tries to infer the original report date from front matter.

2. Source asset selection
   - The user reviews extracted visuals.
   - Selected visuals are analyzed with Gemini Vision.
   - The selected set becomes the pool of source visuals that can stay in the updated report.

3. Source visual update planning
   - The user reviews retained source charts and tables on a dedicated screen.
   - Each item can stay as-is, be refreshed with newer data, or be converted into editable text.

4. Research planning
   - Each chapter gets a blueprint:
     - topic
     - timeframe
     - keywords
     - writing instructions
     - output language
     - audience
   - The user can upload chapter-specific reference documents.

5. Draft generation
   - The app performs:
     - web research via DuckDuckGo
     - academic research via OpenAlex
     - internal search over uploaded reference docs
   - Gemini rewrites each chapter into a new edition.
   - The response includes:
     - updated chapter text
     - citations
     - executive takeaway
     - retained and updated claims
     - visual suggestions

6. Draft review and visual approval
   - The user edits chapter text.
   - The user approves or rejects updated source visuals and newly proposed visuals.
   - A quality gate checks for:
     - unsupported factual claims
     - citation/reference mismatches
     - broken figure markers
     - stale update-window evidence
     - malformed URLs
   - Auto-fixable problems can be cleaned before export.

7. Final assembly
   - Approved graphs are generated.
   - Approved images are searched and downloaded.
   - The final report is assembled as DOCX and Markdown.
   - Optional translated DOCX versions can also be generated.

## Architecture

The repo is designed around a 3-layer model:

- Layer 1: directives
  - Markdown SOPs in `directives/`
  - define intended workflow and behavior

- Layer 2: orchestration
  - mostly `app.py`
  - manages user flow, session state, routing, and step ordering

- Layer 3: execution
  - deterministic Python modules in `execution/`
  - parsing, research, writing, export, translation, and quality checks

## Main files and responsibilities

- `app.py`
  - Streamlit UI and end-to-end orchestration

- `directives/Layer_1.md`
  - master process description for the 7-state workflow

- `execution/parse_pdf.py`
  - extracts PDF chapters and images

- `execution/parse_docx.py`
  - extracts DOCX chapters and images

- `execution/vision_service.py`
  - analyzes selected visuals with Gemini Vision

- `execution/chapter_analyzer.py`
  - creates a baseline summary and metadata for each original chapter

- `execution/report_metadata_analyzer.py`
  - infers original report date from the report text

- `execution/research_agent.py`
  - orchestrates web, academic, and internal research

- `execution/writer_agent.py`
  - rewrites a chapter into an updated edition using Gemini

- `execution/graph_generator.py`
  - generates charts from approved visual suggestions

- `execution/image_search.py`
  - searches and downloads images for approved image suggestions

- `execution/quality_gate.py`
  - checks export readiness and applies limited cleanup fixes

- `execution/doc_builder.py`
  - assembles final DOCX and Markdown outputs

- `execution/translator.py`
  - translates finalized chapter text into other languages

## Inputs and outputs

### Inputs

- source report: PDF or DOCX
- Gemini API key
- optional reference documents: PDF, DOCX, TXT
- user selections for visuals and research settings

### Outputs

- final DOCX report in `exports/`
- final Markdown export in `exports/`
- optional translated DOCX files in `exports/`
- temporary intermediate assets in `.tmp/`

## External services and dependencies

The project depends on:
- Gemini models for analysis, writing, vision, graph code generation, and translation
- DuckDuckGo search for web and image discovery
- OpenAlex for academic search
- Python libraries such as Streamlit, python-docx, PyMuPDF, pdfplumber, requests, and matplotlib

Without a valid `GEMINI_API_KEY`, core parts of the system will not work.

## What is already implemented

The implemented code goes beyond the basic README description. In addition to the main pipeline, it already includes:

- chapter baseline analysis before rewriting
- report date inference from document text
- citation normalization across chapters
- quality gate and auto-cleanup before export
- Markdown export packaging with images
- optional translation of the finalized report

## Practical summary for a future coding agent

If you are picking this project up later, the most important fact is:

This app is meant to turn an old report into a new edition, not merely extract text or generate a generic summary.

The core path to understand first is:

`app.py` -> extraction -> asset analysis -> blueprint planning -> research -> chapter writing -> quality gate -> export

If behavior seems unclear, compare:
- intended workflow in `directives/`
- actual behavior in `app.py`
- implementation details in `execution/`

## Best starting points for future work

If you need to continue development, read these first:

1. `PROJECT_OVERVIEW.md`
2. `README.md`
3. `directives/Layer_1.md`
4. `app.py`
5. the relevant module in `execution/`
