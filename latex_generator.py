"""LaTeX-based PDF generation for CV and cover letter.

Uses Jinja2 to populate .tex templates, then compiles with pdflatex.
"""

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from cv_data import CVData

TEMPLATES_DIR = Path(__file__).parent / "templates"


def escape_latex(text: str) -> str:
    """Escape LaTeX special characters in plain text."""
    # Handle backslash first (before other replacements add backslashes)
    text = text.replace('\\', r'\textbackslash{}')
    # Then handle the rest in order
    replacements = {
        '&': r'\&',
        '%': r'\%',
        '$': r'\$',
        '#': r'\#',
        '_': r'\_',
        '{': r'\{',
        '}': r'\}',
        '~': r'\textasciitilde{}',
        '^': r'\textasciicircum{}',
    }
    for char, replacement in replacements.items():
        text = text.replace(char, replacement)
    return text


def _get_jinja_env() -> Environment:
    """Create Jinja2 environment with LaTeX-safe delimiters."""
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        block_start_string='<%',
        block_end_string='%>',
        variable_start_string='<<',
        variable_end_string='>>',
        comment_start_string='<#',
        comment_end_string='#>',
        autoescape=False,
    )


def _escape_cv_data(cv: CVData) -> CVData:
    """Return a new CVData with all string fields LaTeX-escaped."""
    from cv_data import Experience, SideProject

    return CVData(
        name=escape_latex(cv.name),
        email=cv.email,  # emails go inside \\href, no escaping
        phone=escape_latex(cv.phone),
        location=escape_latex(cv.location),
        title_tagline=escape_latex(cv.title_tagline),
        linkedin=cv.linkedin,  # URLs go inside \\href, no escaping
        skills={escape_latex(k): [escape_latex(v) for v in vs] for k, vs in cv.skills.items()},
        experience=[
            Experience(
                title=escape_latex(e.title),
                company=escape_latex(e.company),
                location=escape_latex(e.location),
                dates=e.dates,  # already uses LaTeX -- for en-dash
                company_description=escape_latex(e.company_description),
                bullets=[escape_latex(b) for b in e.bullets],
            )
            for e in cv.experience
        ],
        side_projects=[
            SideProject(
                name=escape_latex(p.name),
                github_url=p.github_url,  # URL, no escaping
                bullets=[escape_latex(b) for b in p.bullets],
            )
            for p in cv.side_projects
        ],
        education={k: escape_latex(v) for k, v in cv.education.items()},
    )


def render_cv_latex(cv: CVData) -> str:
    """Render CVData into a LaTeX string using the CV template."""
    env = _get_jinja_env()
    template = env.get_template("cv_template.tex")
    escaped = _escape_cv_data(cv)
    return template.render(
        name=escaped.name,
        email=escaped.email,
        phone=escaped.phone,
        location=escaped.location,
        linkedin=escaped.linkedin,
        title_tagline=escaped.title_tagline,
        skills=escaped.skills,
        experience=escaped.experience,
        side_projects=escaped.side_projects,
        education=escaped.education,
    )


def _markdown_body_to_latex(body: str) -> str:
    """Convert a markdown cover letter body to LaTeX.

    Handles: **bold**, *italic*, ---, and paragraph breaks.
    """
    # Strip leading header block (name, email, --- etc.) that LLMs sometimes add
    lines = body.split('\n')
    body_lines = []
    in_header = True
    for line in lines:
        stripped = line.strip()
        if in_header:
            # Skip header-like lines: bold name, email, ---, empty lines
            if stripped.startswith('**') and stripped.endswith('**'):
                continue
            if '@' in stripped and '|' in stripped:
                continue
            if stripped == '---' or stripped == '':
                continue
            if stripped.startswith('Hiring') or stripped.startswith('Dear'):
                in_header = False
            else:
                in_header = False
        body_lines.append(line)

    body = '\n'.join(body_lines)

    # Escape LaTeX special chars first
    body = escape_latex(body)

    # Convert markdown bold **text** to \textbf{text}
    body = re.sub(r'\*\*(.+?)\*\*', r'\\textbf{\1}', body)
    # Convert markdown italic *text* to \textit{text}
    body = re.sub(r'\*(.+?)\*', r'\\textit{\1}', body)
    # Remove horizontal rules
    body = re.sub(r'^---+\s*$', '', body, flags=re.MULTILINE)
    # Convert double newlines to paragraph breaks
    body = re.sub(r'\n\n+', '\n\n', body)

    return body.strip()


def render_cover_letter_latex(
    name: str, email: str, phone: str, location: str, body: str,
) -> str:
    """Render a cover letter into LaTeX."""
    env = _get_jinja_env()
    template = env.get_template("cover_letter_template.tex")
    return template.render(
        name=escape_latex(name),
        email=email,
        phone=escape_latex(phone),
        location=escape_latex(location),
        body=_markdown_body_to_latex(body),
    )


def _find_pdflatex() -> str:
    """Find the pdflatex binary, checking common TexLive install paths."""
    # Check PATH first
    found = shutil.which("pdflatex")
    if found:
        return found
    # Common macOS TexLive locations
    for candidate in [
        "/usr/local/texlive/2026/bin/universal-darwin/pdflatex",
        "/usr/local/texlive/2025/bin/universal-darwin/pdflatex",
        "/Library/TeX/texbin/pdflatex",
    ]:
        if os.path.isfile(candidate):
            return candidate
    raise RuntimeError("pdflatex not found. Install TexLive: brew install --cask mactex-no-gui")


def compile_latex(tex_path: str, pdf_path: str) -> None:
    """Compile a .tex file to PDF using pdflatex.

    Raises RuntimeError if compilation fails.
    """
    tex_path = Path(tex_path)
    pdf_path = Path(pdf_path)
    work_dir = tex_path.parent
    pdflatex = _find_pdflatex()

    result = subprocess.run(
        [pdflatex, "-interaction=nonstopmode", "-output-directory", str(work_dir), str(tex_path)],
        capture_output=True,
        text=True,
        timeout=30,
    )

    compiled_pdf = work_dir / tex_path.with_suffix(".pdf").name

    if result.returncode != 0 or not compiled_pdf.exists():
        error_lines = [line for line in result.stdout.split('\n') if line.startswith('!')]
        error_msg = '\n'.join(error_lines[:5]) if error_lines else result.stdout[-500:]
        raise RuntimeError(f"pdflatex compilation failed:\n{error_msg}")

    if compiled_pdf.resolve() != pdf_path.resolve():
        shutil.move(str(compiled_pdf), str(pdf_path))


def _count_pages(pdf_path: str) -> int:
    """Count pages in a PDF file."""
    content = Path(pdf_path).read_bytes()
    match = re.search(rb'/Count\s+(\d+)', content)
    return int(match.group(1)) if match else 1


def generate_cv_pdf(cv: CVData, output_path: str) -> int:
    """Generate a CV PDF from structured data. Returns page count."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tex_content = render_cv_latex(cv)
        tex_path = os.path.join(tmpdir, "cv.tex")
        Path(tex_path).write_text(tex_content, encoding="utf-8")
        compile_latex(tex_path, output_path)
    return _count_pages(output_path)


def generate_cover_letter_pdf(
    name: str, email: str, phone: str, location: str,
    body: str, output_path: str,
) -> int:
    """Generate a cover letter PDF. Returns page count."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tex_content = render_cover_letter_latex(name, email, phone, location, body)
        tex_path = os.path.join(tmpdir, "cover_letter.tex")
        Path(tex_path).write_text(tex_content, encoding="utf-8")
        compile_latex(tex_path, output_path)
    return _count_pages(output_path)
