from docx import Document
from docx.shared import Inches, Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
import os
import re
import zipfile
import shutil
from datetime import datetime
from typing import List, Dict
from logger_config import setup_logger
import time

logger = setup_logger("DocBuilder")

class ReportBuilder:
    def __init__(self, title: str):
        logger.info(f"Initializing ReportBuilder for report: '{title}'")
        self.doc = Document()
        self.title = title
        self._chapter_count = 0  # Track chapters to add section breaks
        self._setup_styles()
        self._add_page_numbers()

    def _setup_styles(self):
        # Could customize default styles here if needed
        pass

    def _add_page_numbers(self):
        """Adds a right-aligned page number to the footer of the default section."""
        try:
            section = self.doc.sections[0]
            footer = section.footer
            footer.is_linked_to_previous = False
            para = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
            para.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            para.clear()  # Remove any existing content

            run = para.add_run()
            # Add the PAGE field using raw XML
            fld = OxmlElement('w:fldChar')
            fld.set(qn('w:fldCharType'), 'begin')
            run._r.append(fld)

            instrText = OxmlElement('w:instrText')
            instrText.set(qn('xml:space'), 'preserve')
            instrText.text = 'PAGE'
            run._r.append(instrText)

            fld_end = OxmlElement('w:fldChar')
            fld_end.set(qn('w:fldCharType'), 'end')
            run._r.append(fld_end)

            logger.debug("Page numbers added to footer.")
        except Exception as e:
            logger.warning(f"Could not add page numbers: {e}")

    def add_cover_page(self, subtitle: str):
        logger.info(f"Adding cover page with subtitle: '{subtitle}'")
        title_para = self.doc.add_heading(self.title, 0)
        title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        
        subtitle_para = self.doc.add_paragraph(subtitle)
        subtitle_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        
        date_para = self.doc.add_paragraph(f"Date: {datetime.now().strftime('%Y-%m-%d')}")
        date_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        
        self.doc.add_page_break()

    def add_table_of_contents(self):
        """Inserts a Word Table of Contents field that auto-updates when the doc is opened."""
        logger.info("Adding Table of Contents field.")
        toc_heading = self.doc.add_heading("Table of Contents", level=1)
        self._set_rtl_if_hebrew(toc_heading, self.title)  # Match document direction

        paragraph = self.doc.add_paragraph()
        run = paragraph.add_run()
        # BEGIN field
        fldChar_begin = OxmlElement('w:fldChar')
        fldChar_begin.set(qn('w:fldCharType'), 'begin')
        run._r.append(fldChar_begin)
        # Field instruction
        instrText = OxmlElement('w:instrText')
        instrText.set(qn('xml:space'), 'preserve')
        instrText.text = r' TOC \o "1-3" \h \z \u '
        run._r.append(instrText)
        # SEPARATE field
        fldChar_sep = OxmlElement('w:fldChar')
        fldChar_sep.set(qn('w:fldCharType'), 'separate')
        run._r.append(fldChar_sep)
        # Placeholder text shown before user updates TOC in Word
        run2 = paragraph.add_run("Right-click and select 'Update Field' to generate table of contents.")
        run2.font.color.rgb = None  # Default color
        # END field
        run3 = paragraph.add_run()
        fldChar_end = OxmlElement('w:fldChar')
        fldChar_end.set(qn('w:fldCharType'), 'end')
        run3._r.append(fldChar_end)

        # Add a setting to auto-update fields when the document is opened
        try:
            settings = self.doc.settings.element
            update_fields = OxmlElement('w:updateFields')
            update_fields.set(qn('w:val'), 'true')
            settings.append(update_fields)
        except Exception as e:
            logger.warning(f"Could not set auto-update fields: {e}")

        self.doc.add_page_break()
        logger.info("Table of Contents field added.")

    def add_chapter(self, title: str, text: str, visuals: List[Dict] = None):
        logger.info(f"Adding chapter: '{title}' (text length: {len(text)})")
        # Add page break before each chapter (except the very first after the cover)
        if self._chapter_count > 0:
            self.doc.add_page_break()
        self._chapter_count += 1

        h = self.doc.add_heading(title, level=1)
        self._set_rtl_if_hebrew(h, title)
        
        # Mapping visuals for quick lookup — register by BOTH id and original_asset_id
        visual_map = {}
        if visuals:
            for v in visuals:
                # Register by 'id' key
                vid = v.get('id', '')
                if vid:
                    short_id = vid[:8].lower()
                    visual_map[short_id] = v
                    logger.debug(f"Mapped visual (id): {short_id} -> {v.get('type')} (Path: {v.get('path')})")
                # Also register by 'original_asset_id' key (may differ from 'id')
                orig_id = v.get('original_asset_id', '')
                if orig_id:
                    short_orig = orig_id[:8].lower()
                    visual_map[short_orig] = v
                    logger.debug(f"Mapped visual (orig): {short_orig} -> {v.get('type')} (Path: {v.get('path')})")

        # Strip placeholder markers (e.g. [Figure XXXXXXXX: Caption]) that the LLM
        # emits by copying the example literally — these can never be matched to a visual.
        placeholder_regex = r'\[(?:Figure|Asset:?)\s*X{4,}[:\s]*.*?\]'
        text = re.sub(placeholder_regex, '', text, flags=re.IGNORECASE)

        # Split text into lines to handle headers and lists properly
        lines = text.split('\n')
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
                
            # Handle Markers first (Special case) — support 8 to 32 alphanumeric char IDs
            marker_pattern = r'\[(?:Figure|Asset:?)\s*([a-zA-Z0-9]{8,32})[:\s]*.*?\]'
            if re.search(marker_pattern, line, re.IGNORECASE):
                # If we have a marker in the line, we process it specifically
                # We use a non-capturing group for the inner elements and capture the WHOLE tag to split cleanly
                split_pattern = r'(\[(?:Figure|Asset:?)\s*[a-zA-Z0-9]{8,32}[:\s]*.*?\])'
                parts = re.split(split_pattern, line, flags=re.IGNORECASE)
                p = self.doc.add_paragraph()
                for part in parts:
                    if not part: continue
                    match = re.match(marker_pattern, part, re.IGNORECASE)
                    if match:
                        asset_id_short = match.group(1).lower()
                        v = visual_map.get(asset_id_short)
                        img_path = v.get('path') if v else None
                        cap_text = f"Figure: {v.get('title', v.get('short_caption', 'Visual'))}" if v else f"Figure {asset_id_short}"

                        if v is not None and not (img_path and os.path.exists(img_path)):
                            import glob
                            possible = glob.glob(f".tmp/**/*{asset_id_short}*.*", recursive=True)
                            for p_path in possible:
                                if p_path.lower().endswith(('.png', '.jpg', '.jpeg', '.gif')):
                                    img_path = p_path
                                    break

                        if img_path and os.path.exists(img_path):
                            try:
                                img_p = self.doc.add_paragraph()
                                img_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                                img_p.add_run().add_picture(img_path, width=Inches(5))
                                cap = self.doc.add_paragraph(cap_text)
                                cap.style = 'Caption'
                                cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
                                self._set_rtl_if_hebrew(cap, cap_text)
                            except Exception as e:
                                logger.error(f"Failed to add picture {img_path} to document: {e}")
                                pass
                        else:
                            logger.warning(f"Visual marker found for ID '{asset_id_short}' but no matching visual found.")
                            p.add_run(part)
                    else:
                        self._add_markdown_runs(p, part)
                self._set_rtl_if_hebrew(p, line)
                continue

            # Handle Headers
            header_match = re.match(r'^(#{1,6})\s*(.*)', line)
            if header_match:
                level = len(header_match.group(1))
                h_text = header_match.group(2)
                h = self.doc.add_heading(h_text, level=min(level + 1, 9))
                self._set_rtl_if_hebrew(h, h_text)
                continue

            # Handle List Items
            list_match = re.match(r'^[\*\-\+]\s*(.*)', line)
            if list_match:
                p = self.doc.add_paragraph(style='List Bullet')
                self._add_markdown_runs(p, list_match.group(1))
                self._set_rtl_if_hebrew(p, line)
                continue
                
            num_list_match = re.match(r'^\d+\.\s*(.*)', line)
            if num_list_match:
                p = self.doc.add_paragraph(style='List Number')
                self._add_markdown_runs(p, num_list_match.group(1))
                self._set_rtl_if_hebrew(p, line)
                continue

            # Normal Paragraph
            p = self.doc.add_paragraph()
            self._add_markdown_runs(p, line)
            self._set_rtl_if_hebrew(p, line)

    def _add_markdown_runs(self, paragraph, text):
        """
        Parses bold and italic markdown and adds them as runs to a paragraph.
        """
        # Pattern for bold (***bolditalic***, **bold**, *italic*)
        pattern = r'(\*\*\*.*?\*\*\*|\*\*.*?\*\*|\*.*?\*|__.*?__| _.*?_)'
        parts = re.split(pattern, text)
        
        for part in parts:
            if not part: continue
            
            run = paragraph.add_run()
            if part.startswith('***') and part.endswith('***'):
                run.text = part[3:-3]
                run.bold = True
                run.italic = True
            elif part.startswith('**') and part.endswith('**'):
                run.text = part[2:-2]
                run.bold = True
            elif part.startswith('__') and part.endswith('__'):
                run.text = part[2:-2]
                run.bold = True
            elif (part.startswith('*') and part.endswith('*')) or (part.startswith('_') and part.endswith('_')):
                run.text = part[1:-1]
                run.italic = True
            else:
                run.text = part

    def _set_rtl_if_hebrew(self, paragraph, text):
        # Check for Hebrew characters — apply RTL silently (no per-paragraph log)
        if re.search(r'[\u0590-\u05FF]', text):
            paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            paragraph.paragraph_format.bidi = True
            for run in paragraph.runs:
                run.font.rtl = True

    def add_bibliography(self, references: List[Dict]):
        """Adds a numbered bibliography. References are rendered as [index] Title - URL,
        matching the numbered inline citations [1], [2], etc. in the report text."""
        logger.info(f"Adding bibliography with {len(references)} references.")
        self.doc.add_page_break()
        bib_heading = self.doc.add_heading("Bibliography", level=1)
        self._set_rtl_if_hebrew(bib_heading, "Bibliography")

        for ref in references:
            idx = ref.get('index', references.index(ref) + 1)
            title = ref.get('title', 'Unknown Source')
            url = ref.get('url', '')
            category = ref.get('category', '')

            p = self.doc.add_paragraph()
            # Index number in bold
            idx_run = p.add_run(f"[{idx}] ")
            idx_run.bold = True
            # Title
            title_run = p.add_run(title)
            title_run.bold = True
            # URL if available
            if url and url.startswith('http'):
                p.add_run(f" — {url}")
            # Category tag
            if category:
                cat_run = p.add_run(f"  [{category}]")
                cat_run.italic = True
            self._set_rtl_if_hebrew(p, title)

    def save(self, output_path: str):
        save_start = time.time()
        logger.info(f"Saving DOCX to: {output_path}")
        self.doc.save(output_path)
        logger.info(f"DOCX saved in {time.time() - save_start:.2f}s.")
        return output_path

def build_final_report(chapters: List[Dict], output_path: str = "Modernized_Report.docx", title: str = None) -> str:
    report_title = title or "Modernized Industry Report"
    logger.info(f"Starting build_final_report for {len(chapters)} chapters. Title: '{report_title}'")
    builder = ReportBuilder(report_title)
    builder.add_cover_page("Updated and Researched via AI Agent")
    builder.add_table_of_contents()
    
    all_refs = []
    
    for ch in chapters:
        builder.add_chapter(ch['title'], ch['draft_text'], ch.get('approved_visuals', []))
        if 'references' in ch:
            all_refs.extend(ch['references'])
    
    # Keep insertion order (matches numbered inline citations)
    seen_titles = set()
    ordered_refs = []
    for r in all_refs:
        if r['title'] not in seen_titles:
            seen_titles.add(r['title'])
            ordered_refs.append(r)
    
    # Ensure indices are assigned
    for i, ref in enumerate(ordered_refs):
        if 'index' not in ref:
            ref['index'] = i + 1
    
    builder.add_bibliography(ordered_refs)
    
    return builder.save(output_path)

def build_markdown_report(chapters: List[Dict], output_path: str = "Modernized_Report.md", title: str = None) -> str:
    report_title = title or "Modernized Industry Report"
    logger.info(f"Starting build_markdown_report for {len(chapters)} chapters. Title: '{report_title}'")
    
    md_content = []
    
    # Create export directory for markdown and images
    base_name = os.path.splitext(output_path)[0]
    export_dir = f"{base_name}_export"
    images_dir = os.path.join(export_dir, "images")
    os.makedirs(images_dir, exist_ok=True)
    
    output_md_path = os.path.join(export_dir, os.path.basename(output_path))
    
    # Cover & TOC omitted in simple markdown, just title
    md_content.append(f"# {report_title}\n")
    md_content.append(f"_Updated and Researched via AI Agent | Date: {datetime.now().strftime('%Y-%m-%d')}_\n\n")
    
    all_refs = []
    
    for ch in chapters:
        md_content.append(f"# {ch['title']}\n")
        
        visual_map = {}
        if ch.get('approved_visuals'):
            for v in ch['approved_visuals']:
                vid = v.get('id', '')
                if vid:
                    visual_map[vid[:8].lower()] = v
                orig_id = v.get('original_asset_id', '')
                if orig_id:
                    visual_map[orig_id[:8].lower()] = v
        
        text = ch['draft_text']
        placeholder_regex = r'\[(?:Figure|Asset:?)\s*X{4,}[:\s]*.*?\]'
        text = re.sub(placeholder_regex, '', text, flags=re.IGNORECASE)
        
        lines = text.split('\n')
        for line in lines:
            line = line.strip()
            if not line:
                md_content.append("")
                continue
                
            marker_pattern = r'\[(?:Figure|Asset:?)\s*([a-zA-Z0-9]{8,32})[:\s]*.*?\]'
            if re.search(marker_pattern, line, re.IGNORECASE):
                split_pattern = r'(\[(?:Figure|Asset:?)\s*[a-zA-Z0-9]{8,32}[:\s]*.*?\])'
                parts = re.split(split_pattern, line, flags=re.IGNORECASE)
                out_line = ""
                for part in parts:
                    if not part: continue
                    match = re.match(marker_pattern, part, re.IGNORECASE)
                    if match:
                        asset_id_short = match.group(1).lower()
                        v = visual_map.get(asset_id_short)
                        img_path = v.get('path') if v else None
                        cap_text = f"Figure: {v.get('title', v.get('short_caption', 'Visual'))}" if v else f"Figure {asset_id_short}"

                        if v is not None and not (img_path and os.path.exists(img_path)):
                            import glob
                            possible = glob.glob(f".tmp/**/*{asset_id_short}*.*", recursive=True)
                            for p_path in possible:
                                if p_path.lower().endswith(('.png', '.jpg', '.jpeg', '.gif')):
                                    img_path = p_path
                                    break

                        if img_path and os.path.exists(img_path):
                            try:
                                img_ext = os.path.splitext(img_path)[1]
                                if not img_ext:
                                    img_ext = ".png" # fallback
                                dest_img_name = f"{asset_id_short}{img_ext}"
                                dest_img_path = os.path.join(images_dir, dest_img_name)
                                shutil.copy2(img_path, dest_img_path)
                                rel_path = f"images/{dest_img_name}"
                            except Exception as e:
                                logger.error(f"Error copying image {img_path}: {e}")
                                rel_path = img_path # fallback
                            out_line += f"\n\n![{cap_text}]({rel_path})\n*{cap_text}*\n\n"
                        else:
                            out_line += part
                    else:
                        out_line += part
                md_content.append(out_line)
                continue
            
            md_content.append(line)
        
        md_content.append("\n---\n")
        
        if 'references' in ch:
            all_refs.extend(ch['references'])
            
    seen_titles = set()
    ordered_refs = []
    for r in all_refs:
        if r['title'] not in seen_titles:
            seen_titles.add(r['title'])
            ordered_refs.append(r)
            
    for i, ref in enumerate(ordered_refs):
        if 'index' not in ref:
            ref['index'] = i + 1
            
    if ordered_refs:
        md_content.append("# Bibliography\n")
        for ref in ordered_refs:
            idx = ref.get('index', ordered_refs.index(ref) + 1)
            title = ref.get('title', 'Unknown Source')
            url = ref.get('url', '')
            category = ref.get('category', '')
            ref_line = f"**[{idx}] {title}**"
            if url and url.startswith('http'):
                ref_line += f" — {url}"
            if category:
                ref_line += f"  _({category})_"
            md_content.append(ref_line)
            
    try:
        with open(output_md_path, "w", encoding="utf-8") as f:
            f.write("\n".join(md_content))
            
        zip_output_path = f"{base_name}.zip"
        with zipfile.ZipFile(zip_output_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            # Add markdown file
            zipf.write(output_md_path, arcname=os.path.basename(output_md_path))
            
            # Add images
            for root, _, files in os.walk(images_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = f"images/{file}"
                    zipf.write(file_path, arcname=arcname)
                    
        logger.info(f"Markdown report zipped and saved to: {zip_output_path}")
        return zip_output_path
    except Exception as e:
        logger.error(f"Failed to generate Markdown report: {e}")
        return output_path

if __name__ == "__main__":
    test_chapters = [
        {
            "title": "Introduction to AI", 
            "draft_text": "# Header 1\n## Header 2\n**Bold Text** and *Italic Text*.\n- Item 1\n- Item 2",
            "approved_visuals": [],
            "references": [{"title": "Future of AI", "url": "http://example.com", "category": "Academic"}]
        }
    ]
    path = build_final_report(test_chapters, "test_markdown.docx")
    print(f"Report saved to {path}")
