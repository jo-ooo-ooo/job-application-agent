"""Tests for LaTeX CV and cover letter generation."""

import os
import pytest
import tempfile
from pathlib import Path

from cv_data import CVData, Experience, SideProject
from latex_generator import (
    render_cv_latex,
    render_cover_letter_latex,
    compile_latex,
    generate_cv_pdf,
    generate_cover_letter_pdf,
    escape_latex,
)

SAMPLE_CV = CVData(
    name="Jane Doe",
    email="jane@example.com",
    phone="+49 123 456",
    location="Berlin, Germany",
    title_tagline="Senior Product Manager",
    linkedin="https://linkedin.com/in/janedoe",
    skills={"Product": ["A/B testing", "roadmaps"], "Technical": ["SQL", "Python"]},
    experience=[
        Experience(
            title="Senior PM",
            company="Acme Corp",
            location="Berlin",
            dates="2022 -- 2025",
            company_description="SaaS platform",
            bullets=["Led team of 10", "Grew revenue by 30%"],
        ),
    ],
    side_projects=[
        SideProject(
            name="Cool Tool",
            github_url="https://github.com/user/cool",
            bullets=["Built a CLI tool"],
        ),
    ],
    education={"degree": "BA in CS", "university": "MIT"},
)


class TestEscapeLatex:
    def test_ampersand(self):
        assert escape_latex("AT&T") == r"AT\&T"

    def test_percent(self):
        assert escape_latex("20%") == r"20\%"

    def test_dollar(self):
        assert escape_latex("$100") == r"\$100"

    def test_hash(self):
        assert escape_latex("#1") == r"\#1"

    def test_underscore(self):
        assert escape_latex("my_var") == r"my\_var"

    def test_tilde(self):
        assert escape_latex("~approx") == r"\textasciitilde{}approx"

    def test_caret(self):
        assert escape_latex("x^2") == r"x\textasciicircum{}2"

    def test_braces(self):
        assert escape_latex("{test}") == r"\{test\}"

    def test_plain_text_unchanged(self):
        assert escape_latex("Hello world") == "Hello world"

    def test_multiple_special_chars(self):
        result = escape_latex("Cost: $100 & 20% off")
        assert r"\$100" in result
        assert r"\&" in result
        assert r"20\%" in result


class TestRenderCvLatex:
    def test_contains_name(self):
        tex = render_cv_latex(SAMPLE_CV)
        assert "Jane Doe" in tex

    def test_contains_experience(self):
        tex = render_cv_latex(SAMPLE_CV)
        assert "Acme Corp" in tex
        assert "Senior PM" in tex

    def test_contains_skills(self):
        tex = render_cv_latex(SAMPLE_CV)
        assert "A/B testing" in tex
        assert "SQL" in tex

    def test_contains_side_projects(self):
        tex = render_cv_latex(SAMPLE_CV)
        assert "Cool Tool" in tex
        assert "github.com/user/cool" in tex

    def test_contains_education(self):
        tex = render_cv_latex(SAMPLE_CV)
        assert "MIT" in tex
        assert "BA in CS" in tex

    def test_github_url_rendered_in_header(self):
        # github field was previously dropped by render_cv_latex — verify it appears
        cv = CVData(
            name="Jane", email="a@b.com", phone="+1", location="Berlin",
            title_tagline="PM", skills={}, experience=[],
            education={"degree": "BA", "university": "U"},
            github="https://github.com/testuser",
        )
        tex = render_cv_latex(cv)
        assert "github.com/testuser" in tex

    def test_no_side_projects_section_when_empty(self):
        cv = CVData(
            name="Jane", email="a@b.com", phone="+1", location="Berlin",
            title_tagline="PM", skills={}, experience=[], education={"degree": "BA", "university": "U"},
        )
        tex = render_cv_latex(cv)
        assert "Projects" not in tex

    def test_special_chars_escaped_in_bullets(self):
        cv = CVData(
            name="Jane", email="a@b.com", phone="+1", location="Berlin",
            title_tagline="PM", skills={},
            experience=[
                Experience(
                    title="PM", company="AT&T", location="NYC",
                    dates="2022 -- 2025", bullets=["Saved $1M & improved 20% efficiency"],
                ),
            ],
            education={"degree": "BA", "university": "U"},
        )
        tex = render_cv_latex(cv)
        assert r"AT\&T" in tex
        assert r"\$1M" in tex
        assert r"20\%" in tex


class TestRenderCoverLetterLatex:
    def test_contains_name(self):
        tex = render_cover_letter_latex("Jane Doe", "jane@example.com", "+1", "Berlin", "Dear Manager,\n\nI am interested.")
        assert "Jane Doe" in tex

    def test_contains_body(self):
        tex = render_cover_letter_latex("Jane", "a@b.com", "+1", "Berlin", "This is the body text.")
        assert "This is the body text" in tex


class TestCompileLatex:
    def test_compiles_minimal_document(self):
        tex = r"""\documentclass{article}
\begin{document}
Hello World
\end{document}"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tex_path = Path(tmpdir) / "test.tex"
            pdf_path = Path(tmpdir) / "test.pdf"
            tex_path.write_text(tex)
            compile_latex(str(tex_path), str(pdf_path))
            assert pdf_path.exists()
            assert pdf_path.stat().st_size > 0

    def test_compile_error_raises(self):
        tex = r"\documentclass{article}\begin{document}\invalidcommand\end{document}"
        with tempfile.TemporaryDirectory() as tmpdir:
            tex_path = Path(tmpdir) / "bad.tex"
            pdf_path = Path(tmpdir) / "bad.pdf"
            tex_path.write_text(tex)
            with pytest.raises(RuntimeError, match="pdflatex"):
                compile_latex(str(tex_path), str(pdf_path))


class TestGenerateCvPdf:
    def test_generates_pdf_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "cv.pdf")
            pages = generate_cv_pdf(SAMPLE_CV, output_path)
            assert os.path.exists(output_path)
            assert pages >= 1

    def test_returns_page_count(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "cv.pdf")
            pages = generate_cv_pdf(SAMPLE_CV, output_path)
            assert isinstance(pages, int)
            assert pages >= 1


class TestGenerateCoverLetterPdf:
    def test_generates_pdf_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "cl.pdf")
            pages = generate_cover_letter_pdf(
                "Jane Doe", "jane@example.com", "+1", "Berlin",
                "Dear Manager,\n\nI am interested in the role.",
                output_path,
            )
            assert os.path.exists(output_path)
            assert pages >= 1
