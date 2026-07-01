# Claude Hyperframes Package

This folder contains everything needed to ask Claude to help turn the Report Updater v3 materials into a Hyperframes video.

## Start Here

Give Claude this file first:

`CLAUDE_PROMPT.md`

Then upload or reference the whole folder so Claude can inspect the docs and images.

## Contents

### Prompt

- `CLAUDE_PROMPT.md`: the complete prompt to paste into Claude.

### Documents

- `docs/HYPERFRAMES_VIDEO_PLAN.md`: current storyboard, voiceover, prompts, and production notes.
- `docs/ARCHITECTURE_SCHEMATICS_CEO.md`: high-level CEO architecture framing.
- `docs/PROJECT_OVERVIEW.md`: product workflow and implementation overview.
- `docs/README.md`: project summary, setup, and feature list.
- `docs/ARCHITECTURE_SCHEMATICS.md`: implementation-oriented architecture reference.

### Images

- `images/crops/`: primary 1920x1080 Hyperframes-ready image references.
- `images/originals/`: original supplied images for backup context.

## Recommended Claude Request

Paste the contents of `CLAUDE_PROMPT.md` into Claude and attach this folder.

Ask Claude to return a scene-by-scene Hyperframes production plan rather than one giant prompt. Scene-by-scene generation should preserve the real UI and keep the video coherent.

## Recommended Hyperframes Workflow

1. Create a 16:9, 1080p project.
2. Generate one scene at a time.
3. Attach the exact image crop listed for each scene.
4. Paste the scene prompt Claude produces.
5. Keep motion subtle: push-ins, pans, highlight pulses, line traces.
6. Assemble the generated clips in order.
7. Add the voiceover and low-volume corporate music.
8. Export as MP4.

