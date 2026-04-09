"""Tests for eval_criteria with current pipeline architecture."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "eval"))

from eval_criteria import (
    run_automated_checks,
    keyword_match,
    company_research_completeness,
    role_analysis_completeness,
)

SAMPLE_STATE = {
    "job_description": "Senior PM role. Must have Python and SQL. Team leadership required.",
    "company_research": "Company: Acme. Role: Senior PM. Compensation: $150k. Notable: Series B.",
    "role_analysis": "MUST-HAVES: Python, SQL. NICE-TO-HAVES: React. KEY SIGNALS: data-driven. ROLE TYPE: IC.",
    "gap_analysis": (
        "- Technical skills match: 7/10 — solid Python background\n"
        "- Seniority level match: 8/10 — right level\n"
        "- Domain/industry experience: 6/10 — adjacent\n"
        "- Leadership & soft skills: 7/10 — led teams\n"
        "- Culture & values fit: 7/10 — fits culture"
    ),
    "cover_letter_markdown": (
        "Dear Hiring Manager,\n\n"
        "I am excited about the Senior PM role at Acme. Python and SQL are core to my work.\n\n"
        "Best,\nTest Candidate"
    ),
}


def test_keyword_match_uses_cover_letter():
    result = keyword_match(SAMPLE_STATE)
    assert result["name"] == "JD keyword match"
    assert result["score"] > 0, "Should find keyword matches in cover letter"


def test_role_analysis_completeness():
    result = role_analysis_completeness(SAMPLE_STATE)
    assert result["score"] >= 3, f"Should find at least 3/4 sections, got {result['score']}"


def test_run_automated_checks_no_crash_without_cv():
    """run_automated_checks should not crash when cv_markdown/cv_json are absent."""
    results = run_automated_checks(SAMPLE_STATE, candidate_name="Test Candidate")
    assert len(results) > 0
    names = [r["name"] for r in results]
    assert "Company research completeness" in names
    assert "Role analysis completeness" in names


def test_run_automated_checks_no_cv_word_count_without_cv():
    """cv_word_count should not appear in results when cv_markdown is absent."""
    results = run_automated_checks(SAMPLE_STATE, candidate_name="Test Candidate")
    names = [r["name"] for r in results]
    assert "CV word count" not in names, "cv_word_count should be skipped when no cv data"
