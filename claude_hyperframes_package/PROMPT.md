# Prompt To Give Claude

You are helping produce a Hyperframes video for a software product called **Report Updater v3**.

I have uploaded a folder containing the documents and image assets you need. Please use the materials in this folder as the source of truth.

## Your Task

Turn the included product context, architecture notes, storyboard, and images into a practical Hyperframes production package that I can execute scene by scene.

Produce:

1. A final scene-by-scene Hyperframes build plan.
2. A concise prompt for each scene.
3. The exact image asset(s) to attach to each scene.
4. Recommended scene durations and transitions.
5. On-screen text for each scene.
6. Voiceover script aligned to scene timing.
7. A final checklist for generating/exporting the video in Hyperframes.

## Source Files To Read First

Read these in order:

1. `docs/HYPERFRAMES_VIDEO_PLAN.md`
2. `docs/ARCHITECTURE_SCHEMATICS_CEO.md`
3. `docs/PROJECT_OVERVIEW.md`
4. `docs/README.md`
5. `docs/ARCHITECTURE_SCHEMATICS.md` only if you need implementation-level clarification

## Image Assets

Use image assets from:

- `images/crops/` as the primary Hyperframes references.
- `images/originals/` only if you need wider context.

Prefer the cropped 16:9 images because they are already video-safe at 1920x1080.

Important crop names:

- Brand/open/close: `images/crops/logo_lockup_16x9.png`
- Main UI sequence: `images/crops/1_16x9.png`, `2-1_16x9.png`, `2-2_16x9.png`, `3_16x9.png`, `4_16x9.png`, `4-1_16x9.png`, `5_16x9.png`, `5-1_16x9.png`, `6_16x9.png`, `6-1_16x9.png`
- Architecture pan: `images/crops/flow-1_left_16x9.png`, `flow-1_center_16x9.png`, `flow-1_right_16x9.png`
- Vertical workflow reference: `images/crops/flow-2_full_padded_16x9.png`
- Final output pan: `images/crops/final_report_left_16x9.png`, `final_report_center_16x9.png`, `final_report_right_16x9.png`

## Product Summary

Report Updater v3 is a Streamlit application that modernizes legacy PDF/DOCX reports. It extracts chapters and visuals, lets a user choose what to keep or refresh, researches current evidence, rewrites chapters with citations, proposes or generates visuals, checks quality, and exports final DOCX/Markdown reports with usage and cost telemetry.

The CEO-level framing is:

- A guided production line for report modernization.
- Human approval remains in the loop.
- AI accelerates understanding, research, writing, and visual refresh.
- Governance is built in through citations, evidence checks, figure-link validation, export readiness, and usage/cost tracking.

## Target Video

- Length: 80-95 seconds.
- Aspect ratio: 16:9.
- Output: 1080p MP4.
- Audience: CEO, senior leadership, report owners, internal stakeholders.
- Tone: boardroom-ready, practical, credible, not flashy.
- Style: polished enterprise product explainer using real screenshots and schematic references.
- Motion: slow push-ins, pans, line traces, subtle highlight pulses, clean transitions.

## Creative Constraints

- Do not invent new product screens.
- Do not create fake search results, fake citations, or fake report outputs.
- Keep screenshots and diagrams legible.
- Treat the provided images as visual truth.
- Use motion to clarify workflow, not to decorate.
- Keep the human-in-the-loop control points visible.
- Frame governance as a strength, not as a problem.

## Preferred Story Arc

Use this arc unless you have a strong reason to adjust:

1. Brand open.
2. Legacy report enters the system.
3. CEO architecture: production line from source inputs to deliverables.
4. Intake and understanding: chapters, visuals, metadata, dated claims.
5. Human scope control: keep, refresh, convert, configure.
6. Research engine: web, academic, internal references.
7. Drafting and visual intelligence: updated chapters, citations, visual recommendations.
8. Quality and governance: citation checks, visual links, export readiness.
9. Publishing package: DOCX, Markdown, visuals, change summary, usage/cost report.
10. Close with value proposition.

## Output Format

Please output in Markdown with these sections:

1. `Executive Video Concept`
2. `Scene Plan`
3. `Hyperframes Prompts`
4. `Voiceover Script`
5. `Asset Attachment Checklist`
6. `Generation Workflow`
7. `Final Export Checklist`

For the `Scene Plan`, use a table with:

- Scene number
- Time range
- Duration
- Asset(s)
- Motion direction
- On-screen text
- Voiceover

For `Hyperframes Prompts`, provide one prompt per scene and explicitly say which asset to attach.

## Extra Requirement

Also provide a very short "one-shot fallback prompt" at the end in case I want to try generating a rough full video in one pass, but make clear that the recommended workflow is scene-by-scene generation.

