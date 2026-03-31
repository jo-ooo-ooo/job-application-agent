"""Tests for multi-agent coordination — parallel research and critic loop."""

import pytest
from unittest.mock import patch, MagicMock
from agents import run_parallel_research, run_critic_loop, _split_revision, CriticResult, _extract_revision_issues
from agents import _format_cv_for_review
import json


class TestRunParallelResearch:
    """Test that company and role research run in parallel and return combined results."""

    @patch("agents.run_step")
    def test_returns_both_results(self, mock_run_step):
        """Both agents should run and their results should be in the returned dict."""
        def side_effect(client, system_prompt, user_message, **kwargs):
            if "Research the company" in user_message:
                return "Company: Acme Corp, Series B, 200 employees"
            return "MUST-HAVES:\n- Python\n- 5 years PM experience"

        mock_run_step.side_effect = side_effect

        result = run_parallel_research(
            client=MagicMock(),
            job_description="Senior PM role at Acme Corp",
            logger=MagicMock(),
        )

        assert "company_research" in result
        assert "role_analysis" in result
        assert "Acme Corp" in result["company_research"]
        assert "MUST-HAVES" in result["role_analysis"]

    @patch("agents.run_step")
    def test_calls_run_step_twice(self, mock_run_step):
        """Should make exactly 2 run_step calls (company + role)."""
        mock_run_step.return_value = "some result"

        run_parallel_research(
            client=MagicMock(),
            job_description="Some JD",
            logger=MagicMock(),
        )

        assert mock_run_step.call_count == 2

    @patch("agents.run_step")
    def test_one_agent_fails_other_still_returns(self, mock_run_step):
        """If one agent fails, the other should still return its result."""
        def side_effect(client, system_prompt, user_message, **kwargs):
            if "Research the company" in user_message:
                raise Exception("API error")
            return "MUST-HAVES:\n- Python"

        mock_run_step.side_effect = side_effect

        result = run_parallel_research(
            client=MagicMock(),
            job_description="Some JD",
            logger=MagicMock(),
        )

        assert "Error" in result["company_research"]
        assert "MUST-HAVES" in result["role_analysis"]


class TestRunCriticLoop:
    """Test that the critic reviews and the writer revises in a loop."""

    @patch("agents.run_step")
    def test_approved_on_first_try(self, mock_run_step):
        """If critic says APPROVED, no revision happens."""
        mock_run_step.return_value = "APPROVED"

        result = run_critic_loop(
            client=MagicMock(),
            job_description="Some JD",
            role_analysis="MUST-HAVES: Python",
            cv_markdown="# Jane Doe\n## Experience\n...",
            cover_letter_markdown="Dear Manager,\n...",
            logger=MagicMock(),
        )

        assert result.iterations == 1
        assert result.approved is True
        assert result.cv_markdown == "# Jane Doe\n## Experience\n..."
        assert result.cover_letter_markdown == "Dear Manager,\n..."
        assert "APPROVED" in result.status

    @patch("agents.run_step")
    def test_revision_then_approved(self, mock_run_step):
        """Critic requests revision, writer fixes, critic approves."""
        mock_run_step.side_effect = [
            "REVISIONS NEEDED:\n- CV: Add Python to skills section",
            "## REVISED CV\n# Jane Doe\n## Experience\n...\n\n## REVISED COVER LETTER\nDear Manager, revised...",
            "APPROVED",
        ]

        result = run_critic_loop(
            client=MagicMock(),
            job_description="Some JD",
            role_analysis="MUST-HAVES: Python",
            cv_markdown="# Jane Doe\n## Experience\n...",
            cover_letter_markdown="Dear Manager,\n...",
            logger=MagicMock(),
        )

        assert result.iterations == 2
        assert result.approved is True
        assert len(result.rounds) == 2
        assert result.rounds[0].approved is False
        assert result.rounds[1].approved is True

    @patch("agents.run_step")
    def test_max_iterations_reached(self, mock_run_step):
        """After max iterations, return latest version even without approval."""
        mock_run_step.return_value = "REVISIONS NEEDED:\n- CV: Still needs work"

        result = run_critic_loop(
            client=MagicMock(),
            job_description="Some JD",
            role_analysis="MUST-HAVES: Python",
            cv_markdown="# Jane Doe",
            cover_letter_markdown="Dear Manager",
            logger=MagicMock(),
            max_iterations=3,
        )

        assert result.iterations == 3
        assert result.approved is False
        assert "MAX_ITERATIONS" in result.status

    @patch("agents.run_step")
    def test_revision_output_parsed_correctly(self, mock_run_step):
        """Writer revision output should be split into CV and CL by header markers."""
        mock_run_step.side_effect = [
            "REVISIONS NEEDED:\n- CV: Add metrics",
            "## REVISED CV\n# Jane Doe\nUpdated CV content\n\n## REVISED COVER LETTER\nDear Manager,\nUpdated CL content",
            "APPROVED",
        ]

        result = run_critic_loop(
            client=MagicMock(),
            job_description="Some JD",
            role_analysis="MUST-HAVES: Python",
            cv_markdown="# Jane Doe\nOld CV",
            cover_letter_markdown="Dear Manager,\nOld CL",
            logger=MagicMock(),
        )

        assert "Updated CV content" in result.cv_markdown
        assert "Updated CL content" in result.cover_letter_markdown

    @patch("agents.run_step")
    def test_revision_issues_extracted(self, mock_run_step):
        """Critic feedback issues should be parsed into structured list."""
        mock_run_step.side_effect = [
            "REVISIONS NEEDED:\n- CV: Add Python to skills\n- CV: Quantify impact\n- Cover Letter: Be more specific about company",
            "## REVISED CV\nRevised\n\n## REVISED COVER LETTER\nRevised CL",
            "APPROVED",
        ]

        result = run_critic_loop(
            client=MagicMock(),
            job_description="Some JD",
            role_analysis="MUST-HAVES: Python",
            cv_markdown="# Jane Doe",
            cover_letter_markdown="Dear Manager",
            logger=MagicMock(),
        )

        assert len(result.rounds[0].revision_issues) == 3
        assert "Add Python to skills" in result.rounds[0].revision_issues[0]

    @patch("agents.run_step")
    def test_to_dict_serializable(self, mock_run_step):
        """CriticResult.to_dict() should produce JSON-serializable output."""
        import json
        mock_run_step.return_value = "APPROVED"

        result = run_critic_loop(
            client=MagicMock(),
            job_description="Some JD",
            role_analysis="MUST-HAVES: Python",
            cv_markdown="# Jane Doe",
            cover_letter_markdown="Dear Manager",
            logger=MagicMock(),
        )

        d = result.to_dict()
        json_str = json.dumps(d)  # Should not raise
        assert d["approved"] is True
        assert d["iterations"] == 1


class TestSplitRevision:
    def test_header_based_split(self):
        """Primary parsing: ## REVISED CV / ## REVISED COVER LETTER headers."""
        text = "## REVISED CV\n# Jane Doe\nCV content here\n\n## REVISED COVER LETTER\nDear Manager, cover letter"
        cv, cl = _split_revision(text, "fallback cv", "fallback cl")
        assert "CV content here" in cv
        assert "cover letter" in cl

    def test_header_based_split_reverse_order(self):
        """Headers can appear in any order."""
        text = "## REVISED COVER LETTER\nDear Manager, CL\n\n## REVISED CV\n# Jane Doe\nCV here"
        cv, cl = _split_revision(text, "fallback cv", "fallback cl")
        assert "CV here" in cv
        assert "CL" in cl

    def test_fallback_separator_split(self):
        """Fallback: --- separator when no headers present."""
        text = "# CV content\n---\nDear Manager, cover letter"
        cv, cl = _split_revision(text, "fallback cv", "fallback cl")
        assert "CV content" in cv
        assert "cover letter" in cl

    def test_no_separator_returns_fallback(self):
        text = "Just some text without separator"
        cv, cl = _split_revision(text, "fallback cv", "fallback cl")
        assert cv == "fallback cv"
        assert cl == "fallback cl"

    def test_headers_preferred_over_separator(self):
        """Headers take priority even if --- is also present."""
        text = "## REVISED CV\nCV part\n---\nstill CV\n\n## REVISED COVER LETTER\nCL part"
        cv, cl = _split_revision(text, "fb", "fb")
        assert "CV part" in cv
        assert "still CV" in cv  # --- is inside the CV section, not a split point
        assert "CL part" in cl


class TestExtractRevisionIssues:
    def test_extracts_cv_and_cl_issues(self):
        text = "REVISIONS NEEDED:\n- CV: Add metrics\n- CV: Fix formatting\n- Cover Letter: More specific"
        issues = _extract_revision_issues(text)
        assert len(issues) == 3
        assert "CV: Add metrics" in issues[0]
        assert "Cover Letter: More specific" in issues[2]

    def test_bold_format(self):
        """Handles **CV:** bold format."""
        text = "REVISIONS NEEDED:\n- **CV:** Add metrics\n- **Cover Letter:** Be specific"
        issues = _extract_revision_issues(text)
        assert len(issues) == 2
        assert "CV:" in issues[0]
        assert "Cover Letter:" in issues[1]

    def test_numbered_format(self):
        """Handles 1. CV: numbered format."""
        text = "REVISIONS NEEDED:\n1. CV: Add metrics\n2. Cover Letter: Be specific"
        issues = _extract_revision_issues(text)
        assert len(issues) == 2

    def test_no_issues_returns_empty(self):
        assert _extract_revision_issues("APPROVED") == []

    def test_ignores_non_issue_lines(self):
        text = "Some commentary\n- CV: Real issue\nMore text"
        issues = _extract_revision_issues(text)
        assert len(issues) == 1


class TestFormatCvForReview:
    def test_formats_json_cv(self):
        cv_json = json.dumps({
            "name": "Jane Doe",
            "title_tagline": "Senior PM",
            "skills": {"Product": ["A/B testing"]},
            "experience": [{"title": "PM", "company": "Acme", "dates": "2022 -- 2025", "bullets": ["Did stuff"]}],
            "education": {"degree": "BA", "university": "MIT"},
        })
        result = _format_cv_for_review(cv_json)
        assert "Jane Doe" in result
        assert "Acme" in result
        assert "Did stuff" in result

    def test_returns_markdown_as_is(self):
        md = "# Jane Doe\n## Experience\nSome content"
        assert _format_cv_for_review(md) == md

    def test_handles_empty_string(self):
        result = _format_cv_for_review("")
        assert result == ""
