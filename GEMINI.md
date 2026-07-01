# Agent Instructions

> This file is mirrored across CLAUDE.md, AGENTS.md, and GEMINI.md so the same instructions load in any AI environment.

You operate within a 3-layer architecture that separates concerns to maximize reliability. LLMs are probabilistic, whereas most business logic is deterministic and requires consistency. This system fixes that mismatch.

## Start Here

When you first enter this repo, anchor on the real runtime surfaces before reading broader planning docs.

- App entry: `app.py`
- Launchers: `run.sh`, `run.bat`, `run_app.bat`
- Core implementation: `execution/`
- Workflow directives: `directives/`
- Regression suite: `tests/`
- Deliverables and sidecars: `exports/`

Use these commands first when you need to run or validate the system:

```bash
pip install -r requirements.txt
./run.sh
pytest
pytest tests/test_chapter_update_evaluator.py tests/test_research_agent.py tests/test_gemini_client.py tests/test_doc_builder.py
RUN_LIVE_API_TESTS=1 pytest tests/test_live_single_chapter.py -m live_api
```

## The 3-Layer Architecture

**Layer 1: Directive (What to do)**
- SOPs in `directives/`
- Define goals, inputs, tools/scripts to use, outputs, and edge cases
- Natural-language instructions, like you would give a capable operator

**Layer 2: Orchestration (Decision making)**
- This is you
- Read directives, route work to the right scripts, handle errors, ask for clarification when inputs are genuinely missing, and keep the workflow moving
- Prefer using existing repo tools over improvising manual work

**Layer 3: Execution (Doing the work)**
- Deterministic Python modules in `execution/`
- Handle parsing, LLM calls, research, graph/image generation, export, and validation
- Environment variables and credentials live in `.env` and ignored local auth files

## Runtime Shape

The application is a Streamlit state machine in `app.py` with this high-level flow:

1. Upload and extract source report
2. Keep or discard source assets
3. Plan source visual updates
4. Edit research blueprint per chapter
5. Generate updated chapter drafts
6. Review drafts and approve visuals
7. Assemble final exports

Most business logic is not in the UI widgets themselves. The controlling modules are typically:

- Parsing: `execution/parse_pdf.py`, `execution/parse_docx.py`
- Asset analysis: `execution/vision_service.py`
- Research: `execution/research_agent.py`
- Writing: `execution/writer_agent.py`
- Graph generation: `execution/graph_generator.py`
- Export assembly: `execution/doc_builder.py`
- Quality checks: `execution/quality_gate.py`
- Provider routing and usage tracking: `execution/llm_client.py`, `execution/llm_usage.py`

## Environment and Model Configuration

Default provider behavior is controlled centrally through `execution/llm_client.py`.

- `LLM_PROVIDER=gemini|openai`
- `GEMINI_API_KEY` for Gemini
- `OPENAI_API_KEY` for OpenAI
- `OPENAI_MODEL` for the default OpenAI model
- Optional role-specific overrides:
	- `OPENAI_WRITER_MODEL`
	- `OPENAI_ANALYZER_MODEL`
	- `OPENAI_VISION_MODEL`
	- `OPENAI_RESEARCH_RANKER_MODEL`
	- `OPENAI_TRANSLATOR_MODEL`
	- `OPENAI_GRAPH_MODEL`
	- `OPENAI_CHAPTER_JUDGE_MODEL`

Do not bypass `execution/llm_client.py` for app-level provider calls unless there is a very good reason. That module centralizes provider selection, compatibility handling, and usage telemetry.

## Runtime Data Contracts

The app depends heavily on `st.session_state`. Preserve shape compatibility when you change workflow code.

Common chapter fields include:

- `id`
- `title`
- `content`
- `original_full_text`
- `baseline`
- `blueprint`
- `draft_text`
- `references`
- `suggested_visuals`
- `approved_visuals`
- `graphable_questions`
- `source_graph_refreshes`

Common asset fields include:

- `id`
- `type`
- `path`
- `short_caption`
- `description`
- `analysis`
- `update_query`
- `extracted_data_points`

Before changing chapter or asset structures, check downstream consumers in `app.py`, `execution/doc_builder.py`, `execution/quality_gate.py`, and the corresponding tests.

## Operating Principles

**1. Check for tools first**
- Before writing a new script, inspect `execution/` and the relevant directive
- Reuse the existing deterministic modules whenever possible

**2. Follow the controlling code path**
- Start from the concrete runtime surface that owns the behavior
- In this repo that is often `app.py` for orchestration and one module in `execution/` for the real logic

**3. Self-anneal when things break**
- Read the actual error and stack trace
- Fix the script or routing issue
- Re-run the smallest relevant validation
- If the change teaches the system something durable, update the directive or instructions when asked

**4. Respect paid and live surfaces**
- Some tests use network or paid APIs
- Prefer deterministic tests first
- Be explicit before running expensive or quota-sensitive live checks unless the user has already asked for them

**5. Keep directives stable**
- Directives are part of the instruction set, not throwaway notes
- Improve them when the user asks or when the workflow explicitly calls for directive maintenance
- Do not casually replace them during unrelated code work

## File and Artifact Conventions

**Intermediates**
- `.tmp/` is for temporary processing artifacts and regenerated work files

**Deliverables**
- `exports/` holds report outputs such as `.docx`, `.zip`, usage sidecars, and visual manifests

**Source code**
- `execution/` contains deterministic implementation code
- `directives/` contains workflow SOPs
- `tests/` contains regression coverage and live canaries

When you notice temp or generated files outside `.tmp/` or `exports/`, treat that as repo hygiene debt rather than normal structure.

## Practical Guidance

- Prefer targeted tests in `tests/` over broad manual inspection
- When changing export behavior, inspect both `execution/doc_builder.py` and `execution/quality_gate.py`
- When changing provider behavior, inspect `execution/llm_client.py` and the tests around it
- When changing chapter-generation behavior, inspect `execution/research_agent.py`, `execution/writer_agent.py`, and the state transitions in `app.py`
- Treat the top-level plan and architecture markdown files as supporting context, not the final source of truth over the code

## Summary

You sit between human intent, repo directives, and deterministic execution modules. Read the closest directive, locate the controlling runtime path, prefer existing tools, validate narrowly, and keep output artifacts and workflow contracts consistent.

