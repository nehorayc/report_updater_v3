# Visual Remediation Plan

## Goal

Make the visual pipeline trustworthy and fail-safe so the next regenerated report ships only visuals that are:

- relevant to the chapter
- mapped to the correct marker and caption
- rendered successfully
- traceable from suggestion to export

This plan is intentionally visual-first. It addresses the latest run failures, with non-visual grounding cleanup kept as a follow-on track.

## Why This Plan Exists

The latest checklist pass exposed a repeatable visual failure pattern:

- two different captions resolved to the same underlying image file
- the `TRL Progression` update graph was suggested but never made it into the final export
- approved graphs can still reach final assembly with no plottable data
- image sourcing degrades badly under DuckDuckGo `403 Ratelimit` failures
- visual marker cleanup happens late instead of preventing bad mappings upstream
- final assembly can continue even when the quality gate is still blocking
- export can silently drop unresolved citations, which undermines trust in visual-heavy chapters

## Relationship To Existing Plans

- Use [GRAPH_UPDATE_UPGRADE_PLAN.md](/workspaces/report_updater_v3-main/GRAPH_UPDATE_UPGRADE_PLAN.md:1) for the historical-series graph-update upgrade.
- Use this document for the broader visual system: suggestion, sourcing, rendering, marker mapping, export fidelity, and release gates.

## Visual-First Success Criteria

- Every approved visual has one stable marker id, one resolved asset path, and one final caption.
- Every approved graph has validated plottable data before it reaches the renderer.
- Updated charts preserve historical values and extend through the requested update end year when applicable.
- Failed image searches never degrade into off-topic substitutions or silent omissions.
- Final assembly blocks on unresolved visual or visual-chapter citation errors unless an explicit fallback is attached.
- Markdown and DOCX exports contain the same visual set.
- Two materially different captions do not point to the same underlying file unless that reuse is explicit and intentional.
- The same graph may appear in multiple places only when reuse is declared intentionally and tied to one canonical source asset.

## Reuse Policy For The Same Graph In Multiple Places

Intentional reuse is allowed, but only under a strict rule set.

Allowed:

- the same graph is reused in more than one place because the report intentionally references the same evidence
- the reused graph points back to one canonical asset id
- the export manifest marks the later occurrence as a reuse, not as a new generated visual
- the caption is the same or a clearly labeled shortened variant of the same graph

Not allowed:

- the same file is reused accidentally because image search or marker resolution collapsed two visuals together
- two different analytical roles share the same graph without explicit approval
- two different captions imply different content but point to the same underlying graph
- a reused graph hides the fact that a chapter-specific update visual failed to generate

Required metadata for intentional reuse:

- `source_asset_id`: canonical original or generated graph asset
- `reuse_of_asset_id`: the asset being reused in this location
- `reuse_reason`: short explanation such as `cross-chapter reference`, `executive summary repeat`, or `same evidence reused intentionally`
- `is_reused_visual`: boolean flag for export and validation

Decision rule:

- if the same graph is needed in multiple places, reuse the same asset intentionally and record it as reuse
- if the chapter needs a graph with different scope, timeframe, highlight, or caption meaning, create a new graph and a new asset id instead of reusing the old one

## Workstreams

### Phase 0: Shipping Guardrails

Owner areas:

- [app.py](/workspaces/report_updater_v3-main/app.py:1659)
- [execution/quality_gate.py](/workspaces/report_updater_v3-main/execution/quality_gate.py:363)
- [execution/doc_builder.py](/workspaces/report_updater_v3-main/execution/doc_builder.py:707)

Tasks:

- Treat `broken_figure_marker`, missing visual paths, export-time citation drops, and graph no-data failures as hard blockers.
- Change final assembly so visual and citation blockers do not continue by default just because the override checkbox is enabled.
- Stop silent normalization from hiding export defects. If citations would be dropped during export normalization, fail the export and surface the exact chapter and tokens.
- If an updated visual fails, preserve the original source asset only when that fallback is explicit and clearly labeled as the original figure. Otherwise block assembly.

Acceptance:

- No final export is produced when an approved visual is unresolved.
- No exported report contains silently dropped citations for chapters that still reference the affected evidence.

### Phase 1: Graph Update Reliability

Owner areas:

- [execution/vision_service.py](/workspaces/report_updater_v3-main/execution/vision_service.py:72)
- [execution/writer_agent.py](/workspaces/report_updater_v3-main/execution/writer_agent.py:172)
- [execution/graph_generator.py](/workspaces/report_updater_v3-main/execution/graph_generator.py:337)
- [GRAPH_UPDATE_UPGRADE_PLAN.md](/workspaces/report_updater_v3-main/GRAPH_UPDATE_UPGRADE_PLAN.md:1)

Tasks:

- Finish the extracted-datapoint and merged-series flow described in the graph upgrade plan.
- Require every update graph to carry `original_asset_id`, normalized `marker_id`, `chart_type`, and validated `data_points`.
- Reject graph suggestions with empty or misaligned labels and values before they reach `generate_graph()`.
- Add deterministic post-render checks so empty-template charts, all-zero charts, and charts that stop before the requested update year cannot be approved.
- Make the current `TRL Progression` failure mode binary: either a rendered graph exists, or final assembly blocks.

Acceptance:

- No approved graph logs `No data points found for graph`.
- Updated graphs either render with validated data or fail closed before export.

### Phase 2: Image Sourcing And Relevance

Owner areas:

- [execution/image_search.py](/workspaces/report_updater_v3-main/execution/image_search.py:11)
- [app.py](/workspaces/report_updater_v3-main/app.py:1683)
- [execution/vision_service.py](/workspaces/report_updater_v3-main/execution/vision_service.py:227)

Tasks:

- Replace deprecated `duckduckgo_search` usage with `ddgs` and add a real provider and backoff strategy instead of repeating the same failing requests.
- Prefer deterministic sourcing in this order: original asset reuse, uploaded asset, curated known-good source, then broad web search.
- Store source metadata on each resolved image, including `source_url`, `provider`, `content_hash`, and `selection_reason`.
- Add validation for resolution, MIME type, aspect ratio, source hostname, and perceptual duplication.
- Detect when the same underlying file is being assigned to different captions or visual roles and block that unless it is explicitly approved reuse.

Acceptance:

- Repeated DuckDuckGo `403` failures no longer lead to dead-end retries without fallback.
- Two distinct captions no longer export the same image file by accident.

### Phase 3: Marker, Mapping, And Export Fidelity

Owner areas:

- [app.py](/workspaces/report_updater_v3-main/app.py:394)
- [app.py](/workspaces/report_updater_v3-main/app.py:427)
- [execution/doc_builder.py](/workspaces/report_updater_v3-main/execution/doc_builder.py:744)
- [execution/quality_gate.py](/workspaces/report_updater_v3-main/execution/quality_gate.py:376)

Tasks:

- Keep one canonical marker id from writer output through approval, asset resolution, markdown export, and DOCX export.
- Add an export preflight that compares figure markers in text against approved visuals and actual files on disk.
- Add duplicate-asset detection in export packaging using content hash, not only filename or marker id.
- Distinguish accidental duplicates from intentional reuse by requiring explicit reuse metadata when the same content hash appears more than once.
- Produce a structured visual manifest per export containing chapter, marker id, caption, asset type, source type, path, and content hash.
- Extend the visual manifest with reuse fields so repeated graphs can be audited.
- Ensure markdown and DOCX export from the same resolved visual map instead of re-discovering assets separately.

Acceptance:

- Every exported figure marker resolves to exactly one asset.
- Markdown and DOCX contain the same visual manifest entries.
- Reused graphs are visible in the manifest as intentional reuse, not silent duplication.

### Phase 4: Tests And Canary Coverage

Owner areas:

- [tests/test_live_graph_upgrade_flow.py](/workspaces/report_updater_v3-main/tests/test_live_graph_upgrade_flow.py:1)
- [tests/test_live_graph_updater.py](/workspaces/report_updater_v3-main/tests/test_live_graph_updater.py:1)
- [tests/test_export_pipeline.py](/workspaces/report_updater_v3-main/tests/test_export_pipeline.py:1)
- [tests/test_quality_gate.py](/workspaces/report_updater_v3-main/tests/test_quality_gate.py:1)

Tasks:

- Add unit tests for unresolved visual blockers, duplicate-content images under different captions, graph rejection on empty data, and export failure when citation tokens would be dropped.
- Add tests that allow intentional same-graph reuse when reuse metadata is present and fail accidental duplicate reuse when it is not.
- Add integration tests that confirm updated graphs survive final assembly with preserved historical years and that markdown and DOCX exports share the same visual manifest.
- Add a focused image-search fallback test that simulates provider ratelimits and verifies deterministic fallback behavior.
- Keep the live graph-upgrade canary as required coverage for future visual work.

Acceptance:

- The checklist rows for visual relevance, rendering, and export fidelity are covered mostly by tests instead of manual inspection.
- Visual regressions fail before export.

### Phase 5: Follow-On Cleanup

Owner areas:

- [execution/writer_agent.py](/workspaces/report_updater_v3-main/execution/writer_agent.py:907)
- [directives/generate_visuals.md](/workspaces/report_updater_v3-main/directives/generate_visuals.md:1)
- [directives/doc_assembly.md](/workspaces/report_updater_v3-main/directives/doc_assembly.md:1)

Tasks:

- Tighten source selection so cross-domain medical papers stop indirectly justifying DNA-storage visuals and outlook charts.
- Update directives so they match the actual fallback, blocking, and export behavior we want.
- Clean root-level temp artifacts so post-run ops hygiene matches the checklist.

Acceptance:

- The visual pipeline is stable enough that the remaining failures are content-grounding issues rather than mechanics.
- Directives and checklist expectations match the real system behavior.

## Suggested Execution Order

1. Phase 0: stop bad visuals from shipping.
2. Phase 1: finish graph reliability and deterministic update validation.
3. Phase 2: harden image sourcing and duplicate detection.
4. Phase 3: enforce one-to-one marker and export fidelity.
5. Phase 4: lock the behavior in with tests and canaries.
6. Phase 5: clean up directives and adjacent grounding issues.

## Definition Of Done

This plan is complete when the next DNA-storage regeneration can pass all of the following:

- no duplicate-image exports under different captions
- no missing approved graphs
- no `No data points found for graph` errors for approved charts
- no unresolved figure markers in markdown or DOCX
- no silent citation drops during export
- no need to rely on the blocking quality-gate override for visual issues
- green targeted visual regression suite, including the live graph-upgrade canary when enabled
