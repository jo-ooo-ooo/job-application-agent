# Multi-Agent Refactor Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the 7-step sequential pipeline into a multi-agent architecture with parallel research (company + role analysis), and a writer/critic review loop replacing the guardrail auto-fix.

**Architecture:** Two research agents (company + role) run in parallel via `concurrent.futures.ThreadPoolExecutor`. A new critic agent reviews CV and cover letter output from the writer, providing strategic feedback in a loop. The hiring manager step is removed entirely. No orchestrator needed — it's a fixed pipeline.

**Tech Stack:** Python 3.13, anthropic SDK, concurrent.futures for parallelism, pytest for testing.

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `agents.py` | **Create** | Multi-agent runner: `run_parallel_research()`, `run_critic_loop()` |
| `prompts.py` | **Modify** | Add `STEP_ROLE_ANALYSIS`, `STEP_CRITIC_REVIEW`, `STEP_CRITIC_REVISION` prompts; remove `STEP_HIRING_MANAGER`, `STEP_HIRING_MANAGER_SKIP`, `STEP_GUARDRAIL_FIX_CV`, `STEP_GUARDRAIL_FIX_CL`; remove `{manager_research}` from CV/CL prompts; add `{role_analysis}` to gap analysis prompt |
| `main.py` | **Modify** | Replace steps 1-2 with parallel research, replace guardrail auto-fix with critic loop, remove hiring manager references, add checkpoint backward compatibility |
| `agent.py` | **Modify** | Add temperature entries for new step names |
| `test_agents.py` | **Create** | Tests for `run_parallel_research()`, `run_critic_loop()`, `_split_revision()` |
| `test_unit.py` | **Modify** | Remove/update tests that reference removed prompts |
| `test_checkpoint.py` | **Modify** | Update test fixtures to use new state shape |

---

## Chunk 1: Role Analysis Agent + Parallel Research

### Task 1: Add the Role Analysis prompt

**Files:**
- Modify: `prompts.py`

- [ ] **Step 1: Add STEP_ROLE_ANALYSIS prompt to prompts.py**

Add after `STEP_COMPANY_RESEARCH` (around line 56):

```python
STEP_ROLE_ANALYSIS = """\
Analyze this job description deeply from a hiring manager's perspective.

JOB DESCRIPTION:
{job_description}

Go beyond surface-level requirements. Output a SHORT analysis (max 15 lines):

MUST-HAVES (non-negotiable — candidate gets filtered without these):
- [list the 3-5 requirements that are truly required, not wish-list items]

NICE-TO-HAVES (bonus points, but won't get you filtered):
- [list items that are clearly preferred but not required]

REAL SENIORITY: [What level are they actually hiring for? Sometimes the JD says
"senior" but the requirements suggest mid-level, or vice versa. Call it out.]

KEY SIGNALS: [What keywords, technologies, or phrases should appear in the CV
to pass ATS and catch the hiring manager's eye? List 5-8.]

ROLE TYPE: [New headcount or backfill? IC or people management? Strategic or execution-heavy?
Infer from clues in the JD.]
"""
```

- [ ] **Step 2: Remove hiring manager prompts from prompts.py**

Delete `STEP_HIRING_MANAGER` (lines 58-63) and `STEP_HIRING_MANAGER_SKIP` (lines 65-67).

- [ ] **Step 3: Add `{role_analysis}` to STEP_GAP_ANALYSIS prompt**

In `STEP_GAP_ANALYSIS`, add role analysis input. Change:

```python
ROLE CONTEXT (from research):
{company_research}
```

To:

```python
ROLE CONTEXT (from research):
{company_research}

ROLE ANALYSIS:
{role_analysis}
```

This ensures the gap analysis scores against the actual must-haves and real seniority from the role analysis.

- [ ] **Step 4: Remove `{manager_research}` from STEP_CV_CONSTRUCTION**

Delete these two lines from `STEP_CV_CONSTRUCTION` (lines 194-195):

```
HIRING MANAGER CONTEXT:
{manager_research}
```

- [ ] **Step 5: Remove `{manager_research}` from STEP_COVER_LETTER**

Delete these two lines from `STEP_COVER_LETTER` (lines 225-226):

```
HIRING MANAGER:
{manager_research}
```

Also delete line 238: `- If hiring manager name is known, address them directly`

- [ ] **Step 6: Verify no syntax errors**

Run: `python3 -c "import prompts; print('OK')"`
Expected: `OK`

- [ ] **Step 7: Commit**

```bash
git add prompts.py
git commit -m "feat: add role analysis prompt, remove hiring manager prompts, feed role analysis into gap analysis"
```

---

### Task 2: Create agents.py with parallel research

**Files:**
- Create: `agents.py`
- Create: `test_agents.py`

- [ ] **Step 1: Write the failing test for run_parallel_research**

Create `test_agents.py`:

```python
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

        # Company should have error, role should succeed
        assert "Error" in result["company_research"]
        assert "MUST-HAVES" in result["role_analysis"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest test_agents.py::TestRunParallelResearch -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agents'` or `ImportError`

- [ ] **Step 3: Write agents.py with run_parallel_research**

```python
"""Multi-agent coordination — parallel research and critic review loop."""

from concurrent.futures import ThreadPoolExecutor, as_completed

from agent import run_step
from prompts import SYSTEM_PROMPT, STEP_COMPANY_RESEARCH, STEP_ROLE_ANALYSIS
from run_logger import RunLogger


def run_parallel_research(
    client,
    job_description: str,
    logger: RunLogger,
) -> dict:
    """Run company research and role analysis agents in parallel.

    Returns dict with keys: company_research, role_analysis.
    If one agent fails, the other still returns its result.
    """

    def _run_company():
        metrics = logger.start_step("company_research")
        try:
            result = run_step(
                client, SYSTEM_PROMPT,
                STEP_COMPANY_RESEARCH.format(job_description=job_description),
                metrics=metrics, step_name="company_research",
            )
            logger.finish_step()
            return "company_research", result
        except Exception as e:
            logger.finish_step()
            return "company_research", f"Error: {e}"

    def _run_role():
        metrics = logger.start_step("role_analysis")
        try:
            result = run_step(
                client, SYSTEM_PROMPT,
                STEP_ROLE_ANALYSIS.format(job_description=job_description),
                metrics=metrics, step_name="role_analysis",
            )
            logger.finish_step()
            return "role_analysis", result
        except Exception as e:
            logger.finish_step()
            return "role_analysis", f"Error: {e}"

    results = {}
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(_run_company), executor.submit(_run_role)]
        for future in as_completed(futures):
            key, value = future.result()
            results[key] = value

    return results
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest test_agents.py::TestRunParallelResearch -v`
Expected: 3 passed

- [ ] **Step 5: Add temperature entry for role_analysis in agent.py**

In `agent.py`, add to `STEP_TEMPERATURES` dict:

```python
"role_analysis": 0,
```

- [ ] **Step 6: Commit**

```bash
git add agents.py test_agents.py agent.py
git commit -m "feat: add parallel research agents (company + role analysis)"
```

---

## Chunk 2: Writer + Critic Loop

### Task 3: Add the Critic Review prompt

**Files:**
- Modify: `prompts.py`

- [ ] **Step 1: Add STEP_CRITIC_REVIEW prompt to prompts.py**

Add after `STEP_COVER_LETTER`:

```python
STEP_CRITIC_REVIEW = """\
You are a hiring manager reviewing this application. Be specific and actionable.

JOB DESCRIPTION:
{job_description}

ROLE ANALYSIS:
{role_analysis}

CV:
{cv_markdown}

COVER LETTER:
{cover_letter_markdown}

Review both documents as if you're deciding whether to interview this candidate.
Check for:
1. Are the must-have skills from the role analysis clearly visible?
2. Are key signals/keywords present for ATS?
3. Is the most relevant experience given the most space?
4. Are bullet points specific (Action + Result + Impact) or vague?
5. Does the cover letter show genuine understanding of the company?
6. Is anything misleading, generic, or buried that should be prominent?

If BOTH documents are strong enough to get an interview, respond with exactly:
APPROVED

Otherwise, give specific revision instructions. Be direct:
REVISIONS NEEDED:
- CV: [specific issue and how to fix it]
- CV: [another issue]
- Cover Letter: [specific issue and how to fix it]

Max 5 revision items. Focus on what would actually change the hiring decision.
Do NOT nitpick formatting or style. Focus on substance and positioning.
"""
```

- [ ] **Step 2: Remove guardrail fix prompts from prompts.py**

Delete `STEP_GUARDRAIL_FIX_CV` (lines 261-275) and `STEP_GUARDRAIL_FIX_CL` (lines 277-291).

- [ ] **Step 3: Add STEP_CRITIC_REVISION prompt to prompts.py**

```python
STEP_CRITIC_REVISION = """\
A hiring manager reviewed your CV and cover letter and found issues. Fix them.

REVISION INSTRUCTIONS:
{critic_feedback}

JOB DESCRIPTION:
{job_description}

CURRENT CV:
{cv_markdown}

CURRENT COVER LETTER:
{cover_letter_markdown}

Fix ALL listed issues. Output both revised documents as markdown.
First the CV, then a line with only "---", then the cover letter.
Rules: Never invent new experience. Only address the specific issues listed.
"""
```

- [ ] **Step 4: Verify no syntax errors**

Run: `python3 -c "import prompts; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add prompts.py
git commit -m "feat: add critic review and revision prompts, remove guardrail fix prompts"
```

---

### Task 4: Implement the critic loop in agents.py

**Files:**
- Modify: `agents.py`
- Modify: `test_agents.py`

- [ ] **Step 1: Write failing tests for run_critic_loop**

Add to `test_agents.py`:

```python
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
            "REVISIONS NEEDED:\n- CV: Add Python to skills section",  # critic round 1
            "# Jane Doe\n## Experience\n...\n---\nDear Manager, revised...",  # writer revision
            "APPROVED",  # critic round 2
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
            "REVISIONS NEEDED:\n- CV: Add metrics",  # critic
            "# Jane Doe\nUpdated CV content\n---\nDear Manager,\nUpdated CL content",  # writer
            "APPROVED",  # critic
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest test_agents.py::TestRunCriticLoop -v`
Expected: FAIL — `ImportError: cannot import name 'run_critic_loop'`

- [ ] **Step 3: Implement run_critic_loop in agents.py**

Add to `agents.py`:

```python
from prompts import STEP_CRITIC_REVIEW, STEP_CRITIC_REVISION

MAX_CRITIC_ITERATIONS = 3


def run_critic_loop(
    client,
    job_description: str,
    role_analysis: str,
    cv_markdown: str,
    cover_letter_markdown: str,
    logger: RunLogger,
    max_iterations: int = MAX_CRITIC_ITERATIONS,
) -> tuple[str, str, int]:
    """Run writer/critic review loop.

    The critic reviews CV + cover letter from a hiring manager's perspective.
    If not approved, the writer revises based on critic feedback. Loop until
    approved or max_iterations reached.

    Returns (cv_markdown, cover_letter_markdown, iterations).
    """
    cv = cv_markdown
    cl = cover_letter_markdown

    for iteration in range(1, max_iterations + 1):
        # Critic reviews
        print(f"\n  [critic] Review round {iteration}...")
        metrics = logger.start_step(f"critic_review_{iteration}")
        review = run_step(
            client, SYSTEM_PROMPT,
            STEP_CRITIC_REVIEW.format(
                job_description=job_description,
                role_analysis=role_analysis,
                cv_markdown=cv,
                cover_letter_markdown=cl,
            ),
            metrics=metrics, step_name="critic_review",
        )
        logger.finish_step()

        print(f"  [critic] {review[:200]}...")

        if "APPROVED" in review and "REVISIONS" not in review:
            print("  [critic] Approved!")
            return cv, cl, iteration

        if iteration == max_iterations:
            print(f"  [critic] Max iterations ({max_iterations}) reached. Using latest version.")
            return cv, cl, iteration

        # Writer revises
        print(f"  [writer] Revising based on critic feedback...")
        metrics = logger.start_step(f"critic_revision_{iteration}")
        revision = run_step(
            client, SYSTEM_PROMPT,
            STEP_CRITIC_REVISION.format(
                critic_feedback=review,
                job_description=job_description,
                cv_markdown=cv,
                cover_letter_markdown=cl,
            ),
            metrics=metrics, step_name="revision",
        )
        logger.finish_step()

        # Parse revision output — split by ---
        cv, cl = _split_revision(revision, cv, cl)

    return cv, cl, max_iterations


def _split_revision(revision: str, fallback_cv: str, fallback_cl: str) -> tuple[str, str]:
    """Split writer revision output into CV and cover letter by --- separator."""
    if "\n---\n" in revision:
        parts = revision.split("\n---\n", 1)
        return parts[0].strip(), parts[1].strip()
    return fallback_cv, fallback_cl
```

- [ ] **Step 4: Add temperature entries in agent.py**

In `agent.py`, add to `STEP_TEMPERATURES`:

```python
"critic_review": 0,
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest test_agents.py -v`
Expected: 7 passed (3 parallel research + 4 critic loop)

- [ ] **Step 6: Commit**

```bash
git add agents.py test_agents.py agent.py
git commit -m "feat: add writer/critic review loop"
```

---

## Chunk 3: Wire Into Main Pipeline

### Task 5: Update main.py to use new multi-agent architecture

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Update imports in main.py**

Replace:
```python
from prompts import (
    SYSTEM_PROMPT,
    STEP_COMPANY_RESEARCH,
    STEP_HIRING_MANAGER,
    STEP_HIRING_MANAGER_SKIP,
    STEP_GAP_ANALYSIS,
    STEP_GAP_UPDATE,
    STEP_GAP_REASSESSMENT,
    STEP_PROJECT_SELECTION,
    STEP_CV_CONSTRUCTION,
    STEP_COVER_LETTER,
    STEP_REVISION,
    STEP_PDF_GENERATION,
    STEP_GUARDRAIL_FIX_CV,
    STEP_GUARDRAIL_FIX_CL,
)
```

With:
```python
from prompts import (
    SYSTEM_PROMPT,
    STEP_GAP_ANALYSIS,
    STEP_GAP_UPDATE,
    STEP_GAP_REASSESSMENT,
    STEP_PROJECT_SELECTION,
    STEP_CV_CONSTRUCTION,
    STEP_COVER_LETTER,
    STEP_REVISION,
    STEP_PDF_GENERATION,
)
from agents import run_parallel_research, run_critic_loop
```

- [ ] **Step 2: Remove `--manager` argument and add checkpoint backward compatibility**

Remove `--manager` argument from argparse. Update state initialization:

```python
state = {
    "job_description": job_desc,
    "company_research": "",
    "role_analysis": "",
    "gap_analysis": "",
    "project_selection": "",
    "cv_markdown": "",
    "cover_letter_markdown": "",
}
```

After loading a checkpoint, add backward compatibility for old checkpoints:

```python
if checkpoint:
    state = checkpoint["state"]
    # Backward compatibility: old checkpoints may have manager fields
    state.pop("manager_name", None)
    state.pop("manager_research", None)
    state.setdefault("role_analysis", "")
```

- [ ] **Step 3: Replace Steps 1-2 with parallel research**

Replace the sequential Step 1 (company research) and Step 2 (hiring manager) blocks with:

```python
# ── Step 1: Parallel Research (Company + Role) ───────────
if "research" not in completed_steps:
    print("\n[Step 1/6] Researching company and analyzing role (parallel)...")
    research = run_parallel_research(client, state["job_description"], logger)
    state["company_research"] = research["company_research"]
    state["role_analysis"] = research["role_analysis"]
    completed_steps.append("research")
    save_checkpoint(run_id, state, completed_steps, completed_gates)
else:
    print("\n[Step 1/6] Research — skipped (cached)")
print(state["company_research"])
print(state["role_analysis"])
```

Also handle old checkpoints that used separate step names: add before the research block:

```python
# Backward compat: treat old step names as equivalent to "research"
if "company_research" in completed_steps and "hiring_manager" in completed_steps:
    if "research" not in completed_steps:
        completed_steps.append("research")
```

- [ ] **Step 4: Update gap analysis to pass role_analysis**

In `_run_gap_analysis`, update the `STEP_GAP_ANALYSIS.format()` call:

```python
STEP_GAP_ANALYSIS.format(
    job_description=state["job_description"],
    company_research=state["company_research"],
    role_analysis=state["role_analysis"],
)
```

Do the same for the borderline re-run call inside `_run_gap_analysis`.

Update the print statement from `"Step 3/7"` to `"Step 2/6"`.

- [ ] **Step 5: Update remaining step numbers**

- Gap analysis: Step 2/6
- Project selection: Step 3/6
- CV construction: Step 4/6
- Cover letter: Step 5/6
- PDF generation: Step 6/6

- [ ] **Step 6: Remove manager_research from CV and cover letter format calls**

In CV construction step, change:
```python
STEP_CV_CONSTRUCTION.format(
    job_description=state["job_description"],
    company_research=state["company_research"],
    project_selection=state["project_selection"],
    manager_research=state["manager_research"],
)
```
To:
```python
STEP_CV_CONSTRUCTION.format(
    job_description=state["job_description"],
    company_research=state["company_research"],
    project_selection=state["project_selection"],
)
```

In cover letter step, change:
```python
STEP_COVER_LETTER.format(
    job_description=state["job_description"],
    company_research=state["company_research"],
    gap_analysis=state["gap_analysis"],
    manager_research=state["manager_research"],
)
```
To:
```python
STEP_COVER_LETTER.format(
    job_description=state["job_description"],
    company_research=state["company_research"],
    gap_analysis=state["gap_analysis"],
)
```

- [ ] **Step 7: Replace guardrail auto-fix with critic loop**

Replace the `_guardrail_auto_fix()` call with:

```python
# ── Critic Review Loop ────────────────────────────────────
state["cv_markdown"], state["cover_letter_markdown"], critic_rounds = run_critic_loop(
    client,
    job_description=state["job_description"],
    role_analysis=state["role_analysis"],
    cv_markdown=state["cv_markdown"],
    cover_letter_markdown=state["cover_letter_markdown"],
    logger=logger,
)
print(f"  [critic] Completed in {critic_rounds} round(s)")

# Run structural guardrails as a final safety net (no auto-fix, just warn)
cv_warnings = validate_cv(state["cv_markdown"], candidate_name)
cl_warnings = validate_cover_letter(state["cover_letter_markdown"], candidate_name)
if cv_warnings:
    print(format_warnings(cv_warnings, "CV"))
if cl_warnings:
    print(format_warnings(cl_warnings, "Cover Letter"))
```

Keep the existing STOP Gate 2 (approve/revise/quit) loop after this.

- [ ] **Step 8: Remove _guardrail_auto_fix function and unused imports**

Delete the `_guardrail_auto_fix()` function and `MAX_GUARDRAIL_RETRIES` constant. Remove imports for `STEP_GUARDRAIL_FIX_CV` and `STEP_GUARDRAIL_FIX_CL`. Keep `validate_cv`, `validate_cover_letter` imports (used as final safety net).

- [ ] **Step 9: Remove the debug print line**

Delete this line from the Sheets logging section:
```python
print(f"  [debug] Logging score: {final_score}, recommendation: {final_recommendation}")
```

- [ ] **Step 10: Verify the full import chain works**

Run: `python3 -c "import main; print('OK')"`
Expected: `OK`

- [ ] **Step 11: Commit**

```bash
git add main.py
git commit -m "feat: wire multi-agent architecture into main pipeline"
```

---

### Task 6: Fix broken tests

**Files:**
- Modify: `test_unit.py`
- Modify: `test_checkpoint.py`
- Modify: `test_agents.py`

- [ ] **Step 1: Add _split_revision edge case tests to test_agents.py**

```python
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
```

- [ ] **Step 2: Update test_checkpoint.py fixtures**

If any test in `test_checkpoint.py` uses `"manager_name"` or `"manager_research"` in state dicts, replace with `"role_analysis"`. Example — change:

```python
"manager_name": "John",
"manager_research": "some research",
```

To:

```python
"role_analysis": "MUST-HAVES: Python",
```

- [ ] **Step 3: Run the full test suite**

Run: `python3 -m pytest test_unit.py test_guardrails.py test_checkpoint.py test_agents.py --tb=short -v`
Expected: All pass (~100 total: 90 original minus any removed + ~10 new)

- [ ] **Step 4: Fix any remaining broken tests**

If any tests import removed prompts (`STEP_HIRING_MANAGER`, `STEP_GUARDRAIL_FIX_CV`, etc.) or reference `manager_research`, update them.

- [ ] **Step 5: Commit**

```bash
git add test_agents.py test_unit.py test_checkpoint.py
git commit -m "test: update tests for multi-agent refactor"
```

---

### Task 7: Final verification

- [ ] **Step 1: Run the full test suite one more time**

Run: `python3 -m pytest test_unit.py test_guardrails.py test_checkpoint.py test_agents.py --tb=short -q`
Expected: All tests pass

- [ ] **Step 2: Verify the CLI works**

Run: `python3 main.py --help`
Expected: Shows usage without `--manager` flag, with `--job` and `--resume` flags.

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "chore: finalize multi-agent refactor"
```
