import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from logger_config import setup_logger

logger = setup_logger("QualityGate")

FACTUAL_SIGNAL_PATTERN = re.compile(
    r"(\b(?:19|20)\d{2}\b|[$€£]\s?\d|\b\d+(?:\.\d+)?%|\baccording to\b|\breported\b|\bincreased\b|\bdecreased\b|\breached\b|\bgrew\b)",
    re.IGNORECASE,
)
CITATION_GROUP_PATTERN = re.compile(
    r"\[((?:\s*(?:Original(?:\s+Report)?|\d+)\s*)(?:,\s*(?:Original(?:\s+Report)?|\d+)\s*)*)\]",
    re.IGNORECASE,
)
FIGURE_MARKER_PATTERN = re.compile(
    r"\[(?:Figure|Asset|Image|Figura|איור|תמונה)(?:\s+ID)?\s*:?\s*([A-Za-z0-9][A-Za-z0-9_-]{3,63})[:\s]*.*?\]",
    re.IGNORECASE,
)
RAW_VISUAL_TOKEN_PATTERN = re.compile(r"\[\s*visual\s*:\s*([A-Za-z0-9][A-Za-z0-9_-]{3,63})[^\]]*\]", re.IGNORECASE)
URL_PATTERN = re.compile(r"^https?://\S+$", re.IGNORECASE)
CITATION_PATTERN = re.compile(r"\[\s*(Original(?:\s+Report)?|\d+)\s*\]", re.IGNORECASE)
RAW_ORIGINAL_CITATION_PATTERN = re.compile(r"\[\s*Original\s+Report\s*\]", re.IGNORECASE)
STRUCTURAL_PARAGRAPH_PATTERN = re.compile(r"^(?:[#|]|[-*]\s|\d+\.\s|\[(?:Figure|Asset|Image|Figura|איור|תמונה|visual))", re.IGNORECASE)
META_PROMPT_LEAK_PATTERN = re.compile(
    r"(diverging from the original report's focus|align with the specified user objective|this updated edition addresses the topic of|user objective|analyst agent)",
    re.IGNORECASE,
)
PRIVATE_USE_PATTERN = re.compile(r"[\uE000-\uF8FF]")
MARKDOWN_HEADING_PATTERN = re.compile(r"^\s*#{1,6}\s+(.+?)\s*$")


def _issue(
    severity: str,
    code: str,
    message: str,
    *,
    hint: str = "",
    auto_fixable: bool = False,
    context: str = "",
    paragraph_number: Optional[int] = None,
) -> Dict[str, Any]:
    issue: Dict[str, Any] = {
        "severity": severity,
        "code": code,
        "message": message,
        "auto_fixable": auto_fixable,
    }
    if hint:
        issue["hint"] = hint
    if context:
        issue["context"] = context
    if paragraph_number is not None:
        issue["paragraph_number"] = paragraph_number
    return issue


def _compact_context(text: str, limit: int = 180) -> str:
    compact = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def _extract_year(value: Any) -> Optional[int]:
    match = re.search(r"\b(19\d{2}|20\d{2})\b", str(value or ""))
    return int(match.group(1)) if match else None


def _normalize_citation_token(value: Any) -> str:
    token = str(value or "").strip()
    if not token:
        return ""
    if token.isdigit():
        return str(int(token))
    if token.lower() in {"original", "original report"}:
        return "Original"
    return token


def _normalize_marker_token(value: Any) -> str:
    token = str(value or "").strip().lower()
    if not token:
        return ""
    return re.sub(r"[^a-z0-9_-]", "", token)


def _time_window(report_metadata: Dict[str, Any]) -> tuple[Optional[int], Optional[int]]:
    start_year = _extract_year(report_metadata.get("update_start_date"))
    end_year = _extract_year(report_metadata.get("update_end_date")) or datetime.now().year
    return start_year, end_year


def _split_paragraphs(text: str) -> List[str]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text or "") if part.strip()]
    if paragraphs:
        return paragraphs
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


def _approved_visual_ids(chapter: Dict[str, Any]) -> set[str]:
    ids = set()
    for visual in chapter.get("approved_visuals", []):
        for key in ("marker_id", "id", "original_asset_id"):
            value = _normalize_marker_token(visual.get(key))
            if value:
                ids.add(value)
                if len(value) > 8:
                    ids.add(value[:8])
    return ids


def _citation_numbers_in_text(text: str) -> set[int]:
    numbers: set[int] = set()
    for group in CITATION_GROUP_PATTERN.findall(text or ""):
        for raw_token in group.split(","):
            normalized = _normalize_citation_token(raw_token)
            if normalized.isdigit():
                numbers.add(int(normalized))
    return numbers


def _reference_index(ref: Dict[str, Any], fallback_position: int) -> int:
    try:
        return int(ref.get("index", fallback_position))
    except (TypeError, ValueError):
        return fallback_position


def _is_structural_paragraph(paragraph: str) -> bool:
    stripped = str(paragraph or "").strip()
    if not stripped:
        return True
    if len(stripped) < 40 or len(stripped.split()) < 7:
        return True
    if STRUCTURAL_PARAGRAPH_PATTERN.match(stripped):
        return True
    if stripped.startswith("**") and stripped.endswith("**"):
        return True
    return False


def _normalize_heading_label(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().strip(":")).lower()


def _has_duplicate_lead_heading(chapter: Dict[str, Any]) -> bool:
    title = _normalize_heading_label(chapter.get("title", ""))
    if not title:
        return False

    for line in str(chapter.get("draft_text", "") or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        match = MARKDOWN_HEADING_PATTERN.match(stripped)
        if not match:
            return False
        return _normalize_heading_label(match.group(1)) == title
    return False


def _looks_like_artifact_line(line: str) -> bool:
    stripped = str(line or "").strip()
    if not stripped:
        return False
    if PRIVATE_USE_PATTERN.search(stripped):
        return True
    if stripped.startswith("#") or stripped.startswith("-") or stripped.startswith("*"):
        return False

    tokens = stripped.split()
    numeric_tokens = sum(1 for token in tokens if re.search(r"\d", token))
    if (
        len(tokens) >= 4
        and len({token.lower() for token in tokens}) <= max(2, len(tokens) // 2)
        and numeric_tokens >= 1
        and not re.search(r"[.!?;:]\s*$", stripped)
    ):
        return True

    if (
        len(tokens) <= 8
        and numeric_tokens >= 2
        and not re.search(r"[.!?;:]\s*$", stripped)
        and not re.search(r"\[\d+\]", stripped)
    ):
        return True

    return False


def _looks_like_artifact_heading(line: str) -> bool:
    match = MARKDOWN_HEADING_PATTERN.match(str(line or "").strip())
    if not match:
        return False
    heading = re.sub(r"\s+", " ", match.group(1)).strip()
    lowered = heading.lower()
    if not heading:
        return True
    if PRIVATE_USE_PATTERN.search(heading):
        return True
    if "area boxes" in lowered:
        return True
    if heading.endswith("•") or heading.endswith("·"):
        return True
    return False


def _has_empty_heading_block(text: str) -> bool:
    lines = str(text or "").splitlines()
    for index, line in enumerate(lines):
        if not MARKDOWN_HEADING_PATTERN.match(line.strip()):
            continue
        next_index = index + 1
        while next_index < len(lines) and not lines[next_index].strip():
            next_index += 1
        if next_index >= len(lines):
            return True
        next_line = lines[next_index].strip()
        if MARKDOWN_HEADING_PATTERN.match(next_line) or re.match(r"^\s*(?:---|\*\*\*|___)\s*$", next_line):
            return True
    return False


def _nearby_numeric_citations(paragraphs: List[str], index: int) -> List[str]:
    citations: List[str] = []
    for neighbor_index in (index - 1, index + 1):
        if neighbor_index < 0 or neighbor_index >= len(paragraphs):
            continue
        for token in sorted(_citation_numbers_in_text(paragraphs[neighbor_index])):
            string_token = str(token)
            if string_token not in citations:
                citations.append(string_token)
    return citations


def _chapter_issues(chapter: Dict[str, Any], start_year: Optional[int], end_year: Optional[int]) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    draft_text = chapter.get("draft_text", "")
    references = chapter.get("references", [])
    paragraphs = _split_paragraphs(draft_text)

    citation_numbers = _citation_numbers_in_text(draft_text)
    chapter_is_well_cited = len(citation_numbers) >= 3 or len(references) >= 3
    local_reference_indices = set()
    for position, ref in enumerate(references, start=1):
            local_reference_indices.add(_reference_index(ref, position))
            normalized_ref_index = _normalize_citation_token(ref.get("index", position))
            if normalized_ref_index.isdigit():
                local_reference_indices.add(int(normalized_ref_index))

    if META_PROMPT_LEAK_PATTERN.search(draft_text):
        issues.append(
            _issue(
                "error",
                "meta_prompt_leakage",
                "The chapter text appears to leak prompt or meta-update framing instead of report prose.",
                hint="Regenerate the chapter with stronger source anchoring or remove the meta framing manually.",
                context=_compact_context(draft_text),
            )
        )

    if _has_duplicate_lead_heading(chapter):
        issues.append(
            _issue(
                "warning",
                "duplicate_lead_heading",
                "The chapter body starts by repeating the chapter title as a heading.",
                hint="Clean Fixable Issues can remove the duplicated heading so the export does not show the same title twice.",
                auto_fixable=True,
                context=str(chapter.get("title", "Untitled Chapter")),
            )
        )

    if any(_looks_like_artifact_line(line) or _looks_like_artifact_heading(line) for line in draft_text.splitlines()):
        issues.append(
            _issue(
                "warning",
                "pdf_artifact_text",
                "The chapter still contains lines that look like PDF extraction or chart/table artifact text.",
                hint="Clean Fixable Issues can remove obvious artifact lines before export.",
                auto_fixable=True,
                context=_compact_context(draft_text),
            )
        )

    if _has_empty_heading_block(draft_text):
        issues.append(
            _issue(
                "warning",
                "empty_heading_block",
                "The chapter contains empty or consecutive markdown headings with no body text between them.",
                hint="Clean Fixable Issues can remove empty heading ladders before export.",
                auto_fixable=True,
                context=_compact_context(draft_text),
            )
        )

    for paragraph_number, paragraph in enumerate(paragraphs, start=1):
        if _is_structural_paragraph(paragraph):
            continue
        if FACTUAL_SIGNAL_PATTERN.search(paragraph) and not _citation_numbers_in_text(paragraph):
            nearby_citations = _nearby_numeric_citations(paragraphs, paragraph_number - 1)
            issues.append(
                _issue(
                    "warning" if chapter_is_well_cited else "error",
                    "unsupported_claim_no_citation",
                    "A factual-looking paragraph appears to be missing an inline citation.",
                    hint=(
                        "Use Clean Fixable Issues to borrow nearby citations for this paragraph, "
                        "or add a specific citation manually if it needs its own source."
                        if nearby_citations
                        else "Add a numeric citation to this paragraph or rewrite it so it does not make a factual claim."
                    ),
                    auto_fixable=bool(nearby_citations),
                    context=_compact_context(paragraph),
                    paragraph_number=paragraph_number,
                )
            )
            break

    missing_reference_numbers = sorted(citation_numbers - local_reference_indices)
    if missing_reference_numbers:
        issues.append(
            _issue(
                "error",
                "citation_reference_mismatch",
                f"Inline citations reference missing chapter sources: {missing_reference_numbers}.",
                hint="Use Clean Fixable Issues to remap stale citation numbers, or regenerate the chapter if the references are actually wrong.",
                auto_fixable=True,
                context=_compact_context(draft_text),
            )
        )

    for ref in references:
        url = ref.get("url")
        if url and not URL_PATTERN.match(str(url)):
            issues.append(
                _issue(
                    "error",
                    "invalid_reference_url",
                    f"Reference URL looks malformed: {url}",
                    hint="Clean Fixable Issues can remove malformed URLs from the bibliography entry.",
                    auto_fixable=True,
                    context=str(ref.get("title", "Untitled reference")),
                )
            )

    if RAW_ORIGINAL_CITATION_PATTERN.search(draft_text):
        issues.append(
            _issue(
                "error",
                "raw_original_citation_token",
                "A raw original-report citation token is still present in the chapter text.",
                hint="Clean Fixable Issues can normalize '[Original Report]' into the report bibliography format.",
                auto_fixable=True,
                context="Original Report",
            )
        )

    raw_visual_match = RAW_VISUAL_TOKEN_PATTERN.search(draft_text)
    if raw_visual_match:
        issues.append(
            _issue(
                "error",
                "raw_visual_token",
                "A raw visual placeholder token is still present in the chapter text.",
                hint="Clean Fixable Issues can remove raw [visual: ...] tokens before export.",
                auto_fixable=True,
                context=raw_visual_match.group(1)[:8],
            )
        )

    approved_visual_ids = _approved_visual_ids(chapter)
    for marker in FIGURE_MARKER_PATTERN.findall(draft_text):
        normalized_marker = _normalize_marker_token(marker)
        if normalized_marker not in approved_visual_ids and normalized_marker[:8] not in approved_visual_ids:
            issues.append(
                _issue(
                    "error",
                    "broken_figure_marker",
                    f"Figure marker {normalized_marker[:8]} does not match any approved visual.",
                    hint="Clean Fixable Issues can remove orphaned figure markers, or you can approve the matching visual.",
                    auto_fixable=True,
                    context=normalized_marker[:32],
                )
            )
            break

    years_in_text = {int(year) for year in re.findall(r"\b(19\d{2}|20\d{2})\b", draft_text)}
    if start_year and years_in_text and max(years_in_text) < start_year:
        issues.append(
            _issue(
                "warning",
                "stale_years_only",
                f"The chapter still only cites years before the update window ({start_year}-{end_year}).",
                hint="Add newer evidence or regenerate the chapter with stronger recent sources.",
            )
        )

    window_years = {year for year in years_in_text if start_year and start_year <= year <= (end_year or year)}
    if start_year and not window_years and not references:
        issues.append(
            _issue(
                "error",
                "no_update_window_evidence",
                f"No citations or year evidence from the selected update window ({start_year}-{end_year}) were detected.",
                hint="Regenerate the chapter or add more recent sources before exporting.",
            )
        )
    elif start_year and not window_years:
        issues.append(
            _issue(
                "warning",
                "weak_update_window_evidence",
                f"No explicit years from the selected update window ({start_year}-{end_year}) were detected in the chapter text.",
                hint="The chapter may still be fine, but adding explicit recent years usually makes the update clearer.",
            )
        )

    return issues


def _normalize_cleanup_citations(chapter: Dict[str, Any]) -> int:
    draft_text = str(chapter.get("draft_text", "") or "")
    references = chapter.get("references", [])
    if not draft_text or not references:
        return 0

    original_index: Optional[int] = None
    valid_numeric_indices: List[int] = []
    for position, ref in enumerate(references, start=1):
        index = _reference_index(ref, position)
        if str(ref.get("category", "")).strip().lower() == "original":
            original_index = index
        else:
            valid_numeric_indices.append(index)

    seen_numeric_tokens: List[str] = []
    for match in re.finditer(r"\[(\d+)\]", draft_text):
        token = str(int(match.group(1)))
        if token not in seen_numeric_tokens:
            seen_numeric_tokens.append(token)

    valid_numeric_set = {str(index) for index in valid_numeric_indices}
    already_valid = [int(token) for token in seen_numeric_tokens if token in valid_numeric_set]
    missing_tokens = [token for token in seen_numeric_tokens if token not in valid_numeric_set]
    available_targets = [index for index in valid_numeric_indices if index not in already_valid]

    citation_map: Dict[str, int] = {}
    if original_index is not None and re.search(r"\[\s*Original(?:\s+Report)?\s*\]", draft_text, re.IGNORECASE):
        citation_map["Original"] = original_index

    for token, target in zip(missing_tokens, available_targets):
        citation_map[token] = target

    if not citation_map:
        return 0

    replacements = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal replacements
        raw_token = match.group(1).strip()
        normalized_token = "Original" if raw_token.lower() in {"original", "original report"} else str(int(raw_token))
        mapped = citation_map.get(normalized_token)
        if mapped is None:
            return match.group(0)
        replacements += 1
        return f"[{mapped}]"

    chapter["draft_text"] = CITATION_PATTERN.sub(replace, draft_text)
    return replacements


def _borrow_nearby_citations(chapter: Dict[str, Any]) -> int:
    draft_text = str(chapter.get("draft_text", "") or "")
    if not draft_text:
        return 0

    paragraphs = _split_paragraphs(draft_text)
    if len(paragraphs) < 2:
        return 0

    fixes = 0
    repaired_paragraphs: List[str] = []
    for index, paragraph in enumerate(paragraphs):
        stripped = paragraph.strip()
        if _is_structural_paragraph(stripped) or _citation_numbers_in_text(stripped) or not FACTUAL_SIGNAL_PATTERN.search(stripped):
            repaired_paragraphs.append(stripped)
            continue

        nearby_citations = _nearby_numeric_citations(paragraphs, index)
        if not nearby_citations:
            repaired_paragraphs.append(stripped)
            continue

        fixes += 1
        borrowed = " ".join(f"[{citation}]" for citation in nearby_citations[:2])
        repaired_paragraphs.append(f"{stripped.rstrip()} {borrowed}".strip())

    if fixes:
        chapter["draft_text"] = "\n\n".join(repaired_paragraphs).strip()
    return fixes


def _remove_broken_figure_markers(chapter: Dict[str, Any]) -> int:
    draft_text = str(chapter.get("draft_text", "") or "")
    if not draft_text:
        return 0

    approved_visual_ids = _approved_visual_ids(chapter)
    removals = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal removals
        marker = _normalize_marker_token(match.group(1))
        if marker in approved_visual_ids or marker[:8] in approved_visual_ids:
            return match.group(0)
        removals += 1
        return ""

    cleaned = FIGURE_MARKER_PATTERN.sub(replace, draft_text)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    chapter["draft_text"] = cleaned
    return removals


def _remove_raw_visual_tokens(chapter: Dict[str, Any]) -> int:
    draft_text = str(chapter.get("draft_text", "") or "")
    if not draft_text:
        return 0

    removals = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal removals
        removals += 1
        return ""

    cleaned = RAW_VISUAL_TOKEN_PATTERN.sub(replace, draft_text)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    chapter["draft_text"] = cleaned
    return removals


def _remove_duplicate_lead_heading(chapter: Dict[str, Any]) -> int:
    draft_text = str(chapter.get("draft_text", "") or "")
    if not draft_text or not _has_duplicate_lead_heading(chapter):
        return 0

    lines = draft_text.splitlines()
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if MARKDOWN_HEADING_PATTERN.match(stripped):
            del lines[index]
            cleaned = "\n".join(lines)
            cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
            chapter["draft_text"] = cleaned
            return 1
        return 0
    return 0


def _remove_artifact_lines(chapter: Dict[str, Any]) -> int:
    draft_text = str(chapter.get("draft_text", "") or "")
    if not draft_text:
        return 0

    removals = 0
    cleaned_lines: List[str] = []
    for line in draft_text.splitlines():
        if _looks_like_artifact_line(line) or _looks_like_artifact_heading(line):
            removals += 1
            continue
        cleaned_lines.append(line.rstrip())

    if removals:
        cleaned = "\n".join(cleaned_lines)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
        chapter["draft_text"] = cleaned
    return removals


def _remove_empty_headings(chapter: Dict[str, Any]) -> int:
    draft_text = str(chapter.get("draft_text", "") or "")
    if not draft_text:
        return 0

    lines = draft_text.splitlines()
    keep_flags = [True] * len(lines)
    removals = 0

    for index, line in enumerate(lines):
        if not MARKDOWN_HEADING_PATTERN.match(line.strip()):
            continue
        next_index = index + 1
        while next_index < len(lines) and not lines[next_index].strip():
            next_index += 1

        if next_index >= len(lines):
            keep_flags[index] = False
            removals += 1
            continue

        next_line = lines[next_index].strip()
        if MARKDOWN_HEADING_PATTERN.match(next_line) or re.match(r"^\s*(?:---|\*\*\*|___)\s*$", next_line):
            keep_flags[index] = False
            removals += 1

    if removals:
        cleaned = "\n".join(line for index, line in enumerate(lines) if keep_flags[index])
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
        chapter["draft_text"] = cleaned

    return removals


def _remove_invalid_reference_urls(chapter: Dict[str, Any]) -> int:
    fixes = 0
    for ref in chapter.get("references", []):
        url = ref.get("url")
        if url and not URL_PATTERN.match(str(url)):
            ref.pop("url", None)
            fixes += 1
    return fixes


def clean_fixable_issues(chapters: List[Dict[str, Any]]) -> Dict[str, Any]:
    details = []
    total_fixes = 0

    for index, chapter in enumerate(chapters, start=1):
        chapter_fixes = {
            "chapter_index": index,
            "chapter_title": chapter.get("title", f"Chapter {index}"),
            "citation_fixes": _normalize_cleanup_citations(chapter),
            "borrowed_citation_fixes": _borrow_nearby_citations(chapter),
            "figure_marker_fixes": _remove_broken_figure_markers(chapter),
            "raw_visual_token_fixes": _remove_raw_visual_tokens(chapter),
            "duplicate_heading_fixes": _remove_duplicate_lead_heading(chapter),
            "artifact_line_fixes": _remove_artifact_lines(chapter),
            "empty_heading_fixes": _remove_empty_headings(chapter),
            "reference_url_fixes": _remove_invalid_reference_urls(chapter),
        }
        chapter_fixes["total_fixes"] = (
            chapter_fixes["citation_fixes"]
            + chapter_fixes["borrowed_citation_fixes"]
            + chapter_fixes["figure_marker_fixes"]
            + chapter_fixes["raw_visual_token_fixes"]
            + chapter_fixes["duplicate_heading_fixes"]
            + chapter_fixes["artifact_line_fixes"]
            + chapter_fixes["empty_heading_fixes"]
            + chapter_fixes["reference_url_fixes"]
        )
        total_fixes += chapter_fixes["total_fixes"]
        details.append(chapter_fixes)

    changed_chapters = sum(1 for item in details if item["total_fixes"] > 0)
    summary = {
        "changed_chapters": changed_chapters,
        "fixes_applied": total_fixes,
    }
    logger.info(
        "Quality cleanup complete. Changed chapters=%s Fixes=%s",
        changed_chapters,
        total_fixes,
    )
    return {
        "summary": summary,
        "chapters": details,
    }


def evaluate_report_quality(chapters: List[Dict[str, Any]], report_metadata: Dict[str, Any]) -> Dict[str, Any]:
    start_year, end_year = _time_window(report_metadata)
    chapter_results = []
    error_count = 0
    warning_count = 0
    by_code: Dict[str, int] = {}
    auto_fixable_count = 0

    for index, chapter in enumerate(chapters, start=1):
        issues = _chapter_issues(chapter, start_year, end_year)
        error_count += sum(1 for issue in issues if issue["severity"] == "error")
        warning_count += sum(1 for issue in issues if issue["severity"] == "warning")
        auto_fixable_count += sum(1 for issue in issues if issue.get("auto_fixable"))
        for issue in issues:
            by_code[issue["code"]] = by_code.get(issue["code"], 0) + 1
        chapter_results.append(
            {
                "chapter_index": index,
                "chapter_title": chapter.get("title", f"Chapter {index}"),
                "issues": issues,
            }
        )

    result = {
        "summary": {
            "error_count": error_count,
            "warning_count": warning_count,
            "blocking": error_count > 0,
            "update_window": f"{start_year}-{end_year}" if start_year else str(end_year),
            "auto_fixable_count": auto_fixable_count,
            "by_code": by_code,
        },
        "chapters": chapter_results,
    }
    for chapter_result in chapter_results:
        issues = chapter_result.get("issues", [])
        if not issues:
            continue
        details = "; ".join(
            f"{issue.get('severity')}:{issue.get('code')}={issue.get('message')}"
            + (f" | paragraph={issue.get('paragraph_number')}" if issue.get("paragraph_number") is not None else "")
            + (f" | context={issue.get('context')}" if issue.get("context") else "")
            for issue in issues
        )
        logger.warning(
            "Quality gate issues for chapter %s (%s): %s",
            chapter_result.get("chapter_index"),
            chapter_result.get("chapter_title"),
            details,
        )
    logger.info(
        "Quality gate complete. Errors=%s Warnings=%s Blocking=%s",
        error_count,
        warning_count,
        result["summary"]["blocking"],
    )
    return result


def has_blocking_issues(result: Dict[str, Any]) -> bool:
    return bool(result.get("summary", {}).get("blocking"))
