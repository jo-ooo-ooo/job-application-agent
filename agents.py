"""Multi-agent coordination — parallel research and critic review loop."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from agent import run_step
from prompts import SYSTEM_PROMPT, STEP_COMPANY_RESEARCH, STEP_ROLE_ANALYSIS, STEP_CRITIC_REVIEW, STEP_CRITIC_REVISION
from run_logger import RunLogger

MAX_CRITIC_ITERATIONS = 3


@dataclass
class CriticRound:
    """One round of critic review + optional revision."""
    iteration: int
    feedback: str
    approved: bool
    revision_issues: list[str] = field(default_factory=list)
    cv_word_delta: int = 0
    cl_word_delta: int = 0


@dataclass
class CriticResult:
    """Full result from the critic review loop."""
    cv_markdown: str
    cover_letter_markdown: str
    rounds: list[CriticRound]

    @property
    def iterations(self) -> int:
        return len(self.rounds)

    @property
    def approved(self) -> bool:
        return any(r.approved for r in self.rounds)

    @property
    def status(self) -> str:
        if self.approved:
            return f"APPROVED (round {next(r.iteration for r in self.rounds if r.approved)})"
        return f"MAX_ITERATIONS ({self.iterations})"

    def to_dict(self) -> dict:
        return {
            "iterations": self.iterations,
            "approved": self.approved,
            "status": self.status,
            "rounds": [
                {
                    "iteration": r.iteration,
                    "approved": r.approved,
                    "feedback": r.feedback,
                    "revision_issues": r.revision_issues,
                    "cv_word_delta": r.cv_word_delta,
                    "cl_word_delta": r.cl_word_delta,
                }
                for r in self.rounds
            ],
        }

    def print_summary(self):
        """Print a readable summary of what the critic loop did."""
        print(f"\n  {'─' * 50}")
        print(f"  CRITIC LOOP SUMMARY: {self.status}")
        print(f"  {'─' * 50}")
        for r in self.rounds:
            status = "✓ APPROVED" if r.approved else f"✗ {len(r.revision_issues)} issue(s)"
            print(f"  Round {r.iteration}: {status}")
            if r.revision_issues:
                for issue in r.revision_issues[:5]:
                    print(f"    - {issue}")
                if not r.approved:
                    print(f"    → Revised: CV {r.cv_word_delta:+d} words, CL {r.cl_word_delta:+d} words")
        print(f"  {'─' * 50}")


def _word_count(text: str) -> int:
    return len(text.split()) if text else 0


def _extract_revision_issues(review: str) -> list[str]:
    """Extract individual revision items from critic feedback.

    Handles various formats the critic might use:
    - CV: issue text
    - **CV:** issue text
    - 1. CV: issue text
    - Cover Letter: issue text
    """
    import re
    issues = []
    for line in review.split("\n"):
        line = line.strip()
        # Match bullet or numbered list items containing CV: or Cover Letter:
        m = re.match(r'^(?:[-*]|\d+[.)])\s*\**\s*((?:CV|Cover\s*Letter)\s*:\s*.+)', line, re.IGNORECASE)
        if m:
            # Clean up bold markers
            issue = m.group(1).replace("**", "").strip()
            issues.append(issue)
    return issues


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
            metrics.finish()
            print(metrics.summary_line())
            return "company_research", result
        except Exception as e:
            metrics.finish(error=str(e))
            print(metrics.summary_line())
            return "company_research", f"Error: {e}"

    def _run_role():
        metrics = logger.start_step("role_analysis")
        try:
            result = run_step(
                client, SYSTEM_PROMPT,
                STEP_ROLE_ANALYSIS.format(job_description=job_description),
                metrics=metrics, step_name="role_analysis",
            )
            metrics.finish()
            print(metrics.summary_line())
            return "role_analysis", result
        except Exception as e:
            metrics.finish(error=str(e))
            print(metrics.summary_line())
            return "role_analysis", f"Error: {e}"

    results = {}
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(_run_company), executor.submit(_run_role)]
        for future in as_completed(futures):
            key, value = future.result()
            results[key] = value

    return results


def _format_cv_for_review(cv_content: str) -> str:
    """Format CV content for human-readable review by the critic.

    If cv_content is JSON, renders it as readable text.
    If it's markdown (legacy), returns as-is.
    """
    import json
    try:
        data = json.loads(cv_content)
        lines = [f"Name: {data.get('name', '')}"]
        lines.append(f"Tagline: {data.get('title_tagline', '')}")
        if data.get('skills'):
            lines.append("\nSkills:")
            for cat, items in data['skills'].items():
                lines.append(f"  {cat}: {', '.join(items)}")
        if data.get('experience'):
            lines.append("\nExperience:")
            for exp in data['experience']:
                lines.append(f"\n  {exp['title']} — {exp['company']} ({exp['dates']})")
                if exp.get('company_description'):
                    lines.append(f"  {exp['company_description']}")
                for b in exp.get('bullets', []):
                    lines.append(f"  - {b}")
        if data.get('side_projects'):
            lines.append("\nProjects:")
            for p in data['side_projects']:
                lines.append(f"\n  {p['name']}")
                for b in p.get('bullets', []):
                    lines.append(f"  - {b}")
        if data.get('education'):
            lines.append(f"\nEducation: {data['education'].get('degree', '')} — {data['education'].get('university', '')}")
        return '\n'.join(lines)
    except (json.JSONDecodeError, KeyError, TypeError):
        return cv_content  # Legacy markdown fallback


def run_critic_loop(
    client,
    job_description: str,
    role_analysis: str,
    cv_markdown: str,
    cover_letter_markdown: str,
    logger: RunLogger,
    max_iterations: int = MAX_CRITIC_ITERATIONS,
) -> CriticResult:
    """Run writer/critic review loop.

    The critic reviews CV + cover letter from a hiring manager's perspective.
    If not approved, the writer revises based on critic feedback. Loop until
    approved or max_iterations reached.

    Returns a CriticResult with full review history.
    """
    cv = cv_markdown
    cl = cover_letter_markdown
    rounds = []

    for iteration in range(1, max_iterations + 1):
        # Critic reviews
        print(f"\n  [critic] Review round {iteration}/{max_iterations}...")
        metrics = logger.start_step(f"critic_review_{iteration}")
        review = run_step(
            client, SYSTEM_PROMPT,
            STEP_CRITIC_REVIEW.format(
                job_description=job_description,
                role_analysis=role_analysis,
                cv_display=_format_cv_for_review(cv),
                cover_letter_markdown=cl,
            ),
            metrics=metrics, step_name="critic_review",
            exclude_tools=["generate_pdf"],
        )
        logger.finish_step()

        is_approved = "APPROVED" in review and "REVISIONS" not in review
        issues = [] if is_approved else _extract_revision_issues(review)

        # Print the critic's feedback
        print(f"  [critic] {'APPROVED' if is_approved else 'REVISIONS NEEDED'}")
        if not is_approved:
            if issues:
                for issue in issues:
                    print(f"    - {issue}")
            else:
                # Show raw feedback if we couldn't parse structured issues
                for line in review.strip().split("\n"):
                    line = line.strip()
                    if line and not line.startswith("REVISIONS"):
                        print(f"    {line}")

        if is_approved:
            rounds.append(CriticRound(
                iteration=iteration,
                feedback=review,
                approved=True,
            ))
            result = CriticResult(cv, cl, rounds)
            result.print_summary()
            return result

        # Log what the critic found
        round_data = CriticRound(
            iteration=iteration,
            feedback=review,
            approved=False,
            revision_issues=issues,
        )

        if iteration == max_iterations:
            rounds.append(round_data)
            result = CriticResult(cv, cl, rounds)
            result.print_summary()
            return result

        # Writer revises
        print(f"  [writer] Revising {len(issues)} issue(s)...")
        cv_before = _word_count(cv)
        cl_before = _word_count(cl)

        metrics = logger.start_step(f"critic_revision_{iteration}")
        revision = run_step(
            client, SYSTEM_PROMPT,
            STEP_CRITIC_REVISION.format(
                critic_feedback=review,
                job_description=job_description,
                cv_json=cv,
                cover_letter_markdown=cl,
            ),
            metrics=metrics, step_name="revision",
            exclude_tools=["generate_pdf"],
        )
        logger.finish_step()

        cv, cl = _split_revision(revision, cv, cl)

        round_data.cv_word_delta = _word_count(cv) - cv_before
        round_data.cl_word_delta = _word_count(cl) - cl_before
        rounds.append(round_data)

    result = CriticResult(cv, cl, rounds)
    result.print_summary()
    return result


def _split_revision(revision: str, fallback_cv: str, fallback_cl: str) -> tuple[str, str]:
    """Split writer revision output into CV and cover letter sections.

    Looks for ## REVISED CV and ## REVISED COVER LETTER headers.
    Falls back to --- separator, then to fallback values.
    """
    import re

    # Try header-based split first
    cv_match = re.search(r'##\s*REVISED\s+CV\s*\n', revision, re.IGNORECASE)
    cl_match = re.search(r'##\s*REVISED\s+COVER\s+LETTER\s*\n', revision, re.IGNORECASE)

    if cv_match and cl_match:
        cv_start = cv_match.end()
        cl_start = cl_match.end()
        if cv_start < cl_start:
            cv = revision[cv_start:cl_match.start()].strip()
            cl = revision[cl_start:].strip()
        else:
            cl = revision[cl_start:cv_match.start()].strip()
            cv = revision[cv_start:].strip()
        return cv, cl

    # Fallback: --- separator
    if "\n---\n" in revision:
        parts = revision.split("\n---\n", 1)
        return parts[0].strip(), parts[1].strip()

    return fallback_cv, fallback_cl
