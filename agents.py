"""Multi-agent coordination — parallel research and critic review loop."""

from concurrent.futures import ThreadPoolExecutor, as_completed

from agent import run_step
from prompts import SYSTEM_PROMPT, STEP_COMPANY_RESEARCH, STEP_ROLE_ANALYSIS, STEP_CRITIC_REVIEW, STEP_CRITIC_REVISION
from run_logger import RunLogger

MAX_CRITIC_ITERATIONS = 3


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
