#!/usr/bin/env python3
"""Job Application Agent — structured state approach with hiring manager perspective."""

import argparse
import os
import sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from agent import run_step
from run_logger import RunLogger
from checkpoint import (
    generate_run_id,
    save_checkpoint,
    load_checkpoint,
    list_checkpoints,
    is_step_completed,
    is_gate_completed,
)
from scoring import (
    parse_dimension_scores,
    compute_weighted_score,
    get_recommendation,
    is_borderline,
    format_score_summary,
)
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
from tools import PROJECT_DIR
from pdf_generator import generate_pdf_from_markdown
from guardrails import (
    validate_cv,
    validate_cover_letter,
    validate_gap_analysis,
    extract_candidate_name,
    format_warnings,
)

load_dotenv()


def main():
    parser = argparse.ArgumentParser(description="AI-powered job application agent")
    parser.add_argument("--job", type=str, help="Job description text, file path, or URL")
    parser.add_argument("--manager", type=str, default="", help="Hiring manager name (optional)")
    parser.add_argument("--resume", type=str, nargs="?", const="latest", help="Resume from checkpoint (run ID, or 'latest')")
    args = parser.parse_args()

    if not args.job and not args.resume:
        print("Usage: python3 main.py --job 'job description text'")
        print("       python3 main.py --job path/to/job.txt")
        print("       python3 main.py --job https://linkedin.com/jobs/view/...")
        print("       python3 main.py --resume              (resume latest run)")
        print("       python3 main.py --resume <run_id>     (resume specific run)")
        sys.exit(1)

    # ── Handle resume from checkpoint ────────────────────────
    checkpoint = None
    completed_steps = []
    completed_gates = []
    run_id = generate_run_id()

    if args.resume:
        if args.resume == "latest":
            checkpoints = list_checkpoints()
            if not checkpoints:
                print("No checkpoints found. Start a new run with --job.")
                sys.exit(1)
            checkpoint = load_checkpoint(checkpoints[0]["run_id"])
        else:
            checkpoint = load_checkpoint(args.resume)

        if not checkpoint:
            print(f"Checkpoint '{args.resume}' not found.")
            available = list_checkpoints()
            if available:
                print("Available checkpoints:")
                for cp in available[:5]:
                    print(f"  {cp['run_id']}  ({len(cp['completed_steps'])} steps: {', '.join(cp['completed_steps'])})")
            sys.exit(1)

        run_id = checkpoint["run_id"]
        completed_steps = checkpoint["completed_steps"]
        completed_gates = checkpoint.get("completed_gates", [])
        print(f"Resuming run {run_id} — {len(completed_steps)} steps completed: {', '.join(completed_steps)}")

    # ── Load job description ──────────────────────────────────
    if checkpoint:
        job_desc = checkpoint["state"]["job_description"]
        manager_name = checkpoint["state"].get("manager_name", "")
    else:
        if not args.job:
            print("Usage: python3 main.py --job 'job description text'")
            print("       python3 main.py --job path/to/job.txt")
            print("       python3 main.py --job https://linkedin.com/jobs/view/...")
            sys.exit(1)
        job_desc = args.job
        if job_desc.startswith("http://") or job_desc.startswith("https://"):
            job_desc = _fetch_job_from_url(job_desc)
        elif os.path.isfile(job_desc):
            job_desc = Path(job_desc).read_text(encoding="utf-8")
        manager_name = args.manager

    # Verify required files
    master_list_path = PROJECT_DIR / "cvs" / "projects_master_list.md"
    template_path = PROJECT_DIR / "cvs" / "template_standard.md"
    if not master_list_path.exists():
        print(f"Error: {master_list_path} not found. See cvs_examples/ for format.")
        sys.exit(1)
    if not template_path.exists():
        print(f"Error: {template_path} not found. See cvs_examples/ for format.")
        sys.exit(1)

    # Extract candidate name from template for guardrail checks
    candidate_name = extract_candidate_name(template_path.read_text(encoding="utf-8"))

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY not set. Copy .env.example to .env and add your key.")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)
    logger = RunLogger()

    # ── Structured state ──────────────────────────────────────
    if checkpoint:
        state = checkpoint["state"]
    else:
        state = {
            "job_description": job_desc,
            "manager_name": manager_name,
            "company_research": "",
            "manager_research": "",
            "gap_analysis": "",
            "project_selection": "",
            "cv_markdown": "",
            "cover_letter_markdown": "",
        }

    print("=" * 60)
    print("JOB APPLICATION AGENT")
    if checkpoint:
        print(f"  (resumed from checkpoint {run_id})")
    print("=" * 60)

    # ── Step 1: Company Research ──────────────────────────────
    if "company_research" not in completed_steps:
        print("\n[Step 1/7] Researching company and role...")
        metrics = logger.start_step("company_research")
        state["company_research"] = run_step(
            client, SYSTEM_PROMPT,
            STEP_COMPANY_RESEARCH.format(job_description=state["job_description"]),
            metrics=metrics, step_name="company_research",
        )
        logger.finish_step()
        completed_steps.append("company_research")
        save_checkpoint(run_id, state, completed_steps, completed_gates)
    else:
        print("\n[Step 1/7] Company research — skipped (cached)")
    print(state["company_research"])

    # ── Step 2: Hiring Manager Research ───────────────────────
    if "hiring_manager" not in completed_steps:
        print("\n[Step 2/7] Researching hiring manager...")
        if state["manager_name"]:
            metrics = logger.start_step("hiring_manager")
            state["manager_research"] = run_step(
                client, SYSTEM_PROMPT,
                STEP_HIRING_MANAGER.format(manager_name=state["manager_name"]),
                metrics=metrics, step_name="hiring_manager",
            )
            logger.finish_step()
        else:
            state["manager_research"] = "No hiring manager specified — skipping."
        completed_steps.append("hiring_manager")
        save_checkpoint(run_id, state, completed_steps, completed_gates)
    else:
        print("\n[Step 2/7] Hiring manager research — skipped (cached)")
    print(state["manager_research"])

    # ── Step 3: Gap Analysis (with decomposed scoring) ────────
    if "gap_analysis" not in completed_steps:
        score, recommendation = _run_gap_analysis(client, state, logger)

        # Guardrail: validate gap analysis structure
        gap_warnings = validate_gap_analysis(state["gap_analysis"])
        print(format_warnings(gap_warnings, "Gap Analysis"))

        # ── Gap Questions: Ask user about potential missing experience ──
        user_answers = _handle_gap_questions(client, state, master_list_path, logger)

        # ── Re-assess if we learned new info ──────────────────────
        if user_answers:
            print("\n[Step 3b] Re-assessing fit with updated experience...")
            metrics = logger.start_step("gap_reassessment")
            reassessment = run_step(
                client, SYSTEM_PROMPT,
                STEP_GAP_REASSESSMENT.format(
                    job_description=state["job_description"],
                    company_research=state["company_research"],
                    previous_gap_analysis=state["gap_analysis"],
                    user_answers=user_answers,
                ),
                metrics=metrics, step_name="gap_reassessment",
            )
            logger.finish_step()
            print(reassessment)
            state["gap_analysis"] = state["gap_analysis"] + "\n\n--- UPDATED ---\n" + reassessment

            # Re-parse scores if the reassessment contains updated dimension scores
            new_scores = parse_dimension_scores(reassessment)
            if new_scores:
                score = compute_weighted_score(new_scores)
                recommendation = get_recommendation(score)
                print(format_score_summary(new_scores, score, recommendation))

        completed_steps.append("gap_analysis")
        save_checkpoint(run_id, state, completed_steps, completed_gates)
    else:
        print("\n[Step 3/7] Gap analysis — skipped (cached)")
        print(state["gap_analysis"])
        # Re-derive score for the gate display
        dimension_scores = parse_dimension_scores(state["gap_analysis"])
        if dimension_scores:
            score = compute_weighted_score(dimension_scores)
            recommendation = get_recommendation(score)
        else:
            score, recommendation = 50.0, "STRATEGIC APPLY"

    # ── STOP Gate 1 ───────────────────────────────────────────
    if "gate_1" not in completed_gates:
        print("\n" + "=" * 60)
        print(f"STOP GATE: Score {score:.0f}/100 — {recommendation}")
        print("=" * 60)
        proceed = input("Proceed with application? (y/n): ").strip().lower()
        if proceed != "y":
            print("Skipping this application. Goodbye!")
            logger.print_summary()
            logger.save()
            sys.exit(0)
        completed_gates.append("gate_1")
        save_checkpoint(run_id, state, completed_steps, completed_gates)
    else:
        print(f"\n[Gate 1] Already passed — score {score:.0f}/100")

    # ── Step 4: Project Selection ─────────────────────────────
    if "project_selection" not in completed_steps:
        print("\n[Step 4/7] Selecting best-fit projects...")
        metrics = logger.start_step("project_selection")
        state["project_selection"] = run_step(
            client, SYSTEM_PROMPT,
            STEP_PROJECT_SELECTION.format(
                job_description=state["job_description"],
                company_research=state["company_research"],
                gap_analysis=state["gap_analysis"],
            ),
            metrics=metrics, step_name="project_selection",
        )
        logger.finish_step()
        completed_steps.append("project_selection")
        save_checkpoint(run_id, state, completed_steps, completed_gates)
    else:
        print("\n[Step 4/7] Project selection — skipped (cached)")
    print(state["project_selection"])

    # ── Step 5: CV Construction ───────────────────────────────
    if "cv_construction" not in completed_steps:
        print("\n[Step 5/7] Constructing tailored CV...")
        metrics = logger.start_step("cv_construction")
        state["cv_markdown"] = run_step(
            client, SYSTEM_PROMPT,
            STEP_CV_CONSTRUCTION.format(
                job_description=state["job_description"],
                company_research=state["company_research"],
                project_selection=state["project_selection"],
                manager_research=state["manager_research"],
            ),
            metrics=metrics, step_name="cv_construction",
        )
        logger.finish_step()
        completed_steps.append("cv_construction")
        save_checkpoint(run_id, state, completed_steps, completed_gates)
    else:
        print("\n[Step 5/7] CV construction — skipped (cached)")
    print(state["cv_markdown"])

    # ── Step 6: Cover Letter ──────────────────────────────────
    if "cover_letter" not in completed_steps:
        print("\n[Step 6/7] Writing cover letter...")
        metrics = logger.start_step("cover_letter")
        state["cover_letter_markdown"] = run_step(
            client, SYSTEM_PROMPT,
            STEP_COVER_LETTER.format(
                job_description=state["job_description"],
                company_research=state["company_research"],
                gap_analysis=state["gap_analysis"],
                manager_research=state["manager_research"],
            ),
            metrics=metrics, step_name="cover_letter",
        )
        logger.finish_step()
        completed_steps.append("cover_letter")
        save_checkpoint(run_id, state, completed_steps, completed_gates)
    else:
        print("\n[Step 6/7] Cover letter — skipped (cached)")
    print(state["cover_letter_markdown"])

    # Guardrails: validate and auto-fix CV and cover letter
    state["cv_markdown"], state["cover_letter_markdown"] = _guardrail_auto_fix(
        client, state, candidate_name, logger,
    )

    # ── STOP Gate 2 ───────────────────────────────────────────
    while True:
        print("\n" + "=" * 60)
        print("STOP GATE: Review CV and cover letter above.")
        print("=" * 60)
        print("Options: (a)pprove  (r)evise  (q)uit")
        choice = input("Your choice: ").strip().lower()

        if choice == "q":
            print("Exiting without generating PDFs. Goodbye!")
            logger.print_summary()
            logger.save()
            sys.exit(0)
        elif choice == "a":
            break
        elif choice == "r":
            feedback = input("Enter your feedback: ").strip()
            if not feedback:
                print("No feedback provided, try again.")
                continue
            print("\nRevising based on your feedback...")
            metrics = logger.start_step("revision")
            revision = run_step(
                client, SYSTEM_PROMPT,
                STEP_REVISION.format(
                    feedback=feedback,
                    job_description=state["job_description"],
                    cv_markdown=state["cv_markdown"],
                    cover_letter_markdown=state["cover_letter_markdown"],
                ),
                metrics=metrics, step_name="revision",
            )
            logger.finish_step()
            print(revision)
            state["cv_markdown"] = _extract_section(revision, "CV", state["cv_markdown"])
            state["cover_letter_markdown"] = _extract_section(revision, "Cover Letter", state["cover_letter_markdown"])
        else:
            print("Invalid choice. Enter 'a', 'r', or 'q'.")

    # ── Step 7: PDF Generation (no LLM needed) ───────────────
    print("\n[Step 7/7] Generating PDFs...")
    output_dir = PROJECT_DIR / "output"
    output_dir.mkdir(exist_ok=True)

    cv_path = output_dir / "cv.pdf"
    cl_path = output_dir / "cover_letter.pdf"

    cv_pages = generate_pdf_from_markdown(state["cv_markdown"], str(cv_path))
    print(f"  CV saved to {cv_path} ({cv_pages} page{'s' if cv_pages > 1 else ''})")

    cl_pages = generate_pdf_from_markdown(state["cover_letter_markdown"], str(cl_path))
    print(f"  Cover letter saved to {cl_path} ({cl_pages} page{'s' if cl_pages > 1 else ''})")

    # ── Run Summary ───────────────────────────────────────────
    logger.print_summary()
    logger.save()

    print("Done! Check the output/ directory for your PDFs.")


# ── Gap analysis with borderline re-run ──────────────────────

def _run_gap_analysis(client, state, logger):
    """Run gap analysis, parse decomposed scores, and re-run if borderline (45-65).

    Returns (score, recommendation) tuple.
    """
    print("\n[Step 3/7] Analyzing fit (hiring manager perspective)...")
    metrics = logger.start_step("gap_analysis")
    state["gap_analysis"] = run_step(
        client, SYSTEM_PROMPT,
        STEP_GAP_ANALYSIS.format(
            job_description=state["job_description"],
            company_research=state["company_research"],
        ),
        metrics=metrics, step_name="gap_analysis",
    )
    logger.finish_step()
    print(state["gap_analysis"])

    # Parse dimension scores and compute weighted total
    dimension_scores = parse_dimension_scores(state["gap_analysis"])
    if not dimension_scores:
        print("  [warning] Could not parse dimension scores. Using default 50/100.")
        return 50.0, "STRATEGIC APPLY"

    score = compute_weighted_score(dimension_scores)
    recommendation = get_recommendation(score)
    print(format_score_summary(dimension_scores, score, recommendation))

    # Borderline re-run: if score is 45-65, run once more for confirmation
    if is_borderline(score):
        print("\n  [borderline] Score is in the 45-65 range. Running a second assessment...")
        metrics = logger.start_step("gap_analysis_rerun")
        second_analysis = run_step(
            client, SYSTEM_PROMPT,
            STEP_GAP_ANALYSIS.format(
                job_description=state["job_description"],
                company_research=state["company_research"],
            ),
            metrics=metrics, step_name="gap_analysis",
        )
        logger.finish_step()

        second_scores = parse_dimension_scores(second_analysis)
        if second_scores:
            second_total = compute_weighted_score(second_scores)
            # Average the two runs
            score = (score + second_total) / 2
            recommendation = get_recommendation(score)
            print(f"  [borderline] Second run: {second_total:.0f}/100. Averaged: {score:.0f}/100 — {recommendation}")
        else:
            print("  [borderline] Could not parse second run scores. Keeping first result.")

    return score, recommendation


# ── Guardrail auto-fix ────────────────────────────────────────

MAX_GUARDRAIL_RETRIES = 2

def _guardrail_auto_fix(client, state, candidate_name, logger):
    """Validate CV and cover letter. Auto-fix if guardrails fire. Max 2 retries each.

    Returns (cv_markdown, cover_letter_markdown) — either original or fixed.
    """
    cv = state["cv_markdown"]
    cl = state["cover_letter_markdown"]

    # Auto-fix CV
    for attempt in range(MAX_GUARDRAIL_RETRIES):
        cv_warnings = validate_cv(cv, candidate_name)
        if not cv_warnings:
            break
        warning_text = format_warnings(cv_warnings, "CV")
        print(warning_text)
        print(f"  [auto-fix] Asking the model to fix CV issues (attempt {attempt + 1}/{MAX_GUARDRAIL_RETRIES})...")
        metrics = logger.start_step(f"guardrail_fix_cv_{attempt + 1}")
        cv = run_step(
            client, SYSTEM_PROMPT,
            STEP_GUARDRAIL_FIX_CV.format(
                warnings="\n".join(f"- {w}" for w in cv_warnings),
                cv_markdown=cv,
            ),
            metrics=metrics, step_name="revision",
        )
        logger.finish_step()
    else:
        # Ran out of retries — show remaining warnings
        cv_warnings = validate_cv(cv, candidate_name)
        if cv_warnings:
            print(format_warnings(cv_warnings, "CV (unfixed — review manually)"))

    # Auto-fix cover letter
    for attempt in range(MAX_GUARDRAIL_RETRIES):
        cl_warnings = validate_cover_letter(cl, candidate_name)
        if not cl_warnings:
            break
        warning_text = format_warnings(cl_warnings, "Cover Letter")
        print(warning_text)
        print(f"  [auto-fix] Asking the model to fix cover letter issues (attempt {attempt + 1}/{MAX_GUARDRAIL_RETRIES})...")
        metrics = logger.start_step(f"guardrail_fix_cl_{attempt + 1}")
        cl = run_step(
            client, SYSTEM_PROMPT,
            STEP_GUARDRAIL_FIX_CL.format(
                warnings="\n".join(f"- {w}" for w in cl_warnings),
                cl_markdown=cl,
            ),
            metrics=metrics, step_name="revision",
        )
        logger.finish_step()
    else:
        cl_warnings = validate_cover_letter(cl, candidate_name)
        if cl_warnings:
            print(format_warnings(cl_warnings, "Cover Letter (unfixed — review manually)"))

    return cv, cl


# ── Gap question handler ──────────────────────────────────────

def _handle_gap_questions(client, state, master_list_path, logger=None):
    """Check if the gap analysis contains questions for the user.
    If so, ask them and update the master list with any new experience.

    Returns the joined answers string if any were given, or None.
    """
    gap_text = state["gap_analysis"]

    # Extract questions from the gap analysis
    questions = _extract_questions(gap_text)

    if not questions:
        return None

    print("\n" + "-" * 60)
    print("The agent has questions about potential missing experience.")
    print("Your answers help improve this application AND future ones.")
    print("-" * 60)
    print("\nAnswer each question, or press Enter to skip. Type 'done' to finish.\n")

    answers = []
    for i, question in enumerate(questions, 1):
        print(f"Q{i}: {question}")
        answer = input("A:  ").strip()
        if answer.lower() == "done":
            break
        if answer:
            answers.append(f"Q: {question}\nA: {answer}")

    if not answers:
        print("No new experience to add.")
        return None

    answers_text = "\n\n".join(answers)

    # Use the LLM to update the master list
    print("\nUpdating master list with your answers...")
    metrics = logger.start_step("gap_update") if logger else None
    current_content = master_list_path.read_text(encoding="utf-8")
    updated_content = run_step(
        client, SYSTEM_PROMPT,
        STEP_GAP_UPDATE.format(
            user_answers=answers_text,
            master_list_content=current_content,
        ),
        metrics=metrics, step_name="gap_update",
    )
    if logger:
        logger.finish_step()

    # Only write if the content actually changed
    if updated_content.strip() != current_content.strip() and len(updated_content.strip()) > 100:
        master_list_path.write_text(updated_content, encoding="utf-8")
        print("Master list updated with new experience.")
    else:
        print("No updates needed.")

    return answers_text


# ── Helper functions ──────────────────────────────────────────

def _fetch_job_from_url(url: str) -> str:
    """Fetch a job description from a URL (LinkedIn, etc.)."""
    import requests
    from bs4 import BeautifulSoup

    print(f"Fetching job description from: {url}")
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        job_text = None
        for selector in [
            ".description__text",
            ".show-more-less-html__markup",
            "[class*='description']",
            "article",
        ]:
            el = soup.select_one(selector)
            if el and len(el.get_text(strip=True)) > 100:
                job_text = el.get_text("\n", strip=True)
                break

        if not job_text:
            texts = []
            for tag in soup.find_all(["div", "section", "article"]):
                t = tag.get_text("\n", strip=True)
                if len(t) > 200:
                    texts.append(t)
            if texts:
                job_text = max(texts, key=len)

        if not job_text or len(job_text) < 100:
            print("\nCouldn't extract enough text from the URL.")
            print("Try: python3 main.py --job job.txt  (paste JD into a text file)")
            sys.exit(1)

        print(f"Extracted {len(job_text)} characters.\n")
        return job_text

    except requests.RequestException as e:
        print(f"\nFailed to fetch URL: {e}")
        print("Try: python3 main.py --job job.txt")
        sys.exit(1)


def _extract_questions(gap_text: str) -> list[str]:
    """Extract questions from gap analysis output, handling various formats.

    Handles:
    - "- question text"
    - "1. question text"
    - "1. **\"question text\"**"
    - "- \"question text\""
    """
    import re

    # Find the questions section — case-insensitive, handles bold markers
    import re as _re
    questions_start = None
    # Strip bold markers and normalize for matching
    match = _re.search(r'\*{0,2}questions[^*\n]*\*{0,2}', gap_text, _re.IGNORECASE)
    if match:
        questions_start = match.end()

    if questions_start is None:
        return []

    questions_text = gap_text[questions_start:]

    # Check for "None" right after the header
    first_50 = questions_text[:80].strip()
    if first_50.lower().startswith("none") or first_50.lower().startswith("- none"):
        return []

    questions = []
    for line in questions_text.split("\n"):
        line = line.strip()
        if not line:
            continue

        # Stop if we hit the next section (recommendation, etc.)
        if line.startswith("**") and "question" not in line.lower() and line.endswith("**"):
            break
        if line.lower().startswith("one-line") or line.lower().startswith("recommendation"):
            break

        # Match bullet or numbered list items
        # "- text", "* text", "1. text", "2. text", etc.
        m = re.match(r'^(?:[-*]|\d+[.)]) ?\s*(.*)', line)
        if m:
            q = m.group(1).strip()
            # Clean up formatting: **"text"** → text
            q = q.replace('**', '')  # Remove bold markers
            q = q.replace('""', '"')  # Fix double quotes
            # Remove orphan quotes (e.g., `cycle?"` → `cycle?`)
            q = re.sub(r'(?<=[?!.])"(?=\s|$)', '', q)
            # Remove leading/trailing quotes
            q = q.strip().strip('"').strip()
            if len(q) > 10:  # Skip very short non-question lines
                questions.append(q)

    return questions


def _extract_section(text: str, section_name: str, fallback: str) -> str:
    """Extract a section from revision output by looking for markdown headers."""
    markers = {
        "CV": ["# CV", "## CV", "# Revised CV", "## Revised CV"],
        "Cover Letter": ["# Cover Letter", "## Cover Letter", "# Revised Cover Letter", "## Revised Cover Letter"],
    }

    search_markers = markers.get(section_name, [])
    other_markers = [m for name, mlist in markers.items() if name != section_name for m in mlist]

    for marker in search_markers:
        idx = text.find(marker)
        if idx == -1:
            continue
        content = text[idx:]
        end = len(content)
        for other in other_markers:
            other_idx = content.find(other, len(marker))
            if other_idx != -1:
                end = min(end, other_idx)
        return content[:end].strip()

    return fallback


if __name__ == "__main__":
    main()
