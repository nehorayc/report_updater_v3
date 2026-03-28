import json
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import google.generativeai as genai
from dotenv import load_dotenv

from llm_json_utils import salvage_ordered_json, try_parse_json
from logger_config import setup_logger

load_dotenv()

logger = setup_logger("WriterAgent")

WRITER_SCHEMA = {
    "chapter_title": "string",
    "executive_takeaway": "string",
    "retained_claims": "string_list",
    "updated_claims": "string_list",
    "new_claims": "string_list",
    "open_questions": "string_list",
    "text_content": "string",
    "visual_suggestions": "json",
    "references": "json",
}
OUTLINE_LINE_PATTERN = re.compile(r"^\s*(?:\d+[.)]|[A-Za-z][.)]|[\u0590-\u05EA][.)])\s+")
BULLET_LINE_PATTERN = re.compile(r"^\s*[*-]\s+(.*)$")
BULLET_HEADING_PATTERN = re.compile(r"^\s*[*-]\s+\*\*(.+?)\*\*:?\s*(.*)$")


def _stringify_findings(research_findings: List[Dict[str, Any]]) -> str:
    lines = []
    for index, finding in enumerate(research_findings, start=1):
        title = finding.get("title", "Untitled finding")
        snippet = finding.get("snippet", "")
        url = finding.get("url") or "N/A"
        source_type = finding.get("source_type") or finding.get("source") or "unknown"
        published_date = finding.get("published_date") or "Unknown"
        lines.append(
            f"- [{index}] {title} | Source Type: {source_type} | Published: {published_date} | URL: {url} | Snippet: {snippet}"
        )
    return "\n".join(lines)


def _build_evidence_snapshot(research_findings: List[Dict[str, Any]], limit: int = 6) -> str:
    ranked = []
    for finding in research_findings:
        relevance = finding.get("relevance_score", 0) or 0
        freshness = finding.get("freshness_score", 0) or 0
        quality = finding.get("source_quality", 0) or 0
        score = (relevance * 2) + freshness + quality
        ranked.append((score, finding))

    snapshot_lines = []
    for _, finding in sorted(ranked, key=lambda item: item[0], reverse=True)[:limit]:
        title = finding.get("title", "Untitled finding")
        source_type = finding.get("source_type") or finding.get("source") or "unknown"
        published_date = finding.get("published_date") or "Unknown"
        snippet = str(finding.get("snippet", "")).strip()
        if len(snippet) > 180:
            snippet = snippet[:177] + "..."
        snapshot_lines.append(
            f"- {title} ({source_type}, {published_date}): {snippet or 'No snippet available.'}"
        )
    return "\n".join(snapshot_lines) if snapshot_lines else "- No ranked evidence snapshot available."


def _normalize_list(value: Any, limit: int = 8) -> List[str]:
    if not isinstance(value, list):
        return []
    cleaned = []
    seen = set()
    for item in value:
        text = str(item).strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
        if len(cleaned) >= limit:
            break
    return cleaned


def _infer_text_language(text: str) -> str:
    return "Hebrew" if re.search(r"[\u0590-\u05FF]", text or "") else "English"


def _soften_outline_structure(text: str) -> str:
    if not text:
        return text

    lines = text.splitlines()
    outline_lines = sum(1 for line in lines if OUTLINE_LINE_PATTERN.match(line.strip()))
    if outline_lines < 4:
        return text

    cleaned_lines = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            cleaned_lines.append("")
            continue
        if OUTLINE_LINE_PATTERN.match(stripped):
            stripped = OUTLINE_LINE_PATTERN.sub("", stripped, count=1)
        cleaned_lines.append(stripped)

    softened = "\n".join(cleaned_lines)
    softened = re.sub(r"\n{3,}", "\n\n", softened)
    return softened.strip()


def _reshape_bullet_heavy_text(text: str) -> str:
    if not text:
        return text

    lines = text.splitlines()
    bullet_lines = sum(1 for line in lines if BULLET_LINE_PATTERN.match(line.strip()))
    if bullet_lines < 6:
        return text

    reshaped_lines: List[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if reshaped_lines and reshaped_lines[-1] != "":
                reshaped_lines.append("")
            continue

        heading_match = BULLET_HEADING_PATTERN.match(line)
        if heading_match:
            heading = heading_match.group(1).strip().rstrip(":")
            remainder = heading_match.group(2).strip()
            reshaped_lines.append(f"### {heading}")
            if remainder:
                reshaped_lines.append(remainder)
            continue

        bullet_match = BULLET_LINE_PATTERN.match(line)
        if bullet_match:
            reshaped_lines.append(bullet_match.group(1).strip())
            continue

        reshaped_lines.append(stripped)

    reshaped = "\n".join(reshaped_lines)
    reshaped = re.sub(r"\n{3,}", "\n\n", reshaped)
    return reshaped.strip()


def _normalize_reference_category(raw_category: Any, source_hint: Any = None) -> str:
    category = str(raw_category or "").strip().lower()
    source_hint = str(source_hint or "").strip().lower()
    if category in {"academic", "web", "original", "uploaded"}:
        return category.title()
    if source_hint in {"academic", "paper", "journal", "openalex", "scholar"}:
        return "Academic"
    if source_hint in {"original"}:
        return "Original"
    if source_hint in {"uploaded", "internal", "reference_doc", "reference-doc"}:
        return "Uploaded"
    return "Web"


def _normalize_reference_title(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def _reference_token(value: Any) -> str:
    token = str(value or "").strip()
    if not token:
        return ""
    if token.isdigit():
        return str(int(token))
    if token.lower() in {"original", "original report"}:
        return "Original"
    return token


def _normalize_references(
    references: Any,
    research_findings: List[Dict[str, Any]],
    include_original_reference: bool,
    edition_title: str,
    original_report_date: str,
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    allowed_urls = {
        str(finding.get("url", "")).strip()
        for finding in research_findings
        if str(finding.get("url", "")).strip().startswith("http")
    }
    credible_titles_by_category = {
        "academic": set(),
        "uploaded": set(),
        "original": set(),
        "web": set(),
    }
    for finding in research_findings:
        source_hint = finding.get("source_type") or finding.get("source")
        category = _normalize_reference_category(finding.get("category"), source_hint).lower()
        title = _normalize_reference_title(finding.get("title", ""))
        if not title:
            continue
        if category == "web" and not finding.get("source_credible", True):
            continue
        credible_titles_by_category.setdefault(category, set()).add(title)
    normalized_refs: List[Dict[str, Any]] = []
    citation_map: Dict[str, int] = {}
    ref_positions: Dict[tuple[str, str, str], int] = {}

    if isinstance(references, list):
        for position, ref in enumerate(references, start=1):
            if not isinstance(ref, dict):
                continue
            title = str(ref.get("title", "")).strip()
            if not title:
                continue
            category = _normalize_reference_category(ref.get("category"), ref.get("source_type") or ref.get("source"))
            normalized_title = _normalize_reference_title(title)
            url = str(ref.get("url", "")).strip()
            if url and url not in allowed_urls:
                url = ""
            if category == "Web" and not url and normalized_title not in credible_titles_by_category.get("web", set()):
                continue
            if category == "Academic" and not url and normalized_title not in credible_titles_by_category.get("academic", set()):
                continue
            if category == "Uploaded" and normalized_title not in credible_titles_by_category.get("uploaded", set()):
                continue
            key = (title.lower(), url.lower(), category.lower())
            normalized_index = ref_positions.get(key)
            if normalized_index is None:
                normalized = {
                    "title": title,
                    "category": category,
                    "_raw_tokens": set(),
                }
                if url:
                    normalized["url"] = url
                normalized_refs.append(normalized)
                normalized_index = len(normalized_refs) - 1
                ref_positions[key] = normalized_index

            raw_tokens = normalized_refs[normalized_index].setdefault("_raw_tokens", set())
            for candidate in (ref.get("index"), ref.get("citation"), ref.get("token"), position):
                token = _reference_token(candidate)
                if token:
                    raw_tokens.add(token)

    if include_original_reference and not any(ref.get("category") == "Original" for ref in normalized_refs):
        title = edition_title or "Original report"
        if original_report_date and original_report_date != "Unknown":
            title = f"{title} (original edition dated {original_report_date})"
        normalized_refs.append(
            {
                "title": title,
                "category": "Original",
                "_raw_tokens": {"Original"},
            }
        )

    for index, ref in enumerate(normalized_refs, start=1):
        for token in ref.pop("_raw_tokens", set()):
            citation_map[token] = index
        ref["index"] = index

    return normalized_refs, citation_map


def _normalize_inline_citations(text: str, citation_map: Dict[str, int]) -> str:
    if not text or not citation_map:
        return text

    citation_pattern = re.compile(r"\[\s*(Original(?:\s+Report)?|\d+)\s*\]", re.IGNORECASE)

    def replace(match: re.Match[str]) -> str:
        token = _reference_token(match.group(1))
        mapped = citation_map.get(token)
        if mapped is None:
            return match.group(0)
        return f"[{mapped}]"

    return citation_pattern.sub(replace, text)


def _fallback_chapter_title(parsed: Dict[str, Any], fallback_title: str) -> str:
    candidate = str(parsed.get("chapter_title", "")).strip()
    if candidate:
        return candidate
    return str(fallback_title or "Untitled Chapter").strip()


def _fallback_executive_takeaway(parsed: Dict[str, Any]) -> str:
    if str(parsed.get("executive_takeaway", "")).strip():
        return str(parsed.get("executive_takeaway", "")).strip()

    claim_pool = []
    for key in ("updated_claims", "new_claims", "retained_claims"):
        claim_pool.extend(_normalize_list(parsed.get(key), limit=2))

    if claim_pool:
        summary = " ".join(claim_pool[:2]).strip()
        return summary[:300]
    return ""


def _normalize_response(parsed: Dict[str, Any], fallback_title: str) -> Dict[str, Any]:
    normalized = {
        "chapter_title": _fallback_chapter_title(parsed, fallback_title),
        "executive_takeaway": _fallback_executive_takeaway(parsed),
        "retained_claims": _normalize_list(parsed.get("retained_claims"), limit=6),
        "updated_claims": _normalize_list(parsed.get("updated_claims"), limit=6),
        "new_claims": _normalize_list(parsed.get("new_claims"), limit=6),
        "open_questions": _normalize_list(parsed.get("open_questions"), limit=5),
        "text_content": str(parsed.get("text_content", "")).strip(),
        "visual_suggestions": parsed.get("visual_suggestions", []) if isinstance(parsed.get("visual_suggestions"), list) else [],
        "references": [],
    }
    return normalized


def write_chapter(
    original_text: str,
    research_findings: List[Dict],
    blueprint: Dict,
    writing_style: str = "Professional",
    assets_to_update: Optional[List[Dict]] = None,
    target_word_count: int = 500,
    temperature: float = 0.5,
) -> Dict:
    """
    Uses Gemini to produce an updated-edition chapter based on the original text,
    structured baseline hints, and fresh research findings.
    """
    logger.info(f"Starting chapter generation for topic: {blueprint.get('topic')} (Target: {target_word_count} words)")
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.error("GEMINI_API_KEY not found in environment.")
        return {"error": "GEMINI_API_KEY not found"}

    assets_to_update = assets_to_update or []

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.5-flash")

    findings_str = _stringify_findings(research_findings)
    evidence_snapshot = _build_evidence_snapshot(research_findings)
    baseline_summary = blueprint.get("baseline_summary", "")
    baseline_claims = "\n".join(f"- {claim}" for claim in blueprint.get("baseline_claims", []))
    original_report_date = blueprint.get("original_report_date", "Unknown")
    update_start_date = blueprint.get("update_start_date", "Unknown")
    update_end_date = blueprint.get("update_end_date", "Unknown")
    target_audience = blueprint.get("target_audience", "General professional audience")
    output_language = blueprint.get("output_language", "Match Source Language")
    edition_title = blueprint.get("edition_title", "")
    chapter_role = blueprint.get("chapter_role", "body")
    preserve_original_voice = blueprint.get("preserve_original_voice", True)
    source_language = _infer_text_language(original_text)

    update_instructions = ""
    if assets_to_update:
        logger.info(f"Preparing update instructions for {len(assets_to_update)} assets.")
        update_instructions = "MANDATORY VISUAL/TABLE UPDATES:\n"
        for asset in assets_to_update:
            if asset.get("type") == "table" and asset.get("convert_to_text"):
                update_instructions += (
                    f"- CONVERT TO TEXT: Replace Figure '{asset.get('short_caption')}' (ID: {asset['id']}) "
                    f"with this markdown table: {asset.get('analysis', {}).get('table_markdown')}. "
                    "Integrate it into the text flow.\n"
                )
            elif asset.get("type") == "table" and asset.get("do_update"):
                update_instructions += (
                    f"- UPDATE TABLE: Recreate Figure '{asset.get('short_caption')}' (ID: {asset['id']}) "
                    f"as a Markdown table using NEW data from research. Original structure: {asset.get('description')}\n"
                )
            else:
                update_instructions += (
                    f"- RECREATE GRAPH: Recreate Figure '{asset.get('short_caption')}' (Original ID: {asset['id']}) "
                    f"using NEW data from research through {update_end_date}. Description: {asset.get('description')}. "
                    f"YOU MUST add a matching entry in 'visual_suggestions' with id '{asset['id']}' and the new data points so the system can redraw it.\n"
                )
        update_instructions += (
            "For each of these items, you MUST include a [Figure ID] marker in the appropriate place in "
            "'text_content' (using the ID provided) so it appears in the final report.\n"
        )
    task_update_instruction = f"7. {update_instructions.strip()}" if update_instructions.strip() else ""

    prompt = f"""
Original Report Chapter Text:
---
{original_text}
---

Original Chapter Baseline:
- Chapter Role: {chapter_role}
- Baseline Summary: {baseline_summary}
- Baseline Claims:
{baseline_claims or '- None supplied'}

Report Update Metadata:
- Edition Title: {edition_title or 'Updated Edition'}
- Original Report Date: {original_report_date}
- Update Window Start: {update_start_date}
- Update Through Date: {update_end_date}
- Output Language: {output_language}
- Target Audience: {target_audience}
- Preserve Original Voice: {preserve_original_voice}

Recent Research Findings:
---
{findings_str}
---

Highest-Value Evidence Snapshot:
{evidence_snapshot}

User Objective (Blueprint):
- Topic: {blueprint.get('topic')}
- Timeframe: {blueprint.get('timeframe')}
- Additional Instructions: {blueprint.get('instructions', 'None')}
- Writing Style: {writing_style}
- TARGET LENGTH: Approximately {target_word_count} words.

THINK STEP BY STEP (do not output this reasoning, just follow the process):
Step 1 - Identify the chapter's original thesis, strongest still-valid claims, and outdated claims.
Step 2 - Match the outdated claims to the strongest research findings from the update window.
Step 3 - Write a new-edition chapter that preserves the original report's through-line while updating the evidence and implications.

CRITICAL WRITING RULES:
- You are producing a NEW EDITION of the original report chapter, not a generic rewrite.
- The source chapter language appears to be: {source_language}.
- If Output Language is "Match Source Language", keep the entire output in {source_language}.
- If Output Language is explicitly set to English or Hebrew, the entire output must stay in that language, including chapter prose, takeaways, claims, visual titles, and section labels you generate.
- The chapter_title field MUST also be in that same language.
- Preserve the original chapter's logic, intent, and strongest insights where they still hold up.
- The updated chapter should clearly reflect developments between {update_start_date} and {update_end_date}.
- Use the original text for context and continuity, but let the new evidence carry the chapter forward.
- Open with the most important change since the original edition, not background filler.
- Every paragraph containing concrete facts, figures, dates, named organizations, or comparative claims must include at least one inline citation.
- Attribute disagreements explicitly when sources conflict. Name the organizations, publications, or researchers behind the disagreement.
- Prefer exact years, dates, organizations, model names, products, laws, datasets, and figures over generic wording.
- Do not invent statistics, organizations, or URLs. If a detail is uncertain, state the uncertainty instead of guessing.
- Do NOT write phrases like "this section was updated", "compared to the previous edition", or "in the old report".
- Do NOT flatten conflicting evidence. If the evidence is mixed, state that clearly and professionally.
- Do NOT preserve numbered or lettered outline structure from the source unless absolutely necessary.
- Prefer flowing report prose with short subsection headers over memo-style numbering like 1., 2., a., b., or א., ב..

TASK:
1. Produce an updated-edition chapter for the requested audience.
2. Keep the chapter structure readable and useful: opening change statement, context, developments, current state, implications, near-term outlook.
3. Make the chapter evidence-dense, not generic. Every paragraph should either add new evidence, refine an original claim, or explain a decision-relevant implication.
4. Be specific: use named organizations, exact numbers, exact years, and concrete developments whenever available.
5. Use numbered inline citations: [1], [2], [3], etc. Every factual claim from research should have citation support.
6. Include the original report as a reference when original claims or historical framing are retained.
7. Keep the chapter flowing. Use bullets only when they materially improve readability; otherwise write coherent narrative paragraphs.
{task_update_instruction}

CRITICAL - VISUAL MARKERS:
- The original text may contain existing figure markers with real hex IDs (e.g. [Figure 4a1b2c3d: Caption]).
- You MUST preserve those existing markers in the appropriate context within your 'text_content'.
- If you are UPDATING or RECREATING an existing visual, insert a marker using ONLY the real ID provided in the update instructions above.
- Do NOT use placeholder text like "XXXXXXXX".
- For BRAND-NEW visual suggestions, invent a random 8-character hex ID for each one.
- For EVERY visual in the 'visual_suggestions' list, include its 'id' field.
- For EVERY recreated/updated visual in the 'visual_suggestions' list, include an "action": "update" field.

MANDATORY OUTPUT FIELDS:
- executive_takeaway: 2-3 sentence summary of what changed in this chapter
- retained_claims: 2-6 short bullets capturing original claims that still hold
- updated_claims: 2-6 short bullets capturing original claims that needed revision
- new_claims: 2-6 short bullets capturing new developments since the original report
- open_questions: 0-5 unresolved questions, uncertainties, or tensions worth noting
- chapter_title: the final chapter title in the selected output language
- text_content: the actual updated chapter, with factual paragraphs cited and the first paragraph clearly answering what changed
- visual_suggestions: at least 2 new visuals, using EXACTLY "graph" or "image" as the type
- references: ordered list containing only sources actually used in the text and matching the inline citation numbers

BIBLIOGRAPHY RULES:
- Include an "index" field for each reference.
- Use category values like "Academic", "Web", "Original", or "Uploaded".
- Only include a `url` field when that exact URL appears in the research findings.
- If you retain historical framing from the original chapter, include one reference with category "Original".

OUTPUT FORMAT (MANDATORY JSON):
{{
  "executive_takeaway": "2-3 sentence chapter takeaway...",
  "chapter_title": "Localized chapter title...",
  "retained_claims": ["Claim that still holds"],
  "updated_claims": ["Claim from the original report that needed revision"],
  "new_claims": ["New development since the original edition"],
  "open_questions": ["Optional uncertainty or unresolved issue"],
  "text_content": "The markdown-formatted updated chapter with [1], [2] citations...",
  "visual_suggestions": [
    {{
      "id": "a1b2c3d4",
      "type": "graph",
      "title": "Short descriptive title",
      "description": "What this graph shows and why it is relevant",
      "chart_type": "bar",
      "data_points": {{
        "labels": ["Label A", "Label B"],
        "values": [10, 20],
        "unit": "USD Billions"
      }}
    }},
    {{
      "id": "e5f6g7h8",
      "type": "image",
      "title": "Short descriptive title",
      "description": "What this image should show",
      "query": "specific English DuckDuckGo search query for the image"
    }}
  ],
  "references": [
    {{
      "index": 1,
      "title": "Exact Title of Source",
      "url": "http://...",
      "category": "Web"
    }}
  ]
}}
"""

    generation_config = {
        "response_mime_type": "application/json",
        "temperature": temperature,
    }

    logger.debug(f"Prompt sent to Gemini (truncated): {prompt[:500]}...")
    start_time = time.time()
    try:
        response = model.generate_content(prompt, generation_config=generation_config)
        latency = time.time() - start_time
        logger.info(f"Gemini response received in {latency:.2f}s.")

        text = response.text.strip()
        logger.debug(f"FULL Gemini Response:\n{text}")

        if text.startswith("```json"):
            text = text[7:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        try:
            parsed = try_parse_json(text)
        except json.JSONDecodeError:
            logger.warning("Writer JSON decode failed, attempting ordered salvage.")
            parsed = salvage_ordered_json(text, WRITER_SCHEMA)

        normalized = _normalize_response(parsed, blueprint.get("topic") or blueprint.get("title") or "Untitled Chapter")
        uses_original_marker = bool(re.search(r"\[\s*Original(?:\s+Report)?\s*\]", normalized.get("text_content", ""), re.IGNORECASE))
        normalized_references, citation_map = _normalize_references(
            parsed.get("references", []),
            research_findings,
            include_original_reference=bool(normalized["retained_claims"]) or uses_original_marker,
            edition_title=edition_title or blueprint.get("topic", "Original report"),
            original_report_date=original_report_date,
        )
        normalized["references"] = normalized_references
        normalized["text_content"] = _normalize_inline_citations(normalized.get("text_content", ""), citation_map)
        normalized["text_content"] = _soften_outline_structure(normalized.get("text_content", ""))
        normalized["text_content"] = _reshape_bullet_heavy_text(normalized.get("text_content", ""))
        logger.info(f"Successfully generated chapter. Text length: {len(normalized.get('text_content', ''))}")
        return normalized
    except Exception as e:
        logger.error(f"Failed to generate chapter: {e}", exc_info=True)
        return {
            "error": f"Failed to generate chapter: {str(e)}",
            "raw_content": response.text if "response" in locals() else "",
        }


if __name__ == "__main__":
    res = write_chapter(
        "AI is growing.",
        [{"title": "AI in 2025", "snippet": "Market grew by 40% in 2024.", "url": "example.com", "source": "web"}],
        {
            "topic": "AI Trends",
            "baseline_summary": "A baseline chapter on AI adoption.",
            "baseline_claims": ["AI adoption was accelerating across industries."],
            "original_report_date": "2023-01-01",
            "update_start_date": "2023-01-01",
            "update_end_date": "2026-03-22",
        },
    )
    print(json.dumps(res, indent=2))
