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

# State Machine Constants
STATE_UPLOAD_EXTRACT = "UPLOAD_AND_EXTRACT"
STATE_ASSET_SELECTION = "ASSET_SELECTION"
STATE_RESEARCH_PLANNING = "RESEARCH_PLANNING"
STATE_DRAFT_GENERATION = "DRAFT_GENERATION"
STATE_DRAFT_VERIFICATON = "DRAFT_VERIFICATION"
STATE_FINAL_ASSEMBLY = "FINAL_ASSEMBLY"

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

if "debug_mode" not in st.session_state:
    st.session_state.debug_mode = True

if "ui_notices" not in st.session_state:
    st.session_state.ui_notices = []

# --- Sidebar ---
st.sidebar.title("Navigation")
st.sidebar.info(f"Current State: {st.session_state.current_state}")
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
        [
            STATE_UPLOAD_EXTRACT,
            STATE_ASSET_SELECTION,
            STATE_RESEARCH_PLANNING,
            STATE_DRAFT_GENERATION,
            STATE_DRAFT_VERIFICATON,
            STATE_FINAL_ASSEMBLY
        ]
    )
    if st.sidebar.button("Jump"):
        st.session_state.current_state = state_selection
        st.rerun()

@st.dialog("API Key Required")
def ask_for_api_key():
    st.warning("GEMINI_API_KEY is not set. Please enter your Gemini API Key to continue.")
    api_key = st.text_input("Gemini API Key", type="password")
    if st.button("Save"):
        if api_key.strip():
            os.environ["GEMINI_API_KEY"] = api_key.strip()
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


def _quality_gate_block_message(result: dict) -> str:
    summary = result.get("summary", {})
    errors = summary.get("error_count", 0)
    warnings = summary.get("warning_count", 0)

    issue_snippets = []
    for chapter in result.get("chapters", []):
        for issue in chapter.get("issues", []):
            issue_snippets.append(f"{chapter.get('chapter_title', 'Untitled')}: {issue.get('message', '')}")
            if len(issue_snippets) >= 2:
                break
        if len(issue_snippets) >= 2:
            break

    suffix = f" Top issue: {' | '.join(issue_snippets)}" if issue_snippets else ""
    return (
        f"Final assembly is blocked by the quality gate ({errors} error(s), {warnings} warning(s)). "
        f"Review step 5 and fix or clean the blocking issues before exporting.{suffix}"
    )


def _format_update_window(metadata):
    return f"{metadata['update_start_date'].isoformat()} to {metadata['update_end_date'].isoformat()}"


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
        for key in ("id", "original_asset_id"):
            value = visual.get(key)
            if value:
                ids.add(str(value)[:8].lower())
    return ids


def _visual_short_id(visual):
    for key in ("id", "original_asset_id"):
        value = visual.get(key)
        if value:
            return str(value)[:8].lower()
    return ""


def _strip_unapproved_visual_markers(text: str, approved_visual_ids):
    marker_pattern = re.compile(
        r"\[(?:Figure|Asset|Image|Figura|איור|תמונה):?\s*([a-zA-Z0-9]{8,32})[:\s]*.*?\]",
        re.IGNORECASE,
    )

    def replace_marker(match):
        marker_id = match.group(1)[:8].lower()
        return match.group(0) if marker_id in approved_visual_ids else ""

    cleaned = marker_pattern.sub(replace_marker, text or "")
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()

def _strip_export_visual_tokens(text: str, approved_visual_ids):
    cleaned = _strip_unapproved_visual_markers(text, approved_visual_ids)
    cleaned = re.sub(r"\[\s*visual\s*:\s*([a-zA-Z0-9]{8,32})[^\]]*\]", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


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
    _render_ui_notices()
    
    if not os.environ.get("GEMINI_API_KEY"):
        ask_for_api_key()
        st.stop()
    
    current_state = st.session_state.current_state
    logger.debug(f"Rendering main page - Current State: {current_state}")
    
    if current_state == STATE_UPLOAD_EXTRACT:
        render_upload_extract()
    elif current_state == STATE_ASSET_SELECTION:
        render_asset_selection()
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
    st.header("1. Upload & Blind Extraction")
    st.write("Upload a source PDF or DOCX to begin.")

    uploaded_file = st.file_uploader("Source Document", type=["pdf", "docx"])

    if uploaded_file:
        report_metadata = render_report_metadata_editor("upload")
        metadata_errors = _validate_report_metadata(report_metadata)
        for error in metadata_errors:
            st.error(error)

        if not os.path.exists(".tmp"):
            os.makedirs(".tmp")
        temp_path = os.path.join(".tmp", uploaded_file.name)
        with open(temp_path, "wb") as f:
            f.write(uploaded_file.getbuffer())

        if st.button("Process Document"):
            _clear_ui_notices()
            if metadata_errors:
                logger.warning("Blocked document processing due to invalid report metadata.")
                return

            logger.info(f"User clicked 'Process Document' for file: {uploaded_file.name}")
            with st.spinner("Extracting text and media..."):
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
                    status.text(f"Analyzing {total_ch} chapter(s) with Gemini...")
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
        with st.status("Analyzing selected assets with Gemini Vision...") as status:
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
    st.header("2. Source Asset Selection")
    st.write("Review the images extracted from the report. Select those you want to include in the new version.")

    if not st.session_state.assets:
        st.info("No images detected in the document.")
        if st.button("Continue to Planning"):
            st.session_state.current_state = STATE_RESEARCH_PLANNING
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
        st.caption(f"{selected_count} of {len(st.session_state.assets)} assets currently selected.")

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
            st.write("Images that couldn't be definitively linked to a specific chapter.")
            cols = st.columns(3)
            for u_idx, a_id in enumerate(unassigned_ids):
                asset = asset_map[a_id]
                with cols[u_idx % 3]:
                    st.image(asset["path"], caption=f"ID: {a_id[:8]}")
                    st.checkbox(
                        f"Include {a_id[:8]}",
                        key=asset_selection_widget_key(a_id),
                    )

        confirmed = st.form_submit_button("Confirm Selection", type="primary")

    if confirmed:
        st.session_state.selected_asset_ids = selected_asset_ids_from_widget_state(
            st.session_state.assets,
            st.session_state,
        )
        _clear_ui_notices(source="vision")
        logger.info(f"User confirmed asset selection. Count: {len(st.session_state.selected_asset_ids)}")

        with st.status("Analyzing selected assets with Gemini Vision...") as status:
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
                status.update(label="No assets selected. Continuing to planning.")
                logger.info("No assets selected in stage 2. Skipping Vision analysis.")

        st.session_state.current_state = STATE_RESEARCH_PLANNING
        logger.info("Transitioning to STATE_RESEARCH_PLANNING.")
        st.rerun()


def render_research_planning():
    st.header("3. Research Planning")
    st.write("Define the research blueprint and refine contents for each chapter.")

    report_metadata = render_report_metadata_editor("planning")
    metadata_errors = _validate_report_metadata(report_metadata)
    for error in metadata_errors:
        st.error(error)
    st.caption(
        f"Updating from {report_metadata['update_start_date'].isoformat()} to {report_metadata['update_end_date'].isoformat()} "
        f"based on an original report dated {report_metadata['original_report_date'].isoformat()}."
    )

    to_remove = None

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
            chapter['content'] = st.text_area("Chapter Summary (AI Generated)", value=chapter.get('content', ''), height=200, key=f"content_{c_id}")

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
                    "timeframe": _format_update_window(report_metadata),
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
            blueprint['timeframe'] = st.text_input("Timeframe", value=blueprint.get('timeframe', _format_update_window(report_metadata)), key=f"time_{c_id}")

            kw_val = ", ".join(blueprint.get('keywords', []))
            kw_str = st.text_input("Search Keywords (comma separated)", value=kw_val, key=f"kw_{c_id}")
            blueprint['keywords'] = [k.strip() for k in kw_str.split(",") if k.strip()]

            blueprint['instructions'] = st.text_area("Specific Writing Instructions", value=blueprint.get('instructions', ''), key=f"inst_{c_id}")
            blueprint['report_metadata'] = _serialize_report_metadata(report_metadata)
            blueprint['original_report_date'] = blueprint['report_metadata']['original_report_date']
            blueprint['update_start_date'] = blueprint['report_metadata']['update_start_date']
            blueprint['update_end_date'] = blueprint['report_metadata']['update_end_date']
            blueprint['output_language'] = report_metadata.get('output_language', 'Match Source Language')
            blueprint['target_audience'] = report_metadata.get('target_audience', 'General professional audience')
            blueprint['edition_title'] = report_metadata.get('edition_title') or st.session_state.original_report_name or ''
            blueprint['preserve_original_voice'] = report_metadata.get('preserve_original_voice', True)
            blueprint['baseline_summary'] = baseline.get('summary', chapter.get('content', ''))
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

            if 'asset_ids' in chapter:
                assets_in_chapter = [a for a in st.session_state.assets if a['id'] in chapter['asset_ids']]
                charts = [a for a in assets_in_chapter if a.get('type') == 'chart']
                if charts:
                    st.markdown("##### 📊 Graph Updates")
                    for chart in charts:
                        with st.container(border=True):
                            c_col1, c_col2 = st.columns([1, 3])
                            with c_col1:
                                st.image(chart['path'], width=100)
                            with c_col2:
                                st.caption(f"**Fig {chart['id'][:8]}**: {chart.get('short_caption', '')}")
                                do_update = st.checkbox("🔄 Recreate with updated data (2010-Present)", value=chart.get('do_update', False), key=f"update_{chart['id']}")
                                chart['do_update'] = do_update
                                if do_update:
                                    def_query = chart.get('update_query') or f"{chart.get('short_caption')} statistics {report_metadata['update_end_date'].year}"
                                    chart['update_query'] = st.text_input("Search Query", value=def_query, key=f"query_{chart['id']}")

                tables = [a for a in assets_in_chapter if a.get('type') == 'table']
                if tables:
                    st.markdown("##### 📋 Table Updates")
                    for table in tables:
                        with st.container(border=True):
                            t_col1, t_col2 = st.columns([1, 3])
                            with t_col1:
                                st.image(table['path'], width=100)
                            with t_col2:
                                st.caption(f"**Fig {table['id'][:8]}**: {table.get('short_caption', '')}")
                                conv_key = f"conv_{table['id']}"
                                st.checkbox("📄 Convert to editable Markdown table", value=table.get('convert_to_text', False), key=conv_key)
                                table['convert_to_text'] = st.session_state[conv_key]
                                upd_key = f"upd_table_{table['id']}"
                                st.checkbox("🔄 Recreate with updated data", value=table.get('do_update', False), key=upd_key)
                                table['do_update'] = st.session_state[upd_key]
                                if table['do_update']:
                                    def_query = table.get('update_query') or f"{table.get('short_caption')} data {report_metadata['update_end_date'].year}"
                                    table['update_query'] = st.text_input("Search Query", value=def_query, key=f"query_tbl_{table['id']}")

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
                "timeframe": _format_update_window(report_metadata),
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

    if st.button("Start Research & Drafting"):
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
from quality_gate import clean_fixable_issues, evaluate_report_quality, has_blocking_issues

def render_draft_generation():
    st.header("4. Draft Generation")
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
            if 'asset_ids' in chapter:
                # Find assets marked for update
                assets_in_chapter = [a for a in st.session_state.assets if a['id'] in chapter['asset_ids']]
                for asset in assets_in_chapter:
                    if asset.get('do_update') or asset.get('convert_to_text'):
                        assets_to_update.append(asset)
                        
                        if asset.get('do_update'):
                            # Perform specific research for this graph/table
                            query = asset.get('update_query')
                            if query:
                                status_text.text(f"Researching updated data for Figure {asset['id'][:8]}...")
                                reset_research_runtime_diagnostics()
                                graph_findings = perform_comprehensive_research({
                                    "topic": query,
                                    "keywords": [], # Query is specific enough
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
                                # Tag these findings so the writer knows they are for the graph
                                for gf in graph_findings:
                                    gf['title'] = f"[For Figure {asset['id'][:8]}] " + gf['title']
                                
                                findings.extend(graph_findings)

            # 3. Write Chapter
            writing_style = chapter.get('writing_style', 'Professional')
            prior_chapter_context = build_prior_chapter_context(st.session_state.chapters, idx)
            result = write_chapter(
                chapter.get('original_full_text', chapter['content']), 
                findings, 
                chapter['blueprint'],
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
            else:
                draft_text = result['text_content']
                visual_suggestions = result.get('visual_suggestions', [])
                generated_title = str(result.get('chapter_title', '')).strip()
                if generated_title:
                    chapter.setdefault('source_title', chapter.get('title', ''))
                    chapter['title'] = generated_title
                
                # --- Post-process Visuals and Markers ---
                # Ensure IDs match DocBuilder format (8-char hex) and markers exist
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

                    short_id = v['id'][:8]

                    # 2. Check if a marker for this ID already exists (from new prompt instructions)
                    marker_exists = bool(re.search(r'\[(?:Figure|Asset|איור|תמונה|Figura|Image):?\s*' + re.escape(short_id) + r'[:\s\]]', draft_text, re.IGNORECASE))

                    if not marker_exists:
                        # 3. Handle older logic or replacements
                        ai_marker = v.get('marker_in_text')
                        if ai_marker and ai_marker in draft_text:
                            caption = v.get('description', 'Visual')
                            new_marker = f"[Figure {short_id}: {caption}]"
                            draft_text = draft_text.replace(ai_marker, new_marker)
                            logger.info(f"Replaced marker '{ai_marker}' with '{new_marker}'")
                        elif ai_marker:
                            # Marker was specified but not found — log only, don't append
                            logger.warning(f"Marker '{ai_marker}' not found in draft text for visual '{v.get('title')}'. Visual will appear at chapter end.")
                        else:
                            # Brand-new suggestion with no marker — inject one at end of chapter
                            # so DocBuilder can locate and embed the visual.
                            caption = v.get('title') or v.get('description', 'Figure')
                            injected_marker = f"\n\n[Figure {short_id}: {caption}]\n"
                            draft_text += injected_marker
                            logger.info(f"Injected new visual marker for '{v.get('title')}' (id={short_id}) at chapter end.")

                chapter['draft_text'] = draft_text
                chapter['executive_takeaway'] = result.get('executive_takeaway', '')
                chapter['retained_claims'] = result.get('retained_claims', [])
                chapter['updated_claims'] = result.get('updated_claims', [])
                chapter['new_claims'] = result.get('new_claims', [])
                chapter['open_questions'] = result.get('open_questions', [])
                chapter['suggested_visuals'] = visual_suggestions
                chapter['references'] = result.get('references', [])
            
        progress_bar.progress((idx + 1) / total)

    status_text.text("Draft generation complete. Review the notices above if anything degraded during research or writing.")
    st.success("All chapters processed!")
    if st.button("Review Drafts"):
        st.session_state.current_state = STATE_DRAFT_VERIFICATON
        st.rerun()

from graph_generator import generate_graph
from image_search import search_and_download_image
from doc_builder import build_final_report, build_markdown_report

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
    if summary.get("blocking"):
        st.error(f"Blocking issues found: {error_count} errors and {warning_count} warnings for update window {update_window}.")
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
    if cleanup_summary:
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


def run_quality_gate():
    quality_report = evaluate_report_quality(
        st.session_state.chapters,
        _serialize_report_metadata(_get_report_metadata()),
    )
    st.session_state.quality_gate_result = quality_report
    return quality_report

def render_draft_verification():
    st.header("5. Verification & Refinement")
    st.write("Review and edit the new report content. Approve suggested visuals.")

    def reset_generated_chapter(chapter):
        for key in (
            "draft_text",
            "executive_takeaway",
            "retained_claims",
            "updated_claims",
            "new_claims",
            "open_questions",
            "suggested_visuals",
            "references",
            "approved_visuals",
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
                st.subheader("Visual Suggestions")
                if 'suggested_visuals' in chapter:
                    # Separate suggestions
                    updates = [v for v in chapter['suggested_visuals'] if v.get('original_asset_id') or v.get('action') == 'update']
                    new_visuals = [v for v in chapter['suggested_visuals'] if v not in updates]
                    
                    if updates:
                        st.markdown("#### Updates to Original Assets")
                        for v_idx, visual in enumerate(updates):
                            with st.container(border=True):
                                # Source type badge
                                v_type = visual.get('type', 'visual').lower()
                                if v_type == 'graph':
                                    st.caption("Graph generated from your data")
                                elif v_type == 'image':
                                    st.caption("Web image from DuckDuckGo search")
                                else:
                                    st.caption(v_type.capitalize())
                                
                                st.write(f"**{visual.get('type', 'Visual').upper()}**: {visual.get('title', visual.get('description'))}")
                                st.checkbox("Approve Update", value=True, key=f"app_upd_{idx}_{v_idx}")

                    if new_visuals:
                        st.markdown("#### New Suggestions")
                        for n_idx, visual in enumerate(new_visuals):
                            with st.container(border=True):
                                # Source type badge
                                v_type = visual.get('type', 'visual').lower()
                                if v_type == 'graph':
                                    st.caption("Graph generated from research data")
                                elif v_type == 'image':
                                    query = visual.get('query', visual.get('description', ''))
                                    st.caption(f"Web image from DuckDuckGo search: {query[:50]}")
                                else:
                                    st.caption(v_type.capitalize())
                                
                                st.write(f"**{visual.get('type', 'Visual').upper()}**: {visual.get('title', visual.get('description'))}")
                                st.caption(visual.get('description'))
                                st.checkbox("Approve New Visual", key=f"app_new_{idx}_{n_idx}")
                else:
                    st.info("No new visuals suggested.")

                # Show original retained assets independent of above approvals.
                if 'asset_ids' in chapter:
                    # Filter for selected assets only
                    selected_original = [a for a in st.session_state.assets 
                                         if a['id'] in chapter['asset_ids'] 
                                         and a['id'] in st.session_state.selected_asset_ids]
                    
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
        st.session_state.last_cleanup_result = clean_fixable_issues(st.session_state.chapters)
        run_quality_gate()
        st.rerun()

    render_quality_gate_results(st.session_state.get("quality_gate_result"))

    if st.button("Finalize and Assemble Report", type="primary"):
        _clear_ui_notices(source="quality_gate")
        # Build approved_visuals from checkbox state for each chapter
        for idx, chapter in enumerate(st.session_state.chapters):
            chapter['approved_visuals'] = []
            
            if 'suggested_visuals' in chapter:
                updates = [v for v in chapter['suggested_visuals'] if v.get('original_asset_id') or v.get('action') == 'update']
                new_visuals = [v for v in chapter['suggested_visuals'] if v not in updates]
                
                for v_idx, visual in enumerate(updates):
                    if st.session_state.get(f"app_upd_{idx}_{v_idx}", True):
                        chapter['approved_visuals'].append(visual)
                
                for n_idx, visual in enumerate(new_visuals):
                    if st.session_state.get(f"app_new_{idx}_{n_idx}", False):
                        chapter['approved_visuals'].append(visual)
            
            # Add retained original assets
            if 'asset_ids' in chapter:
                selected_original = [a for a in st.session_state.assets 
                                     if a['id'] in chapter['asset_ids'] 
                                     and a['id'] in st.session_state.selected_asset_ids]
                
                for r_idx, r_asset in enumerate(selected_original):
                    if st.session_state.get(f"retained_{idx}_{r_idx}", True):
                        # Check it's not already being replaced by an approved update
                        approved_orig_ids = [v.get('original_asset_id') for v in chapter['approved_visuals'] if v.get('original_asset_id')]
                        if r_asset['id'] not in approved_orig_ids:
                            chapter['approved_visuals'].append({
                                "type": "image",
                                "original_asset_id": r_asset['id'],
                                "path": r_asset['path'],
                                "title": r_asset.get('short_caption', 'Original Figure'),
                                "short_caption": r_asset.get('short_caption', '')
                            })

            chapter['draft_text'] = _strip_export_visual_tokens(
                chapter.get('draft_text', ''),
                _approved_visual_short_ids(chapter),
            )

        st.session_state.last_cleanup_result = clean_fixable_issues(st.session_state.chapters)
        quality_report = run_quality_gate()
        st.session_state.quality_gate_result = quality_report
        if has_blocking_issues(quality_report):
            logger.warning("Blocked final assembly due to quality gate errors.")
            _queue_ui_notice("error", _quality_gate_block_message(quality_report), source="quality_gate")
            st.rerun()

        st.session_state.current_state = STATE_FINAL_ASSEMBLY
        st.rerun()

def render_final_assembly():
    st.header("6. Final Assembly")
    st.write("Producing visuals and constructing final document...")
    report_metadata = _serialize_report_metadata(_get_report_metadata())
    
    if "final_doc_path" not in st.session_state:
        with st.status("Generating visuals and building DOCX...") as status:
            for chapter in st.session_state.chapters:
                if 'approved_visuals' in chapter:
                    retained_visuals = []
                    dropped_visual_ids = set()
                    for visual in chapter['approved_visuals']:
                        # Skip if it's an original asset already on disk
                        if 'path' in visual and os.path.exists(visual['path']):
                            logger.info(f"Using existing visual path for {visual.get('original_asset_id', 'new')}")
                            retained_visuals.append(visual)
                            continue

                        status.update(label=f"Generating {visual['type']} for {chapter['title']}...")
                        if visual['type'] == 'graph':
                            res = generate_graph(visual)
                        else:
                            # For suggestions, use the description or title as search query
                            query = visual.get('query') or visual.get('description') or visual.get('title')
                            res = search_and_download_image(query)
                        
                        if 'path' in res:
                            visual['path'] = res['path']
                            retained_visuals.append(visual)
                        else:
                            logger.error(f"Failed to generate visual: {res.get('error')}")
                            short_id = _visual_short_id(visual)
                            if short_id:
                                dropped_visual_ids.add(short_id)

                    chapter['approved_visuals'] = retained_visuals
                    if dropped_visual_ids:
                        chapter['draft_text'] = _strip_export_visual_tokens(
                            chapter.get('draft_text', ''),
                            _approved_visual_short_ids(chapter),
                        )
                        logger.warning(
                            "Dropped failed visuals before export for chapter '%s': %s",
                            chapter.get('title', 'Untitled Chapter'),
                            ", ".join(sorted(dropped_visual_ids)),
                        )
            
            status.update(label="Assembling DOCX...")
            report_name = st.session_state.get('original_report_name') or 'Modernized_Report'
            timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            export_dir_base = "exports"
            os.makedirs(export_dir_base, exist_ok=True)
            output_filename = os.path.join(export_dir_base, f"{report_name}_{timestamp_str}.docx")
            output_md_filename = os.path.join(export_dir_base, f"{report_name}_{timestamp_str}.md")
            path = build_final_report(
                st.session_state.chapters, 
                output_filename,
                title=report_name,
                report_metadata=report_metadata,
            )
            st.session_state.final_doc_path = path

            status.update(label="Assembling Markdown...")
            md_path = build_markdown_report(
                st.session_state.chapters,
                output_md_filename,
                title=report_name,
                report_metadata=report_metadata,
            )
            st.session_state.final_md_path = md_path

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
