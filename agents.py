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
