"""Unit tests for pure functions — scoring, question parsing, section extraction, PDF sanitization."""

import pytest
from scoring import (
    parse_dimension_scores,
    compute_weighted_score,
    get_recommendation,
    is_borderline,
    format_score_summary,
    DIMENSION_WEIGHTS,
)
from pdf_generator import _sanitize


# ── scoring.py: parse_dimension_scores ────────────────────────

class TestParseDimensionScores:
    def test_standard_format(self):
        text = (
            "SCORING BREAKDOWN:\n"
            "- Technical skills match: 7/10 — solid Python and data skills\n"
            "- Seniority level match: 8/10 — matches senior PM level\n"
            "- Domain/industry experience: 5/10 — no fintech background\n"
            "- Leadership & soft skills: 9/10 — strong cross-functional leadership\n"
            "- Culture & values fit: 6/10 — remote culture may differ\n"
        )
        scores = parse_dimension_scores(text)
        assert scores["technical_skills"]["score"] == 7
        assert scores["seniority_level"]["score"] == 8
        assert scores["domain_experience"]["score"] == 5
        assert scores["leadership_soft_skills"]["score"] == 9
        assert scores["culture_values"]["score"] == 6

    def test_justification_extracted(self):
        text = "- Technical skills match: 7/10 — solid Python and data skills"
        scores = parse_dimension_scores(text)
        assert scores["technical_skills"]["justification"] == "solid Python and data skills"

    def test_no_justification(self):
        text = "- Technical skills match: 7/10"
        scores = parse_dimension_scores(text)
        assert scores["technical_skills"]["score"] == 7
        assert scores["technical_skills"]["justification"] == ""

    def test_bold_markers_stripped(self):
        text = "- **Technical skills match**: 7/10 — good"
        scores = parse_dimension_scores(text)
        assert scores["technical_skills"]["score"] == 7

    def test_alias_variations(self):
        """Different label phrasings should map to the same key."""
        cases = [
            ("- Technical match: 7/10", "technical_skills"),
            ("- Seniority match: 8/10", "seniority_level"),
            ("- Industry experience: 5/10", "domain_experience"),
            ("- Leadership: 9/10", "leadership_soft_skills"),
            ("- Culture fit: 6/10", "culture_values"),
        ]
        for text, expected_key in cases:
            scores = parse_dimension_scores(text)
            assert expected_key in scores, f"Expected {expected_key} from: {text}"

    def test_irrelevant_lines_ignored(self):
        text = (
            "Some intro text\n"
            "- Technical skills match: 7/10 — good\n"
            "Random commentary here\n"
            "- Culture & values fit: 6/10 — ok\n"
        )
        scores = parse_dimension_scores(text)
        assert len(scores) == 2
        assert "technical_skills" in scores
        assert "culture_values" in scores

    def test_empty_input(self):
        assert parse_dimension_scores("") == {}

    def test_no_matching_lines(self):
        assert parse_dimension_scores("Just some random text\nNo scores here") == {}


# ── scoring.py: compute_weighted_score ────────────────────────

class TestComputeWeightedScore:
    def test_all_perfect(self):
        scores = {k: {"score": 10, "justification": ""} for k in DIMENSION_WEIGHTS}
        assert compute_weighted_score(scores) == 100.0

    def test_all_zero(self):
        scores = {k: {"score": 0, "justification": ""} for k in DIMENSION_WEIGHTS}
        assert compute_weighted_score(scores) == 0.0

    def test_partial_dimensions(self):
        """If only some dimensions are present, normalize by available weights."""
        scores = {"technical_skills": {"score": 8, "justification": ""}}
        # 8 * 0.25 / 0.25 * 10 = 80
        assert compute_weighted_score(scores) == 80.0

    def test_empty_scores(self):
        assert compute_weighted_score({}) == 0

    def test_mixed_scores(self):
        scores = {
            "technical_skills": {"score": 7, "justification": ""},
            "seniority_level": {"score": 8, "justification": ""},
            "domain_experience": {"score": 5, "justification": ""},
            "leadership_soft_skills": {"score": 9, "justification": ""},
            "culture_values": {"score": 6, "justification": ""},
        }
        # (7*0.25 + 8*0.20 + 5*0.25 + 9*0.15 + 6*0.15) / 1.0 * 10
        expected = (1.75 + 1.6 + 1.25 + 1.35 + 0.9) / 1.0 * 10
        assert abs(compute_weighted_score(scores) - expected) < 0.01


# ── scoring.py: get_recommendation ────────────────────────────

class TestGetRecommendation:
    def test_strong_apply(self):
        assert get_recommendation(85) == "STRONG APPLY"
        assert get_recommendation(80) == "STRONG APPLY"

    def test_apply(self):
        assert get_recommendation(70) == "APPLY"
        assert get_recommendation(60) == "APPLY"

    def test_strategic_apply(self):
        assert get_recommendation(55) == "STRATEGIC APPLY"
        assert get_recommendation(50) == "STRATEGIC APPLY"

    def test_skip(self):
        assert get_recommendation(40) == "SKIP"
        assert get_recommendation(0) == "SKIP"

    def test_boundary_values(self):
        assert get_recommendation(79.9) == "APPLY"
        assert get_recommendation(59.9) == "STRATEGIC APPLY"
        assert get_recommendation(49.9) == "SKIP"


# ── scoring.py: is_borderline ─────────────────────────────────

class TestIsBorderline:
    def test_in_range(self):
        assert is_borderline(50) is True
        assert is_borderline(45) is True
        assert is_borderline(65) is True
        assert is_borderline(55) is True

    def test_out_of_range(self):
        assert is_borderline(44) is False
        assert is_borderline(66) is False
        assert is_borderline(80) is False
        assert is_borderline(30) is False


# ── scoring.py: format_score_summary ──────────────────────────

class TestFormatScoreSummary:
    def test_output_contains_key_info(self):
        scores = {
            "technical_skills": {"score": 7, "justification": "good"},
            "seniority_level": {"score": 8, "justification": "fine"},
        }
        output = format_score_summary(scores, 75.0, "APPLY")
        assert "75/100" in output
        assert "APPLY" in output
        assert "Technical skills" in output
        assert "7/10" in output

    def test_missing_dimensions_shown(self):
        scores = {"technical_skills": {"score": 7, "justification": ""}}
        output = format_score_summary(scores, 70.0, "APPLY")
        assert "missing" in output.lower()


# ── main.py: _extract_questions ───────────────────────────────

# Import the private function for testing
from main import _extract_questions


class TestExtractQuestions:
    def test_bullet_format(self):
        text = (
            "Some analysis...\n\n"
            "QUESTIONS:\n"
            "- Do you have experience with Kubernetes?\n"
            "- Have you worked with gRPC?\n"
        )
        qs = _extract_questions(text)
        assert len(qs) == 2
        assert "Kubernetes" in qs[0]
        assert "gRPC" in qs[1]

    def test_numbered_format(self):
        text = (
            "QUESTIONS:\n"
            "1. Do you have experience with Kubernetes?\n"
            "2. Have you worked with gRPC?\n"
        )
        qs = _extract_questions(text)
        assert len(qs) == 2

    def test_bold_questions_header(self):
        text = (
            "**QUESTIONS:**\n"
            "- Do you have experience with Kubernetes?\n"
        )
        qs = _extract_questions(text)
        assert len(qs) == 1

    def test_questions_with_bold_and_quotes(self):
        text = (
            "QUESTIONS:\n"
            '1. **"Do you have experience with Kubernetes?"**\n'
            '2. **"Have you worked with gRPC?"**\n'
        )
        qs = _extract_questions(text)
        assert len(qs) == 2
        assert "**" not in qs[0]

    def test_none_questions(self):
        text = "QUESTIONS:\nNone — gaps are clear."
        qs = _extract_questions(text)
        assert qs == []

    def test_dash_none(self):
        text = "QUESTIONS:\n- None"
        qs = _extract_questions(text)
        assert qs == []

    def test_no_questions_section(self):
        text = "Some analysis without a questions section."
        qs = _extract_questions(text)
        assert qs == []

    def test_stops_at_next_section(self):
        text = (
            "QUESTIONS:\n"
            "- Do you have experience with K8s?\n"
            "**Recommendation**\n"
            "This should not be a question.\n"
        )
        qs = _extract_questions(text)
        assert len(qs) == 1

    def test_short_lines_skipped(self):
        text = (
            "QUESTIONS:\n"
            "- Yes\n"
            "- Do you have experience with distributed systems and microservices?\n"
        )
        qs = _extract_questions(text)
        assert len(qs) == 1  # "Yes" is too short (<10 chars)


# ── main.py: _extract_section ─────────────────────────────────

from main import _extract_section


class TestExtractSection:
    def test_extract_cv(self):
        text = "# CV\nJane Doe\n## Skills\n---\n# Cover Letter\nDear hiring manager"
        result = _extract_section(text, "CV", "fallback")
        assert "Jane Doe" in result
        assert "Dear hiring manager" not in result

    def test_extract_cover_letter(self):
        text = "# CV\nJane Doe\n# Cover Letter\nDear hiring manager"
        result = _extract_section(text, "Cover Letter", "fallback")
        assert "Dear hiring manager" in result
        assert "Jane Doe" not in result

    def test_fallback_when_missing(self):
        text = "Some unrelated content"
        result = _extract_section(text, "CV", "fallback text")
        assert result == "fallback text"

    def test_revised_cv_header(self):
        text = "## Revised CV\nUpdated content here\n# Cover Letter\nLetter"
        result = _extract_section(text, "CV", "fallback")
        assert "Updated content" in result


# ── pdf_generator.py: _sanitize ───────────────────────────────

class TestSanitize:
    def test_em_dash(self):
        assert _sanitize("hello \u2014 world") == "hello -- world"

    def test_smart_quotes(self):
        assert _sanitize("\u201chello\u201d") == '"hello"'
        assert _sanitize("\u2018hello\u2019") == "'hello'"

    def test_ellipsis(self):
        assert _sanitize("wait\u2026") == "wait..."

    def test_accented_chars(self):
        assert _sanitize("caf\u00e9") == "cafe"
        assert _sanitize("\u00fcber") == "uber"

    def test_plain_ascii_unchanged(self):
        assert _sanitize("hello world 123") == "hello world 123"

    def test_non_latin1_fallback(self):
        """Characters not in our map or latin-1 should be replaced, not crash."""
        result = _sanitize("hello \u4e16\u754c")  # Chinese characters
        assert "hello" in result  # Should not crash


# ── tools.py: _read_file path restriction ─────────────────────

from tools import _read_file, PROJECT_DIR


class TestReadFile:
    def test_path_traversal_blocked(self):
        result = _read_file("../../etc/passwd")
        assert "denied" in result.lower() or "error" in result.lower()

    def test_nonexistent_file(self):
        result = _read_file("nonexistent_file_12345.txt")
        assert "not found" in result.lower()

    def test_reads_existing_file(self):
        result = _read_file("requirements.txt")
        assert "anthropic" in result
