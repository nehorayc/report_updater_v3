# Active Backlog - Report Updater v3

This file is the active project roadmap.

The existing [implementation_plan.md](implementation_plan.md) is still useful as v1 build history, but this backlog is now the source of truth for current work.

## Product Definition

The app should turn an older report into a new dated edition.

Example:
- Input: an AI report originally published in 2023
- Output: a refreshed report covering the period from the original report date through `2026-03-22`, while preserving the original report as a baseline source and clearly referencing it

The system should behave like an edition updater, not a generic rewrite tool.

## Goals

1. Preserve the original report's thesis, structure, and strongest insights.
2. Update outdated claims, numbers, and visuals with newer evidence.
3. Make it obvious what changed since the original edition.
4. Produce a cleaner, more credible report with stronger citations and better structure.
5. Prefer deterministic, testable logic for high-risk steps.

## Latest Review Findings - 2026-03-24

Review of the latest generated product report surfaced a few gaps that now need to drive the active backlog:

1. Citation integrity is still not reliable in exports. Some inline citations point to missing bibliography entries or still leak raw `Original`-style markers.
2. The original report is still being overused as evidence for claims that are supposed to describe the update window.
3. Bibliography quality is too weak in places. Generic topic/archive pages are getting through as if they were strong sources.
4. Output language is inconsistent. Titles, chapter names, front matter, captions, and bibliography text can mix Hebrew and English in the same report.
5. Chapter prose does not flow well enough yet. The model still carries forward numbered indents and source-outline structure instead of producing smooth narrative chapters.
6. Visual integration still has artifacts, including raw marker remnants and chart caption/date mismatches.

## Latest Review Findings - 2026-03-25

Review of the newest successful export and matching runtime logs surfaced a tighter set of defects:

1. The quality gate allowed a report to export even though raw `[Original Report]` citations and raw `[visual: ...]` / `[Figure ...]` tokens were still visible in the final Markdown.
2. Failed visual downloads are logged, but the failed visual can still leak its placeholder into the exported report.
3. Some PDFs still collapse into a single giant extracted chapter, which then pushes the writer toward one long memo-like output.
4. Narrative flow is still too list-heavy in monolithic chapters even when citations and language are otherwise improved.

## Status Legend

- `todo`: not started
- `in_progress`: actively being implemented
- `blocked`: waiting on a decision or dependency
- `done`: implemented and verified

## Priority Legend

- `P0`: core product behavior
- `P1`: major output-quality improvement
- `P2`: polish, resilience, and workflow improvement

## P0 - Core Product Behavior

### B001 - Add explicit report update metadata
- Priority: `P0`
- Status: `in_progress`
- Owner area: [app.py](app.py)
- Goal: collect `original_report_date`, `update_start_date`, `update_end_date`, `target_audience`, `edition_title`, and `preserve_original_voice`
- Notes:
  - Default `update_end_date` to `2026-03-22`
  - Use absolute dates in the UI and downstream prompts
- Acceptance criteria:
  - Metadata is collected before research begins
  - Metadata is stored in `st.session_state`
  - All downstream steps can access the selected update window

### B002 - Build a structured baseline from the original report
- Priority: `P0`
- Status: `in_progress`
- Owner areas: [execution/chapter_analyzer.py](execution/chapter_analyzer.py), [app.py](app.py)
- Goal: extract a chapter baseline instead of only a summary
- Required baseline fields:
  - `summary`
  - `keywords`
  - `core_claims`
  - `dated_facts`
  - `named_entities`
  - `stats`
  - `original_citations`
  - `original_figures`
  - `chapter_role`
- Acceptance criteria:
  - Each chapter stores a structured `baseline`
  - The planning UI shows the extracted baseline for review
  - Draft generation uses the baseline, not just a short summary

### B003 - Fix uploaded reference document ingestion
- Priority: `P0`
- Status: `in_progress`
- Owner areas: [execution/research_agent.py](execution/research_agent.py), [execution/parse_pdf.py](execution/parse_pdf.py), [execution/parse_docx.py](execution/parse_docx.py), [app.py](app.py)
- Goal: properly read uploaded `pdf`, `docx`, and `txt` files for internal research
- Notes:
  - Current behavior treats binary files as plain text
  - Reference docs should be normalized into text blocks before search
- Acceptance criteria:
  - Uploaded PDF and DOCX files produce readable internal search results
  - Internal search returns real paragraph matches
  - Reference parsing failures are visible in the UI

### B004 - Make research window-aware and source-ranked
- Priority: `P0`
- Status: `in_progress`
- Owner area: [execution/research_agent.py](execution/research_agent.py)
- Goal: research specifically for the selected update window instead of doing generic "latest" search
- Required improvements:
  - Build queries from topic + timeframe + keywords + original report year
  - Rank sources by freshness, relevance, and source quality
  - Distinguish `Original`, `Uploaded`, `Academic`, and `Web`
  - Add a real academic path such as OpenAlex
- Acceptance criteria:
  - Research results are tied to the chosen update window
  - Result objects include source metadata and ranking signals
  - Academic sources can be surfaced separately from web results

### B005 - Change writing from generic rewrite to edition update
- Priority: `P0`
- Status: `in_progress`
- Owner area: [execution/writer_agent.py](execution/writer_agent.py)
- Goal: generate a proper updated edition chapter
- Required output fields:
  - `executive_takeaway`
  - `retained_claims`
  - `updated_claims`
  - `new_claims`
  - `open_questions`
  - `text_content`
  - `visual_suggestions`
  - `references`
- Required chapter flow:
  - original context
  - developments since original edition
  - current state
  - implications
  - near-term outlook
- Acceptance criteria:
  - New chapters preserve original insights where appropriate
  - Updated claims are supported by newer evidence
  - Output reads like a new edition, not a generic rewritten article

### B006 - Normalize citations globally before export
- Priority: `P0`
- Status: `in_progress`
- Owner areas: [execution/doc_builder.py](execution/doc_builder.py), [app.py](app.py)
- Goal: ensure inline citations match the final bibliography after merging and deduplication
- Notes:
  - Writer output can stay chapter-local
  - Final assembly must remap citation numbers globally
  - Review on `2026-03-24` found export regressions: missing bibliography items, raw `Original` markers, and references cited in text but not present in the final bibliography
- Acceptance criteria:
  - Inline references match the final bibliography numbering
  - Deduplicated sources keep a stable final index
  - DOCX and Markdown exports use the same citation mapping
  - No exported report contains raw `Original` citation markers
  - No exported report cites a reference number that is absent from the bibliography

### B007 - Add a pre-export quality gate
- Priority: `P0`
- Status: `done`
- Owner areas: [app.py](app.py), `execution/quality_gate.py`
- Goal: detect major content and assembly issues before final export
- Required checks:
  - stale years left unaddressed
  - unsupported factual claims
  - hallucinated URLs
  - missing citations
  - broken figure markers
  - no evidence from the selected update window
- Acceptance criteria:
  - Severe issues are shown to the user before export
  - Export is blocked on severe failures
  - Warnings are visible chapter by chapter

### B019 - Harden export-safe token cleanup and failed visual stripping
- Priority: `P0`
- Status: `in_progress`
- Owner areas: [app.py](app.py), [execution/doc_builder.py](execution/doc_builder.py), [execution/quality_gate.py](execution/quality_gate.py), [execution/writer_agent.py](execution/writer_agent.py)
- Goal: guarantee that no internal citation or visual placeholder syntax survives into a user-facing export
- Required improvements:
  - normalize raw original-report citations such as `[Original Report]` before export
  - detect and clean raw visual tokens such as `[visual: ...]` and orphan `[Figure ...]` markers
  - remove failed visuals from the export path instead of leaving a broken placeholder behind
  - make the quality gate aware of export-visible raw tokens
- Acceptance criteria:
  - exported DOCX and Markdown files contain no raw internal citation tokens
  - exported DOCX and Markdown files contain no raw visual placeholder tokens
  - failed image or chart generation cannot leak a marker into the final report
  - quality gate catches these defects before export if cleanup misses them

## P1 - Output Quality Improvements

### B008 - Improve the final report structure
- Priority: `P1`
- Status: `done`
- Owner areas: [app.py](app.py), [execution/doc_builder.py](execution/doc_builder.py)
- Goal: make the report feel like a professional updated edition
- Add these sections:
  - title page with original edition date and updated-through date
  - executive summary
  - methodology
  - key developments since the original edition
  - updated chapters
  - bibliography
- Acceptance criteria:
  - Final report explains how original and updated evidence were combined
  - The executive summary highlights what changed since the original report
  - Output feels editorially structured rather than AI-generated

### B009 - Improve chapter content quality rules
- Priority: `P1`
- Status: `in_progress`
- Owner area: [execution/writer_agent.py](execution/writer_agent.py)
- Goal: consistently produce stronger, more useful prose
- Content rules:
  - Every factual paragraph should have at least one citation
  - New evidence should lead the narrative
  - Original insights should be preserved when still relevant
  - Conflicting evidence should be surfaced rather than flattened
  - Claims should use exact organizations, dates, and figures when available
  - The chapter should read like a report chapter, not like a preserved source outline
  - Avoid lettered and numbered indents unless the user explicitly wants outline style
- Acceptance criteria:
  - Chapters are less generic and more evidence-dense
  - Citation coverage improves materially
  - Chapters answer "what changed since the original edition?"
  - Chapters flow as narrative prose with only selective use of bullets or numbering

### B010 - Enforce citation-to-source credibility
- Priority: `P1`
- Status: `in_progress`
- Owner areas: [execution/research_agent.py](execution/research_agent.py), [execution/writer_agent.py](execution/writer_agent.py), [execution/doc_builder.py](execution/doc_builder.py)
- Goal: stop low-quality or generic pages from entering the final report as if they were evidence
- Required improvements:
  - reject generic archive pages, topic pages, and navigational pages from the final bibliography
  - prefer primary sources, papers, company releases, filings, standards bodies, and high-signal reporting
  - only keep references that actually support a claim in the text
  - separate "background" sources from "evidence" sources if both are retained
- Acceptance criteria:
  - final bibliographies do not include generic archive/topic pages unless the user explicitly approves them
  - each retained citation supports a concrete claim in the text
  - source quality is visibly higher in generated reports

### B011 - Normalize output language by report target language
- Priority: `P1`
- Status: `in_progress`
- Owner areas: [app.py](app.py), [execution/writer_agent.py](execution/writer_agent.py), [execution/doc_builder.py](execution/doc_builder.py)
- Goal: keep each exported report linguistically consistent from title to bibliography
- Required improvements:
  - infer or let the user choose a target output language
  - keep front matter, chapter names, section headers, captions, and bibliography labels in that language
  - avoid mixed Hebrew/English section titles unless the user explicitly wants bilingual output
- Acceptance criteria:
  - chapter names match the selected report language
  - executive summary, methodology, and bibliography labels match the selected report language
  - mixed-language output is treated as a defect unless explicitly requested

### B012 - Improve narrative flow and remove outline carryover
- Priority: `P1`
- Status: `in_progress`
- Owner areas: [execution/writer_agent.py](execution/writer_agent.py), [app.py](app.py)
- Goal: turn extracted outline structure into readable report prose
- Required improvements:
  - flatten excessive numbered and lettered lists into paragraphs or short bullet groups
  - preserve section hierarchy without copying memo-style indentation from the source report
  - add transition sentences between major sections
  - add a style rule that favors report narrative over outline reproduction
- Acceptance criteria:
  - generated chapters read continuously instead of as nested outline notes
  - numbered indents only appear when genuinely helpful
  - the report feels editorially coherent from start to finish

### B020 - Improve monolithic PDF fallback structure
- Priority: `P1`
- Status: `in_progress`
- Owner areas: [execution/parse_pdf.py](execution/parse_pdf.py), [execution/writer_agent.py](execution/writer_agent.py)
- Goal: preserve internal structure when a source PDF fails to split cleanly into multiple chapters
- Required improvements:
  - strip recurring page-marker noise from extracted text
  - detect internal heading lines inside large single-chapter extracts
  - promote detected internal headings into structured source text that the writer can follow
  - add a deterministic prose-shaping pass so one big chapter does not become a giant bullet memo
- Acceptance criteria:
  - large single-chapter extracts preserve recognizable internal section boundaries
  - generated chapters have clearer transitions and fewer long bullet runs
  - sample PDFs that previously produced one giant memo now yield cleaner sectioned prose

### B013 - Add topic-specific update packs
- Priority: `P1`
- Status: `todo`
- Owner areas: [execution/writer_agent.py](execution/writer_agent.py), `directives/topic_ai_update.md`
- Goal: improve coverage for recurring report types
- First topic pack:
  - AI update pack covering models, enterprise adoption, regulation, compute, multimodality, agents, and safety
- Acceptance criteria:
  - AI reports stop missing major modern themes
  - Topic packs can be extended to other domains later

### B014 - Improve visual update quality
- Priority: `P1`
- Status: `todo`
- Owner areas: [execution/vision_service.py](execution/vision_service.py), [execution/graph_generator.py](execution/graph_generator.py), [execution/doc_builder.py](execution/doc_builder.py)
- Goal: better preserve the intent of original figures and tables
- Required improvements:
  - extract more structured chart metadata from original visuals
  - carry source note and time range into regenerated charts
  - improve handling of updated tables as text
  - ensure the final embedded caption matches the chart time range and the in-text claim
  - remove raw visual markers from final exports
- Acceptance criteria:
  - regenerated visuals stay faithful to the original figure's role
  - updated visuals are easier to interpret and better labeled
  - no raw figure markers remain in exported reports

## P1 - Safety And Determinism

### B015 - Replace risky LLM code execution for charts
- Priority: `P1`
- Status: `todo`
- Owner area: [execution/graph_generator.py](execution/graph_generator.py)
- Goal: move from executable LLM chart code to deterministic chart rendering
- Notes:
  - Keep LLM help for describing chart intent if needed
  - Do not rely on `exec` for final chart production
- Acceptance criteria:
  - Charts are rendered from structured data only
  - Chart generation is predictable and testable
  - Arbitrary code execution is removed from the chart path

## P2 - Workflow, Reliability, And Cleanup

### B016 - Align directives with the real product goal
- Priority: `P2`
- Status: `todo`
- Owner areas:
  - [directives/Layer_1.md](directives/Layer_1.md)
  - [directives/research_chapter.md](directives/research_chapter.md)
  - [directives/generate_visuals.md](directives/generate_visuals.md)
  - [directives/doc_assembly.md](directives/doc_assembly.md)
- Goal: make the directives explicitly about edition updating, not generic modernization
- Acceptance criteria:
  - Directives consistently describe the edition-update workflow
  - Date-window handling and original-report preservation are documented

### B017 - Improve export naming and cleanup
- Priority: `P2`
- Status: `todo`
- Owner areas: [app.py](app.py), [execution/doc_builder.py](execution/doc_builder.py)
- Goal: make exports cleaner and closer to the directive spec
- Required improvements:
  - use the original report name for translated exports too
  - include metadata like original edition date and updated-through date
  - clean `.tmp/` intermediates after successful export
- Acceptance criteria:
  - Export names are consistent
  - Temporary files do not accumulate unnecessarily
  - Export metadata reflects the edition update window

### B018 - Add proper automated tests
- Priority: `P2`
- Status: `todo`
- Owner areas: [requirements.txt](requirements.txt), [tests](tests)
- Goal: make the repo verifiable in a repeatable way
- Test targets:
  - citation remapping
  - baseline extraction schema
  - reference document parsing
  - update-window query generation
  - quality gate checks
  - deterministic chart rendering
- Acceptance criteria:
  - `pytest` is installed in the project environment
  - `python -m pytest -q` runs successfully
  - Critical document-assembly logic has coverage

## Recommended Build Order

1. `B001` Add report update metadata
2. `B002` Build chapter baselines
3. `B003` Fix reference doc ingestion
4. `B004` Make research window-aware and ranked
5. `B005` Change the writer to edition-update mode
6. `B006` Normalize citations globally
7. `B010` Enforce citation-to-source credibility
8. `B011` Normalize output language by report target language
9. `B012` Improve narrative flow and remove outline carryover
10. `B007` Add the pre-export quality gate
11. `B008` Improve final report structure
12. `B014` Improve visual update quality
13. `B015` Replace risky LLM chart execution
14. `B018` Add automated tests

## Immediate Next Slice

If we start implementation now, the best first slice is:

1. [app.py](app.py), [execution/doc_builder.py](execution/doc_builder.py), [execution/quality_gate.py](execution/quality_gate.py), and [execution/writer_agent.py](execution/writer_agent.py): remove raw citation and visual tokens from the export path and strip failed visuals before assembly
2. [execution/parse_pdf.py](execution/parse_pdf.py) and [execution/writer_agent.py](execution/writer_agent.py): improve monolithic single-chapter flow so large reports keep internal structure and export as readable prose
3. [execution/research_agent.py](execution/research_agent.py): continue tightening source filtering so weak archive/topic pages do not survive into exports
4. [app.py](app.py): keep review feedback clear when cleanup changed the draft or when a visual was dropped before export

This slice targets the most visible defects in the current product output: raw export tokens, failed-visual leakage, weak monolithic flow, and still-fragile source quality.
