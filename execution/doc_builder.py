from docx import Document
from docx.shared import Inches, Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
import os
import re
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
        self._setup_styles()

    def _setup_styles(self):
        # Could customize default styles here if needed
        pass

    def add_cover_page(self, subtitle: str):
        logger.info(f"Adding cover page with subtitle: '{subtitle}'")
        # Add a placeholder for a logo
        self.doc.add_page_break() # Start with a gap
        
        title_para = self.doc.add_heading(self.title, 0)
        title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        
        subtitle_para = self.doc.add_paragraph(subtitle)
        subtitle_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        
        date_para = self.doc.add_paragraph(f"Date: {datetime.now().strftime('%Y-%m-%d')}")
        date_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        
        self.doc.add_page_break()

    def add_chapter(self, title: str, text: str, visuals: List[Dict] = None):
        logger.info(f"Adding chapter: '{title}' (text length: {len(text)})")
        h = self.doc.add_heading(title, level=1)
        self._set_rtl_if_hebrew(h, title)
        
        # Mapping visuals for quick lookup
        visual_map = {}
        if visuals:
            for v in visuals:
                vid = v.get('original_asset_id', v.get('id', ''))
                if vid:
                    short_id = vid[:8].lower()
                    visual_map[short_id] = v
                    logger.debug(f"Mapped visual: {short_id} -> {v.get('type')} (Path: {v.get('path')})")
        
        # Split text into lines to handle headers and lists properly
        lines = text.split('\n')
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
                
            # Handle Markers first (Special case)
            marker_regex = r'\[(?:Figure|Asset:?)\s*([a-f0-9]{8})[:\s]*.*?\]'
            if re.search(marker_regex, line, re.IGNORECASE):
                # If we have a marker in the line, we process it specifically
                parts = re.split(f'({marker_regex})', line, flags=re.IGNORECASE)
                p = self.doc.add_paragraph()
                for part in parts:
                    if not part: continue
                    match = re.match(marker_regex, part, re.IGNORECASE)
                    if match:
                        asset_id_short = match.group(1).lower()
                        if asset_id_short in visual_map:
                            v = visual_map[asset_id_short]
                            if 'path' in v and os.path.exists(v['path']):
                                try:
                                    img_p = self.doc.add_paragraph()
                                    img_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                                    img_p.add_run().add_picture(v['path'], width=Inches(5))
                                    cap_text = f"Figure: {v.get('title', v.get('short_caption', 'Visual'))}"
                                    cap = self.doc.add_paragraph(cap_text)
                                    cap.style = 'Caption'
                                    cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
                                    self._set_rtl_if_hebrew(cap, cap_text)
                                except Exception as e:
                                    logger.error(f"Failed to add picture {v['path']} to document: {e}")
                                    # Remove the empty paragraph if we couldn't add the picture
                                    # Actually, just leave it or don't worry about it. 
                                    # But let's try to be clean.
                                    pass
                        else:
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
        # Check for Hebrew characters
        if re.search(r'[\u0590-\u05FF]', text):
            logger.debug(f"Hebrew detected, applying RTL formatting.")
            paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            paragraph.paragraph_format.bidi = True
            for run in paragraph.runs:
                run.font.rtl = True

    def add_bibliography(self, references: List[Dict]):
        logger.info(f"Adding bibliography with {len(references)} unique references.")
        self.doc.add_page_break()
        self.doc.add_heading("Bibliography", level=1)
        
        # Categorize references
        categories = {
            "Academic": "Academic & Scholarly Research",
            "Web": "Web Sources & Industry Reports",
            "Original": "Original Report Documents",
            "Uploaded": "Uploaded Reference Materials"
        }
        
        # Group references by category
        grouped = {}
        for ref in references:
            cat = ref.get('category', 'Web')
            if cat not in grouped:
                grouped[cat] = []
            grouped[cat].append(ref)
            
        for cat_key, cat_title in categories.items():
            if cat_key in grouped:
                cat_head = self.doc.add_heading(cat_title, level=2)
                self._set_rtl_if_hebrew(cat_head, cat_title)
                
                for ref in grouped[cat_key]:
                    p = self.doc.add_paragraph(style='List Bullet')
                    title = ref.get('title', 'Unknown Source')
                    run = p.add_run(title)
                    run.bold = True
                    self._set_rtl_if_hebrew(p, title)
                    if 'url' in ref and ref['url'] and ref['url'].startswith('http'):
                        p.add_run(f" - [Link]({ref['url']})")
                    elif 'url' in ref and ref['url']:
                        p.add_run(f" ({ref['url']})")

    def save(self, output_path: str):
        save_start = time.time()
        logger.info(f"Saving DOCX to: {output_path}")
        self.doc.save(output_path)
        logger.info(f"DOCX saved in {time.time() - save_start:.2f}s.")
        return output_path

def build_final_report(chapters: List[Dict], output_path: str = "Modernized_Report.docx") -> str:
    logger.info(f"Starting build_final_report for {len(chapters)} chapters.")
    builder = ReportBuilder("Modernized Industry Report")
    builder.add_cover_page("Updated and Researched via AI Agent")
    
    all_refs = []
    
    for ch in chapters:
        builder.add_chapter(ch['title'], ch['draft_text'], ch.get('approved_visuals', []))
        if 'references' in ch:
            all_refs.extend(ch['references'])
    
    unique_refs = {r['title']: r for r in all_refs}.values()
    builder.add_bibliography(list(unique_refs))
    
    return builder.save(output_path)

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
