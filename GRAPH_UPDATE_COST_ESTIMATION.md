# Graph Update Cost Estimation

## Purpose

This document isolates the expected call volume for the upgraded graph-update workflow so the main upgrade plan can stay focused on architecture and implementation.

## Sizing Variables

| Symbol | Meaning |
| --- | --- |
| `C` | number of chapters in the report |
| `A` | number of selected source assets sent through vision analysis |
| `U` | number of source graphs or tables marked for update-specific research |
| `S` | number of graph slots that go through shortlist generation in the upgraded flow |
| `G` | number of approved graphs rendered in final assembly |
| `I` | number of approved images fetched in final assembly |

## Token Conventions

This section estimates LLM token use for Gemini-backed stages only.

- DDG, OpenAlex, direct HTTP fetches, and local deterministic steps do not consume LLM tokens.
- For text-heavy prompts, a practical planning shortcut is `tokens ~= characters / 4`.
- For generated prose, a practical shortcut is `tokens ~= words * 1.3` for English prose.
- Multimodal image inputs are harder to normalize from code alone, so this document uses image-token variables instead of pretending the raw byte count maps cleanly to text tokens.

### Token variables

| Symbol | Meaning |
| --- | --- |
| `T_ch` | average source chapter tokens actually sent to the writer or analyzer |
| `T_ch_batch` | average chapter tokens sent to the batch chapter analyzer after truncation |
| `T_find` | average serialized research-finding tokens included in one writer prompt |
| `T_prior` | average prior-chapter context tokens included in one writer prompt |
| `T_gq` | average graphable-question guidance tokens included in one writer prompt |
| `T_upd` | average update-instruction tokens per updated graph/table in the writer prompt |
| `U_ch` | average number of updated graphs/tables attached to one chapter |
| `F` | average number of findings passed into one research rerank call |
| `T_find_rr` | average reranker prompt tokens contributed by one candidate finding |
| `W` | target output words for one generated chapter |
| `K` | candidate graphs generated per graph slot in the upgraded shortlist flow, target `4-8` |
| `T_slot` | graph-brief tokens for one graph-slot candidate-generation call |
| `T_graph_payload` | graph title, description, chart-type, and data tokens passed into one graph-render fallback call |
| `V_asset` | token-equivalent input cost for one source asset image in batch vision analysis |
| `V_chart` | token-equivalent input cost for one chart image in focused datapoint repair |
| `T_code` | average code-output tokens for one LLM graph-render fallback |
| `T_ca_out` | average output tokens per analyzed chapter |
| `T_va_out` | average output tokens per analyzed asset |

### Fixed prompt-overhead variables

These are the non-data-dependent instruction blocks around the dynamic content.

| Symbol | Meaning |
| --- | --- |
| `B_ca` | batch chapter-analysis prompt overhead |
| `B_va` | batch vision-analysis text overhead |
| `B_vr` | focused chart datapoint-repair prompt overhead |
| `B_rr` | research-reranker prompt overhead |
| `B_wr` | chapter-writer prompt overhead |
| `B_cg` | candidate-generation prompt overhead for one graph slot |
| `B_gr` | LLM graph-render fallback prompt overhead |

## Per-Stage Call Table

| Stage | Service | Budget rule | Practical reading |
| --- | --- | --- | --- |
| Chapter analysis | Gemini text | `1 call per <=10 chapters` | Batch chapter analysis should stay coarse-grained. |
| Asset analysis | Gemini vision | `1 call per <=5 assets` | Source visuals are already analyzed in chunks of `5`. |
| Chart datapoint repair | Gemini vision | `0-1 extra calls per 1 chart asset` | Only needed when batch vision does not return usable `extracted_data_points` and no sidecar JSON exists. |
| Main chapter research | DDG text + OpenAlex | `up to 4 DDG text searches and 4 OpenAlex calls per 1 chapter` | `execution/research_agent.py` caps query generation at `4`. |
| Main chapter research rerank | Gemini text | `1 call per 1 chapter` | The LLM reranker runs once per research pass. |
| Visual update research | DDG text + OpenAlex | `up to 4 DDG text searches and 4 OpenAlex calls per 1 updated graph/table` | Each `do_update` asset currently triggers its own research pass. |
| Visual update rerank | Gemini text | `1 call per 1 updated graph/table` | Same reranking path as chapter research. |
| Graphable-question discovery | deterministic | `0 calls per report element` | Keep this local; it does not need an extra model hop. |
| Candidate batch generation | Gemini text | `1 call per 1 graph slot for 4-8 graph candidates` | Generate the whole candidate batch in one response, not `4-8` separate calls. |
| Ranking and shortlist | deterministic | `0 calls per 1 graph slot` | Hard blockers, scoring, and sorting should stay local. |
| Chapter writing | Gemini text | `1 call per 1 chapter` | The writer already returns prose plus visual suggestions in one shot. |
| Graph rendering | local first, Gemini fallback | `0 calls per 1 graph` on the static path, `1-2 Gemini calls per 1 graph` on fallback | Structured graphs should normally render locally. |
| Image fetching | DDG images + HTTP download | `1 image-search call per 1 image` nominal | Retries can raise the real count. |

## Per-Stage Token Budget

### Core Gemini stages

| Stage | Input token estimate | Output token estimate | Notes |
| --- | --- | --- | --- |
| Batch chapter analysis | `B_ca + sum(min(T_ch_batch_i, 2000))` per batch | `~180-260` per chapter in the batch | Code truncates batch chapter text at about `8000` chars per chapter, so `T_ch_batch_i` is naturally capped near `2000` tokens. |
| Asset analysis | `B_va + sum(V_asset_i)` per <=`5` assets | `~120-250` per asset | Output depends on whether the model returns image, table, or chart metadata plus `suggested_update_query`. |
| Chart datapoint repair | `B_vr + V_chart` per repaired chart | `~40-140` per repaired chart | Usually small JSON unless the chart is multi-series. |
| Research rerank | `B_rr + F * T_find_rr` per research pass | `~25 + 20F` | Output is compact JSON with one judgment object per finding. |
| Chapter writer | `B_wr + T_ch + T_find + T_prior + T_gq + U_ch * T_upd` per chapter | `~(1.3 * W) + 250-450` | Output includes prose plus structured JSON for claims, visuals, and references. |
| Candidate batch generation | `B_cg + T_slot` per graph slot | `K * (120-220)` | Planned upgraded flow should generate the full `4-8` candidate batch in one call. |
| Graph-render fallback | `B_gr + T_graph_payload` per fallback graph | `T_code`, typically `250-700` | First-choice path should remain local/static; this is a fallback-only budget. |

### Conditional Gemini stages

| Stage | Input token estimate | Output token estimate | When it applies |
| --- | --- | --- | --- |
| Hebrew-term translation batch | `~80 + total Hebrew term tokens in chunk` | `~same order as source terms` | Only when research topics/keywords include Hebrew terms. |
| Gemini research fallback | `~120 + topic/keyword tokens` | `~300-700` | Only when DDG and OpenAlex return no usable findings for a research pass. |
| LLM chapter judge | `judge prompt overhead + chapter text + findings + references` | `~80-180` | Optional path, not part of the default app flow today. |

## Report-Level Token Formulas

### Nominal input tokens

These formulas assume:

- English-only research terms
- no Gemini research fallback
- no focused chart datapoint repair retries
- no optional LLM chapter judge
- shortlist candidate generation is implemented as one call per slot

| Budget type | Formula |
| --- | --- |
| Chapter-analysis input tokens | `sum_batches(B_ca + sum(min(T_ch_batch_i, 2000)))` |
| Asset-analysis input tokens | `ceil(A / 5) * B_va + A * V_asset` |
| Research-rerank input tokens | `(C + U) * (B_rr + F * T_find_rr)` |
| Chapter-writer input tokens | `sum_chapters(B_wr + T_ch_i + T_find_i + T_prior_i + T_gq_i + U_i * T_upd)` |
| Candidate-generation input tokens | `S * (B_cg + T_slot)` |
| Graph-render fallback input tokens | `G_fallback * (B_gr + T_graph_payload)` where `0 <= G_fallback <= G` |

### Nominal output tokens

| Budget type | Formula |
| --- | --- |
| Chapter-analysis output tokens | `C * T_ca_out`, where `T_ca_out ~= 180-260` |
| Asset-analysis output tokens | `A * T_va_out`, where `T_va_out ~= 120-250` |
| Research-rerank output tokens | `(C + U) * (25 + 20F)` |
| Chapter-writer output tokens | `sum_chapters((1.3 * W_i) + 250-450)` |
| Candidate-generation output tokens | `S * K * (120-220)` |
| Graph-render fallback output tokens | `G_fallback * T_code` |

### Compact nominal total

If you want one simplified Gemini-token estimate for planning, use:

`Total input ~= chapter_analysis_in + asset_analysis_in + research_rerank_in + chapter_writer_in + candidate_generation_in + graph_fallback_in`

`Total output ~= chapter_analysis_out + asset_analysis_out + research_rerank_out + chapter_writer_out + candidate_generation_out + graph_fallback_out`

## Planning Defaults

Use these when you want a quick estimate without measuring the actual prompt payloads:

| Variable | Quick default |
| --- | --- |
| `T_ch_batch` | `min(source chapter chars / 4, 2000)` |
| `T_ch` | `source chapter chars / 4` |
| `T_find` | `1200-2500` per chapter writer call, depending on finding snippet length |
| `T_prior` | `150-400` |
| `T_gq` | `80-180` |
| `T_upd` | `80-180` per updated graph/table |
| `U_ch` | `U / C` for a quick average, or use per-chapter `U_i` directly |
| `F` | `8-12` |
| `T_find_rr` | `120-220` per finding |
| `W` | use the chapter target word count from the blueprint, often around `500` |
| `T_slot` | `180-350` |
| `T_graph_payload` | `120-300` |
| `T_code` | `250-700` |
| `T_ca_out` | `180-260` per analyzed chapter |
| `T_va_out` | `120-250` per analyzed asset |

## Worked Token Example

Assume:

- `C = 8`
- `A = 10`
- `U = 4`
- `S = 6`
- no graph-render fallbacks in the nominal path
- `T_ch_batch = 1600`
- `T_ch = 1800`
- `T_find = 1800`
- `T_prior = 250`
- `T_gq = 120`
- `T_upd = 120`
- `F = 10`
- `T_find_rr = 160`
- `W = 500`
- `T_slot = 250`
- `B_ca = 220`
- `B_va = 120`
- `B_rr = 260`
- `B_wr = 1100`
- `B_cg = 300`
- `V_asset = variable image-token cost per asset`

Then the text-token portions come out to:

| Metric | Estimate |
| --- | --- |
| Batch chapter-analysis input | `ceil(8 / 10)` batch -> `220 + 8 * 1600 = 13,020` |
| Research-rerank input | `(8 + 4) * (260 + 10 * 160) = 22,320` |
| Chapter-writer input | `8 * (1100 + 1800 + 1800 + 250 + 120) + 4 * 120 = 40,240` |
| Candidate-generation input | `6 * (300 + 250) = 3,300` |
| Chapter-writer output | `8 * ((1.3 * 500) + 350) = 8,000` using a `350` JSON overhead midpoint |

To turn that into a fuller Gemini estimate, add:

- asset-analysis multimodal input: `10 * V_asset + 2 * 120`
- asset-analysis output: `10 * T_va_out`, where `T_va_out ~= 120-250`
- chapter-analysis output: `8 * T_ca_out`, where `T_ca_out ~= 180-260`
- research-rerank output: `12 * (25 + 20 * 10) = 2,700`
- candidate-generation output: `6 * K * (120-220)`

This example is intentionally split so you can plug in the provider-specific image token accounting without rewriting the whole report estimate.

## Nominal Report Formulas

These formulas assume:

- English-only research terms, so no translation batches
- no zero-result Gemini research fallback
- no chart datapoint repair calls
- graph shortlist generation is implemented as one batched call per slot
- final graphs mostly stay on the static renderer path

| Budget type | Formula |
| --- | --- |
| Gemini calls, nominal | `ceil(C / 10) + ceil(A / 5) + 2C + U + S` |
| DDG text searches, nominal upper bound | `4(C + U)` |
| OpenAlex calls, nominal upper bound | `4(C + U)` |
| Web article fetches, nominal upper bound | `20(C + U)` |
| DDG image searches, nominal | `I` |
| Gemini graph-render fallback range | `0-2G` |

## Worked Example

For a report with:

- `8` chapters
- `10` selected source assets
- `4` graphs/tables marked for update-specific research
- `6` graph slots going through shortlist generation
- `6` final graphs
- `4` final images

the nominal budget is:

| Metric | Estimate |
| --- | --- |
| Gemini calls before render fallbacks | `ceil(8 / 10) + ceil(10 / 5) + 2(8) + 4 + 6 = 29` |
| DDG text searches | `4(8 + 4) = 48` |
| OpenAlex calls | `4(8 + 4) = 48` |
| Web article fetches ceiling | `20(8 + 4) = 240` |
| DDG image searches | `4` |
| Gemini graph-render fallback range | `0-12` |

## Call-Saving Guidance

- If candidate generation is folded into the existing chapter-writer call, subtract `S` Gemini calls from the nominal budget.
- Do not add an extra model call for ranking, shortlist explanation, or graphability checks unless deterministic scoring proves inadequate.
- Reused research queries will benefit from the current caches, so repeated graph update queries can lower the realized call count.
- The biggest token driver is the chapter-writer prompt, especially the serialized research findings block. Trimming or summarizing finding snippets before the writer call reduces token cost much more than squeezing small helper prompts.
