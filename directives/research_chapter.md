# Directive: Research & Writing Logic (State 4)

## Goal
To transform a "Chapter Blueprint" into a fully researched, high-quality report section that includes factual updates, citations, and suggestions for relevant visuals.

## Inputs
- **Original Text**: The source text from the legacy report.
- **Chapter Blueprint**:
  - `topic`: The specific focus for the update.
  - `timeframe`: The temporal scope (e.g., "Last 2 years", "2024-2025").
  - `keywords`: Optimized search queries.
- **Reference Docs**: Context from internal files uploaded by the user.

## Steps

### 1. Multi-Source Research
- **Web Research**: Use DuckDuckGo to find recent news, statistics, and industry trends.
  - After getting results, **fetch the full article body** (first 2500 chars) for each URL in parallel (5s timeout per URL). Use full body if richer than the snippet; fall back to snippet on failure.
- **Academic/Deep Web**: Search for specialized reports or data points that add depth.
- **Internal Context**: Query the provided "Reference Docs" using keyword scoring — return the top 3 matching **paragraphs** per document (not just the filename).

### 2. Information Synthesis
- Compare findings with the **Original Text**.
- Prioritize newer data while maintaining the core narrative structure of the chapter.
- Identify logical gaps where a visual representation (graph/table/image) would improve clarity.

### 3. Draft Generation
Rewrite the chapter text ensuring:
- **Tone**: Match the original text's style, tone, and structure. Write as if you are the original author updating their own report.
- **Citations**: Use numbered inline citations `[1]`, `[2]`, etc. Each number must match the index in the ordered references list.
- **Specificity**: Cite exact numbers, percentages, named organizations, and years. Never make generic claims — always quantify.
- **Anti-Hallucination Rule**: Only include a URL in references if it appeared verbatim in the research findings. Never invent URLs.
- **No Comparisons**: Do NOT explain how the chapter differs from the previous version. Write the updated chapter as if it were the current, authoritative version.
- **Chain-of-thought**: First identify outdated claims, then find replacements in research, then write.
- **Structure**: Clear headings and sub-headings.

### 4. Visual Ideation
For every chapter, the AI must propose at least one (but no more than three) visual enhancements.
- **Visual Types**:
  - `graph`: When trend data or comparisons are present.
  - `table`: When complex data needs organization.
  - `image`: When a conceptual illustration or specific real-world object is mentioned.
- **Output Format**: A structured JSON object found at the end of the text.

## Output Format Specification
The writing agent must return a response in the following format:

```json
{
  "text_content": "Full rewritten markdown text here...",
  "visual_suggestions": [
    {
      "type": "graph",
      "title": "...",
      "description": "Bar chart showing X vs Y based on [data]",
      "suggested_location": "after_paragraph_2",
      "data_points": {"labels": [], "values": []}
    },
    {
      "type": "image",
      "query": "High quality photo of [subject]",
      "description": "Illustration of [concept]",
      "suggested_location": "before_final_paragraph"
    }
  ],
  "references": [
    {"title": "...", "url": "...", "type": "web|internal|academic"}
  ]
}
```

## Constraints
- Do **not** hallucinate data. If information is missing, state the current trend generically or flag it.
- Keep rewritten text approximately the same length as the original unless depth is explicitly requested.
- Ensure bibliography entries are complete.
