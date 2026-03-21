"""Tests for multi-agent coordination — parallel research and critic loop."""

import pytest
from unittest.mock import patch, MagicMock
from agents import run_parallel_research, run_critic_loop, _split_revision


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

        cv, cl, iterations = run_critic_loop(
            client=MagicMock(),
            job_description="Some JD",
            role_analysis="MUST-HAVES: Python",
            cv_markdown="# Jane Doe\n## Experience\n...",
            cover_letter_markdown="Dear Manager,\n...",
            logger=MagicMock(),
        )

        assert iterations == 1
        assert cv == "# Jane Doe\n## Experience\n..."
        assert cl == "Dear Manager,\n..."

    @patch("agents.run_step")
    def test_revision_then_approved(self, mock_run_step):
        """Critic requests revision, writer fixes, critic approves."""
        mock_run_step.side_effect = [
            "REVISIONS NEEDED:\n- CV: Add Python to skills section",
            "# Jane Doe\n## Experience\n...\n---\nDear Manager, revised...",
            "APPROVED",
        ]

        cv, cl, iterations = run_critic_loop(
            client=MagicMock(),
            job_description="Some JD",
            role_analysis="MUST-HAVES: Python",
            cv_markdown="# Jane Doe\n## Experience\n...",
            cover_letter_markdown="Dear Manager,\n...",
            logger=MagicMock(),
        )

        assert iterations == 2

    @patch("agents.run_step")
    def test_max_iterations_reached(self, mock_run_step):
        """After max iterations, return latest version even without approval."""
        mock_run_step.return_value = "REVISIONS NEEDED:\n- CV: Still needs work"

        cv, cl, iterations = run_critic_loop(
            client=MagicMock(),
            job_description="Some JD",
            role_analysis="MUST-HAVES: Python",
            cv_markdown="# Jane Doe",
            cover_letter_markdown="Dear Manager",
            logger=MagicMock(),
            max_iterations=3,
        )

        assert iterations == 3

    @patch("agents.run_step")
    def test_revision_output_parsed_correctly(self, mock_run_step):
        """Writer revision output should be split into CV and CL by --- separator."""
        mock_run_step.side_effect = [
            "REVISIONS NEEDED:\n- CV: Add metrics",
            "# Jane Doe\nUpdated CV content\n---\nDear Manager,\nUpdated CL content",
            "APPROVED",
        ]

        cv, cl, iterations = run_critic_loop(
            client=MagicMock(),
            job_description="Some JD",
            role_analysis="MUST-HAVES: Python",
            cv_markdown="# Jane Doe\nOld CV",
            cover_letter_markdown="Dear Manager,\nOld CL",
            logger=MagicMock(),
        )

        assert "Updated CV content" in cv
        assert "Updated CL content" in cl


class TestSplitRevision:
    def test_clean_split(self):
        text = "# CV content\n---\nDear Manager, cover letter"
        cv, cl = _split_revision(text, "fallback cv", "fallback cl")
        assert "CV content" in cv
        assert "cover letter" in cl

    def test_no_separator_returns_fallback(self):
        text = "Just some text without separator"
        cv, cl = _split_revision(text, "fallback cv", "fallback cl")
        assert cv == "fallback cv"
        assert cl == "fallback cl"

    def test_multiple_separators_splits_on_first(self):
        text = "Part 1\n---\nPart 2\n---\nPart 3"
        cv, cl = _split_revision(text, "fb", "fb")
        assert cv == "Part 1"
        assert "Part 2" in cl
        assert "Part 3" in cl
