import streamlit as st
import os
import sys
import re
import json
import uuid
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# Page Configuration
st.set_page_config(
    page_title="Report Updater v3",
    page_icon="📄",
    layout="wide",
)

# Custom CSS for RTL support
st.markdown("""
<style>
    .rtl-text {
        direction: rtl;
        text-align: right;
    }
    /* Target all text areas to support RTL if they contain Hebrew */
    textarea {
        direction: auto; /* Browser detects direction automatically */
    }
    div[data-testid="stExpander"] div[role="button"] p {
        direction: auto;
    }
</style>
""", unsafe_allow_html=True)
# Add execution directory to path for imports
sys.path.append(os.path.join(os.getcwd(), "execution"))

from logger_config import setup_logger
import time

logger = setup_logger("StreamlitApp")

from parse_pdf import extract_pdf_content
from parse_docx import extract_docx_content
from vision_service import (
    analyze_batch_assets,
    consume_runtime_diagnostics as consume_vision_runtime_diagnostics,
    reset_runtime_diagnostics as reset_vision_runtime_diagnostics,
)
from asset_selection_helpers import (
    asset_selection_widget_key,
    build_asset_to_chapters,
    initialize_asset_selection_state,
    selected_asset_ids_from_widget_state,
)
from translator import translate_texts_batch
from chapter_analyzer import analyze_chapters_batch
from report_metadata_analyzer import infer_report_metadata
from report_context import build_chapter_blueprint_defaults, build_prior_chapter_context
from graph_question_discovery import (
    discover_graphable_questions,
    evaluate_graphable_question_candidates,
)
from graph_update_helpers import (
    GRAPH_UPDATE_STATUS_INVALID,
    GRAPH_UPDATE_STATUS_NO_NEW_DATA,
    GRAPH_UPDATE_STATUS_UPDATED,
    asset_has_update_plan,
    asset_requires_chart_refresh,
    graph_update_required_years,
    inject_prepared_source_graph_updates,
    merge_graph_update_references,
    normalize_chart_series,
    preferred_extracted_data_points,
    prepare_source_graph_refresh,
    unresolved_source_chart_updates,
)
from graph_ranking import build_ranked_graph_candidate_groups
from visual_pipeline_helpers import (
    build_figure_marker,
    place_marker_near_relevant_paragraph,
    resolve_visual_for_export,
)
from llm_client import (
    get_api_key,
    get_provider,
    provider_display_name,
    required_api_key_env,
    selected_provider_model,
)
from llm_pricing import format_cost
from llm_usage import export_usage_reports, get_usage_rows, reset_usage, summarize_usage
from report_change_summary import (
    build_report_change_payload,
    compute_report_change_signature,
    generate_ai_report_change_summary,
    selected_change_summary_model,
)

# State Machine Constants
STATE_UPLOAD_EXTRACT = "UPLOAD_AND_EXTRACT"
STATE_ASSET_SELECTION = "ASSET_SELECTION"
STATE_SOURCE_VISUAL_PLANNING = "SOURCE_VISUAL_PLANNING"
STATE_RESEARCH_PLANNING = "RESEARCH_PLANNING"
STATE_DRAFT_GENERATION = "DRAFT_GENERATION"
STATE_DRAFT_VERIFICATON = "DRAFT_VERIFICATION"
STATE_FINAL_ASSEMBLY = "FINAL_ASSEMBLY"

STATE_SEQUENCE = [
    STATE_UPLOAD_EXTRACT,
    STATE_ASSET_SELECTION,
    STATE_SOURCE_VISUAL_PLANNING,
    STATE_RESEARCH_PLANNING,
    STATE_DRAFT_GENERATION,
    STATE_DRAFT_VERIFICATON,
    STATE_FINAL_ASSEMBLY,
]

STATE_DISPLAY_NAMES = {
    STATE_UPLOAD_EXTRACT: "1. Upload Source Report",
    STATE_ASSET_SELECTION: "2. Keep Source Visuals",
    STATE_SOURCE_VISUAL_PLANNING: "3. Plan Source Visual Updates",
    STATE_RESEARCH_PLANNING: "4. Research Planning",
    STATE_DRAFT_GENERATION: "5. Draft Generation",
    STATE_DRAFT_VERIFICATON: "6. Draft Review & Visual Approval",
    STATE_FINAL_ASSEMBLY: "7. Final Assembly",
}

# Initialize Session State
if "current_state" not in st.session_state:
    logger.info("New session started.")
    st.session_state.current_state = STATE_UPLOAD_EXTRACT
    st.session_state.start_time = time.time()

if "chapters" not in st.session_state:
    st.session_state.chapters = []

if "assets" not in st.session_state:
    st.session_state.assets = []

if "selected_asset_ids" not in st.session_state:
    st.session_state.selected_asset_ids = []

if "original_report_name" not in st.session_state:
    st.session_state.original_report_name = None

if "report_metadata" not in st.session_state:
    today = datetime.now().date()
    st.session_state.report_metadata = {
        "original_report_date": today,
        "update_start_date": today,
        "update_end_date": today,
        "output_language": "Match Source Language",
        "target_audience": "General professional audience",
        "edition_title": "",
        "preserve_original_voice": True,
    }

if "report_date_inference" not in st.session_state:
    st.session_state.report_date_inference = {}

if "global_reference_map" not in st.session_state:
    st.session_state.global_reference_map = {}

if "quality_gate_result" not in st.session_state:
    st.session_state.quality_gate_result = None

if "last_cleanup_result" not in st.session_state:
    st.session_state.last_cleanup_result = None

if "allow_finalize_with_gate_errors" not in st.session_state:
    st.session_state.allow_finalize_with_gate_errors = False

if "final_assembly_error" not in st.session_state:
    st.session_state.final_assembly_error = None

if "final_assembly_warnings" not in st.session_state:
    st.session_state.final_assembly_warnings = []

if "debug_mode" not in st.session_state:
    st.session_state.debug_mode = True

if "ui_notices" not in st.session_state:
    st.session_state.ui_notices = []

if "llm_provider" not in st.session_state:
    st.session_state.llm_provider = get_provider()

if "llm_usage_artifacts" not in st.session_state:
    st.session_state.llm_usage_artifacts = {}

if "change_summary_result" not in st.session_state:
    st.session_state.change_summary_result = None

if "change_summary_signature" not in st.session_state:
    st.session_state.change_summary_signature = None

if "change_summary_error" not in st.session_state:
    st.session_state.change_summary_error = None

os.environ["LLM_PROVIDER"] = st.session_state.llm_provider

# --- Sidebar ---
st.sidebar.title("Navigation")
st.sidebar.info(
    f"Current Step: {STATE_DISPLAY_NAMES.get(st.session_state.current_state, st.session_state.current_state)}"
)
st.sidebar.divider()
st.sidebar.subheader("LLM Settings")
provider_options = ["gemini", "openai"]
current_provider = st.session_state.get("llm_provider", get_provider())
if current_provider not in provider_options:
    current_provider = "gemini"
provider_choice = st.sidebar.selectbox(
    "Provider",
    provider_options,
    index=provider_options.index(current_provider),
    format_func=lambda value: "OpenAI" if value == "openai" else "Gemini",
)
st.session_state.llm_provider = provider_choice
os.environ["LLM_PROVIDER"] = provider_choice
st.sidebar.caption(f"Model: {selected_provider_model()}")
key_env_name = required_api_key_env()
if get_api_key():
    st.sidebar.success(f"{key_env_name} loaded")
else:
    st.sidebar.warning(f"{key_env_name} missing")

if st.session_state.debug_mode:
    st.sidebar.divider()
    st.sidebar.subheader("Debug Controls")
    if st.sidebar.button("Reset State"):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()
    
    # State Jumper
    state_selection = st.sidebar.selectbox(
        "Jump to State",
        STATE_SEQUENCE,
        format_func=lambda state: STATE_DISPLAY_NAMES.get(state, state),
    )
    if st.sidebar.button("Jump"):
        st.session_state.current_state = state_selection
        st.rerun()

@st.dialog("API Key Required")
def ask_for_api_key():
    key_env = required_api_key_env()
    provider_name = provider_display_name()
    st.warning(f"{key_env} is not set. Please enter your {provider_name} API key to continue.")
    api_key = st.text_input(f"{provider_name} API Key", type="password")
    if st.button("Save"):
        if api_key.strip():
            os.environ[key_env] = api_key.strip()
            st.rerun()
        else:
            st.error("Please enter a valid API Key.")


def _coerce_date(value, fallback=None):
    fallback = fallback or datetime.now().date()
    if value is None:
        return fallback
    if isinstance(value, datetime):
        return value.date()
    if hasattr(value, "year") and hasattr(value, "month") and hasattr(value, "day") and not isinstance(value, str):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value).date()
        except ValueError:
            match = re.search(r'(\d{4}-\d{2}-\d{2})', value)
            if match:
                return datetime.fromisoformat(match.group(1)).date()
    return fallback


def _get_report_metadata():
    stored = st.session_state.get("report_metadata", {})
    today = datetime.now().date()
    return {
        "original_report_date": _coerce_date(stored.get("original_report_date"), today),
        "update_start_date": _coerce_date(stored.get("update_start_date"), today),
        "update_end_date": _coerce_date(stored.get("update_end_date"), today),
        "output_language": stored.get("output_language", "Match Source Language"),
        "target_audience": stored.get("target_audience", "General professional audience"),
        "edition_title": stored.get("edition_title", ""),
        "preserve_original_voice": bool(stored.get("preserve_original_voice", True)),
    }


def _serialize_report_metadata(metadata):
    return {
        "original_report_date": metadata["original_report_date"].isoformat(),
        "update_start_date": metadata["update_start_date"].isoformat(),
        "update_end_date": metadata["update_end_date"].isoformat(),
        "output_language": metadata.get("output_language", "Match Source Language"),
        "target_audience": metadata.get("target_audience", "General professional audience"),
        "edition_title": metadata.get("edition_title", ""),
        "preserve_original_voice": bool(metadata.get("preserve_original_voice", True)),
    }


def _queue_ui_notice(level: str, message: str, source: str = "general") -> None:
    normalized = re.sub(r"\s+", " ", str(message or "")).strip()
    if not normalized:
        return

    notice = {"level": level, "message": normalized, "source": source}
    notices = st.session_state.setdefault("ui_notices", [])
    if notice not in notices:
        notices.append(notice)
        if len(notices) > 10:
            del notices[:-10]


def _clear_ui_notices(source: str | None = None) -> None:
    notices = st.session_state.setdefault("ui_notices", [])
    if source is None:
        notices.clear()
        return
    st.session_state.ui_notices = [notice for notice in notices if notice.get("source") != source]


def _render_ui_notices() -> None:
    for notice in st.session_state.get("ui_notices", []):
        level = notice.get("level", "info")
        message = notice.get("message", "")
        if level == "error":
            st.error(message)
        elif level == "warning":
            st.warning(message)
        else:
            st.info(message)


def _queue_runtime_diagnostics(diagnostics, source: str, context_label: str = "") -> None:
    for diagnostic in diagnostics or []:
        message = diagnostic.get("message", "")
        if context_label:
            message = f"{context_label}: {message}"
        _queue_ui_notice(diagnostic.get("level", "info"), message, source=source)


def _format_update_window(metadata):
    return f"{metadata['update_start_date'].isoformat()} to {metadata['update_end_date'].isoformat()}"


def _selected_asset_id_set():
    return {str(asset_id) for asset_id in st.session_state.get("selected_asset_ids", [])}


def _selected_source_assets():
    selected_ids = _selected_asset_id_set()
    return [asset for asset in st.session_state.get("assets", []) if str(asset.get("id")) in selected_ids]


def _selected_assets_for_chapter(chapter):
    selected_ids = _selected_asset_id_set()
    chapter_asset_ids = {str(asset_id) for asset_id in chapter.get("asset_ids", []) or []}
    return [
        asset
        for asset in st.session_state.get("assets", [])
        if str(asset.get("id")) in selected_ids and str(asset.get("id")) in chapter_asset_ids
    ]


def _selected_updateable_assets():
    return [
        asset
        for asset in _selected_source_assets()
        if str(asset.get("type", "")).lower() in {"chart", "graph", "table"}
    ]


def _selected_retained_source_assets_for_chapter(chapter):
    return [
        asset
        for asset in _selected_assets_for_chapter(chapter)
        if not asset_has_update_plan(asset)
        or str(asset.get("graph_update_status", "")).strip().lower() == GRAPH_UPDATE_STATUS_NO_NEW_DATA
    ]


def _format_unresolved_chart_update_message(failures):
    snippets = []
    for failure in failures[:3]:
        chapter_title = failure.get("chapter_title", "Untitled Chapter")
        asset_id = str(failure.get("asset_id", ""))[:8] or "unknown"
        short_caption = failure.get("short_caption", "Source chart")
        snippets.append(f"{chapter_title}: Figure {asset_id} ({short_caption})")
    suffix = f" Affected charts: {' | '.join(snippets)}." if snippets else ""
    return (
        "Final assembly is blocked because one or more source charts were marked "
        "'Refresh with updated data' but no approved replacement graph is ready for export. "
        "Review the graph selections in step 6 or change the source-visual plan in step 3."
        + suffix
    )


def _default_asset_update_query(asset, report_metadata):
    fallback_year = report_metadata["update_end_date"].year
    if asset.get("update_query"):
        return asset["update_query"]
    if str(asset.get("type", "")).lower() == "table":
        return f"{asset.get('short_caption') or 'table'} data {fallback_year}"
    return f"{asset.get('short_caption') or 'chart'} statistics {fallback_year}"


_ASSET_MARKER_PATTERN = re.compile(r"\[Asset:\s*([A-Za-z0-9_-]{4,64})\s*\]", re.IGNORECASE)
_GRAPH_CONTEXT_TOKEN_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9%/-]{2,}")
_GRAPH_CONTEXT_STOPWORDS = {
    "about", "after", "also", "annual", "area", "areas", "asset", "based", "below", "between",
    "both", "chart", "count", "data", "field", "figure", "from", "graph", "into", "main",
    "original", "recent", "report", "series", "share", "shows", "showing", "source", "technology",
    "that", "their", "there", "these", "this", "through", "time", "total", "updated", "using",
    "value", "values", "with", "year", "years",
}


def _clean_source_context_text(text, max_chars=500):
    cleaned = str(text or "")
    cleaned = _ASSET_MARKER_PATTERN.sub(" ", cleaned)
    cleaned = VISUAL_MARKER_PATTERN.sub(" ", cleaned)
    cleaned = RAW_VISUAL_TOKEN_PATTERN.sub(" ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 1].rstrip() + "…"


def _extract_asset_context_from_chapter_text(text, asset, *, max_chars=500):
    source_text = str(text or "").strip()
    if not source_text:
        return ""

    short_id = str(asset.get("id") or "")[:8]
    marker_candidates = [
        f"[Asset: {short_id}]",
        f"Figure {short_id}",
        f"Asset: {short_id}",
    ]
    paragraphs = [block.strip() for block in re.split(r"\n\s*\n", source_text) if block.strip()]
    target_index = None
    for index, paragraph in enumerate(paragraphs):
        if any(candidate in paragraph for candidate in marker_candidates):
            target_index = index
            break

    if target_index is None:
        for index, paragraph in enumerate(paragraphs):
            if short_id and short_id in paragraph:
                target_index = index
                break

    if target_index is None:
        for index, paragraph in enumerate(paragraphs):
            cleaned = _clean_source_context_text(paragraph, max_chars=max_chars)
            if len(cleaned.split()) >= 6:
                target_index = index
                break

    if target_index is None:
        return ""

    window_start = max(0, target_index - 1)
    window_end = min(len(paragraphs), target_index + 2)
    excerpt_parts = []
    for index in range(window_start, window_end):
        cleaned = _clean_source_context_text(paragraphs[index], max_chars=max_chars)
        if cleaned and cleaned not in excerpt_parts:
            excerpt_parts.append(cleaned)
    return _clean_source_context_text(" ".join(excerpt_parts), max_chars=max_chars)


def _asset_context_fallback_for_chapter(chapter, asset):
    original_text = chapter.get("original_full_text") or chapter.get("content") or ""
    marker_excerpt = _extract_asset_context_from_chapter_text(original_text, asset, max_chars=500)
    if marker_excerpt:
        return marker_excerpt
    return _clean_source_context_text(original_text, max_chars=500)


def _asset_context_heading_for_chapter(chapter):
    blueprint = chapter.get("blueprint") or {}
    return (
        str(blueprint.get("source_chapter_title") or "").strip()
        or str(chapter.get("source_title") or "").strip()
        or str(chapter.get("title") or "").strip()
    )


def _attach_source_context_to_asset_for_chapter(asset, chapter):
    if not isinstance(asset, dict):
        return asset
    asset["source_context_fallback"] = _asset_context_fallback_for_chapter(chapter, asset)
    asset["source_context_chapter_title"] = _asset_context_heading_for_chapter(chapter)
    if not asset.get("source_context_heading"):
        asset["source_context_heading"] = asset["source_context_chapter_title"]
    return asset


def _graph_context_query_seed(asset, *, limit=8):
    seed_parts = []
    heading = " ".join(str(asset.get("source_context_heading") or "").split()).strip()
    if heading:
        seed_parts.append(heading)

    seen_tokens = set()
    excerpt_pool = " ".join(
        str(asset.get(key) or "").strip()
        for key in ("source_context_excerpt", "source_context_fallback")
    )
    for token in _GRAPH_CONTEXT_TOKEN_PATTERN.findall(excerpt_pool):
        normalized = token.lower()
        if normalized in _GRAPH_CONTEXT_STOPWORDS or normalized in seen_tokens:
            continue
        seen_tokens.add(normalized)
        seed_parts.append(token)
        if len(seen_tokens) >= limit:
            break

    return " ".join(seed_parts[: limit + 1]).strip()


def _clear_graph_refresh_state(asset):
    if not isinstance(asset, dict):
        return
    for key in (
        "graph_update_status",
        "prepared_update_visual",
        "update_reason",
        "required_years",
        "graph_update_validation_errors",
        "graph_update_research_findings",
        "graph_update_references",
    ):
        asset.pop(key, None)


def _graph_refresh_research_topic(asset, update_end_date):
    base_query = " ".join(
        str(asset.get("update_query") or asset.get("short_caption") or asset.get("description") or "chart").split()
    ).strip()
    extracted_data_points = preferred_extracted_data_points(asset)
    required_years = graph_update_required_years(extracted_data_points, update_end_date)
    normalized = normalize_chart_series(extracted_data_points)
    unit = normalized[2] if normalized else ""
    context_seed = _graph_context_query_seed(asset)

    suffix_parts = []
    if context_seed and context_seed.lower() not in base_query.lower():
        suffix_parts.append(context_seed)
    if required_years:
        suffix_parts.append(" ".join(str(year) for year in required_years))
    if unit:
        suffix_parts.append(unit)

    suffix = " ".join(part for part in suffix_parts if part).strip()
    if suffix and suffix.lower() not in base_query.lower():
        return f"{base_query} {suffix}".strip()
    return base_query


def _current_visual_plan_mode(asset):
    if str(asset.get("type", "")).lower() == "table":
        if asset.get("convert_to_text"):
            return "Convert to editable table"
        if asset.get("do_update"):
            return "Refresh with updated data"
        return "Keep original"
    return "Refresh with updated data" if asset.get("do_update") else "Keep original"


def _validate_report_metadata(metadata):
    errors = []
    if metadata["update_start_date"] < metadata["original_report_date"]:
        errors.append("Update start date must be on or after the original report date.")
    if metadata["update_end_date"] < metadata["update_start_date"]:
        errors.append("Update end date must be on or after the update start date.")
    return errors


def _approved_visual_short_ids(chapter):
    ids = set()
    for visual in chapter.get("approved_visuals", []):
        ids.update(_visual_marker_keys(visual))
    return ids


VISUAL_MARKER_PATTERN = re.compile(
    r"\[(?:Figure|Asset|Image|Figura|איור|תמונה)(?:\s+ID)?\s*:?\s*([A-Za-z0-9][A-Za-z0-9_-]{3,63})[:\s]*.*?\]",
    re.IGNORECASE,
)
RAW_VISUAL_TOKEN_PATTERN = re.compile(
    r"\[\s*visual\s*:\s*([A-Za-z0-9][A-Za-z0-9_-]{3,63})[^\]]*\]",
    re.IGNORECASE,
)


def _normalize_marker_token(value) -> str:
    token = str(value or "").strip().lower()
    if not token:
        return ""
    return re.sub(r"[^a-z0-9_-]", "", token)


def _visual_marker_keys(visual) -> set[str]:
    keys = set()
    for key in ("marker_id", "id", "original_asset_id"):
        normalized = _normalize_marker_token(visual.get(key))
        if not normalized:
            continue
        keys.add(normalized)
        if len(normalized) > 8:
            keys.add(normalized[:8])
    return keys


def _canonical_visual_marker_id(visual) -> str:
    original_asset_id = _normalize_marker_token(visual.get("original_asset_id"))
    if original_asset_id:
        return original_asset_id

    explicit_marker_id = _normalize_marker_token(visual.get("marker_id"))
    if explicit_marker_id:
        return explicit_marker_id

    normalized_visual_id = _normalize_marker_token(visual.get("id"))
    if len(normalized_visual_id) >= 12:
        return normalized_visual_id
    if normalized_visual_id and not visual.get("original_asset_id"):
        return uuid.uuid4().hex
    return normalized_visual_id or uuid.uuid4().hex


def _apply_visual_resolution_metadata(visual, result):
    if not isinstance(visual, dict) or not isinstance(result, dict):
        return

    visual["path"] = result["path"]
    for key in (
        "url",
        "source_url",
        "source",
        "provider",
        "query",
        "selection_reason",
        "content_hash",
        "mime_type",
        "width",
        "height",
        "aspect_ratio",
        "filename",
        "thumbnail",
        "photographer_name",
        "photographer_url",
        "license_label",
        "attribution_text",
    ):
        value = result.get(key)
        if value not in (None, ""):
            visual[key] = value


def _rewrite_visual_markers(text: str, marker_ids: set[str], canonical_marker_id: str, caption: str) -> tuple[str, int]:
    if not text or not marker_ids or not canonical_marker_id:
        return text, 0

    replacements = 0
    canonical_marker = build_figure_marker(canonical_marker_id, caption)

    def replace(match):
        nonlocal replacements
        marker_id = _normalize_marker_token(match.group(1))
        if marker_id in marker_ids or marker_id[:8] in marker_ids:
            replacements += 1
            return canonical_marker
        return match.group(0)

    return VISUAL_MARKER_PATTERN.sub(replace, text), replacements


def _visual_short_id(visual):
    marker_id = _canonical_visual_marker_id(visual)
    return marker_id[:8].lower()


def _ensure_source_asset_marker(text: str, asset: dict) -> str:
    asset_id = _normalize_marker_token(asset.get("id"))
    if not asset_id:
        return text

    for marker in VISUAL_MARKER_PATTERN.findall(text or ""):
        normalized_marker = _normalize_marker_token(marker)
        if normalized_marker == asset_id or normalized_marker[:8] == asset_id[:8]:
            return text

    caption = asset.get("short_caption") or asset.get("title") or "Source Figure"
    marker = build_figure_marker(asset.get("id"), caption)
    if not str(text or "").strip():
        return marker
    return f"{str(text).rstrip()}\n\n{marker}\n"


def _strip_unapproved_visual_markers(text: str, approved_visual_ids):
    def replace_marker(match):
        marker_id = _normalize_marker_token(match.group(1))
        return match.group(0) if marker_id in approved_visual_ids or marker_id[:8] in approved_visual_ids else ""

    cleaned = VISUAL_MARKER_PATTERN.sub(replace_marker, text or "")
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()

def _strip_export_visual_tokens(text: str, approved_visual_ids):
    cleaned = _strip_unapproved_visual_markers(text, approved_visual_ids)
    cleaned = RAW_VISUAL_TOKEN_PATTERN.sub("", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


_SKIP_GRAPH_OPTION = "__skip_graph__"


def _graph_selection_key(chapter_index, slot_id):
    return f"graph_pick_{chapter_index}_{slot_id}"


def _graph_selection_options(group):
    return [_SKIP_GRAPH_OPTION] + [candidate["id"] for candidate in group.get("shortlist", [])]


def _graph_default_selection(group):
    auto_selected = group.get("auto_select_candidate_id")
    return auto_selected or _SKIP_GRAPH_OPTION


def _find_graph_candidate(group, candidate_id):
    for candidate in group.get("candidates", []):
        if candidate.get("id") == candidate_id:
            return candidate
    return None


def _graph_option_label(group, option_id):
    if option_id == _SKIP_GRAPH_OPTION:
        if group.get("selection_mode") == "review":
            return "Skip for now (top candidate is below threshold)"
        if group.get("selection_mode") == "skip":
            return "Skip (no safe candidate)"
        return "Do not include a graph"

    candidate = _find_graph_candidate(group, option_id) or {}
    scorecard = candidate.get("scorecard", {})
    return (
        f"#{candidate.get('rank', '?')} {candidate.get('variant_label', 'Graph')} "
        f"| {scorecard.get('quality_band', 'Unscored')} "
        f"| {scorecard.get('overall_score', 0.0):.2f}"
    )


def _ensure_graph_candidate_preview(candidate):
    preview_path = candidate.get("preview_path") or candidate.get("path")
    if preview_path and os.path.exists(preview_path):
        return preview_path
    if candidate.get("blocked"):
        return None
    if candidate.get("preview_error"):
        return None

    preview_result = generate_graph(candidate, output_dir=os.path.join(".tmp", "graph_candidate_previews"))
    if "path" in preview_result:
        candidate["preview_path"] = preview_result["path"]
        return preview_result["path"]

    candidate["preview_error"] = preview_result.get("error", "Preview generation failed")
    return None


def render_report_metadata_editor(key_prefix: str):
    metadata = _get_report_metadata()
    inference = st.session_state.get("report_date_inference") or {}

    st.markdown("##### Edition Update Settings")
    if inference.get("original_report_date"):
        source_excerpt = inference.get("source_excerpt", "")
        st.caption(
            f"Auto-detected from report text: {inference['original_report_date']} "
            f"({inference.get('confidence', 'unknown')} confidence). {source_excerpt}"
        )
    else:
        st.caption("If left unchanged, the original report date and update start date will be inferred from the report text during extraction when possible.")
    col1, col2, col3 = st.columns(3)
    with col1:
        metadata["original_report_date"] = st.date_input("Original Report Date", value=metadata["original_report_date"], key=f"{key_prefix}_original_report_date")
    with col2:
        metadata["update_start_date"] = st.date_input("Update Start Date", value=metadata["update_start_date"], key=f"{key_prefix}_update_start_date")
    with col3:
        metadata["update_end_date"] = st.date_input("Update Through Date", value=metadata["update_end_date"], key=f"{key_prefix}_update_end_date")

    metadata["output_language"] = st.selectbox(
        "Output Language",
        ["Match Source Language", "English", "Hebrew"],
        index=["Match Source Language", "English", "Hebrew"].index(metadata.get("output_language", "Match Source Language")),
        key=f"{key_prefix}_output_language",
    )
    metadata["target_audience"] = st.text_input("Target Audience", value=metadata.get("target_audience", "General professional audience"), key=f"{key_prefix}_target_audience", placeholder="e.g. policymakers, executives, technical leaders")
    metadata["edition_title"] = st.text_input("Edition Title", value=metadata.get("edition_title", ""), key=f"{key_prefix}_edition_title", placeholder="Optional custom title for the updated edition")
    metadata["preserve_original_voice"] = st.checkbox("Preserve original voice and structure where possible", value=bool(metadata.get("preserve_original_voice", True)), key=f"{key_prefix}_preserve_original_voice")

    st.session_state.report_metadata = metadata
    return metadata

# --- Main Logic ---
def main():
    st.title("Report Updater v3 (Horizon/Elisha)")
    st.caption(
        "Workflow: Upload source report -> Keep source visuals -> Plan source visual updates -> "
        "Research planning -> Draft generation -> Review and approve visuals -> Final export"
    )
    _render_ui_notices()
    
    if not get_api_key():
        ask_for_api_key()
        st.stop()
    
    current_state = st.session_state.current_state
    logger.debug(f"Rendering main page - Current State: {current_state}")
    
    if current_state == STATE_UPLOAD_EXTRACT:
        render_upload_extract()
    elif current_state == STATE_ASSET_SELECTION:
        render_asset_selection()
    elif current_state == STATE_SOURCE_VISUAL_PLANNING:
        render_source_visual_planning()
    elif current_state == STATE_RESEARCH_PLANNING:
        render_research_planning()
    elif current_state == STATE_DRAFT_GENERATION:
        render_draft_generation()
    elif current_state == STATE_DRAFT_VERIFICATON:
        render_draft_verification()
    elif current_state == STATE_FINAL_ASSEMBLY:
        render_final_assembly()
    else:
        logger.error(f"Unknown State reached: {current_state}")
        st.error(f"Unknown State: {current_state}")

# --- Render Functions (Placeholders) ---


def render_upload_extract():
    st.header("1. Upload Source Report")
    st.write("Upload a source PDF or DOCX. We will extract chapters, visuals, and baseline metadata after you confirm.")
    st.caption("Report-wide dates, language, audience, and voice settings are configured later in Research Planning.")

    uploaded_file = st.file_uploader("Source Document", type=["pdf", "docx"])

    if uploaded_file:
        if not os.path.exists(".tmp"):
            os.makedirs(".tmp")
        temp_path = os.path.join(".tmp", uploaded_file.name)
        with open(temp_path, "wb") as f:
            f.write(uploaded_file.getbuffer())

        if st.button("Extract Chapters & Visuals", type="primary"):
            _clear_ui_notices()
            reset_usage()
            st.session_state.llm_usage_artifacts = {}
            st.session_state.llm_usage_export_base = None
            logger.info(f"User clicked 'Extract Chapters & Visuals' for file: {uploaded_file.name}")
            with st.spinner("Extracting text and media..."):
                report_metadata = _get_report_metadata()
                st.session_state.change_summary_result = None
                st.session_state.change_summary_signature = None
                st.session_state.change_summary_error = None
                if uploaded_file.name.endswith(".pdf"):
                    results = extract_pdf_content(temp_path)
                else:
                    results = extract_docx_content(temp_path)

                original_name = os.path.splitext(uploaded_file.name)[0]
                st.session_state.original_report_name = original_name
                inferred_report_metadata = infer_report_metadata(original_name, results.get("chapters", []))
                st.session_state.report_date_inference = inferred_report_metadata

                inferred_original_date = None
                raw_inferred_date = inferred_report_metadata.get("original_report_date")
                if raw_inferred_date:
                    try:
                        inferred_original_date = datetime.fromisoformat(raw_inferred_date).date()
                    except ValueError:
                        logger.warning("Unable to parse inferred report date '%s'.", raw_inferred_date)

                today = datetime.now().date()
                if inferred_original_date:
                    if report_metadata.get("original_report_date") == today:
                        report_metadata["original_report_date"] = inferred_original_date
                    if report_metadata.get("update_start_date") == today:
                        report_metadata["update_start_date"] = inferred_original_date

                if not report_metadata.get("edition_title"):
                    report_metadata["edition_title"] = f"{original_name} Updated Edition"
                st.session_state.report_metadata = report_metadata

                toc_patterns = [
                    "table of contents", "contents", "תוכן עניינים",
                    "תוכן", "toc", "índice", "inhaltsverzeichnis"
                ]

                st.session_state.chapters = []
                status = st.empty()
                progress = st.progress(0)
                chapters_to_process = []

                for ch in results["chapters"]:
                    if ch['title'].strip().lower() in toc_patterns:
                        logger.info(f"Skipping ToC chapter: '{ch['title']}'")
                        continue

                    ch['id'] = str(uuid.uuid4())
                    chapters_to_process.append(ch)

                total_ch = len(chapters_to_process)
                analysis_by_id = {}
                if chapters_to_process:
                    status.text(f"Analyzing {total_ch} chapter(s) with {provider_display_name()}...")
                    analysis_by_id = analyze_chapters_batch(chapters_to_process)

                for i, ch in enumerate(chapters_to_process):
                    status.text(f"Applying analysis {i+1}/{total_ch}: {ch['title'][:30]}...")
                    analysis = analysis_by_id.get(ch['id'], {})

                    ch['original_full_text'] = ch['content']
                    ch['original_word_count'] = len(ch['content'].split())
                    ch['baseline'] = analysis
                    ch['content'] = analysis.get('summary', ch['content'][:500] + "...")
                    ch['extracted_keywords'] = analysis.get('keywords', [])

                    st.session_state.chapters.append(ch)
                    progress.progress((i + 1) / total_ch)

                status.empty()
                progress.empty()

                st.session_state.assets = results["assets"]
                logger.info(f"Extraction & Analysis complete. Chapters: {len(st.session_state.chapters)}, Assets: {len(st.session_state.assets)}")
                st.session_state.current_state = STATE_ASSET_SELECTION
                st.rerun()

def _render_asset_selection_legacy():
    st.header("2. Source Asset Selection")
    st.write("Review the images extracted from the report. Select those you want to include in the new version.")
    
    if not st.session_state.assets:
        st.info("No images detected in the document.")
        if st.button("Continue to Planning"):
            st.session_state.current_state = STATE_RESEARCH_PLANNING
            st.rerun()
        return

    # Create mappings for lookup
    asset_map = {a['id']: a for a in st.session_state.assets}
    asset_to_chapters = {}
    for c_idx, chapter in enumerate(st.session_state.chapters):
        for a_id in chapter.get('asset_ids', []):
            if a_id not in asset_to_chapters:
                asset_to_chapters[a_id] = []
            asset_to_chapters[a_id].append(f"Chapter {c_idx+1}")

    displayed_asset_ids = set()

    # Callback for synchronization
    def on_asset_toggle(a_id):
        # The key logic handles the check, we just need to update the central list
        # Since multiple checkboxes might represent the same a_id, we use a central list
        pass # The state is updated in the loop based on the checkbox key usually, 
             # but here we'll handle it manually to be safe.

    # 1. Grouped by Chapter
    for c_idx, chapter in enumerate(st.session_state.chapters):
        asset_ids = chapter.get('asset_ids', [])
        if asset_ids:
            st.divider()
            st.subheader(f"Chapter {c_idx+1}: {chapter['title']}")
            
            cols = st.columns(3)
            for a_idx, a_id in enumerate(asset_ids):
                if a_id in asset_map:
                    asset = asset_map[a_id]
                    displayed_asset_ids.add(a_id)
                    with cols[a_idx % 3]:
                        st.image(asset["path"], caption=f"ID: {a_id[:8]}")
                        
                        # Note for repeated assets
                        other_chapters = [ch for ch in asset_to_chapters.get(a_id, []) if ch != f"Chapter {c_idx+1}"]
                        if other_chapters:
                            st.info(f"🔄 Also in: {', '.join(other_chapters)}", icon="ℹ️")

                        # Sync logic
                        is_selected = st.checkbox(
                            f"Include {a_id[:8]}", 
                            value=(a_id in st.session_state.selected_asset_ids),
                            key=f"select_ch_{c_idx}_{a_id}"
                        )
                        
                        # Trigger rerun on change to update all instances
                        if is_selected and a_id not in st.session_state.selected_asset_ids:
                            st.session_state.selected_asset_ids.append(a_id)
                            st.rerun()
                        elif not is_selected and a_id in st.session_state.selected_asset_ids:
                            st.session_state.selected_asset_ids.remove(a_id)
                            st.rerun()

    # 2. Unassigned Assets
    unassigned_ids = [a['id'] for a in st.session_state.assets if a['id'] not in displayed_asset_ids]
    if unassigned_ids:
        st.divider()
        st.subheader("📍 Unassigned Assets")
        st.write("Images that couldn't be definitively linked to a specific chapter.")
        cols = st.columns(3)
        for u_idx, a_id in enumerate(unassigned_ids):
            asset = asset_map[a_id]
            with cols[u_idx % 3]:
                st.image(asset["path"], caption=f"ID: {a_id[:8]}")
                
                is_selected = st.checkbox(
                    f"Include {a_id[:8]}", 
                    value=(a_id in st.session_state.selected_asset_ids),
                    key=f"select_unassigned_{a_id}"
                )
                if is_selected and a_id not in st.session_state.selected_asset_ids:
                    st.session_state.selected_asset_ids.append(a_id)
                    st.rerun()
                elif not is_selected and a_id in st.session_state.selected_asset_ids:
                    st.session_state.selected_asset_ids.remove(a_id)
                    st.rerun()

    if st.button("Confirm Selection", type="primary"):
        _clear_ui_notices(source="vision")
        logger.info(f"User confirmed asset selection. Count: {len(st.session_state.selected_asset_ids)}")
        # Background: Analyze selected assets in batch
        with st.status(f"Analyzing selected assets with {provider_display_name()} Vision...") as status:
            selected_assets = [a for a in st.session_state.assets if a['id'] in st.session_state.selected_asset_ids]
            
            if selected_assets:
                status.update(label="Sending assets to Vision API (this may take a moment)...")
                logger.info(f"Triggering analyze_batch_assets for {len(selected_assets)} assets.")
                v_start_time = time.time()
                # Perform batch analysis
                reset_vision_runtime_diagnostics()
                analysis_results = analyze_batch_assets(selected_assets)
                _queue_runtime_diagnostics(
                    consume_vision_runtime_diagnostics(),
                    source="vision",
                    context_label="Source asset analysis",
                )
                v_latency = time.time() - v_start_time
                logger.info(f"Vision analysis complete in {v_latency:.2f}s. Results count: {len(analysis_results)}")
                unique_result_ids = {str(item.get("id", "")) for item in analysis_results if item.get("id")}
                if unique_result_ids and len(unique_result_ids) != len(selected_assets):
                    _queue_ui_notice(
                        "warning",
                        "Source asset analysis returned an unexpected number of results. Some captions or update suggestions may need a manual check.",
                        source="vision",
                    )
                
                # Map results back to assets
                result_map = {r['id']: r for r in analysis_results}
                
                for asset in st.session_state.assets:
                    if asset['id'] in result_map:
                        res = result_map[asset['id']]
                        asset['analysis'] = res # Store full analysis
                        asset['short_caption'] = res.get('short_caption', 'Image')
                        asset['description'] = res.get('dataset_description', '')
                        asset['type'] = res.get('type', 'image')
                        asset['update_query'] = res.get('suggested_update_query')
                        asset['extracted_data_points'] = res.get('extracted_data_points')
                        
                        # Now, mark this information inside the chapter summaries
                        for chapter in st.session_state.chapters:
                            if 'asset_ids' in chapter and asset['id'] in chapter['asset_ids']:
                                marker = f"[Asset: {asset['id'][:8]}]"
                                # Use the short caption for the summary as requested
                                info_block = f"\n[Figure {asset['id'][:8]}: {asset['short_caption']}]\n"
                                if marker in chapter['content']:
                                    chapter['content'] = chapter['content'].replace(marker, info_block)
                                else:
                                    # specific check to avoid duplicating if already replaced (though marker check handles simple case)
                                    if f"Figure {asset['id'][:8]}" not in chapter['content']:
                                        chapter['content'] += info_block

                # Clean up: Remove markers for unselected assets
                unselected_ids = [a['id'] for a in st.session_state.assets if a['id'] not in st.session_state.selected_asset_ids]
                for chapter in st.session_state.chapters:
                    for u_id in unselected_ids:
                         marker = f"[Asset: {u_id[:8]}]"
                         if marker in chapter['content']:
                             chapter['content'] = chapter['content'].replace(marker, "")
                         if 'original_full_text' in chapter and marker in chapter['original_full_text']:
                             chapter['original_full_text'] = chapter['original_full_text'].replace(marker, "")
                
                logger.info(f"Removed markers for {len(unselected_ids)} unselected assets from chapters.")

        st.session_state.current_state = STATE_RESEARCH_PLANNING
        logger.info("Transitioning to STATE_RESEARCH_PLANNING.")
        st.rerun()

def render_asset_selection():
    st.header("2. Keep Source Visuals")
    st.write("Choose which original images, charts, and tables should stay available in the updated report.")

    if not st.session_state.assets:
        st.info("No source visuals were detected in the document.")
        if st.button("Continue to Source Visual Planning"):
            st.session_state.current_state = STATE_SOURCE_VISUAL_PLANNING
            st.rerun()
        return

    asset_map = {a['id']: a for a in st.session_state.assets}
    asset_to_chapters = build_asset_to_chapters(st.session_state.chapters)
    initialize_asset_selection_state(
        st.session_state.assets,
        st.session_state.selected_asset_ids,
        st.session_state,
    )

    assigned_asset_ids = set()
    rendered_asset_ids = set()

    with st.form("asset_selection_form"):
        selected_count = len(selected_asset_ids_from_widget_state(st.session_state.assets, st.session_state))
        st.caption(f"{selected_count} of {len(st.session_state.assets)} source visuals currently selected.")

        for c_idx, chapter in enumerate(st.session_state.chapters):
            asset_ids = chapter.get('asset_ids', [])
            if asset_ids:
                st.divider()
                st.subheader(f"Chapter {c_idx+1}: {chapter['title']}")

                cols = st.columns(3)
                for a_idx, a_id in enumerate(asset_ids):
                    if a_id not in asset_map:
                        continue

                    asset = asset_map[a_id]
                    assigned_asset_ids.add(a_id)
                    with cols[a_idx % 3]:
                        st.image(asset["path"], caption=f"ID: {a_id[:8]}")

                        other_chapters = [ch for ch in asset_to_chapters.get(a_id, []) if ch != f"Chapter {c_idx+1}"]
                        if other_chapters:
                            st.info(f"Also in: {', '.join(other_chapters)}")

                        if a_id not in rendered_asset_ids:
                            rendered_asset_ids.add(a_id)
                            st.checkbox(
                                f"Include {a_id[:8]}",
                                key=asset_selection_widget_key(a_id),
                            )
                        else:
                            st.caption("Shared asset. Selection is controlled by its first occurrence above.")

        unassigned_ids = [a['id'] for a in st.session_state.assets if a['id'] not in assigned_asset_ids]
        if unassigned_ids:
            st.divider()
            st.subheader("Unassigned Assets")
            st.write("Source visuals that could not be definitively linked to a specific chapter.")
            cols = st.columns(3)
            for u_idx, a_id in enumerate(unassigned_ids):
                asset = asset_map[a_id]
                with cols[u_idx % 3]:
                    st.image(asset["path"], caption=f"ID: {a_id[:8]}")
                    st.checkbox(
                        f"Include {a_id[:8]}",
                        key=asset_selection_widget_key(a_id),
                    )

        confirmed = st.form_submit_button("Save Source Visual Selection", type="primary")

    if confirmed:
        st.session_state.selected_asset_ids = selected_asset_ids_from_widget_state(
            st.session_state.assets,
            st.session_state,
        )
        selected_id_set = _selected_asset_id_set()
        for asset in st.session_state.assets:
            if str(asset.get("id")) not in selected_id_set:
                asset["do_update"] = False
                asset["convert_to_text"] = False
        _clear_ui_notices(source="vision")
        logger.info(f"User confirmed asset selection. Count: {len(st.session_state.selected_asset_ids)}")

        with st.status(f"Analyzing selected assets with {provider_display_name()} Vision...") as status:
            selected_assets = [a for a in st.session_state.assets if a['id'] in st.session_state.selected_asset_ids]

            if selected_assets:
                status.update(label="Sending assets to Vision API (this may take a moment)...")
                logger.info(f"Triggering analyze_batch_assets for {len(selected_assets)} assets.")
                v_start_time = time.time()
                reset_vision_runtime_diagnostics()
                analysis_results = analyze_batch_assets(selected_assets)
                _queue_runtime_diagnostics(
                    consume_vision_runtime_diagnostics(),
                    source="vision",
                    context_label="Source asset analysis",
                )
                v_latency = time.time() - v_start_time
                logger.info(f"Vision analysis complete in {v_latency:.2f}s. Results count: {len(analysis_results)}")
                unique_result_ids = {str(item.get("id", "")) for item in analysis_results if item.get("id")}
                if unique_result_ids and len(unique_result_ids) != len(selected_assets):
                    _queue_ui_notice(
                        "warning",
                        "Source asset analysis returned an unexpected number of results. Some captions or update suggestions may need a manual check.",
                        source="vision",
                    )

                result_map = {r['id']: r for r in analysis_results}

                for asset in st.session_state.assets:
                    if asset['id'] in result_map:
                        res = result_map[asset['id']]
                        asset['analysis'] = res
                        asset['short_caption'] = res.get('short_caption', 'Image')
                        asset['description'] = res.get('dataset_description', '')
                        asset['type'] = res.get('type', 'image')
                        asset['update_query'] = res.get('suggested_update_query')
                        asset['extracted_data_points'] = res.get('extracted_data_points')

                        for chapter in st.session_state.chapters:
                            if 'asset_ids' in chapter and asset['id'] in chapter['asset_ids']:
                                marker = f"[Asset: {asset['id'][:8]}]"
                                info_block = f"\n[Figure {asset['id'][:8]}: {asset['short_caption']}]\n"
                                if marker in chapter['content']:
                                    chapter['content'] = chapter['content'].replace(marker, info_block)
                                elif f"Figure {asset['id'][:8]}" not in chapter['content']:
                                    chapter['content'] += info_block

                unselected_ids = [a['id'] for a in st.session_state.assets if a['id'] not in st.session_state.selected_asset_ids]
                for chapter in st.session_state.chapters:
                    for u_id in unselected_ids:
                        marker = f"[Asset: {u_id[:8]}]"
                        if marker in chapter['content']:
                            chapter['content'] = chapter['content'].replace(marker, "")
                        if 'original_full_text' in chapter and marker in chapter['original_full_text']:
                            chapter['original_full_text'] = chapter['original_full_text'].replace(marker, "")

                logger.info(f"Removed markers for {len(unselected_ids)} unselected assets from chapters.")
            else:
                status.update(label="No source visuals selected. Continuing to the next step.")
                logger.info("No assets selected in stage 2. Skipping Vision analysis.")

        st.session_state.current_state = STATE_SOURCE_VISUAL_PLANNING
        logger.info("Transitioning to STATE_SOURCE_VISUAL_PLANNING.")
        st.rerun()


def render_source_visual_planning():
    st.header("3. Plan Source Visual Updates")
    st.write(
        "Decide which retained source charts and tables should stay as-is, be refreshed with newer data, "
        "or be converted into editable text before drafting begins."
    )

    report_metadata = _get_report_metadata()
    selected_assets = _selected_source_assets()
    updateable_assets = _selected_updateable_assets()
    updateable_asset_ids = {str(asset.get("id")) for asset in updateable_assets}
    asset_to_chapters = build_asset_to_chapters(st.session_state.chapters)

    for asset in selected_assets:
        if str(asset.get("id")) not in updateable_asset_ids:
            asset["do_update"] = False
            asset["convert_to_text"] = False

    chart_count = sum(1 for asset in updateable_assets if str(asset.get("type", "")).lower() == "chart")
    table_count = sum(1 for asset in updateable_assets if str(asset.get("type", "")).lower() == "table")
    planned_count = sum(
        1 for asset in updateable_assets if asset.get("do_update") or asset.get("convert_to_text")
    )

    metric_cols = st.columns(4)
    metric_cols[0].metric("Retained Visuals", len(selected_assets))
    metric_cols[1].metric("Charts", chart_count)
    metric_cols[2].metric("Tables", table_count)
    metric_cols[3].metric("Planned Updates", planned_count)

    st.info(
        "This step only covers original charts and tables from the uploaded report. "
        "New AI-suggested visuals are still approved after drafting."
    )
    st.caption(
        f"Current update window: {report_metadata['update_start_date'].isoformat()} to "
        f"{report_metadata['update_end_date'].isoformat()}."
    )

    if not updateable_assets:
        st.success("No retained charts or tables need a special update plan.")
        st.write(
            "You can move straight into chapter research planning. Any selected source visuals will still "
            "be available later for final retention."
        )
    else:
        for asset in updateable_assets:
            asset_type = str(asset.get("type", "visual")).lower()
            chapter_labels = asset_to_chapters.get(asset["id"], [])
            if not chapter_labels:
                chapter_labels = ["Unassigned"]
            asset_label = asset.get("short_caption") or f"Figure {str(asset['id'])[:8]}"

            with st.container(border=True):
                preview_col, details_col = st.columns([1, 2])
                with preview_col:
                    st.image(asset["path"], width="stretch")
                with details_col:
                    st.markdown(f"#### {asset_type.title()}: {asset_label}")
                    st.caption(f"Figure {asset['id'][:8]} | Appears in: {', '.join(chapter_labels)}")
                    if asset.get("description"):
                        st.caption(asset["description"])

                    if asset_type == "table":
                        table_options = [
                            "Keep original",
                            "Refresh with updated data",
                            "Convert to editable table",
                        ]
                        selection = st.radio(
                            "How should this table be handled?",
                            table_options,
                            index=table_options.index(_current_visual_plan_mode(asset)),
                            key=f"source_visual_strategy_{asset['id']}",
                            horizontal=True,
                        )
                        asset["do_update"] = selection == "Refresh with updated data"
                        asset["convert_to_text"] = selection == "Convert to editable table"
                        if asset["do_update"]:
                            asset["update_query"] = st.text_input(
                                "Research Query",
                                value=_default_asset_update_query(asset, report_metadata),
                                key=f"source_visual_query_{asset['id']}",
                            )
                            st.caption("The drafting step will research fresh data and rebuild this table.")
                        elif asset["convert_to_text"]:
                            table_markdown = (asset.get("analysis") or {}).get("table_markdown")
                            if table_markdown:
                                with st.expander("Preview extracted table text"):
                                    st.code(table_markdown, language="markdown")
                            else:
                                st.warning("No table transcription is available for this source table yet.")
                            _clear_graph_refresh_state(asset)
                        else:
                            _clear_graph_refresh_state(asset)
                    else:
                        chart_options = ["Keep original", "Refresh with updated data"]
                        selection = st.radio(
                            "How should this chart be handled?",
                            chart_options,
                            index=chart_options.index(_current_visual_plan_mode(asset)),
                            key=f"source_visual_strategy_{asset['id']}",
                            horizontal=True,
                        )
                        asset["do_update"] = selection == "Refresh with updated data"
                        asset["convert_to_text"] = False
                        if asset["do_update"]:
                            asset["update_query"] = st.text_input(
                                "Research Query",
                                value=_default_asset_update_query(asset, report_metadata),
                                key=f"source_visual_query_{asset['id']}",
                            )
                            st.caption("The drafting step will research fresh data and recreate this chart.")
                        else:
                            _clear_graph_refresh_state(asset)

    nav_col1, nav_col2 = st.columns(2)
    if nav_col1.button("Back to Source Visual Selection"):
        st.session_state.current_state = STATE_ASSET_SELECTION
        st.rerun()
    if nav_col2.button("Continue to Research Planning", type="primary"):
        st.session_state.current_state = STATE_RESEARCH_PLANNING
        st.rerun()


def render_research_planning():
    st.header("4. Research Planning")
    st.write("Define the research blueprint, chapter scope, and writing guidance for each chapter.")

    report_metadata = render_report_metadata_editor("planning")
    metadata_errors = _validate_report_metadata(report_metadata)
    for error in metadata_errors:
        st.error(error)
    st.caption(
        f"Updating from {report_metadata['update_start_date'].isoformat()} to {report_metadata['update_end_date'].isoformat()} "
        f"based on an original report dated {report_metadata['original_report_date'].isoformat()}."
    )
    st.info(
        "This is the only step where report-wide update settings are edited. "
        "Source chart and table update choices are handled in the previous step so this screen can stay focused on research planning."
    )

    to_remove = None
    chapter_update_window = _format_update_window(report_metadata)

    for idx, chapter in enumerate(st.session_state.chapters):
        c_id = chapter.get('id', str(idx))
        with st.expander(f"Chapter {idx+1}: {chapter['title']}", expanded=(idx == 0)):
            baseline = chapter.get('baseline', {})
            if baseline:
                with st.container(border=True):
                    st.markdown("##### Original Edition Baseline")
                    if baseline.get('summary'):
                        st.write(baseline['summary'])
                    if baseline.get('core_claims'):
                        st.caption("Core claims from the original chapter")
                        for claim in baseline['core_claims']:
                            st.markdown(f"- {claim}")
                    if baseline.get('dated_facts'):
                        st.caption("Dated facts that may need updating")
                        for fact in baseline['dated_facts']:
                            st.markdown(f"- {fact}")
                    if baseline.get('stats'):
                        st.caption("Notable original numbers or metrics")
                        st.write(", ".join(baseline['stats'][:6]))

            chapter['title'] = st.text_input("Chapter Title", value=chapter.get('title', ''), key=f"title_{c_id}")
            with st.expander("Optional Manual Chapter Notes", expanded=False):
                st.caption(
                    "Use this only if you want to override the auto-generated chapter summary or add extra planning context."
                )
                chapter['content'] = st.text_area(
                    "Manual Summary / Notes",
                    value=chapter.get('content', ''),
                    height=200,
                    key=f"content_{c_id}",
                )

            st.divider()

            default_blueprint = build_chapter_blueprint_defaults(
                chapter,
                report_metadata=report_metadata,
                report_title=st.session_state.original_report_name or report_metadata.get("edition_title", ""),
            )
            fallback_keywords = chapter.get('extracted_keywords', chapter['title'].split())
            if 'blueprint' not in chapter:
                chapter['blueprint'] = {
                    "topic": default_blueprint.get("topic") or chapter['title'],
                    "timeframe": chapter_update_window,
                    "keywords": default_blueprint.get("keywords") or fallback_keywords,
                    "instructions": "",
                    "report_subject": default_blueprint.get("report_subject", ""),
                    "source_chapter_title": default_blueprint.get("source_chapter_title", chapter['title']),
                }

            blueprint = chapter['blueprint']
            if not str(blueprint.get('topic', '')).strip() or blueprint.get('topic') == chapter.get('title'):
                blueprint['topic'] = default_blueprint.get("topic") or chapter['title']
            if not blueprint.get('keywords'):
                blueprint['keywords'] = default_blueprint.get("keywords") or fallback_keywords
            blueprint['report_subject'] = default_blueprint.get("report_subject", blueprint.get("report_subject", ""))
            blueprint['source_chapter_title'] = default_blueprint.get("source_chapter_title", chapter['title'])
            blueprint['topic'] = st.text_input("Deep Research Topic", value=blueprint.get('topic', chapter['title']), key=f"topic_{c_id}")
            blueprint['timeframe'] = chapter_update_window
            st.caption(f"Research window: {chapter_update_window}")

            kw_val = ", ".join(blueprint.get('keywords', []))
            kw_str = st.text_input("Search Keywords (comma separated)", value=kw_val, key=f"kw_{c_id}")
            blueprint['keywords'] = [k.strip() for k in kw_str.split(",") if k.strip()]

            blueprint['instructions'] = st.text_area("Specific Writing Instructions (optional)", value=blueprint.get('instructions', ''), key=f"inst_{c_id}")
            blueprint['report_metadata'] = _serialize_report_metadata(report_metadata)
            blueprint['original_report_date'] = blueprint['report_metadata']['original_report_date']
            blueprint['update_start_date'] = blueprint['report_metadata']['update_start_date']
            blueprint['update_end_date'] = blueprint['report_metadata']['update_end_date']
            blueprint['output_language'] = report_metadata.get('output_language', 'Match Source Language')
            blueprint['target_audience'] = report_metadata.get('target_audience', 'General professional audience')
            blueprint['edition_title'] = report_metadata.get('edition_title') or st.session_state.original_report_name or ''
            blueprint['preserve_original_voice'] = report_metadata.get('preserve_original_voice', True)
            blueprint['baseline_summary'] = chapter.get('content', '') or baseline.get('summary', '')
            blueprint['baseline_claims'] = baseline.get('core_claims', [])
            blueprint['chapter_role'] = baseline.get('chapter_role', 'body')

            col1, col2, col3, col4 = st.columns(4)
            with col1:
                current_num = chapter.get('number', idx + 1)
                chapter['number'] = st.number_input("Chapter Number", min_value=1, step=1, value=current_num, key=f"num_{c_id}")
            with col2:
                chapter['writing_style'] = st.text_input("Writing Style", value=chapter.get('writing_style', 'Professional'), key=f"style_{c_id}", placeholder="e.g. Academic, Witty")
            with col3:
                orig_wc = chapter.get('original_word_count', 500)
                if 'target_word_count' not in chapter:
                    chapter['target_word_count'] = max(100, round(orig_wc / 100) * 100)
                chapter['target_word_count'] = st.slider("Target Length (Words)", min_value=100, max_value=max(2000, (orig_wc // 100 + 5) * 100), step=100, value=int(chapter['target_word_count']), help=f"Original length: {orig_wc} words", key=f"len_{c_id}")
                st.caption(f"Original: {orig_wc} words")
            with col4:
                chapter['temperature'] = st.slider("Creativity (Similarity)", min_value=0.0, max_value=1.0, step=0.1, value=chapter.get('temperature', 0.5), help="0.0 = Keeps phrasing very similar to original, 1.0 = Highly creative rewrite", key=f"temp_{c_id}")

            uploaded_refs = st.file_uploader(f"Reference Docs for Chapter {idx+1}", type=["pdf", "docx", "txt"], accept_multiple_files=True, key=f"ref_{c_id}")
            if uploaded_refs:
                os.makedirs(".tmp", exist_ok=True)
                ref_paths = []
                for ref_file in uploaded_refs:
                    path = os.path.join(".tmp", f"ref_{c_id}_{ref_file.name}")
                    with open(path, "wb") as f:
                        f.write(ref_file.getbuffer())
                    ref_paths.append(path)
                blueprint['ref_paths'] = ref_paths

            if st.button(f"Remove Chapter {idx+1}", key=f"remove_{c_id}"):
                to_remove = idx

    if to_remove is not None:
        st.session_state.chapters.pop(to_remove)
        st.rerun()

    st.divider()

    if st.button("Add New Chapter"):
        st.session_state.chapters.append({
            "id": str(uuid.uuid4()),
            "title": "New Chapter",
            "content": "",
            "baseline": {
                "summary": "",
                "keywords": [],
                "core_claims": [],
                "dated_facts": [],
                "named_entities": [],
                "stats": [],
                "original_citations": [],
                "original_figures": [],
                "chapter_role": "body",
                "language": "English",
            },
            "original_word_count": 0,
            "target_word_count": 500,
            "blueprint": {
                "topic": "New Topic",
                "timeframe": chapter_update_window,
                "keywords": [],
                "instructions": "",
                "report_metadata": _serialize_report_metadata(report_metadata),
                "original_report_date": report_metadata['original_report_date'].isoformat(),
                "update_start_date": report_metadata['update_start_date'].isoformat(),
                "update_end_date": report_metadata['update_end_date'].isoformat(),
                "output_language": report_metadata.get('output_language', 'Match Source Language'),
                "target_audience": report_metadata.get('target_audience', 'General professional audience'),
                "edition_title": report_metadata.get('edition_title') or st.session_state.original_report_name or '',
                "preserve_original_voice": report_metadata.get('preserve_original_voice', True),
                "baseline_summary": "",
                "baseline_claims": [],
                "chapter_role": "body",
            }
        })
        st.rerun()

    action_col1, action_col2 = st.columns(2)
    if action_col1.button("Back to Source Visual Updates"):
        st.session_state.current_state = STATE_SOURCE_VISUAL_PLANNING
        st.rerun()

    if action_col2.button("Start Research & Drafting", type="primary"):
        if metadata_errors:
            logger.warning("Blocked draft generation due to invalid report metadata.")
            return
        _clear_ui_notices(source="research")
        _clear_ui_notices(source="generation")
        _clear_ui_notices(source="quality_gate")
        st.session_state.current_state = STATE_DRAFT_GENERATION
        st.rerun()

from research_agent import (
    consume_runtime_diagnostics as consume_research_runtime_diagnostics,
    perform_comprehensive_research,
    reset_runtime_diagnostics as reset_research_runtime_diagnostics,
)
from writer_agent import write_chapter
from quality_gate import (
    build_quality_gate_cleanup_failure_result,
    build_quality_gate_runtime_report,
    clean_fixable_issues,
    evaluate_report_quality,
    final_assembly_gate_decision,
    has_blocking_issues,
)

def render_draft_generation():
    st.header("5. Draft Generation")
    st.write("The AI is now researching and rewriting your report...")
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    generation_alert = st.empty()
    
    # Sort chapters by number before processing
    st.session_state.chapters.sort(key=lambda x: x.get('number', 0))
    
    total = len(st.session_state.chapters)
    
    for idx, chapter in enumerate(st.session_state.chapters):
        if 'draft_text' not in chapter:
            status_text.text(f"Processing Chapter {idx+1}/{total}: {chapter['title']}...")
            
            # 1. Main Topic Research
            reset_research_runtime_diagnostics()
            findings = perform_comprehensive_research(chapter['blueprint'])
            research_diagnostics = consume_research_runtime_diagnostics()
            if research_diagnostics:
                _queue_runtime_diagnostics(
                    research_diagnostics,
                    source="research",
                    context_label=f"Research for '{chapter['title']}'",
                )
                latest = research_diagnostics[-1]
                latest_message = f"{chapter['title']}: {latest.get('message', '')}"
                if latest.get("level") == "error":
                    generation_alert.error(latest_message)
                else:
                    generation_alert.warning(latest_message)
            
            # 2. Graph Update Research
            assets_to_update = []
            source_graph_refreshes = []
            if 'asset_ids' in chapter:
                assets_in_chapter = _selected_assets_for_chapter(chapter)
                chapter_update_end_date = chapter['blueprint'].get('update_end_date')
                for asset in assets_in_chapter:
                    if asset.get('do_update') or asset.get('convert_to_text'):
                        _attach_source_context_to_asset_for_chapter(asset, chapter)
                        assets_to_update.append(asset)
                        if not asset.get('do_update'):
                            _clear_graph_refresh_state(asset)
                            continue

                        if not asset_requires_chart_refresh(asset):
                            _clear_graph_refresh_state(asset)
                            continue

                        status_text.text(f"Researching updated data for Figure {asset['id'][:8]}...")
                        reset_research_runtime_diagnostics()
                        graph_query = _graph_refresh_research_topic(asset, chapter_update_end_date)
                        graph_findings = perform_comprehensive_research({
                            "topic": graph_query,
                            "keywords": [],
                            "report_metadata": chapter['blueprint'].get('report_metadata', {}),
                            "original_report_date": chapter['blueprint'].get('original_report_date'),
                            "update_start_date": chapter['blueprint'].get('update_start_date'),
                            "update_end_date": chapter['blueprint'].get('update_end_date'),
                        })
                        graph_diagnostics = consume_research_runtime_diagnostics()
                        if graph_diagnostics:
                            _queue_runtime_diagnostics(
                                graph_diagnostics,
                                source="research",
                                context_label=f"Visual research for figure {asset['id'][:8]}",
                            )
                            latest = graph_diagnostics[-1]
                            latest_message = f"Figure {asset['id'][:8]}: {latest.get('message', '')}"
                            if latest.get("level") == "error":
                                generation_alert.error(latest_message)
                            else:
                                generation_alert.warning(latest_message)

                        for gf in graph_findings:
                            gf['title'] = f"[For Figure {asset['id'][:8]}] " + gf['title']

                        findings.extend(graph_findings)
                        preferred_extracted_data = preferred_extracted_data_points(asset)
                        if preferred_extracted_data:
                            asset["extracted_data_points"] = preferred_extracted_data
                        asset["graph_update_research_findings"] = graph_findings
                        refresh_result = prepare_source_graph_refresh(
                            asset,
                            graph_findings,
                            update_end_year=chapter_update_end_date,
                        )
                        asset["graph_update_status"] = refresh_result.get("graph_update_status", "")
                        asset["prepared_update_visual"] = refresh_result.get("prepared_update_visual")
                        asset["update_reason"] = refresh_result.get("update_reason", "")
                        asset["required_years"] = refresh_result.get("required_years", [])
                        asset["graph_update_validation_errors"] = refresh_result.get("graph_update_validation_errors", [])
                        asset["graph_update_references"] = refresh_result.get("graph_update_references", [])

                        refresh_status = str(refresh_result.get("graph_update_status", "")).strip().lower()
                        refresh_summary = {
                            "asset_id": str(asset.get("id") or ""),
                            "short_caption": asset.get("short_caption") or asset.get("title") or "Source chart",
                            "graph_update_status": refresh_status,
                            "update_reason": refresh_result.get("update_reason", ""),
                            "required_years": refresh_result.get("required_years", []),
                        }
                        source_graph_refreshes.append(refresh_summary)

                        if refresh_status == GRAPH_UPDATE_STATUS_NO_NEW_DATA:
                            warning_message = (
                                f"Figure {asset['id'][:8]} kept the original source graph because no credible "
                                f"new datapoints were found. {refresh_result.get('update_reason', '')}"
                            ).strip()
                            _queue_ui_notice("warning", warning_message, source="generation")
                            generation_alert.warning(warning_message)
                        elif refresh_status == GRAPH_UPDATE_STATUS_INVALID:
                            error_message = (
                                f"Figure {asset['id'][:8]} could not be refreshed safely. "
                                f"{refresh_result.get('update_reason', '')}"
                            ).strip()
                            _queue_ui_notice("error", error_message, source="generation")
                            generation_alert.error(error_message)

            # 3. Write Chapter
            graph_question_candidates = evaluate_graphable_question_candidates(findings, chapter['blueprint'])
            graphable_questions = discover_graphable_questions(findings, chapter['blueprint'])
            writing_blueprint = dict(chapter['blueprint'])
            writing_blueprint['graphable_questions'] = graphable_questions

            writing_style = chapter.get('writing_style', 'Professional')
            prior_chapter_context = build_prior_chapter_context(st.session_state.chapters, idx)
            result = write_chapter(
                chapter.get('original_full_text', chapter['content']), 
                findings, 
                writing_blueprint,
                writing_style=writing_style,
                assets_to_update=assets_to_update,
                prior_chapter_context=prior_chapter_context,
                target_word_count=chapter.get('target_word_count', 500),
                temperature=chapter.get('temperature', 0.5)
            )
            
            if "error" in result:
                error_message = f"Chapter {idx+1} ({chapter['title']}): {result['error']}"
                _queue_ui_notice("error", error_message, source="generation")
                generation_alert.error(error_message)
                st.error(f"Error in Chapter {idx+1}: {result['error']}")
                chapter['draft_text'] = "Error generating content."
                chapter['source_graph_refreshes'] = source_graph_refreshes
            else:
                draft_text = result['text_content']
                visual_suggestions = inject_prepared_source_graph_updates(
                    result.get('visual_suggestions', []),
                    assets_to_update,
                )
                generated_title = str(result.get('chapter_title', '')).strip()
                if generated_title:
                    chapter.setdefault('source_title', chapter.get('title', ''))
                    chapter['title'] = generated_title
                
                # --- Post-process Visuals and Markers ---
                # Normalize each visual to a stable export marker so later assembly can
                # resolve it without relying on short-ID collisions.
                for v in visual_suggestions:
                    # 0. Normalize type field — LLM sometimes returns variants
                    raw_type = str(v.get('type', '')).lower()
                    if raw_type in ('graph', 'chart', 'bar_chart', 'line_chart', 'pie_chart', 'scatter_chart', 'data'):
                        v['type'] = 'graph'
                    elif raw_type in ('image', 'photo', 'search_image', 'web_image', 'illustration'):
                        v['type'] = 'image'
                    else:
                        v['type'] = 'graph'  # default to graph if unclear

                    # Normalize query field name (LLM sometimes uses search_query instead of query)
                    if 'search_query' in v and 'query' not in v:
                        v['query'] = v.pop('search_query')

                    # 1. Assign ID if missing
                    if 'id' not in v:
                        v['id'] = uuid.uuid4().hex

                    canonical_marker_id = _canonical_visual_marker_id(v)
                    marker_caption = v.get('title') or v.get('description', 'Figure')
                    marker_candidates = _visual_marker_keys(v)
                    v['marker_id'] = canonical_marker_id
                    canonical_marker = build_figure_marker(canonical_marker_id, marker_caption)

                    # 2. Normalize any legacy marker to the canonical export marker.
                    ai_marker = v.get('marker_in_text')
                    if ai_marker and ai_marker in draft_text:
                        draft_text = draft_text.replace(ai_marker, canonical_marker)
                        logger.info(f"Replaced marker '{ai_marker}' with '{canonical_marker}'")
                    else:
                        draft_text, rewritten_markers = _rewrite_visual_markers(
                            draft_text,
                            marker_candidates,
                            canonical_marker_id,
                            marker_caption,
                        )
                        if rewritten_markers:
                            logger.info(
                                "Normalized %s existing visual marker(s) for '%s' to canonical id '%s'.",
                                rewritten_markers,
                                v.get('title'),
                                canonical_marker_id,
                            )
                        else:
                            draft_text, placement_mode = place_marker_near_relevant_paragraph(
                                draft_text,
                                canonical_marker,
                                v,
                            )
                            if placement_mode == "contextual":
                                logger.info(
                                    "Placed visual marker for '%s' (id=%s) near matching chapter text.",
                                    v.get('title'),
                                    canonical_marker_id,
                                )
                            elif placement_mode == "empty":
                                logger.info(
                                    "Inserted visual marker for '%s' (id=%s) into an empty chapter body.",
                                    v.get('title'),
                                    canonical_marker_id,
                                )
                            else:
                                if ai_marker:
                                    logger.warning(
                                        "Marker '%s' was not found for visual '%s'; appended the canonical marker at chapter end.",
                                        ai_marker,
                                        v.get('title'),
                                    )
                                else:
                                    logger.warning(
                                        "Could not find a strong paragraph anchor for visual '%s' (id=%s); appended it at chapter end.",
                                        v.get('title'),
                                        canonical_marker_id,
                                    )

                for asset in assets_to_update:
                    if str(asset.get("graph_update_status", "")).strip().lower() == GRAPH_UPDATE_STATUS_NO_NEW_DATA:
                        draft_text = _ensure_source_asset_marker(draft_text, asset)

                chapter['draft_text'] = draft_text
                chapter['executive_takeaway'] = result.get('executive_takeaway', '')
                chapter['retained_claims'] = result.get('retained_claims', [])
                chapter['updated_claims'] = result.get('updated_claims', [])
                chapter['new_claims'] = result.get('new_claims', [])
                chapter['open_questions'] = result.get('open_questions', [])
                chapter['suggested_visuals'] = visual_suggestions
                chapter['graph_question_candidates'] = graph_question_candidates
                chapter['graphable_questions'] = graphable_questions
                chapter['source_graph_refreshes'] = source_graph_refreshes
                chapter['graph_candidate_groups'] = build_ranked_graph_candidate_groups(
                    [visual for visual in visual_suggestions if str(visual.get("type", "")).strip().lower() == "graph"],
                    chapter_title=chapter.get("title", ""),
                    draft_text=draft_text,
                    chapter_role=(chapter.get("blueprint") or {}).get("chapter_role", ""),
                    graphable_questions=graphable_questions,
                )
                chapter['references'] = merge_graph_update_references(
                    result.get('references', []),
                    assets_to_update,
                )
            
        progress_bar.progress((idx + 1) / total)

    status_text.text("Draft generation complete. Review the notices above if anything degraded during research or writing.")
    st.success("All chapters processed!")
    if st.button("Review Drafts"):
        st.session_state.current_state = STATE_DRAFT_VERIFICATON
        st.rerun()

from graph_generator import generate_graph
from image_search import search_and_download_image
from doc_builder import ExportValidationError, build_final_report, build_markdown_report

def render_quality_gate_results(result):
    if not result:
        return

    summary = result.get("summary", {})
    error_count = summary.get("error_count", 0)
    warning_count = summary.get("warning_count", 0)
    update_window = summary.get("update_window", "selected range")
    auto_fixable_count = summary.get("auto_fixable_count", 0)
    by_code = summary.get("by_code", {})

    st.divider()
    st.subheader("Pre-Export Quality Gate")
    if summary.get("runtime_error"):
        phase = summary.get("runtime_error_phase", "evaluation")
        st.warning(
            f"Quality gate {phase} failed internally and was bypassed for update window {update_window}. "
            "Final assembly can continue in best-effort mode."
        )
    elif summary.get("blocking"):
        st.error(f"Quality gate found {error_count} errors and {warning_count} warnings for update window {update_window}.")
    elif warning_count:
        st.warning(f"No blocking issues found, but there are {warning_count} warnings for update window {update_window}.")
    else:
        st.success(f"Quality gate passed cleanly for update window {update_window}.")

    metric_cols = st.columns(4)
    metric_cols[0].metric("Errors", error_count)
    metric_cols[1].metric("Warnings", warning_count)
    metric_cols[2].metric("Auto-fixable", auto_fixable_count)
    metric_cols[3].metric("Issue Types", len(by_code))

    cleanup_summary = (st.session_state.get("last_cleanup_result") or {}).get("summary", {})
    if cleanup_summary.get("runtime_error"):
        st.warning(
            "Clean Fixable Issues failed internally and was skipped: "
            f"{cleanup_summary.get('runtime_error_type', 'Error')}: {cleanup_summary.get('runtime_error_message', '')}"
        )
    elif cleanup_summary:
        st.info(
            "Last cleanup pass touched "
            f"{cleanup_summary.get('changed_chapters', 0)} chapter(s) and applied "
            f"{cleanup_summary.get('fixes_applied', 0)} fix(es)."
        )

    if by_code:
        with st.expander("Issue Type Summary", expanded=summary.get("blocking", False)):
            for code, count in sorted(by_code.items()):
                st.write(f"- {code}: {count}")

    for chapter_result in result.get("chapters", []):
        issues = chapter_result.get("issues", [])
        if not issues:
            continue
        with st.expander(f"Quality Gate - {chapter_result['chapter_title']}"):
            for issue in issues:
                status_prefix = "Auto-fixable" if issue.get("auto_fixable") else "Manual fix"
                label = f"{issue.get('code', 'issue')}: {issue.get('message', '')}"
                if issue.get("severity") == "error":
                    st.error(label)
                else:
                    st.warning(label)
                st.caption(status_prefix)
                if issue.get("paragraph_number") is not None:
                    st.caption(f"Paragraph: {issue['paragraph_number']}")
                if issue.get("hint"):
                    st.caption(f"Suggested fix: {issue['hint']}")
                if issue.get("context"):
                    st.code(issue["context"], language="text")

    if summary.get("blocking"):
        st.warning(
            "Quality-gate issues are still present. Final assembly will continue in best-effort mode and surface the affected visuals, graphs, or citations as warnings."
        )


def run_quality_gate():
    metadata = _serialize_report_metadata(_get_report_metadata())
    try:
        quality_report = evaluate_report_quality(
            st.session_state.chapters,
            metadata,
        )
    except Exception as exc:
        logger.warning("Quality gate evaluation failed; continuing without blocking: %s", exc, exc_info=True)
        quality_report = build_quality_gate_runtime_report(metadata, exc, phase="evaluation")
    st.session_state.quality_gate_result = quality_report
    return quality_report


def run_quality_cleanup():
    try:
        cleanup_result = clean_fixable_issues(st.session_state.chapters)
    except Exception as exc:
        logger.warning("Quality gate cleanup failed; continuing without blocking: %s", exc, exc_info=True)
        cleanup_result = build_quality_gate_cleanup_failure_result(exc)
    st.session_state.last_cleanup_result = cleanup_result
    return cleanup_result

def render_draft_verification():
    st.header("6. Draft Review & Visual Approval")
    st.write("Review and edit the draft, then approve updated originals and any newly suggested visuals.")

    def reset_generated_chapter(chapter):
        for key in (
            "draft_text",
            "executive_takeaway",
            "retained_claims",
            "updated_claims",
            "new_claims",
            "open_questions",
            "suggested_visuals",
            "graph_question_candidates",
            "graphable_questions",
            "graph_candidate_groups",
            "references",
            "approved_visuals",
            "source_graph_refreshes",
        ):
            chapter.pop(key, None)
    
    for idx, chapter in enumerate(st.session_state.chapters):
        with st.expander(f"Verify Chapter: {chapter['title']}"):
            col1, col2 = st.columns([2, 1])
            
            with col1:
                if any([
                    chapter.get('executive_takeaway'),
                    chapter.get('retained_claims'),
                    chapter.get('updated_claims'),
                    chapter.get('new_claims'),
                    chapter.get('open_questions'),
                ]):
                    with st.container(border=True):
                        st.subheader("Edition Update Summary")
                        if chapter.get('executive_takeaway'):
                            st.caption("Executive Takeaway")
                            st.write(chapter['executive_takeaway'])
                        if chapter.get('retained_claims'):
                            st.caption("Retained Claims")
                            for item in chapter['retained_claims']:
                                st.markdown(f"- {item}")
                        if chapter.get('updated_claims'):
                            st.caption("Updated Claims")
                            for item in chapter['updated_claims']:
                                st.markdown(f"- {item}")
                        if chapter.get('new_claims'):
                            st.caption("New Claims")
                            for item in chapter['new_claims']:
                                st.markdown(f"- {item}")
                        if chapter.get('open_questions'):
                            st.caption("Open Questions")
                            for item in chapter['open_questions']:
                                st.markdown(f"- {item}")

                st.subheader("Draft Text")
                chapter['draft_text'] = st.text_area("Edit Content", value=chapter['draft_text'], height=400, key=f"edit_{idx}")
                if st.button("Regenerate This Chapter", key=f"regen_{idx}"):
                    reset_generated_chapter(chapter)
                    st.session_state.quality_gate_result = None
                    st.session_state.last_cleanup_result = None
                    st.session_state.current_state = STATE_DRAFT_GENERATION
                    st.rerun()
            
            with col2:
                st.subheader("Visual Approval")
                graph_candidate_groups = chapter.get("graph_candidate_groups") or []
                non_graph_visuals = [
                    visual
                    for visual in chapter.get("suggested_visuals", [])
                    if str(visual.get("type", "")).strip().lower() != "graph"
                ]

                if graph_candidate_groups:
                    st.markdown("#### Ranked Graph Candidates")
                    for group in graph_candidate_groups:
                        with st.container(border=True):
                            st.caption("Ranked against the nearby text, readability, and graph validity checks")
                            st.write(f"**{group.get('title', 'Graph')}**")
                            if group.get("description"):
                                st.caption(group["description"])

                            top_score = float(group.get("top_score", 0.0))
                            quality_band = group.get("quality_band", "Blocked")
                            selection_mode = group.get("selection_mode")
                            if selection_mode == "auto":
                                st.success(f"Top candidate is {quality_band.lower()} at {top_score:.2f} and is preselected.")
                            elif selection_mode == "manual":
                                st.info(f"Top candidate is {quality_band.lower()} at {top_score:.2f}. Review before export.")
                            elif selection_mode == "review":
                                st.warning(f"Top candidate is below the auto-include threshold at {top_score:.2f}.")
                            else:
                                st.warning("No safe graph candidate is ready for export yet.")

                            selection_key = _graph_selection_key(idx, group["slot_id"])
                            options = _graph_selection_options(group)
                            default_option = st.session_state.get(selection_key, _graph_default_selection(group))
                            if default_option not in options:
                                default_option = _graph_default_selection(group)
                            default_index = options.index(default_option)
                            selected_candidate_id = st.radio(
                                "Graph selection",
                                options,
                                index=default_index,
                                key=selection_key,
                                format_func=lambda option, current_group=group: _graph_option_label(current_group, option),
                            )

                            for candidate in group.get("shortlist", []):
                                preview_col, details_col = st.columns([1, 2])
                                with preview_col:
                                    preview_path = _ensure_graph_candidate_preview(candidate)
                                    if preview_path and os.path.exists(preview_path):
                                        st.image(preview_path, use_container_width=True)
                                    elif candidate.get("preview_error"):
                                        st.caption(candidate["preview_error"])
                                with details_col:
                                    scorecard = candidate.get("scorecard", {})
                                    st.write(f"**#{candidate.get('rank', '?')} {candidate.get('variant_label', 'Graph')}**")
                                    st.caption(
                                        "Overall "
                                        f"{scorecard.get('quality_band', 'Unscored')} "
                                        f"({scorecard.get('overall_score', 0.0):.2f})"
                                    )
                                    st.caption(
                                        "Relevance "
                                        f"{scorecard.get('text_relevance', 0.0):.2f} | "
                                        f"Helpfulness {scorecard.get('analytical_help', 0.0):.2f} | "
                                        f"Readability {scorecard.get('readability', 0.0):.2f}"
                                    )
                                    for reason in candidate.get("ranking_reasons", []):
                                        st.markdown(f"- {reason}")
                                    if candidate.get("id") == selected_candidate_id:
                                        st.caption("Selected for export.")

                if non_graph_visuals:
                    updates = [v for v in non_graph_visuals if v.get('original_asset_id') or v.get('action') == 'update']
                    new_visuals = [v for v in non_graph_visuals if v not in updates]

                    if updates:
                        st.markdown("#### Updates to Original Assets")
                        for v_idx, visual in enumerate(updates):
                            with st.container(border=True):
                                v_type = visual.get('type', 'visual').lower()
                                if v_type == 'image':
                                    st.caption("Web image suggestion from the configured search providers")
                                    st.write(f"**{visual.get('type', 'Visual').upper()}**: {visual.get('title', visual.get('description'))}")
                                    st.caption(visual.get('description'))
                                    st.checkbox("Approve Update", value=True, key=f"app_upd_{idx}_{v_idx}")
                                else:
                                    st.caption(v_type.capitalize())
                                    st.write(f"**{visual.get('type', 'Visual').upper()}**: {visual.get('title', visual.get('description'))}")
                                    st.checkbox("Approve Update", value=True, key=f"app_upd_{idx}_{v_idx}")

                    if new_visuals:
                        st.markdown("#### New Suggestions")
                        for n_idx, visual in enumerate(new_visuals):
                            with st.container(border=True):
                                v_type = visual.get('type', 'visual').lower()
                                if v_type == 'image':
                                    query = visual.get('query', visual.get('description', ''))
                                    st.caption(f"Web image suggestion: {query[:50]}")
                                    st.write(f"**{visual.get('type', 'Visual').upper()}**: {visual.get('title', visual.get('description'))}")
                                    st.caption(visual.get('description'))
                                    st.checkbox("Approve New Visual", key=f"app_new_{idx}_{n_idx}")
                                else:
                                    st.caption(v_type.capitalize())
                                    st.write(f"**{visual.get('type', 'Visual').upper()}**: {visual.get('title', visual.get('description'))}")
                                    st.caption(visual.get('description'))
                                    st.checkbox("Approve New Visual", key=f"app_new_{idx}_{n_idx}")

                if not graph_candidate_groups and not non_graph_visuals:
                    st.info("No updated or newly suggested visuals for this chapter.")

                # Show original retained assets independent of above approvals.
                if 'asset_ids' in chapter:
                    selected_original = _selected_retained_source_assets_for_chapter(chapter)
                    
                    if selected_original:
                         st.markdown("#### Retained Original Assets")
                         for r_idx, r_asset in enumerate(selected_original):
                             with st.container(border=True):
                                 sub_c1, sub_c2 = st.columns([1, 3])
                                 with sub_c1:
                                     st.image(r_asset['path'], width=60)
                                 with sub_c2:
                                     st.caption(f"**Fig {r_asset['id'][:8]}**: {r_asset.get('short_caption', 'Original Image')}")
                                     st.caption("Original asset from source report")
                                     st.checkbox("Keep Original in Report", value=True, key=f"retained_{idx}_{r_idx}")

    action_col1, action_col2 = st.columns(2)
    if action_col1.button("Run Quality Gate"):
        _clear_ui_notices(source="quality_gate")
        st.session_state.last_cleanup_result = None
        run_quality_gate()
        st.rerun()
    if action_col2.button("Clean Fixable Issues"):
        _clear_ui_notices(source="quality_gate")
        run_quality_cleanup()
        run_quality_gate()
        st.rerun()

    render_quality_gate_results(st.session_state.get("quality_gate_result"))

    if st.button("Finalize and Assemble Report", type="primary"):
        _clear_ui_notices(source="quality_gate")
        st.session_state.final_assembly_error = None
        planned_chart_update_failures = []
        # Build approved_visuals from checkbox state for each chapter
        for idx, chapter in enumerate(st.session_state.chapters):
            chapter['approved_visuals'] = []

            graph_candidate_groups = chapter.get("graph_candidate_groups") or []
            for group in graph_candidate_groups:
                selected_candidate_id = st.session_state.get(
                    _graph_selection_key(idx, group["slot_id"]),
                    _graph_default_selection(group),
                )
                if selected_candidate_id == _SKIP_GRAPH_OPTION:
                    continue
                selected_candidate = _find_graph_candidate(group, selected_candidate_id)
                if not selected_candidate:
                    continue

                approved_candidate = dict(selected_candidate)
                preview_path = approved_candidate.get("preview_path")
                if preview_path and os.path.exists(preview_path):
                    approved_candidate["path"] = preview_path
                chapter["approved_visuals"].append(approved_candidate)

            if 'suggested_visuals' in chapter:
                non_graph_visuals = [
                    visual
                    for visual in chapter['suggested_visuals']
                    if str(visual.get("type", "")).strip().lower() != "graph"
                ]
                updates = [v for v in non_graph_visuals if v.get('original_asset_id') or v.get('action') == 'update']
                new_visuals = [v for v in non_graph_visuals if v not in updates]

                for v_idx, visual in enumerate(updates):
                    if st.session_state.get(f"app_upd_{idx}_{v_idx}", True):
                        chapter['approved_visuals'].append(visual)

                for n_idx, visual in enumerate(new_visuals):
                    if st.session_state.get(f"app_new_{idx}_{n_idx}", False):
                        chapter['approved_visuals'].append(visual)

            # Add retained original assets
            if 'asset_ids' in chapter:
                selected_original = _selected_retained_source_assets_for_chapter(chapter)
                
                for r_idx, r_asset in enumerate(selected_original):
                    if st.session_state.get(f"retained_{idx}_{r_idx}", True):
                        # Check it's not already being replaced by an approved update
                        approved_orig_ids = set()
                        for visual in chapter['approved_visuals']:
                            approved_orig_ids.update(_visual_marker_keys(visual))
                        normalized_asset_id = _normalize_marker_token(r_asset['id'])
                        if normalized_asset_id not in approved_orig_ids and normalized_asset_id[:8] not in approved_orig_ids:
                            chapter['approved_visuals'].append({
                                "type": "image",
                                "original_asset_id": r_asset['id'],
                                "path": r_asset['path'],
                                "title": r_asset.get('short_caption', 'Original Figure'),
                                "short_caption": r_asset.get('short_caption', '')
                            })

            planned_chart_update_failures.extend(
                {
                    **failure,
                    "chapter_title": chapter.get("title", "Untitled Chapter"),
                }
                for failure in unresolved_source_chart_updates(
                    _selected_assets_for_chapter(chapter),
                    chapter['approved_visuals'],
                )
            )

            chapter['draft_text'] = _strip_export_visual_tokens(
                chapter.get('draft_text', ''),
                _approved_visual_short_ids(chapter),
            )

        if planned_chart_update_failures:
            message = _format_unresolved_chart_update_message(planned_chart_update_failures)
            logger.warning(message)
            st.session_state.final_assembly_error = message
            _queue_ui_notice("error", message, source="final_assembly")
            return

        cleanup_result = run_quality_cleanup()
        quality_report = run_quality_gate()
        st.session_state.quality_gate_result = quality_report
        if cleanup_result.get("summary", {}).get("runtime_error"):
            _queue_ui_notice(
                "warning",
                "Clean Fixable Issues failed internally and was skipped. Final assembly will continue in best-effort mode.",
                source="quality_gate",
            )
        gate_decision = final_assembly_gate_decision(quality_report)
        if has_blocking_issues(quality_report):
            logger.warning("Continuing to final assembly in best-effort mode despite quality gate issues.")
        if gate_decision.get("message"):
            _queue_ui_notice(
                gate_decision.get("notice_level") or "warning",
                gate_decision["message"],
                source="quality_gate",
            )

        st.session_state.current_state = STATE_FINAL_ASSEMBLY
        st.session_state.final_assembly_error = None
        st.session_state.final_assembly_warnings = []
        st.rerun()


def _save_llm_usage_artifacts(base_path_without_ext: str) -> dict:
    if not base_path_without_ext:
        return {}
    try:
        paths = export_usage_reports(base_path_without_ext)
        st.session_state.llm_usage_artifacts = paths
        return paths
    except Exception as exc:
        logger.error("Unable to save LLM usage artifacts: %s", exc, exc_info=True)
        _queue_ui_notice("warning", f"Unable to save LLM usage report: {exc}", source="llm_usage")
        return {}


def _render_llm_usage_report() -> None:
    rows = get_usage_rows()
    summary = summarize_usage(rows)

    st.subheader("LLM Usage & Estimated Cost")
    if not rows:
        st.info("No LLM calls have been recorded for this run yet.")
        return

    metric_cols = st.columns(5)
    metric_cols[0].metric("Estimated Cost", format_cost(summary.get("estimated_cost_usd")))
    metric_cols[1].metric("LLM Calls", summary.get("calls", 0))
    metric_cols[2].metric("Input Tokens", f"{summary.get('input_tokens', 0):,}")
    metric_cols[3].metric("Output Tokens", f"{summary.get('output_tokens', 0):,}")
    metric_cols[4].metric("Total Tokens", f"{summary.get('total_tokens', 0):,}")

    if summary.get("unknown_cost_calls"):
        st.caption(
            f"{summary['unknown_cost_calls']} successful call(s) used models without built-in pricing, "
            "so the cost total is partial."
        )

    artifacts = st.session_state.get("llm_usage_artifacts") or {}
    if artifacts:
        st.caption(
            "Usage artifacts saved: "
            + ", ".join(os.path.basename(path) for path in artifacts.values() if path)
        )

    grouped_rows = []
    for row in summary.get("by_group", []):
        display_row = dict(row)
        display_row["estimated_cost"] = format_cost(row.get("estimated_cost_usd"))
        display_row.pop("estimated_cost_usd", None)
        grouped_rows.append(display_row)
    st.dataframe(grouped_rows, use_container_width=True, hide_index=True)

    with st.expander("Per-call usage details"):
        detail_rows = []
        for row in rows:
            display_row = dict(row)
            display_row["estimated_cost"] = format_cost(row.get("estimated_cost_usd"))
            display_row.pop("estimated_cost_usd", None)
            detail_rows.append(display_row)
        st.dataframe(detail_rows, use_container_width=True, hide_index=True)


def _current_change_summary_signature() -> str:
    provider = st.session_state.get("llm_provider", get_provider())
    model = selected_change_summary_model(provider)
    return compute_report_change_signature(
        st.session_state.get("chapters", []),
        provider=provider,
        model=model,
    )


def _invalidate_change_summary_cache_if_needed() -> bool:
    current_signature = _current_change_summary_signature()
    stored_signature = st.session_state.get("change_summary_signature")
    had_cached_state = bool(
        st.session_state.get("change_summary_result") or st.session_state.get("change_summary_error")
    )
    is_stale = bool(had_cached_state and stored_signature and stored_signature != current_signature)

    if is_stale:
        st.session_state.change_summary_result = None
        st.session_state.change_summary_error = None

    st.session_state.change_summary_signature = current_signature
    return is_stale


def _render_change_list(caption: str, values: list[str]) -> None:
    if not values:
        return
    st.caption(caption)
    for value in values:
        st.markdown(f"- {value}")


def _render_change_summary_section() -> None:
    st.subheader("What Changed")
    st.caption("Generate an optional report-wide summary on demand, or review the chapter-by-chapter change log below.")

    payload = build_report_change_payload(st.session_state.get("chapters", []))
    counts = payload.get("counts", {})
    summary_became_stale = _invalidate_change_summary_cache_if_needed()
    current_signature = st.session_state.get("change_summary_signature")

    metric_cols = st.columns(5)
    metric_cols[0].metric("Changed Chapters", counts.get("changed_chapters", 0))
    metric_cols[1].metric("Updated Claims", counts.get("total_updated_claims", 0))
    metric_cols[2].metric("New Claims", counts.get("total_new_claims", 0))
    metric_cols[3].metric("Retained Claims", counts.get("total_retained_claims", 0))
    metric_cols[4].metric("Open Questions", counts.get("total_open_questions", 0))

    if summary_became_stale:
        st.info("The report changed since the last AI summary. Regenerate it to refresh the report-wide overview.")

    button_label = "Refresh AI Change Summary" if st.session_state.get("change_summary_result") else "Generate AI Change Summary"
    if st.button(button_label, key="generate_change_summary"):
        summary_result = generate_ai_report_change_summary(payload)
        st.session_state.change_summary_signature = current_signature
        st.session_state.change_summary_result = None
        st.session_state.change_summary_error = None

        if summary_result.get("error"):
            st.session_state.change_summary_error = summary_result["error"]
        else:
            st.session_state.change_summary_result = summary_result

        if st.session_state.get("llm_usage_export_base"):
            _save_llm_usage_artifacts(st.session_state["llm_usage_export_base"])
        st.rerun()

    if st.session_state.get("change_summary_error"):
        st.warning(st.session_state["change_summary_error"])

    summary_result = st.session_state.get("change_summary_result") or {}
    if summary_result:
        with st.container(border=True):
            st.write(f"**{summary_result.get('headline', 'AI Change Summary')}**")
            for bullet in summary_result.get("summary_bullets", []):
                st.markdown(f"- {bullet}")

            important_changes = summary_result.get("important_changes", [])
            if important_changes:
                st.caption("Important Changes")
                for item in important_changes:
                    chapter_title = str(item.get("chapter_title", "")).strip()
                    change_text = str(item.get("change", "")).strip()
                    if not change_text:
                        continue
                    prefix = f"**{chapter_title}:** " if chapter_title else ""
                    st.markdown(f"- {prefix}{change_text}")

            notable_open_questions = summary_result.get("notable_open_questions", [])
            if notable_open_questions:
                st.caption("Notable Open Questions")
                for item in notable_open_questions:
                    chapter_title = str(item.get("chapter_title", "")).strip()
                    question_text = str(item.get("question", "")).strip()
                    if not question_text:
                        continue
                    prefix = f"**{chapter_title}:** " if chapter_title else ""
                    st.markdown(f"- {prefix}{question_text}")

    chapters = payload.get("chapters", [])
    if not chapters:
        st.info("No chapter data is available for change tracking yet.")
        return

    for chapter in chapters:
        title = chapter.get("title", "Untitled Chapter")
        change_count = (
            len(chapter.get("updated_claims", []))
            + len(chapter.get("new_claims", []))
            + len(chapter.get("retained_claims", []))
            + len(chapter.get("open_questions", []))
        )
        changed_flag = "Updated" if chapter.get("changed") else "No structured changes"
        expander_label = f"{title} ({changed_flag}, {change_count} tracked items)"
        with st.expander(expander_label):
            word_cols = st.columns(2)
            word_cols[0].metric("Original Words", chapter.get("original_word_count", 0))
            word_cols[1].metric("Final Words", chapter.get("final_word_count", 0))

            takeaway = str(chapter.get("executive_takeaway", "")).strip()
            if takeaway:
                st.caption("Executive Takeaway")
                st.write(takeaway)

            _render_change_list("Updated Claims", chapter.get("updated_claims", []))
            _render_change_list("New Claims", chapter.get("new_claims", []))
            _render_change_list("Retained Claims", chapter.get("retained_claims", []))
            _render_change_list("Open Questions", chapter.get("open_questions", []))

            if not any(
                [
                    takeaway,
                    chapter.get("updated_claims"),
                    chapter.get("new_claims"),
                    chapter.get("retained_claims"),
                    chapter.get("open_questions"),
                ]
            ):
                st.caption("No structured chapter changes were captured for this section.")


def render_final_assembly():
    st.header("7. Final Assembly")
    st.write("Producing visuals and constructing final document...")
    report_metadata = _serialize_report_metadata(_get_report_metadata())

    if st.session_state.get("final_assembly_error") and "final_doc_path" not in st.session_state:
        st.error(st.session_state["final_assembly_error"])
    elif st.session_state.get("final_assembly_warnings"):
        st.warning("\n".join(st.session_state["final_assembly_warnings"][:6]))

    if "final_doc_path" not in st.session_state:
        with st.status("Generating visuals and building DOCX...") as status:
            try:
                final_assembly_warnings = []
                for chapter in st.session_state.chapters:
                    if 'approved_visuals' not in chapter:
                        continue
                    for visual in chapter['approved_visuals']:
                        if 'path' in visual and os.path.exists(visual['path']):
                            logger.info(f"Using existing visual path for {visual.get('original_asset_id', 'new')}")
                            visual.pop("generation_error", None)
                            continue

                        status.update(label=f"Generating {visual['type']} for {chapter['title']}...")
                        res = resolve_visual_for_export(
                            visual,
                            generate_graph_fn=generate_graph,
                            search_image_fn=search_and_download_image,
                        )

                        if 'path' in res:
                            _apply_visual_resolution_metadata(visual, res)
                            visual.pop("generation_error", None)
                            if str(res.get("provider", "")).strip().lower() == "placeholder":
                                fallback_message = (
                                    f"{chapter.get('title', 'Untitled Chapter')}: "
                                    f"{visual.get('title', visual.get('short_caption', visual.get('type', 'visual')))} "
                                    "used an explicit placeholder because live image search did not return a usable asset."
                                )
                                final_assembly_warnings.append(f"Visual fallback used: {fallback_message}")
                                logger.warning(fallback_message)
                            continue

                        failure_message = (
                            f"{chapter.get('title', 'Untitled Chapter')}: "
                            f"{visual.get('title', visual.get('short_caption', visual.get('type', 'visual')))} "
                            f"failed - {res.get('error', 'unknown error')}"
                        )
                        visual["generation_error"] = res.get("error", "unknown error")
                        final_assembly_warnings.append(f"Visual generation issue: {failure_message}")
                        logger.error("Failed to generate visual: %s", failure_message)

                status.update(label="Assembling DOCX...")
                report_name = st.session_state.get('original_report_name') or 'Modernized_Report'
                timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
                export_dir_base = "exports"
                os.makedirs(export_dir_base, exist_ok=True)
                output_filename = os.path.join(export_dir_base, f"{report_name}_{timestamp_str}.docx")
                output_md_filename = os.path.join(export_dir_base, f"{report_name}_{timestamp_str}.md")
                export_warnings: list[str] = []
                path = build_final_report(
                    st.session_state.chapters, 
                    output_filename,
                    title=report_name,
                    report_metadata=report_metadata,
                    strict=False,
                    export_warnings=export_warnings,
                )
                st.session_state.final_doc_path = path

                status.update(label="Assembling Markdown...")
                md_path = build_markdown_report(
                    st.session_state.chapters,
                    output_md_filename,
                    title=report_name,
                    report_metadata=report_metadata,
                    strict=False,
                    export_warnings=export_warnings,
                )
                st.session_state.final_md_path = md_path
                usage_export_base = os.path.splitext(output_filename)[0]
                st.session_state.llm_usage_export_base = usage_export_base
                _save_llm_usage_artifacts(usage_export_base)
                st.session_state.final_assembly_error = None
                st.session_state.final_assembly_warnings = final_assembly_warnings + export_warnings
                if st.session_state.final_assembly_warnings:
                    _queue_ui_notice(
                        "warning",
                        "Final assembly completed with best-effort warnings: "
                        + " | ".join(st.session_state.final_assembly_warnings[:4]),
                        source="final_assembly",
                    )
            except ExportValidationError as exc:
                logger.error("Final assembly strict export failed unexpectedly: %s", exc)
                status.update(label="Final assembly failed", state="error")
                st.session_state.final_assembly_error = str(exc)
                _queue_ui_notice("error", str(exc), source="final_assembly")
                return
            except Exception as exc:
                logger.error("Final assembly failed unexpectedly: %s", exc, exc_info=True)
                status.update(label="Final assembly failed", state="error")
                st.session_state.final_assembly_error = f"Final assembly failed: {exc}"
                _queue_ui_notice("error", f"Final assembly failed: {exc}", source="final_assembly")
                return

    st.success("✅ Main Report (English) complete!")
    col1, col2 = st.columns(2)
    with col1:
        if os.path.exists(st.session_state.final_doc_path):
            with open(st.session_state.final_doc_path, "rb") as f:
                doc_bytes = f.read()
            st.download_button("Download Report (DOCX)", data=doc_bytes, file_name=os.path.basename(st.session_state.final_doc_path), type="primary")
    with col2:
        if "final_md_path" in st.session_state and os.path.exists(st.session_state.final_md_path):
            md_file_path = st.session_state.final_md_path
            is_zip = md_file_path.endswith('.zip')
            btn_text = "Download Report (MD + Images ZIP)" if is_zip else "Download Report (Markdown)"
            with open(md_file_path, "rb") as f:
                md_bytes = f.read()
            st.download_button(btn_text, data=md_bytes, file_name=os.path.basename(md_file_path), type="secondary")

    st.divider()
    _render_llm_usage_report()

    st.divider()
    _render_change_summary_section()

    st.divider()
    
    # --- Translation Section ---
    st.subheader("🌍 Translate Report")
    st.write("Translate the finalized report into additional languages.")
    
    target_langs = st.multiselect("Select Target Languages", ["Hebrew", "Spanish", "French", "German", "Chinese", "Arabic", "Russian"])
    
    if st.button("Generate Translations", disabled=not target_langs):
        if "translated_reports" not in st.session_state:
            st.session_state.translated_reports = {}
            
        with st.status("Translating chapters...") as status:
            for lang in target_langs:
                if lang in st.session_state.translated_reports:
                    continue
                    
                status.update(label=f"Translating to {lang}...")
                translated_chapters = []
                translated_bodies = translate_texts_batch(
                    [ch['draft_text'] for ch in st.session_state.chapters],
                    lang,
                    preserve_markdown=True,
                )
                translated_titles = translate_texts_batch(
                    [ch['title'] for ch in st.session_state.chapters],
                    lang,
                    preserve_markdown=False,
                )

                for ch, translated_body, translated_title in zip(st.session_state.chapters, translated_bodies, translated_titles):
                    # Deep copy the chapter and translate the text
                    new_ch = ch.copy()
                    new_ch['draft_text'] = translated_body
                    # Strip any markdown separator fences (---) the translator may have wrapped around the title
                    translated_title = re.sub(r'^-{3,}\s*', '', translated_title.strip(), flags=re.MULTILINE).strip()
                    new_ch['title'] = translated_title
                    translated_chapters.append(new_ch)
                
                status.update(label=f"Building {lang} DOCX...")
                export_dir_base = "exports"
                os.makedirs(export_dir_base, exist_ok=True)
                timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = os.path.join(export_dir_base, f"Modernized_Report_{lang}_{timestamp_str}.docx")
                report_name = st.session_state.get('original_report_name') or 'Modernized_Report'
                path = build_final_report(
                    translated_chapters,
                    filename,
                    title=report_name,
                    report_metadata=report_metadata,
                )
                st.session_state.translated_reports[lang] = path

            if st.session_state.get("llm_usage_export_base"):
                _save_llm_usage_artifacts(st.session_state.llm_usage_export_base)
    
    if "translated_reports" in st.session_state:
        for lang, path in st.session_state.translated_reports.items():
            if os.path.exists(path):
                with open(path, "rb") as f:
                    translation_bytes = f.read()
                st.download_button(f"Download Report ({lang})", data=translation_bytes, file_name=os.path.basename(path))

    st.divider()
    if st.button("Start New Report"):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()

if __name__ == "__main__":
    main()
