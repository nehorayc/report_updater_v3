# Hyperframes Video Plan

Working title: `Report Updater v3 - From Legacy Report To Governed Updated Edition`

Primary sources:

- `README.md` and `PROJECT_OVERVIEW.md`: product description and workflow.
- `ARCHITECTURE_SCHEMATICS_CEO.md`: executive architecture framing.
- `hyperframes_images/`: supplied visual references.
- `hyperframes_images/crops/`: generated 16:9-safe crops for video use.

## Goal

Create an executive-grade Hyperframes video that explains Report Updater v3 as a guided production line for modernizing legacy reports. The video should feel clear, credible, and boardroom-ready: the system ingests an old report, understands it, researches what changed, drafts an updated edition, refreshes visuals, validates quality, and publishes a traceable report package.

## Audience

CEO, senior leadership, report owners, and internal stakeholders who need to understand the business value without seeing implementation details.

## Core Message

Report Updater v3 turns static historical reports into current, evidence-backed editions while keeping humans in control and governance visible.

## Format

- Length: 80-95 seconds.
- Aspect: 16:9.
- Resolution: 1920x1080.
- Style: polished enterprise product explainer, subtle motion graphics, clean UI close-ups, restrained cinematic camera moves.
- Tone: confident, practical, transparent.
- Music: low-key modern corporate bed, light pulse accents on workflow transitions.
- Voice: calm executive narrator.

## Asset Prep

The original images remain untouched. Cropped/normalized derivatives were created in:

`hyperframes_images/crops/`

Use these crops for Hyperframes references where possible:

- Main numbered frames:
  - `1_16x9.png`
  - `2-1_16x9.png`
  - `2-2_16x9.png`
  - `3_16x9.png`
  - `4_16x9.png`
  - `4-1_16x9.png`
  - `5_16x9.png`
  - `5-1_16x9.png`
  - `6_16x9.png`
  - `6-1_16x9.png`
- Architecture and flow pans:
  - `flow-1_left_16x9.png`
  - `flow-1_center_16x9.png`
  - `flow-1_right_16x9.png`
  - `flow-2_full_padded_16x9.png`
  - `flow-2_top_16x9.png`
  - `flow-2_mid_16x9.png`
  - `flow-2_bottom_16x9.png`
- Final output pans:
  - `final_report_left_16x9.png`
  - `final_report_center_16x9.png`
  - `final_report_right_16x9.png`
- Branding:
  - `logo_lockup_16x9.png`

## Visual Rules

- Treat supplied UI and schematic images as source-of-truth references.
- Do not invent new product screens.
- Keep text and diagrams legible; prefer slow push-ins and pans over aggressive animation.
- Use glow/line-trace effects only to clarify flow, not as decoration.
- Keep the human-in-loop theme visible: upload, configure, review, approve.
- Governance should be framed as a feature: citations, figure links, export readiness, usage/cost reports.

## Storyboard

| Scene | Time | Source Image | Visual Direction | On-Screen Text | Voiceover |
| --- | ---: | --- | --- | --- | --- |
| 1. Brand Open | 0:00-0:06 | `crops/logo_lockup_16x9.png` | Fade in logos over white. Subtle lens-like light sweep, no heavy effects. | `Report Updater v3` / `Legacy reports, modernized with control` | "Report Updater v3 is a guided workspace for turning legacy reports into current, evidence-backed editions." |
| 2. The Input | 0:06-0:14 | `crops/1_16x9.png` | Slow push toward the first product frame. Add a soft incoming document motion if Hyperframes supports overlays. | `Start with an old report` | "A PDF or DOCX enters the system with its chapters, claims, tables, and visuals still locked in the past." |
| 3. Executive Architecture | 0:14-0:25 | `crops/flow-1_left_16x9.png` -> `flow-1_center_16x9.png` -> `flow-1_right_16x9.png` | Three-part pan across the simplified source-to-report flow. Animate a thin progress line from inputs to actions to deliverables. | `A production line for report modernization` | "The app behaves like a production line: intake, understanding, research, drafting, visual intelligence, quality checks, and publishing." |
| 4. Intake And Understanding | 0:25-0:34 | `crops/2-1_16x9.png`, `crops/2-2_16x9.png` | Cut between related frames. Use highlight boxes over extracted chapters/visuals if available. | `Extract structure and context` | "First, it pulls the source apart into chapters, original visuals, metadata, dated claims, keywords, and context." |
| 5. Human Scope Control | 0:34-0:43 | `crops/3_16x9.png`, `crops/flow-2_full_padded_16x9.png` | Show workflow step framing, then return to app UI. Motion should feel like a checkpoint, not an automated black box. | `User chooses what stays, changes, or gets refreshed` | "The user stays in control, choosing which source visuals to keep, which charts to refresh, and how each chapter should be updated." |
| 6. Research Engine | 0:43-0:54 | `crops/4_16x9.png`, `crops/4-1_16x9.png` | Subtle branching lines to public web, academic sources, and internal documents. Keep it clean and executive. | `Fresh evidence from trusted sources` | "The research engine gathers current evidence from the web, academic sources, and uploaded internal references, then ranks what is useful for writing." |
| 7. Drafting And Visual Intelligence | 0:54-1:05 | `crops/5_16x9.png`, `crops/5-1_16x9.png` | Use a gentle split transition from draft text to visual suggestions. Add small data-line animation around charts only if it preserves legibility. | `Updated chapters + refreshed visuals` | "The drafting engine rewrites the report as a new edition, adds citations, preserves still-valid claims, and proposes or refreshes visuals." |
| 8. Quality And Governance | 1:05-1:16 | `crops/6_16x9.png`, `crops/6-1_16x9.png` | Use checkmark-style pulses around citations, visual links, and readiness indicators. Avoid implying full automation without review. | `Governance before publishing` | "Before export, quality checks look for citation gaps, broken figure markers, stale evidence, malformed URLs, and export risks." |
| 9. Publishing Package | 1:16-1:27 | `crops/final_report_left_16x9.png` -> `final_report_center_16x9.png` -> `final_report_right_16x9.png` | Slow pan across final report output. End on the most polished final-report view. | `DOCX, Markdown, visuals, change summary, usage report` | "The final package includes a polished report, approved visuals, a change summary, and transparent AI usage and cost reporting." |
| 10. Close | 1:27-1:34 | `crops/logo_lockup_16x9.png` | Fade back to brand lockup. Minimal movement. | `Modernize faster. Review with confidence. Publish with traceability.` | "The result is faster modernization, stronger review control, and a clear trail from old report to updated edition." |

## Hyperframes Prompt Pack

Use one prompt per scene with the referenced image attached. Keep prompts short and explicit.

### Scene 1 Prompt

Use the provided logo lockup as the exact visual reference. Create a clean executive product intro on a white background. Subtle premium motion, soft light sweep, no added logos, no invented UI. Add crisp title text: "Report Updater v3".

### Scene 2 Prompt

Use the provided application screenshot as the exact product reference. Slow cinematic push-in on the workspace. Convey an old report entering a guided modernization process. Keep all UI text and layout stable and legible. No invented screens.

### Scene 3 Prompt

Use the provided flow crop as a schematic reference. Animate the architecture as a calm left-to-right production line, with a thin highlight line moving from sources to app actions to deliverables. Keep the diagram readable. Enterprise presentation style.

### Scene 4 Prompt

Use the provided product screenshots as reference frames. Show report intake and content understanding. Use subtle highlight rectangles over chapters, visuals, and extracted structure. Keep the app screen legible and avoid generating new UI.

### Scene 5 Prompt

Use the provided workflow/app references. Emphasize human approval checkpoints: keep, refresh, convert, configure. Gentle camera movement, crisp screen detail, restrained executive SaaS aesthetic.

### Scene 6 Prompt

Use the provided research/planning screenshots as reference. Visualize evidence gathering with subtle connecting lines to web, academic, and internal sources. Keep source-gathering abstract and professional. Do not show fake search results.

### Scene 7 Prompt

Use the provided drafting/visual screenshots as reference. Show chapter text and visual intelligence working together. Add subtle data-line and chart-refresh motion without obscuring the screen. Keep the product UI faithful.

### Scene 8 Prompt

Use the provided quality/review screenshots as reference. Convey governance and readiness checks with subtle check pulses around citations, figure links, and warnings. Do not imply issues disappear automatically; keep review control visible.

### Scene 9 Prompt

Use the provided final report crop as the exact output reference. Slow pan across the final report package. Make the document feel polished, export-ready, and traceable. Do not invent extra pages or charts.

### Scene 10 Prompt

Return to the provided logo lockup. Clean white executive close. Add final line: "Modernize faster. Review with confidence. Publish with traceability." Minimal animation, confident finish.

## Full Voiceover Script

Report Updater v3 is a guided workspace for turning legacy reports into current, evidence-backed editions.

A PDF or DOCX enters the system with its chapters, claims, tables, and visuals still locked in the past.

The app behaves like a production line: intake, understanding, research, drafting, visual intelligence, quality checks, and publishing.

First, it pulls the source apart into chapters, original visuals, metadata, dated claims, keywords, and context.

The user stays in control, choosing which source visuals to keep, which charts to refresh, and how each chapter should be updated.

The research engine gathers current evidence from the web, academic sources, and uploaded internal references, then ranks what is useful for writing.

The drafting engine rewrites the report as a new edition, adds citations, preserves still-valid claims, and proposes or refreshes visuals.

Before export, quality checks look for citation gaps, broken figure markers, stale evidence, malformed URLs, and export risks.

The final package includes a polished report, approved visuals, a change summary, and transparent AI usage and cost reporting.

The result is faster modernization, stronger review control, and a clear trail from old report to updated edition.

## Optional Shorter 60-Second Cut

For a shorter cut, remove Scene 5 and compress Scenes 6-8 into one "Research, Draft, Validate" sequence:

- 0:00-0:06 Brand open
- 0:06-0:14 Legacy report input
- 0:14-0:26 Executive architecture pan
- 0:26-0:38 Intake and understanding
- 0:38-0:50 Research, draft, visuals, governance
- 0:50-0:58 Final report package
- 0:58-1:00 Logo close

## Production Notes

- Prefer cross-dissolves and push-ins over fast cuts.
- Use `flow-1_*` crops for horizontal architecture motion.
- Use `flow-2_full_padded_16x9.png` when the full vertical flow needs to stay visible.
- Use `flow-2_top_16x9.png`, `flow-2_mid_16x9.png`, and `flow-2_bottom_16x9.png` only for detail callouts.
- Use `final_report_*` crops as a slow pan sequence rather than showing the original extra-wide file all at once.
- If Hyperframes struggles with UI legibility, switch to still-image motion: import each crop as a fixed frame and apply camera moves only.
- Keep animations faithful to the product. The credibility of the video comes from clear workflow, human control, and traceability.
