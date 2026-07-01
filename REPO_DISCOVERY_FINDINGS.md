# Repo Discovery Findings

Date: 2026-06-23
Scope: Read-only repo discovery. No existing files were modified.

## 1. Architecture summary

This repo is a Streamlit application that modernizes a legacy report into a current edition. The implementation follows the documented 3-layer model:

- Layer 1: `directives/`
  - Markdown SOPs describing intended workflow and rules.
- Layer 2: orchestration in `app.py`
  - A 7-step Streamlit state machine controls upload, extraction, planning, drafting, review, QA, and export.
- Layer 3: `execution/`
  - Python modules handle parsing, LLM routing, research, writing, graph/image production, QA, export, translation, and usage telemetry.

In practice, `app.py` is the orchestration hub and most business state lives in `st.session_state`. The repo is not packaged as an installable Python module; instead, `app.py` appends `execution/` to `sys.path` and imports execution modules directly.

## 2. Main entry points

Primary runtime entry points:

- `app.py`
  - Main Streamlit app and state machine.
  - `main()` dispatches to the 7 workflow screens.
- `run.sh`
  - Linux/devcontainer launcher for `python -m streamlit run app.py`.
- `run.bat`
  - Windows launcher.
- `run_app.bat`
  - Slightly more verbose Windows launcher with setup guidance.

Secondary direct script entry points, mostly for local debugging/smoke usage:

- `execution/parse_pdf.py`
- `execution/parse_docx.py`
- `execution/chapter_analyzer.py`
- `execution/research_agent.py`
- `execution/writer_agent.py`
- `execution/graph_generator.py`
- `execution/image_search.py`
- `execution/doc_builder.py`

Test entry:

- `pytest`
  - Configured by `pytest.ini` with `tests/` as the test root.

## 3. Important directories

- `execution/`
  - Core deterministic layer.
  - Notable modules:
    - `parse_pdf.py`, `parse_docx.py`
    - `chapter_analyzer.py`, `report_metadata_analyzer.py`
    - `vision_service.py`, `graph_update_helpers.py`
    - `research_agent.py`, `writer_agent.py`
    - `graph_ranking.py`, `graph_question_discovery.py`
    - `quality_gate.py`, `doc_builder.py`
    - `translator.py`, `report_change_summary.py`
    - `llm_client.py`, `gemini_client.py`, `llm_usage.py`
- `directives/`
  - Workflow and export SOPs.
- `tests/`
  - Good coverage across parsers, research, graph update flow, export, QA, usage, and live canaries.
- `.tmp/`
  - Intermediate assets and generated visuals.
- `exports/`
  - Final DOCX, Markdown ZIP, export folders, usage JSON/CSV, visual manifests.
- `skills/`
  - Separate Codex/agent skills; useful for AI tooling, but not part of the app runtime path.
- `.devcontainer/`
  - Devcontainer setup for local development.

## 4. How data flows

High-level flow:

1. Source intake
   - User uploads a PDF or DOCX in `app.py`.
   - The upload is written to `.tmp/`.
   - `parse_pdf.extract_pdf_content()` or `parse_docx.extract_docx_content()` returns:
     - `chapters`
     - `assets`

2. Baseline understanding
   - `report_metadata_analyzer.py` infers the original report date.
   - `chapter_analyzer.analyze_chapters_batch()` summarizes each chapter and extracts baseline metadata.
   - The app stores normalized chapter and asset objects in `st.session_state`.

3. Source visual understanding
   - User selects source visuals to retain.
   - `vision_service.analyze_batch_assets()` analyzes selected visuals.
   - For charts, it may load sidecar datapoints or extract datapoints with an LLM.

4. Research planning
   - `report_context.build_chapter_blueprint_defaults()` seeds each chapter blueprint.
   - User edits topic, timeframe, keywords, audience, language, and reference docs.

5. Research and drafting
   - `research_agent.perform_comprehensive_research()` gathers:
     - internal paragraph matches from uploaded docs
     - web results from DuckDuckGo/DDGS plus fetched article bodies
     - academic results from OpenAlex
     - LLM fallback findings if external search returns nothing
   - If a retained chart is marked for refresh, `graph_update_helpers.prepare_source_graph_refresh()` merges new findings with extracted historical datapoints.
   - `writer_agent.write_chapter()` produces structured output:
     - `text_content`
     - `executive_takeaway`
     - `retained_claims`
     - `updated_claims`
     - `new_claims`
     - `open_questions`
     - `visual_suggestions`
     - `references`

6. Review and candidate ranking
   - The app normalizes visual markers into canonical IDs in the chapter text.
   - `graph_ranking.build_ranked_graph_candidate_groups()` scores graph suggestions and determines auto/manual/review selection modes.
   - User edits draft text and approves visuals.

7. QA and cleanup
   - `quality_gate.clean_fixable_issues()` removes fixable token/marker/citation issues.
   - `quality_gate.evaluate_report_quality()` checks factual/citation/visual/export readiness.
   - Final assembly can proceed in best-effort mode even with blocking issues.

8. Final assembly and export
   - `visual_pipeline_helpers.resolve_visual_for_export()` routes approved visuals to:
     - `graph_generator.generate_graph()`
     - `image_search.search_and_download_image()`
   - `doc_builder.build_final_report()` creates the DOCX.
   - `doc_builder.build_markdown_report()` creates Markdown plus packaged assets.
   - `translator.translate_texts_batch()` optionally generates translated DOCX versions.
   - `llm_usage.export_usage_reports()` writes usage/cost artifacts beside the exports.
   - Outputs land in `exports/`.

## 5. Build/test commands found

Explicitly documented or scripted:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
./run.sh
python -m streamlit run app.py
```

Windows launchers:

```bat
run.bat
run_app.bat
```

Test command clearly implied by repo structure:

```bash
pytest
```

Useful test-related facts found:

- `pytest.ini` defines markers:
  - `slow`
  - `network`
  - `live_api`
- Live canary tests require:
  - `RUN_LIVE_API_TESTS=1`
  - `GEMINI_API_KEY`
- One live path optionally uses:
  - `RUN_LIVE_LLM_JUDGE=1`

Things I did not find:

- No `Makefile`
- No `tox.ini`
- No `noxfile.py`
- No obvious CI workflow checked during this pass
- No documented single-command local test recipe in `README.md`

## 6. Risks or confusing areas

1. `app.py` is very large and owns too much
   - It is 2,678 lines and mixes UI, session-state management, orchestration, runtime notices, visual normalization, and export triggering.
   - This is the main maintainability risk.

2. Import strategy is fragile
   - `app.py` mutates `sys.path` to import from `execution/`.
   - Tests also insert repo paths into `sys.path`.
   - This works, but it makes packaging, tooling, and reuse less predictable.

3. Architecture docs are duplicated
   - The root contains multiple overlapping architecture docs:
     - `ARCHITECTURE_SCHEMATICS.md`
     - `ARCHITECTURE_SCHEMATICS_CEO.md`
     - `CEO_ARCHITECTURE_SCHEMATICS.md`
     - `PROJECT_OVERVIEW.md`
   - They are useful, but keeping them aligned could become a drift risk.

4. Best-effort final assembly may mask real defects
   - The quality gate can report blocking issues, but final assembly still continues in best-effort mode.
   - That is pragmatic for delivery, but risky if users assume output validity is guaranteed.

5. External dependency surface is broad
   - Runtime behavior depends on:
     - Gemini or OpenAI
     - DDGS/DuckDuckGo
     - OpenAlex
     - optional image providers like Pixabay, Pexels, SerpApi
   - Failures are handled thoughtfully, but reproducibility will vary by credentials, quota, rate limits, and provider behavior.

6. Repo discovery is noisy because the root contains many sample/generated binaries
   - There are many `.docx` and `.pdf` artifacts in the repo root plus populated `exports/`.
   - `.gitignore` excludes these patterns, but the working tree still feels cluttered during discovery.

7. Some behavior is documented in directives, but the real logic lives elsewhere
   - To understand the app fully, you have to triangulate across:
     - `directives/`
     - `PROJECT_OVERVIEW.md`
     - `app.py`
     - `execution/`
   - That is manageable, but not especially lightweight for onboarding.

8. Tests are present, but the boundary between deterministic and live tests is not documented for contributors
   - The marker setup is good.
   - The usage pattern for local contributors is not written down in the main docs.

## 7. Suggested AGENTS.md improvements

These are suggestions only. I did not edit `AGENTS.md`.

1. Add a "Start here" checklist for future agents
   - Recommended order:
     - `PROJECT_OVERVIEW.md`
     - `directives/Layer_1.md`
     - `README.md`
     - `app.py`
     - relevant `execution/` module

2. Add explicit runtime entry points
   - Call out:
     - `./run.sh`
     - `run.bat`
     - `python -m streamlit run app.py`
     - `pytest`

3. Add a testing policy section
   - Explain:
     - deterministic vs live tests
     - required env vars for live tests
     - when to avoid paid/live tests without user confirmation

4. Add a repo map
   - A short table of the most important modules in `execution/` would reduce onboarding time.

5. Add packaging/import caveats
   - Mention that imports currently rely on repo-root execution and `sys.path` mutation.
   - This would help agents avoid breaking local import assumptions.

6. Add a "do not trust docs alone" note
   - Encourage agents to verify behavior in `app.py` and `execution/`, because the repo has several parallel architecture docs.

7. Clarify final-assembly safety expectations
   - Note explicitly that the app may continue in best-effort mode after QA findings, so agents should be careful when changing validation/export logic.

8. Add a note about workspace noise
   - Explain that generated reports may already exist in `exports/` and the repo root, and that agents should avoid treating those as source-of-truth code artifacts.

## Short conclusion

This is a fairly mature report-modernization pipeline with good execution-module coverage, strong test presence, and thoughtful provider fallback handling. The biggest structural issue is not missing capability; it is concentration of orchestration complexity in `app.py` plus some doc duplication around the intended architecture.
