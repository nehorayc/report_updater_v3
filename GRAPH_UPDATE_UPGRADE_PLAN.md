# Graph Update Upgrade Plan

## Objective

Upgrade the graph updater from:

- "describe the old chart, research fresh facts, and let the writer recreate a new graph"

to:

- "extract the old chart's historical datapoints, preserve them exactly, append validated new years, and then render the merged graph"

## Replanned Strategy

This plan now assumes a graph should not be produced in a single shot.

The target system should work as:

- mine `2-3` graphable questions from each chapter's on-topic research findings
- verify that each question has enough structured datapoints to support a real graph
- build a structured graph brief for each graph slot in the report
- generate a batch of candidate graph specs for that slot
- reject invalid or low-trust candidates before ranking
- score the survivors on relevance, usefulness, readability, and faithfulness
- present the top shortlist to the user in ranked order with reasons
- auto-select only when the top candidate clearly clears quality thresholds

This is a shift from:

- "make one graph suggestion and hope it is good enough"

to:

- "find the best graphable questions first, then generate several plausible graphs, evaluate them deterministically, and choose from a scored shortlist"

## Latest Production Audit

The newest export reviewed in this repo is:

- `exports/report-DNA-digital-data-storage_20260416_071225_export/`
- built on `2026-04-16 07:12 UTC`
- driven by `logs/system.log`

This run surfaced concrete graph-pipeline failures that should drive the plan.

### Problem Map From The Latest Run

1. Two comparison charts rendered as "one real bar plus zeros".
   - Exported files:
     - `images/dna_density_comparison.png`
     - `images/dna_vs_tape_density_2026.png`
   - Observed behavior:
     - the DNA bar dominates the entire plot
     - the comparison media are visually flattened to the baseline and read like zero
   - Root cause:
     - the writer suggested raw values spanning extreme orders of magnitude
     - the description asked for a logarithmic comparison
     - the static renderer in `execution/graph_generator.py` ignores that intent and renders a plain linear bar chart
   - Result:
     - the figure is technically rendered but not analytically useful
     - the chart does not help the reader understand relative scale in a meaningful way

2. The quantitative chapter's most relevant graphs were dropped before export.
   - Log evidence from `2026-04-16 07:12:24`:
     - `Annual Articles and Field Percentage (2014-2024)` -> `No data points found for graph`
     - `Annual Patents and Field Percentage (2014-2024)` -> `No data points found for graph`
   - Root cause:
     - the writer emitted multi-series data in a `data_points.datasets[...]` shape
     - the graph renderer only reads `data_points.values`
     - the quality gate and renderer therefore treated both graphs as empty
   - Result:
     - the report lost the figures that were actually most relevant to the quantitative chapter text
     - weak replacement visuals remained while the chapter-specific evidence visuals disappeared

3. Two different figure captions resolved to the exact same downloaded image.
   - Exported files:
     - `images/molecular_retrieval_workflow.png`
     - `images/dna_storage_lifecycle_2026.png`
   - Observed behavior:
     - both files are byte-identical and show the same external article figure
   - Log evidence:
     - both image searches hit DuckDuckGo rate limits and ResearchGate 403s
     - both queries then fell through to the same Scribd-hosted image result
   - Root cause:
     - `execution/image_search.py` accepts the first valid image without checking semantic fit against the requested caption
     - duplicate-content detection exists in `execution/doc_builder.py`, but export is run in best-effort mode instead of strict mode
   - Result:
     - the report presents reused image content as if it were two different visuals
     - one of the visuals is almost certainly irrelevant or redundant

4. Approved visuals can silently disappear from the final report.
   - Log evidence:
     - `TRL Progression: 2015 vs. 2026` was approved and rendered
     - it does not appear in the final Markdown export
   - Root cause:
     - the draft hit broken-marker issues during quality review
     - cleanup removed at least one unresolved figure marker before final assembly
     - final export then proceeded with `strict=False`, so "approved visual with no surviving text reference" only remained a warning
   - Result:
     - a generated chart can exist on disk and still fail to make it into the final report
     - the user sees missing visuals without a hard export stop

5. The system knowingly exported with blocking quality issues.
   - Log evidence:
     - `2026-04-16 07:12:02,926 - StreamlitApp - WARNING - Continuing to final assembly despite blocking quality gate errors because override is enabled.`
   - Root cause:
     - the app allows best-effort export even after broken figure markers and citation mismatches remain
   - Result:
     - weak or broken visuals are not fail-closed
     - low-quality charts are allowed to reach the deliverable instead of being blocked

6. Visual relevance drift is happening before rendering.
   - Observed behavior:
     - the chapter text and citations often discuss adjacent clinical-genomics topics
     - the suggested visuals are generic DNA-storage concept art or simplistic comparisons rather than claim-specific evidence charts
   - Root cause:
     - the research pool and writer prompt are still permissive enough to let cross-domain supporting material drive chart ideas
     - there is no deterministic check that a visual's title/data/caption match a specific nearby claim in the chapter
   - Result:
     - even when a chart renders correctly, it may still be weakly connected to the text it is supposed to support

7. The system does not currently let good graph candidates outcompete weak ones.
   - Observed behavior:
     - one graph suggestion is often generated for a slot and either accepted or dropped
     - the system rarely explores alternative chart types, scales, or encodings for the same claim
   - Root cause:
     - there is no candidate-generation batch, no ranking scorecard, and no shortlist review step
   - Result:
     - weak but renderable charts can survive simply because no better option was generated and compared

## Current Gap

Today, chart analysis returns:

- `type`
- `short_caption`
- `dataset_description`
- `suggested_update_query`

but it does not return structured chart datapoints for graphs. That means the updater can refresh a chart conceptually, but it cannot guarantee that original historical values are preserved exactly.

In addition, the current graph path has no explicit ranking layer:

- it does not mine a short list of graphable questions from the chapter research before proposing visuals
- it does not verify that a proposed graph idea actually has enough datapoints to be informative
- it does not build a graph brief tied to a specific nearby claim
- it does not generate a batch of competing graph candidates for the same slot
- it does not score candidates on text relevance, analytical help, readability, and faithfulness
- it does not present the user with a ranked shortlist and explanation of why one candidate is stronger than another

## Target End-to-End Flow

For each graph slot in the report:

1. Identify the target graph slot.
   - chapter id
   - section title
   - nearby paragraph(s)
   - target claim or question
   - source asset id if the slot is updating an original chart

2. Analyze the original chart asset when one exists.

3. Extract structured historical datapoints from the chart image.

4. Store those datapoints on the asset metadata.

5. Run update-specific research through the report's update window.

6. Distill `2-3` graphable questions from the gathered chapter research.
   - each question must tie to a nearby claim, paragraph, or section purpose
   - each question must describe something a graph could actually answer
   - each question must be specific enough to imply a chart family and unit

7. Verify graphability and data sufficiency for each candidate question.
   - reject questions that do not have enough datapoints
   - reject questions with mixed units, weak provenance, or incomparable entities
   - keep only the top `1-3` viable questions for graph generation

8. Build a structured graph brief that defines:
   - what claim the graph must support
   - what question the graph must answer
   - what years must be shown
   - what historical values must be preserved
   - what unit / measure / entity scope is required
   - what chart families are plausible

9. Generate a candidate batch for that graph brief.
   - target size: `4-8` candidates
   - vary chart type, scale treatment, encoding, aggregation, and annotation strategy when appropriate

10. Hard-reject candidates that fail trust or usability checks.

11. Score the surviving candidates.

12. Present the top `2-3` candidates to the user in ranked order with:
   - preview
   - overall score or quality band
   - sub-scores
   - short explanation of strengths and weaknesses

13. Auto-select the top candidate only if it clearly clears quality thresholds and beats the next option by a safe margin.

14. Render the selected graph to a PNG.

15. Verify the selected graph:
   - keeps preserved historical datapoints exactly
   - extends through `2026`
   - remains referenced by the final chapter text

## Question-First Graph Discovery Layer

Before the system ranks chart variants, it should first decide what question is worth graphing.

The graph pipeline should become:

- research chapter findings
- extract `2-3` graphable questions
- verify each question has enough datapoints and unit consistency
- convert viable questions into graph briefs
- generate candidate charts per question
- rank the charts
- present the shortlist

This solves a different failure mode than chart ranking:

- ranking fixes "which chart is best for this idea?"
- question discovery fixes "is this idea worth graphing at all?"

### What counts as a graphable question

A graphable question should:

- support a specific nearby claim, paragraph, or section job
- ask about a trend, comparison, composition, distribution, or before/after change
- imply a coherent metric and unit
- be answerable from gathered research without heroic inference
- have enough datapoints to produce a non-trivial graph

Examples:

- `How has annual patent activity changed from 2020 to 2026?`
- `How does DNA storage density compare with tape and SSD media?`
- `What share of projects are at each TRL stage in 2026?`

### Data sufficiency rules by question type

Minimum acceptance rules:

- `trend`: at least `4` ordered time points
- `comparison`: at least `3` comparable entities
- `composition`: at least `3` categories measured on the same basis
- `before_after`: at least `2` comparable periods using the same metric

Reject a question before graph generation when:

- the datapoints are too sparse
- units are mixed or unclear
- entities are not actually comparable
- provenance is weak
- the chapter text does not really need the answer
- the result would likely be a decorative graph rather than evidence

## Ranking Layer

### Hard blockers

A graph candidate should be rejected before ranking if any of these are true:

- no plottable data
- render failure
- all-zero or effectively empty series
- missing required chart type metadata
- dropped historical years
- preserved history drift
- stops before the requested update end year
- incorrect or missing unit for the intended claim
- duplicate content of another approved graph for a different slot
- no meaningful overlap with the target paragraph / section / claim
- unresolved provenance or unsupported data transformation

### Ranking dimensions

For candidates that survive hard filtering, compute a weighted score across:

- `text_relevance`
  - how well the graph matches the nearby paragraph, section title, chapter role, and target claim
- `analytical_help`
  - how much the graph improves understanding beyond the prose
- `readability`
  - chart-type fit, scale quality, label legibility, contrast, clutter, and overall scanability
- `data_faithfulness`
  - correctness of values, transformations, units, captions, and preserved historical series
- `evidence_strength`
  - how strong and on-topic the supporting data sources are
- `distinctiveness`
  - whether the candidate adds something different from other graphs already selected
- `production_robustness`
  - likelihood that the graph will survive rendering, assembly, resizing, and export cleanly

### Suggested weights

Initial weights for graph ranking:

- `text_relevance`: `30%`
- `analytical_help`: `20%`
- `readability`: `20%`
- `data_faithfulness`: `15%`
- `evidence_strength`: `10%`
- `distinctiveness`: `3%`
- `production_robustness`: `2%`

### Decision thresholds

Suggested decision policy:

- reject any hard-blocked candidate
- `Strong`: overall score `>= 80`
- `Medium`: overall score `65-79`
- `Weak`: overall score `< 65`
- auto-select only if:
  - top candidate is `Strong`
  - `text_relevance >= 8/10`
  - `readability >= 7/10`
  - `data_faithfulness >= 8/10`
  - top candidate leads the second candidate by at least `10` points
- otherwise present the shortlist and require an explicit choice

## Presentation Model

The user should not see a single opaque score alone.

For each shortlisted graph, show:

- preview image
- graph title
- overall score or quality band
- sub-scores by dimension
- `2-4` short reasons such as:
  - `Best text match`
  - `Preserves source history`
  - `Readable on extreme scale`
  - `Weaker because comparison is compressed`

Preferred UX:

- show only the top `2-3` candidates per graph slot
- order top to bottom by score
- pre-check the top candidate only when it clears the auto-select rule
- if no candidate is strong enough, block silent selection and ask for regeneration or manual choice

## Call Budget Per Report

Detailed call and cost budgeting now lives in `GRAPH_UPDATE_COST_ESTIMATION.md`.

That companion file includes:

- per-stage call rules
- explicit `x calls per y chapters/assets/graphs/images` table rows
- nominal report-level formulas
- a worked example for quick sizing

## Required Data Contract Changes

### Vision analysis output

Extend chart analysis to return a new field for charts:

```json
{
  "extracted_data_points": {
    "labels": ["2020", "2021", "2022", "2023"],
    "values": [42, 58, 79, 101],
    "unit": "Thousand Units"
  }
}
```

Behavior:

- required for chart assets when datapoints can be inferred
- should be `null` only when extraction truly fails
- should preserve label order from the source chart
- curated chart fixtures may also provide a same-stem JSON sidecar with `data_points`; when present, that sidecar acts as the deterministic extracted datapoint source of truth

### Asset state

Persist extracted chart datapoints on the asset object after vision analysis.

Suggested asset fields:

- `analysis`
- `description`
- `update_query`
- `extracted_data_points`

### Graph brief

Add a structured graph brief object for each graph slot.

Suggested fields:

- `slot_id`
- `graph_question_id`
- `chapter_id`
- `chapter_title`
- `section_title`
- `target_question_text`
- `question_type`
- `target_claim_text`
- `nearby_text_excerpt`
- `chapter_role`
- `source_asset_id`
- `required_year_start`
- `required_year_end`
- `required_unit`
- `preferred_chart_families`
- `must_preserve_history`
- `must_compare_entities`

### Graphable question

Add a structured graphable-question object before graph brief generation.

Suggested fields:

- `graph_question_id`
- `chapter_id`
- `source_finding_ids`
- `question_text`
- `question_type`
- `target_claim_text`
- `nearby_text_excerpt`
- `candidate_metric`
- `candidate_unit`
- `candidate_entities`
- `candidate_years`
- `data_point_count`
- `provenance_strength`
- `graphable`
- `graphable_reasons`
- `preferred_chart_families`
- `rejected_reason`

### Graph candidate

Each generated candidate should carry enough metadata to be ranked and explained.

Suggested fields:

- `candidate_id`
- `slot_id`
- `title`
- `chart_type`
- `data_points`
- `source_asset_id`
- `graph_brief_snapshot`
- `hard_blockers`
- `scorecard`
- `overall_score`
- `quality_band`
- `decision_reasons`
- `preview_path`
- `rank`
- `selected`

### Scorecard

Suggested scorecard shape:

```json
{
  "text_relevance": 9,
  "analytical_help": 8,
  "readability": 7,
  "data_faithfulness": 9,
  "evidence_strength": 7,
  "distinctiveness": 6,
  "production_robustness": 8,
  "overall_score": 82,
  "quality_band": "Strong",
  "decision_reasons": [
    "Best text match",
    "Preserves source history",
    "Readable scale choice"
  ]
}
```

## Implementation Phases

### Phase 0: Fail Closed On Known Bad Visuals

Owner areas:

- [app.py](/workspaces/report_updater_v3-main/app.py:1735)
- [execution/quality_gate.py](/workspaces/report_updater_v3-main/execution/quality_gate.py:360)
- [execution/doc_builder.py](/workspaces/report_updater_v3-main/execution/doc_builder.py:931)

Tasks:

- stop final assembly when non-overridable visual issues remain
- remove the current best-effort path for:
  - broken figure markers
  - graph missing data
  - approved visual with no surviving marker reference
  - accidental duplicate visual content
- surface those failures clearly in the UI before export

Acceptance:

- a report with broken graph markers or dropped graph data cannot export
- duplicate visual content under different captions blocks export unless reuse metadata is explicit

### Phase 1: Question Discovery, Graph Brief, And Candidate Batch Generation

Owner areas:

- [execution/research_agent.py](/workspaces/report_updater_v3-main/execution/research_agent.py:1)
- [execution/writer_agent.py](/workspaces/report_updater_v3-main/execution/writer_agent.py:678)
- [app.py](/workspaces/report_updater_v3-main/app.py:1313)

Tasks:

- mine `2-3` graphable questions from chapter research findings
- tie each question to a nearby claim, section purpose, or paragraph
- enforce data sufficiency rules before graph generation:
  - enough time points, entities, or categories
  - consistent metric and unit
  - credible provenance
- reject weak graph ideas before they become briefs
- define a graph-slot abstraction tied to nearby report text
- build a structured graph brief for each viable graph question / graph slot
- generate `4-8` candidate graph specs for each slot instead of one single suggestion
- vary chart structure intentionally when useful:
  - bar vs line vs dot
  - linear vs log
  - grouped vs indexed comparison
  - annotated comparison vs plain plot

Acceptance:

- each chapter yields `2-3` graphable questions before candidate generation
- non-graphable questions are rejected with explicit reasons
- each graph slot has a reusable brief
- each graph slot yields a candidate batch rather than one candidate
- candidate generation is deterministic enough to compare options for the same slot

### Phase 2: Vision extraction upgrade

Owner areas:

- [execution/vision_service.py](/workspaces/report_updater_v3-main/execution/vision_service.py:40)
- [app.py](/workspaces/report_updater_v3-main/app.py:718)

Tasks:

- update the Gemini vision prompt so charts return `extracted_data_points`
- validate parsed chart datapoints before storing them
- persist extracted datapoints onto each chart asset in app state

Acceptance:

- a known baseline 2020-2023 chart returns ordered labels and values
- chart assets in session state carry `extracted_data_points`

### Phase 3: Historical-series preservation

Owner areas:

- [execution/writer_agent.py](/workspaces/report_updater_v3-main/execution/writer_agent.py:689)
- optionally a new helper module such as `execution/graph_update_helpers.py`

Tasks:

- include extracted historical datapoints in the writer instructions for updated charts
- instruct the model to preserve those historical values exactly
- normalize update visuals so they retain the original asset id and action
- add a deterministic post-processing step that can reject or repair an updated graph when historical values drift

Preferred deterministic rule:

- if `extracted_data_points` exist, years already present in the source chart must not be changed by the updater

Acceptance:

- updated graphs keep `2020-2023` exactly as extracted from the original chart

### Phase 3.5: Unify The Graph Data Contract

Owner areas:

- [execution/writer_agent.py](/workspaces/report_updater_v3-main/execution/writer_agent.py:628)
- [execution/graph_generator.py](/workspaces/report_updater_v3-main/execution/graph_generator.py:65)
- [tests/test_graph_generator.py](/workspaces/report_updater_v3-main/tests/test_graph_generator.py:1)

Tasks:

- define one canonical graph payload shape and use it everywhere
- either:
  - teach the writer to emit `values`
  - or teach the renderer to accept `datasets`
- normalize multi-series payloads before quality-gate checks and rendering
- add regression tests for writer-style multi-series chart payloads

Acceptance:

- a writer-emitted multi-series graph is recognized as plottable data
- the two quantitative update graphs from the latest run render instead of being dropped

### Phase 4: Ranking Engine

Owner areas:

- new helper module such as `execution/graph_ranking.py`
- [execution/quality_gate.py](/workspaces/report_updater_v3-main/execution/quality_gate.py:360)
- [app.py](/workspaces/report_updater_v3-main/app.py:1580)

Tasks:

- implement hard blockers before score computation
- compute weighted scorecards for surviving candidates
- add explicit penalties for:
  - weak text match
  - unreadable scale compression
  - weak evidence support
  - near-duplicate analytical story
- sort candidates by score and emit a ranked shortlist
- record machine-readable reasons for rank position

Acceptance:

- every candidate receives either:
  - rejection with blocker reasons
  - or a ranked scorecard
- the user can see why candidate `#1` outranks candidate `#2`

### Phase 5: Ranked Shortlist Presentation

Owner areas:

- [app.py](/workspaces/report_updater_v3-main/app.py:1580)

Tasks:

- show top `2-3` candidates per graph slot
- display preview, overall score, sub-scores, and short reason labels
- auto-select the top candidate only when threshold rules are met
- require manual choice or regeneration when all candidates are medium/weak

Acceptance:

- graph candidates are presented top-to-bottom by score
- weak candidates are visibly weak rather than silently accepted
- no slot is silently filled by a poor graph when the shortlist is inconclusive

### Phase 6: Merge and validation

Owner areas:

- new merge helper module or [execution/graph_generator.py](/workspaces/report_updater_v3-main/execution/graph_generator.py:337)
- [execution/quality_gate.py](/workspaces/report_updater_v3-main/execution/quality_gate.py:90)

Tasks:

- create a deterministic merge step for:
  - original historical datapoints
  - newly updated datapoints
- reject merged graphs that:
  - drop historical years
  - alter preserved historical values
  - stop before the requested update end year
- reject visually degenerate comparisons that:
  - collapse one or more categories to an unreadable baseline because of extreme magnitude spread
  - claim to be logarithmic but are rendered on a linear axis
  - use comparison structures that do not match the chart intent

Additional renderer tasks:

- add deterministic support for log-scale comparisons when the ratio spread is extreme
- prefer better structures for high-ratio comparisons:
  - log bar
  - dot plot
  - indexed comparison
  - annotated ratio callout
- validate that chart type, axis treatment, and unit match the figure description

Acceptance:

- merged graph data contains the preserved source series plus new years through `2026`
- comparison charts no longer render as "one visible bar plus zeros"

### Phase 6.5: Figure/Text Relevance Validation

Owner areas:

- [execution/writer_agent.py](/workspaces/report_updater_v3-main/execution/writer_agent.py:757)
- [execution/quality_gate.py](/workspaces/report_updater_v3-main/execution/quality_gate.py:360)

Tasks:

- require each approved visual to support a nearby paragraph claim
- add a deterministic check that a visual's title/caption/data overlaps with the surrounding section topic
- demote or reject generic concept visuals when the chapter really needs an evidence graph

Acceptance:

- each exported graph clearly supports the adjacent text
- chapter-specific evidence charts are preferred over generic background visuals

### Phase 7: End-to-end live coverage

Owner areas:

- [tests/test_live_graph_upgrade_flow.py](/workspaces/report_updater_v3-main/tests/test_live_graph_upgrade_flow.py:1)
- [tests/fixtures/graph_update/](/workspaces/report_updater_v3-main/tests/fixtures/graph_update/)

Tasks:

- run live vision analysis on the baseline chart asset
- confirm structured datapoint extraction
- run the updater through candidate generation and ranking
- confirm the selected final graph:
  - keeps `2020-2023` exactly
  - extends through `2026`
  - renders successfully
- add a regression fixture for the `2026-04-16 07:12 UTC` failure patterns:
  - multi-series writer payload in `datasets`
  - extreme-ratio comparison chart
  - approved visual with no surviving text marker
  - weak top candidate losing to a better-ranked alternative

Acceptance:

- the ranking layer produces a stable shortlist for the curated baseline case
- the selected graph is the highest-ranked passing candidate

## Acceptance Criteria

The upgrade is complete when all of these are true:

- chart vision analysis returns `extracted_data_points`
- the asset stores those extracted datapoints
- updated graph visuals preserve historical values exactly
- updated graph visuals include recent years through `2026`
- the final merged graph renders as a valid PNG
- each chapter yields a short list of graphable questions tied to the text
- only graphable questions with enough datapoints enter candidate generation
- each graph slot generates a candidate batch instead of a single graph suggestion
- hard-blocked candidates never reach user approval
- graph candidates are ranked by a visible scorecard
- the UI presents the top shortlist in descending score order
- auto-selection only occurs when the top graph clearly clears thresholds
- writer-style multi-series graph payloads render without manual repair
- extreme-ratio comparison charts are readable and intentionally scaled
- approved visuals cannot silently disappear during export
- the live upgrade-flow canary passes without xfail

## Test Strategy

### Existing baseline fixtures

Reuse the graph update fixtures in:

- [baseline asset](/workspaces/report_updater_v3-main/tests/fixtures/graph_update/baseline_asset.json:1)
- [baseline data](/workspaces/report_updater_v3-main/tests/fixtures/graph_update/baseline_data_2020_2023.json:1)
- [baseline source chapter](/workspaces/report_updater_v3-main/tests/fixtures/graph_update/baseline_source_chapter.md:1)
- [update findings](/workspaces/report_updater_v3-main/tests/fixtures/graph_update/update_findings_2024_2026.json:1)

### New target merged fixture

Use:

- [expected merged data](/workspaces/report_updater_v3-main/tests/fixtures/graph_update/expected_merged_data_2020_2026.json:1)

### New ranking fixtures

Add fixtures for:

- graphable-question list with `2-3` viable questions
- graphable-question rejection because of insufficient datapoints
- graph brief for a quantitative slot
- candidate batch with mixed quality
- candidate rejected for history drift
- candidate rejected for unreadable extreme-scale comparison
- ranked shortlist with deterministic score ordering

### Live canary command

```bash
RUN_LIVE_API_TESTS=1 pytest tests/test_live_graph_upgrade_flow.py -q
```

## Rollout Note

The live upgrade-flow test now exists as an active regression canary in [tests/test_live_graph_upgrade_flow.py](/workspaces/report_updater_v3-main/tests/test_live_graph_upgrade_flow.py:1). It should stay green for the curated baseline fixture and should be treated as required coverage for future graph updater changes.

This graph plan is intentionally focused on graph-slot selection, ranking, and update fidelity. Broader image-search and generic visual deduplication work should continue to live primarily in [VISUAL_REMEDIATION_PLAN.md](/workspaces/report_updater_v3-main/VISUAL_REMEDIATION_PLAN.md:1).
