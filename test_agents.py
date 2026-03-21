"""Tests for multi-agent coordination — parallel research and critic loop."""

import pytest
from unittest.mock import patch, MagicMock
from agents import run_parallel_research


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
