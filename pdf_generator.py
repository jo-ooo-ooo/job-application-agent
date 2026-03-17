"""Markdown to PDF conversion using fpdf2 (pure Python, no system dependencies)."""

import re
from fpdf import FPDF

# Unicode → ASCII-safe replacements for the built-in Helvetica font
UNICODE_REPLACEMENTS = {
    "\u2014": "--",     # em dash
    "\u2013": "-",      # en dash
    "\u2018": "'",      # left single quote
    "\u2019": "'",      # right single quote
    "\u201c": '"',      # left double quote
    "\u201d": '"',      # right double quote
    "\u2026": "...",    # ellipsis
    "\u2022": "-",      # bullet (we handle bullets separately)
    "\u00a0": " ",      # non-breaking space
    "\u2032": "'",      # prime
    "\u2033": '"',      # double prime
    "\u00b7": "-",      # middle dot
    "\u2010": "-",      # hyphen
    "\u2011": "-",      # non-breaking hyphen
    "\u2012": "-",      # figure dash
    "\u00e9": "e",      # é
    "\u00e8": "e",      # è
    "\u00fc": "u",      # ü
    "\u00f6": "o",      # ö
    "\u00e4": "a",      # ä
}


def _sanitize(text: str) -> str:
    """Replace Unicode characters that Helvetica can't handle."""
    for char, replacement in UNICODE_REPLACEMENTS.items():
        text = text.replace(char, replacement)
    # Catch any remaining non-latin1 characters
    try:
        text.encode("latin-1")
    except UnicodeEncodeError:
        text = text.encode("latin-1", errors="replace").decode("latin-1")
    return text


class CVPdf(FPDF):
    """Custom PDF class with CV styling."""

    def __init__(self):
        super().__init__("P", "mm", "A4")
        self.set_auto_page_break(auto=True, margin=15)
        self.set_margins(20, 15, 20)
        self.add_page()
        self.set_font("Helvetica", size=10)

    def _write_line(self, text: str):
        """Write a single line of markdown-ish text, handling bold/italic."""
        text = _sanitize(text)
        parts = re.split(r'(\*\*.*?\*\*|\*.*?\*)', text)
        for part in parts:
            if part.startswith("**") and part.endswith("**"):
                self.set_font("Helvetica", "B", self.font_size_pt)
                self.write(5, part[2:-2])
                self.set_font("Helvetica", "", self.font_size_pt)
            elif part.startswith("*") and part.endswith("*"):
                self.set_font("Helvetica", "I", self.font_size_pt)
                self.write(5, part[1:-1])
                self.set_font("Helvetica", "", self.font_size_pt)
            else:
                self.write(5, part)


def generate_pdf_from_markdown(md_content: str, output_path: str) -> int:
    """Convert markdown to PDF using fpdf2.

    Args:
        md_content: Markdown string to convert.
        output_path: Where to save the PDF.

    Returns:
        Number of pages in the generated PDF.
    """
    pdf = CVPdf()
    lines = md_content.split("\n")
    i = 0

    while i < len(lines):
        line = lines[i].rstrip()

        # Skip empty lines (add small spacing)
        if not line:
            pdf.ln(2)
            i += 1
            continue

        # H1: # Title
        if line.startswith("# ") and not line.startswith("## "):
            pdf.set_font("Helvetica", "B", 18)
            pdf._write_line(line[2:])
            pdf.ln(7)
            pdf.set_draw_color(34, 34, 34)
            pdf.set_line_width(0.4)
            pdf.line(20, pdf.get_y(), 190, pdf.get_y())
            pdf.ln(3)
            pdf.set_font("Helvetica", "", 10)
            i += 1
            continue

        # H2: ## Section
        if line.startswith("## "):
            pdf.ln(3)
            pdf.set_font("Helvetica", "B", 12)
            pdf.set_text_color(51, 51, 51)
            pdf._write_line(line[3:])
            pdf.ln(5)
            pdf.set_draw_color(204, 204, 204)
            pdf.set_line_width(0.2)
            pdf.line(20, pdf.get_y(), 190, pdf.get_y())
            pdf.ln(2)
            pdf.set_text_color(34, 34, 34)
            pdf.set_font("Helvetica", "", 10)
            i += 1
            continue

        # H3: ### Subsection
        if line.startswith("### "):
            pdf.ln(2)
            pdf.set_font("Helvetica", "B", 10.5)
            pdf._write_line(line[4:])
            pdf.ln(5)
            pdf.set_font("Helvetica", "", 10)
            i += 1
            continue

        # Horizontal rule
        if line.startswith("---"):
            pdf.set_draw_color(204, 204, 204)
            pdf.set_line_width(0.2)
            pdf.line(20, pdf.get_y() + 1, 190, pdf.get_y() + 1)
            pdf.ln(3)
            i += 1
            continue

        # Bullet point
        if line.startswith("- ") or line.startswith("* "):
            pdf.set_font("Helvetica", "", 10)
            bullet_text = line[2:]
            x = pdf.get_x()
            pdf.set_x(x + 3)
            pdf.write(5, "- ")
            pdf._write_line(bullet_text)
            pdf.ln(5)
            i += 1
            continue

        # Regular paragraph
        pdf.set_font("Helvetica", "", 10)
        pdf._write_line(line)
        pdf.ln(5)
        i += 1

    pdf.output(output_path)
    return pdf.pages_count
