# Graph Update System Plan

## Goal

Create a stable, repeatable graph-update scenario where:

1. A baseline source asset only contains data through `2023`.
2. The updater is instructed to refresh that graph with new information through `2026`.
3. Tests verify not only that a new graph is produced, but that the updated graph data actually reaches the recent years.

## Fixture Set

The baseline scenario lives under `tests/fixtures/graph_update/`.

- `baseline_asset.json`
  - Metadata for the original extracted graph asset.
  - Represents a chart that stops at `2023`.
- `baseline_data_2020_2023.json`
  - Structured baseline data used to generate the source graph image.
- `baseline_source_chapter.md`
  - Mock chapter text containing the original figure marker.
- `update_findings_2024_2026.json`
  - Mock research findings that extend the graph through `2026`.
- `enterprise_ai_server_shipments_2020_2023.png`
  - Generated baseline graph image for the original source asset.

## System Under Test

The update flow to validate is:

1. Load the baseline source chapter and original graph asset.
2. Mark the asset for update with a concrete `update_query`.
3. Pass the chapter, asset metadata, and update findings into `write_chapter()`.
4. Confirm the writer emits an updated `graph` visual tied to the original asset.
5. Pass that updated visual into `generate_graph()`.
6. Confirm the rendered graph is a valid PNG.
7. Confirm the updated graph data includes recent-year coverage through `2026`.

## Required Assertions

### Writer-side assertions

- The result contains no writer error.
- The returned `visual_suggestions` include a `graph`.
- At least one graph visual has:
  - `action == "update"`
  - `original_asset_id` matching the baseline asset id
  - non-empty `data_points.labels`
  - non-empty `data_points.values`

### Recency assertions

The updated graph must not merely rephrase the old chart. It must show recent-year coverage.

Preferred strict checks:

- `labels` include `2024`, `2025`, and `2026`
- or the parsed max year in labels is `>= 2026`

Anti-regression checks:

- the updated graph must not stop at `2023`
- the updated graph must not contain only pre-2024 labels

### Renderer-side assertions

- `generate_graph()` returns a `path`
- the file exists
- the file is non-empty
- the file opens successfully as an image

## Test Layers

### 1. Fixture-backed fast test

Purpose:
- validate fixture loading
- validate year-parsing helpers
- validate the baseline asset metadata remains consistent

This layer should stay deterministic and should not call Gemini.

### 2. Live updater canary

Purpose:
- run the writer update path with the baseline 2023 asset fixture
- verify that the updated visual data reaches `2026`
- verify the updated graph renders

This layer may call live Gemini and should stay isolated from DOCX assembly.

Recommended command:

```bash
RUN_LIVE_API_TESTS=1 pytest tests/test_live_graph_updater.py -q
```

### 3. Optional full integration check

Purpose:
- confirm the updated graph survives final assembly
- confirm the original marker is replaced cleanly

This layer should be added only after the focused updater canary is stable.

## Rerun / Fix Loop

1. Run the isolated live graph updater test.
2. If the writer output is wrong, fix `execution/writer_agent.py`.
3. If the graph data is malformed or not recent enough, fix writer normalization or test assertions.
4. If rendering fails, fix `execution/graph_generator.py`.
5. Re-run the same isolated test until it is green repeatedly.
6. Only then widen scope to report assembly.

## Acceptance Criteria

The graph update system is considered healthy for this scenario when:

- the baseline asset clearly stops at `2023`
- the updater produces a replacement graph visual
- the replacement graph is linked to the original asset
- the replacement graph data includes `2024-2026`
- the replacement graph renders successfully as a PNG

