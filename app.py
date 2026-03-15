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
from vision_service import analyze_batch_assets
from translator import translate_content
from chapter_analyzer import analyze_chapter_content

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

if "debug_mode" not in st.session_state:
    st.session_state.debug_mode = True

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

# --- Main Logic ---
def main():
    st.title("Report Updater v3 (Horizon/Elisha)")
    
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
        # Save uploaded file to .tmp
        if not os.path.exists(".tmp"):
            os.makedirs(".tmp")
        temp_path = os.path.join(".tmp", uploaded_file.name)
        with open(temp_path, "wb") as f:
            f.write(uploaded_file.getbuffer())
        
        if st.button("Process Document"):
            logger.info(f"User clicked 'Process Document' for file: {uploaded_file.name}")
            with st.spinner("Extracting text and media..."):
                if uploaded_file.name.endswith(".pdf"):
                    results = extract_pdf_content(temp_path)
                else:
                    results = extract_docx_content(temp_path)
                
                # Store original report name (without extension) for output
                original_name = os.path.splitext(uploaded_file.name)[0]
                st.session_state.original_report_name = original_name
                
                # Patterns for Table of Contents chapters to exclude
                toc_patterns = [
                    "table of contents", "contents", "תוכן עניינים",
                    "תוכן", "toc", "índice", "inhaltsverzeichnis"
                ]
                
                st.session_state.chapters = []
                total_ch = len(results["chapters"])
                status = st.empty()
                progress = st.progress(0)
                
                for i, ch in enumerate(results["chapters"]):
                    # Skip Table of Contents chapters
                    if ch['title'].strip().lower() in toc_patterns:
                        logger.info(f"Skipping ToC chapter: '{ch['title']}'")
                        continue
                    
                    ch['id'] = str(uuid.uuid4())
                    
                    # Analyze Content
                    status.text(f"Analyzing Chapter {i+1}/{total_ch}: {ch['title'][:30]}...")
                    analysis = analyze_chapter_content(ch['title'], ch['content'])
                    
                    # Store original content for reference but use summary for display/research
                    ch['original_full_text'] = ch['content']
                    ch['original_word_count'] = len(ch['content'].split())
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

def render_asset_selection():
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
        logger.info(f"User confirmed asset selection. Count: {len(st.session_state.selected_asset_ids)}")
        # Background: Analyze selected assets in batch
        with st.status("Analyzing selected assets with Gemini Vision...") as status:
            selected_assets = [a for a in st.session_state.assets if a['id'] in st.session_state.selected_asset_ids]
            
            if selected_assets:
                status.update(label="Sending assets to Vision API (this may take a moment)...")
                logger.info(f"Triggering analyze_batch_assets for {len(selected_assets)} assets.")
                v_start_time = time.time()
                # Perform batch analysis
                analysis_results = analyze_batch_assets(selected_assets)
                v_latency = time.time() - v_start_time
                logger.info(f"Vision analysis complete in {v_latency:.2f}s. Results count: {len(analysis_results)}")
                
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

def render_research_planning():
    st.header("3. Research Planning")
    st.write("Define the research blueprint and refine contents for each chapter.")
    
    # Track indices to remove
    to_remove = None

    for idx, chapter in enumerate(st.session_state.chapters):
        c_id = chapter.get('id', str(idx)) # Fallback just in case
        with st.expander(f"Chapter {idx+1}: {chapter['title']}", expanded=(idx==0)):
            # 1. Edit Chapter Title & Summary
            chapter['title'] = st.text_input("Chapter Title", value=chapter.get('title', ''), key=f"title_{c_id}")
            chapter['content'] = st.text_area("Chapter Summary (AI Generated)", value=chapter.get('content', ''), height=200, key=f"content_{c_id}")
            
            st.divider()
            
            # 2. Research Blueprint
            if 'blueprint' not in chapter:
                # Use extracted keywords if available, otherwise just topic
                default_keywords = chapter.get('extracted_keywords', chapter['title'].split())
                chapter['blueprint'] = {
                    "topic": chapter['title'],
                    "timeframe": "Last 2 years",
                    "keywords": default_keywords,
                    "instructions": ""
                }
            
            blueprint = chapter['blueprint']
            blueprint['topic'] = st.text_input("Deep Research Topic", value=blueprint['topic'], key=f"topic_{c_id}")
            blueprint['timeframe'] = st.text_input("Timeframe", value=blueprint['timeframe'], key=f"time_{c_id}")
            
            # Keywords as a string, then split
            kw_val = ", ".join(blueprint['keywords'])
            kw_str = st.text_input("Search Keywords (comma separated)", value=kw_val, key=f"kw_{c_id}")
            blueprint['keywords'] = [k.strip() for k in kw_str.split(",") if k.strip()]
            
            blueprint['instructions'] = st.text_area("Specific Writing Instructions", value=blueprint['instructions'], key=f"inst_{c_id}")
            
            # New: Chapter Number, Style & Length
            col1, col2, col3 = st.columns(3)
            with col1:
                # Default number is index+1 if not set
                current_num = chapter.get('number', idx + 1)
                chapter['number'] = st.number_input("Chapter Number", min_value=1, step=1, value=current_num, key=f"num_{c_id}")
            with col2:
                chapter['writing_style'] = st.text_input("Writing Style", value=chapter.get('writing_style', 'Professional'), key=f"style_{c_id}", placeholder="e.g. Academic, Witty")
            with col3:
                orig_wc = chapter.get('original_word_count', 500)
                
                # Initial value: rounded to nearest 100
                if 'target_word_count' not in chapter:
                    chapter['target_word_count'] = max(100, round(orig_wc / 100) * 100)
                
                # Slider with step=100
                chapter['target_word_count'] = st.slider(
                    f"Target Length (Words)", 
                    min_value=100, 
                    max_value=max(2000, (orig_wc // 100 + 5) * 100), # Ensure max is a multiple of 100
                    step=100,
                    value=int(chapter['target_word_count']),
                    help=f"Original length: {orig_wc} words",
                    key=f"len_{c_id}"
                )
                st.caption(f"Original: {orig_wc} words")

            # New: Graph Update Controls
            if 'asset_ids' in chapter:
                # Find charts in this chapter
                # Need to look up in assets list
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
                                    def_query = chart.get('update_query') or f"{chart.get('short_caption')} statistics 2024"
                                    chart['update_query'] = st.text_input("Search Query", value=def_query, key=f"query_{chart['id']}")

                # Find tables in this chapter
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
                                
                                # Option 1: Convert to Text
                                conv_key = f"conv_{table['id']}"
                                st.checkbox("📄 Convert to editable Markdown table", value=table.get('convert_to_text', False), key=conv_key)
                                table['convert_to_text'] = st.session_state[conv_key]
                                
                                # Option 2: Update Data
                                upd_key = f"upd_table_{table['id']}"
                                st.checkbox("🔄 Recreate with updated data", value=table.get('do_update', False), key=upd_key)
                                table['do_update'] = st.session_state[upd_key]
                                
                                if table['do_update']:
                                    def_query = table.get('update_query') or f"{table.get('short_caption')} data 2024"
                                    table['update_query'] = st.text_input("Search Query", value=def_query, key=f"query_tbl_{table['id']}")

            # Sub-uploader for reference docs
            uploaded_refs = st.file_uploader(f"Reference Docs for Chapter {idx+1}", type=["pdf", "docx", "txt"], accept_multiple_files=True, key=f"ref_{c_id}")
            if uploaded_refs:
                ref_paths = []
                for ref_file in uploaded_refs:
                    path = os.path.join(".tmp", f"ref_{c_id}_{ref_file.name}")
                    with open(path, "wb") as f:
                        f.write(ref_file.getbuffer())
                    ref_paths.append(path)
                blueprint['ref_paths'] = ref_paths

            # 3. Remove Chapter
            if st.button(f"🗑️ Remove Chapter {idx+1}", key=f"remove_{c_id}"):
                to_remove = idx

    # Handle removal
    if to_remove is not None:
        st.session_state.chapters.pop(to_remove)
        st.rerun()

    st.divider()
    
    # 4. Add Chapter
    if st.button("➕ Add New Chapter"):
        st.session_state.chapters.append({
            "id": str(uuid.uuid4()),
            "title": "New Chapter",
            "content": "",
            "original_word_count": 0,
            "target_word_count": 500,
            "blueprint": {
                "topic": "New Topic",
                "timeframe": "Last 2 years",
                "keywords": [],
                "instructions": ""
            }
        })
        st.rerun()

    if st.button("🚀 Start Research & Drafting"):
        st.session_state.current_state = STATE_DRAFT_GENERATION
        st.rerun()

from research_agent import perform_comprehensive_research
from writer_agent import write_chapter

def render_draft_generation():
    st.header("4. Draft Generation")
    st.write("The AI is now researching and rewriting your report...")
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    # Sort chapters by number before processing
    st.session_state.chapters.sort(key=lambda x: x.get('number', 0))
    
    total = len(st.session_state.chapters)
    
    for idx, chapter in enumerate(st.session_state.chapters):
        if 'draft_text' not in chapter:
            status_text.text(f"Processing Chapter {idx+1}/{total}: {chapter['title']}...")
            
            # 1. Main Topic Research
            findings = perform_comprehensive_research(chapter['blueprint'])
            
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
                                graph_findings = perform_comprehensive_research({
                                    "topic": query,
                                    "keywords": [], # Query is specific enough
                                })
                                # Tag these findings so the writer knows they are for the graph
                                for gf in graph_findings:
                                    gf['title'] = f"[For Figure {asset['id'][:8]}] " + gf['title']
                                
                                findings.extend(graph_findings)

            # 3. Write Chapter
            writing_style = chapter.get('writing_style', 'Professional')
            result = write_chapter(
                chapter.get('original_full_text', chapter['content']), 
                findings, 
                chapter['blueprint'],
                writing_style=writing_style,
                assets_to_update=assets_to_update,
                target_word_count=chapter.get('target_word_count', 500)
            )
            
            if "error" in result:
                st.error(f"Error in Chapter {idx+1}: {result['error']}")
                chapter['draft_text'] = "Error generating content."
            else:
                draft_text = result['text_content']
                visual_suggestions = result.get('visual_suggestions', [])
                
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
                    marker_exists = bool(re.search(r'\[(?:Figure|Asset:?)\s*' + re.escape(short_id) + r'[:\s\]]', draft_text, re.IGNORECASE))

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
                chapter['suggested_visuals'] = visual_suggestions
                chapter['references'] = result.get('references', [])
            
        progress_bar.progress((idx + 1) / total)

    st.success("All chapters processed!")
    if st.button("Review Drafts"):
        st.session_state.current_state = STATE_DRAFT_VERIFICATON
        st.rerun()

from graph_generator import generate_graph
from image_search import search_and_download_image
from doc_builder import build_final_report, build_markdown_report

def render_draft_verification():
    st.header("5. Verification & Refinement")
    st.write("Review and edit the new report content. Approve suggested visuals.")
    
    for idx, chapter in enumerate(st.session_state.chapters):
        with st.expander(f"Verify Chapter: {chapter['title']}"):
            col1, col2 = st.columns([2, 1])
            
            with col1:
                st.subheader("Draft Text")
                chapter['draft_text'] = st.text_area("Edit Content", value=chapter['draft_text'], height=400, key=f"edit_{idx}")
            
            with col2:
                st.subheader("Visual Suggestions")
                if 'suggested_visuals' in chapter:
                    # Separate suggestions
                    updates = [v for v in chapter['suggested_visuals'] if v.get('original_asset_id') or v.get('action') == 'update']
                    new_visuals = [v for v in chapter['suggested_visuals'] if v not in updates]
                    
                    if updates:
                        st.markdown("#### 🔄 Updates to Original Assets")
                        for v_idx, visual in enumerate(updates):
                            with st.container(border=True):
                                # Source type badge
                                v_type = visual.get('type', 'visual').lower()
                                if v_type == 'graph':
                                    st.caption("📊 **LLM-Generated Graph** (from your data)")
                                elif v_type == 'image':
                                    st.caption("🔍 **Web Image** (DuckDuckGo search)")
                                else:
                                    st.caption(f"🔄 **{v_type.capitalize()}**")
                                
                                st.write(f"**{visual.get('type', 'Visual').upper()}**: {visual.get('title', visual.get('description'))}")
                                st.checkbox("Approve Update", value=True, key=f"app_upd_{idx}_{v_idx}")

                    if new_visuals:
                        st.markdown("#### ✨ New Suggestions")
                        for n_idx, visual in enumerate(new_visuals):
                            with st.container(border=True):
                                # Source type badge
                                v_type = visual.get('type', 'visual').lower()
                                if v_type == 'graph':
                                    st.caption("📊 **LLM-Generated Graph** (Matplotlib, from research data)")
                                elif v_type == 'image':
                                    query = visual.get('query', visual.get('description', ''))
                                    st.caption(f"🔍 **Web Image** (DuckDuckGo search: _{query[:50]}_)")
                                else:
                                    st.caption(f"📋 **{v_type.capitalize()}**")
                                
                                st.write(f"**{visual.get('type', 'Visual').upper()}**: {visual.get('title', visual.get('description'))}")
                                st.caption(visual.get('description'))
                                st.checkbox("Approve New Visual", key=f"app_new_{idx}_{n_idx}")
                else:
                    st.info("No new visuals suggested.")

                # Show Original Retained Assets — independent of above approvals
                if 'asset_ids' in chapter:
                    # Filter for selected assets only
                    selected_original = [a for a in st.session_state.assets 
                                         if a['id'] in chapter['asset_ids'] 
                                         and a['id'] in st.session_state.selected_asset_ids]
                    
                    if selected_original:
                         st.markdown("#### 🖼️ Retained Original Assets")
                         for r_idx, r_asset in enumerate(selected_original):
                             with st.container(border=True):
                                 sub_c1, sub_c2 = st.columns([1, 3])
                                 with sub_c1:
                                     st.image(r_asset['path'], width=60)
                                 with sub_c2:
                                     st.caption(f"**Fig {r_asset['id'][:8]}**: {r_asset.get('short_caption', 'Original Image')}")
                                     st.caption("📎 **Original Asset** (from source report)")
                                     st.checkbox("Keep Original in Report", value=True, key=f"retained_{idx}_{r_idx}")

    if st.button("🚀 Finalize and Assemble Report", type="primary"):
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
        
        st.session_state.current_state = STATE_FINAL_ASSEMBLY
        st.rerun()

def render_final_assembly():
    st.header("6. Final Assembly")
    st.write("Producing visuals and constructing final document...")
    
    if "final_doc_path" not in st.session_state:
        with st.status("Generating visuals and building DOCX...") as status:
            for chapter in st.session_state.chapters:
                if 'approved_visuals' in chapter:
                    for visual in chapter['approved_visuals']:
                        # Skip if it's an original asset already on disk
                        if 'path' in visual and os.path.exists(visual['path']):
                            logger.info(f"Using existing visual path for {visual.get('original_asset_id', 'new')}")
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
                        else:
                            logger.error(f"Failed to generate visual: {res.get('error')}")
            
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
                title=report_name
            )
            st.session_state.final_doc_path = path

            status.update(label="Assembling Markdown...")
            md_path = build_markdown_report(
                st.session_state.chapters,
                output_md_filename,
                title=report_name
            )
            st.session_state.final_md_path = md_path

    st.success("✅ Main Report (English) complete!")
    col1, col2 = st.columns(2)
    with col1:
        if os.path.exists(st.session_state.final_doc_path):
            with open(st.session_state.final_doc_path, "rb") as f:
                doc_bytes = f.read()
            st.download_button("📥 Download Report (DOCX)", data=doc_bytes, file_name=os.path.basename(st.session_state.final_doc_path), type="primary")
    with col2:
        if "final_md_path" in st.session_state and os.path.exists(st.session_state.final_md_path):
            md_file_path = st.session_state.final_md_path
            is_zip = md_file_path.endswith('.zip')
            btn_text = "📥 Download Report (MD + Images ZIP)" if is_zip else "📥 Download Report (Markdown)"
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
                for ch in st.session_state.chapters:
                    # Deep copy the chapter and translate the text
                    new_ch = ch.copy()
                    new_ch['draft_text'] = translate_content(ch['draft_text'], lang)
                    translated_title = translate_content(ch['title'], lang)
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
                path = build_final_report(translated_chapters, filename, title=report_name)
                st.session_state.translated_reports[lang] = path
    
    if "translated_reports" in st.session_state:
        for lang, path in st.session_state.translated_reports.items():
            if os.path.exists(path):
                with open(path, "rb") as f:
                    translation_bytes = f.read()
                st.download_button(f"📥 Download Report ({lang})", data=translation_bytes, file_name=os.path.basename(path))

    st.divider()
    if st.button("🔄 Start New Report"):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()

if __name__ == "__main__":
    main()
