#!/usr/bin/env python3
"""Job Application Agent — structured state approach with hiring manager perspective."""

import argparse
import json as _json
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
from cv_data import parse_cv_json
from cv_scaffold import parse_scaffold
from latex_generator import generate_cv_pdf, generate_cover_letter_pdf
from prompts import (
    SYSTEM_PROMPT,
    STEP_GAP_ANALYSIS,
    STEP_GAP_UPDATE,
    STEP_GAP_REASSESSMENT,
    STEP_PROJECT_SELECTION,
    STEP_CV_CONSTRUCTION,
    STEP_COVER_LETTER,
    STEP_REVISION,
)
from agents import run_parallel_research, run_critic_loop
from tools import PROJECT_DIR
from pdf_generator import generate_pdf_from_markdown
from mcp_client import SheetsClient
from guardrails import (
    validate_cv,
    validate_cv_structured,
    validate_cv_against_scaffold,
    validate_cover_letter,
    validate_gap_analysis,
    extract_candidate_name,
    format_warnings,
)

load_dotenv()


def main():
    parser = argparse.ArgumentParser(description="AI-powered job application agent")
    parser.add_argument("--job", type=str, help="Job description text, file path, or URL")
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

    # Verify required files
    master_list_path = PROJECT_DIR / "cvs" / "projects_master_list.md"
    template_path = PROJECT_DIR / "cvs" / "template_standard.md"
    if not master_list_path.exists():
        print(f"Error: {master_list_path} not found. See examples/ for format.")
        sys.exit(1)
    if not template_path.exists():
        print(f"Error: {template_path} not found. See examples/ for format.")
        sys.exit(1)

    # Extract candidate name from template for guardrail checks
    candidate_name = extract_candidate_name(template_path.read_text(encoding="utf-8"))

    # Parse CV scaffold (fixed facts: companies, dates, projects, skills inventory)
    try:
        scaffold = parse_scaffold(master_list_path.read_text(encoding="utf-8"))
        print(f"  [scaffold] {len(scaffold.experience_skeletons)} roles, "
              f"{len(scaffold.side_project_refs)} projects, "
              f"{len(scaffold.skills_inventory)} skill tokens")
    except ValueError as e:
        print(f"  [scaffold] Warning: could not parse scaffold — {e}")
        scaffold = None

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY not set. Copy .env.example to .env and add your key.")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)
    logger = RunLogger()

    # ── MCP: Google Sheets (optional — graceful fallback if unavailable) ──
    sheets = SheetsClient()
    sheets.health_check()

    # ── Structured state ──────────────────────────────────────
    if checkpoint:
        state = checkpoint["state"]
        # Backward compatibility: old checkpoints may have manager fields
        state.pop("manager_name", None)
        state.pop("manager_research", None)
        state.setdefault("role_analysis", "")
    else:
        state = {
            "job_description": job_desc,
            "company_research": "",
            "role_analysis": "",
            "gap_analysis": "",
            "project_selection": "",
            "cv_markdown": "",
            "cv_json": "",
            "cover_letter_markdown": "",
        }

    print("=" * 60)
    print("JOB APPLICATION AGENT")
    if checkpoint:
        print(f"  (resumed from checkpoint {run_id})")
    print("=" * 60)

    # Backward compat: treat old step names as equivalent to "research"
    if "company_research" in completed_steps and "hiring_manager" in completed_steps:
        if "research" not in completed_steps:
            completed_steps.append("research")

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
            else:
                # Fallback: extract overall score like "Updated Score: 72/100"
                import re
                m = re.search(r'(\d+)/100', reassessment)
                if m:
                    score = float(m.group(1))
                    recommendation = get_recommendation(score)
                    print(f"\n  Updated score: {score:.0f}/100 — {recommendation}")

        # Store final score in state so Sheets logging always uses the latest
        state["final_score"] = score
        state["final_recommendation"] = recommendation

        completed_steps.append("gap_analysis")
        save_checkpoint(run_id, state, completed_steps, completed_gates)
    else:
        print("\n[Step 2/6] Gap analysis — skipped (cached)")
        print(state["gap_analysis"])
        # Re-derive score for the gate display
        score = state.get("final_score") or 50.0
        recommendation = state.get("final_recommendation") or "STRATEGIC APPLY"
        if not state.get("final_score"):
            gap_text = state["gap_analysis"]
            # Prefer scores from the updated section if a reassessment happened
            if "--- UPDATED ---" in gap_text:
                updated_text = gap_text.split("--- UPDATED ---")[-1]
                # Try overall score first (e.g. "Updated Score: 72/100")
                import re
                m = re.search(r'(\d+)/100', updated_text)
                if m:
                    score = float(m.group(1))
                    recommendation = get_recommendation(score)
                else:
                    dimension_scores = parse_dimension_scores(updated_text)
                    if dimension_scores:
                        score = compute_weighted_score(dimension_scores)
                        recommendation = get_recommendation(score)
            else:
                dimension_scores = parse_dimension_scores(gap_text)
                if dimension_scores:
                    score = compute_weighted_score(dimension_scores)
                    recommendation = get_recommendation(score)
            # Persist so Sheets logging picks it up
            state["final_score"] = score
            state["final_recommendation"] = recommendation

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
        print("\n[Step 3/6] Selecting best-fit projects...")
        metrics = logger.start_step("project_selection")
        scaffold_companies = (
            "\n".join(f"- {s.company} ({s.title})" for s in scaffold.experience_skeletons)
            if scaffold else "(scaffold unavailable — include all companies from master list)"
        )
        state["project_selection"] = run_step(
            client, SYSTEM_PROMPT,
            STEP_PROJECT_SELECTION.format(
                job_description=state["job_description"],
                company_research=state["company_research"],
                gap_analysis=state["gap_analysis"],
                scaffold_companies=scaffold_companies,
            ),
            metrics=metrics, step_name="project_selection",
        )
        logger.finish_step()
        completed_steps.append("project_selection")
        save_checkpoint(run_id, state, completed_steps, completed_gates)
    else:
        print("\n[Step 3/6] Project selection — skipped (cached)")
    print(state["project_selection"])

    # ── Step 5: CV Construction ───────────────────────────────
    if "cv_construction" not in completed_steps:
        print("\n[Step 4/6] Constructing tailored CV...")
        metrics = logger.start_step("cv_construction")

        # Build scaffold JSON for prompt injection
        if scaffold is not None:
            scaffold_data = {
                "experience_skeletons": [
                    {"title": s.title, "company": s.company,
                     "location": s.location, "dates": s.dates}
                    for s in scaffold.experience_skeletons
                ],
                "side_project_refs": [
                    {"name": r.name, "github_url": r.github_url}
                    for r in scaffold.side_project_refs
                ],
                "skills_inventory": sorted(scaffold.skills_inventory),
            }
            scaffold_json = _json.dumps(scaffold_data, ensure_ascii=False, indent=2)
        else:
            scaffold_json = "{}"

        raw_cv = run_step(
            client, SYSTEM_PROMPT,
            STEP_CV_CONSTRUCTION.format(
                job_description=state["job_description"],
                company_research=state["company_research"],
                project_selection=state["project_selection"],
                scaffold_json=scaffold_json,
            ),
            metrics=metrics, step_name="cv_construction",
            exclude_tools=["generate_pdf"],
        )
        # Parse structured JSON output
        try:
            cv_data = parse_cv_json(raw_cv)
            # Store clean JSON (re-serialized from parsed data)
            state["cv_json"] = _json.dumps(cv_data.__dict__, default=lambda o: o.__dict__, indent=2)
        except (ValueError, KeyError) as e:
            print(f"  [warning] Failed to parse structured CV: {e}")
            print("  [warning] Falling back to markdown CV.")
            state["cv_markdown"] = _strip_code_fences(raw_cv)
        logger.finish_step()
        completed_steps.append("cv_construction")
        save_checkpoint(run_id, state, completed_steps, completed_gates)
    else:
        print("\n[Step 4/6] CV construction — skipped (cached)")
    # Display CV content for user review
    if state.get("cv_json"):
        from agents import _format_cv_for_review
        print(_format_cv_for_review(state["cv_json"]))
    else:
        print(state.get("cv_markdown", ""))

    # ── Step 6: Cover Letter ──────────────────────────────────
    if "cover_letter" not in completed_steps:
        print("\n[Step 5/6] Writing cover letter...")
        metrics = logger.start_step("cover_letter")
        raw_cl = run_step(
            client, SYSTEM_PROMPT,
            STEP_COVER_LETTER.format(
                job_description=state["job_description"],
                company_research=state["company_research"],
                gap_analysis=state["gap_analysis"],
            ),
            metrics=metrics, step_name="cover_letter",
            exclude_tools=["generate_pdf"],
        )
        state["cover_letter_markdown"] = _strip_code_fences(raw_cl)
        logger.finish_step()
        completed_steps.append("cover_letter")
        save_checkpoint(run_id, state, completed_steps, completed_gates)
    else:
        print("\n[Step 5/6] Cover letter — skipped (cached)")
    print(state["cover_letter_markdown"])

    # ── Critic Review Loop ────────────────────────────────────
    # Use structured JSON if available, fall back to markdown
    cv_for_critic = state.get("cv_json") or state.get("cv_markdown", "")

    critic_result = run_critic_loop(
        client,
        job_description=state["job_description"],
        role_analysis=state["role_analysis"],
        cv_markdown=cv_for_critic,
        cover_letter_markdown=state["cover_letter_markdown"],
        logger=logger,
    )

    # Update state from critic result
    if state.get("cv_json"):
        state["cv_json"] = critic_result.cv_markdown
    else:
        state["cv_markdown"] = _strip_code_fences(critic_result.cv_markdown)
    state["cover_letter_markdown"] = _strip_code_fences(critic_result.cover_letter_markdown)
    state["critic_result"] = critic_result.to_dict()
    save_checkpoint(run_id, state, completed_steps, completed_gates)

    # Run structural guardrails as a safety net — auto-fix if issues detected
    if state.get("cv_json"):
        try:
            cv_dict = _json.loads(state["cv_json"])
            cv_warnings = validate_cv_structured(cv_dict, candidate_name)
            # Scaffold validation: deterministic check of frozen facts
            if scaffold is not None:
                cv_warnings += validate_cv_against_scaffold(cv_dict, scaffold)
        except _json.JSONDecodeError:
            cv_warnings = ["CV JSON is malformed after critic loop."]
    else:
        cv_warnings = validate_cv(state.get("cv_markdown", ""), candidate_name)
    cl_warnings = validate_cover_letter(state["cover_letter_markdown"], candidate_name)
    if cv_warnings or cl_warnings:
        if cv_warnings:
            print(format_warnings(cv_warnings, "CV"))
        if cl_warnings:
            print(format_warnings(cl_warnings, "Cover Letter"))
        print("  [guardrail] Structural issues detected. Asking the model to fix...")
        metrics = logger.start_step("guardrail_fix")
        cv_for_fix = state.get("cv_json") or state.get("cv_markdown", "")
        feedback_lines = (
            [f"- CV: {w}" for w in cv_warnings] +
            [f"- Cover Letter: {w}" for w in cl_warnings]
        )
        # Inject scaffold frozen facts so the model knows exact title/company/location/dates
        # for any missing roles — without this it may still omit them or hallucinate fields.
        scaffold_hint = ""
        if scaffold is not None:
            scaffold_hint = (
                "\n\nCV SCAFFOLD — FROZEN FACTS (use these exact values when adding missing roles):\n"
                + _json.dumps({
                    "experience_skeletons": [
                        {"title": s.title, "company": s.company, "location": s.location, "dates": s.dates}
                        for s in scaffold.experience_skeletons
                    ],
                    "side_project_refs": [
                        {"name": r.name, "github_url": r.github_url}
                        for r in scaffold.side_project_refs
                    ],
                }, ensure_ascii=False, indent=2)
            )
        fix_prompt = STEP_REVISION.format(
            feedback="Fix these structural issues:\n" + "\n".join(feedback_lines) + scaffold_hint,
            job_description=state["job_description"],
            cv_json=cv_for_fix,
            cover_letter_markdown=state["cover_letter_markdown"],
        )
        fix_result = run_step(client, SYSTEM_PROMPT, fix_prompt, metrics=metrics, step_name="revision", exclude_tools=["generate_pdf"])
        logger.finish_step()
        revised_cv = _extract_section(fix_result, "CV", cv_for_fix)
        if state.get("cv_json"):
            state["cv_json"] = revised_cv
        else:
            state["cv_markdown"] = revised_cv
        state["cover_letter_markdown"] = _extract_section(fix_result, "Cover Letter", state["cover_letter_markdown"])

    # ── Save preview files for review ────────────────────────
    output_dir = PROJECT_DIR / "output"
    output_dir.mkdir(exist_ok=True)
    if state.get("cv_json"):
        (output_dir / "cv_preview.json").write_text(state["cv_json"], encoding="utf-8")
    else:
        (output_dir / "cv_preview.md").write_text(state.get("cv_markdown", ""), encoding="utf-8")
    (output_dir / "cover_letter_preview.md").write_text(state["cover_letter_markdown"], encoding="utf-8")

    # ── STOP Gate 2 ───────────────────────────────────────────
    while True:
        print("\n" + "=" * 60)
        print("STOP GATE: Review CV and cover letter.")
        print(f"  Preview files saved to: {output_dir}/")
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
            cv_for_revision = state.get("cv_json") or state.get("cv_markdown", "")
            revision = run_step(
                client, SYSTEM_PROMPT,
                STEP_REVISION.format(
                    feedback=feedback,
                    job_description=state["job_description"],
                    cv_json=cv_for_revision,
                    cover_letter_markdown=state["cover_letter_markdown"],
                ),
                metrics=metrics, step_name="revision",
            )
            logger.finish_step()
            print(revision)
            revised_cv = _extract_section(revision, "CV", cv_for_revision)
            state["cover_letter_markdown"] = _extract_section(revision, "Cover Letter", state["cover_letter_markdown"])
            if state.get("cv_json"):
                state["cv_json"] = revised_cv
            else:
                state["cv_markdown"] = revised_cv
        else:
            print("Invalid choice. Enter 'a', 'r', or 'q'.")

    # ── Step 6: PDF Generation ───────────────────────────────
    print("\n[Step 6/6] Generating PDFs...")
    output_dir = PROJECT_DIR / "output"
    output_dir.mkdir(exist_ok=True)

    # Build descriptive filenames: Candidate_Name_CV_CompanyName_RoleAbbrev.pdf
    cv_filename, cl_filename = _build_pdf_filenames(candidate_name, state)
    cv_path = output_dir / cv_filename
    cl_path = output_dir / cl_filename

    # CV: use LaTeX if structured JSON available, fall back to fpdf2
    if state.get("cv_json"):
        try:
            cv_data = parse_cv_json(state["cv_json"])
            cv_pages = generate_cv_pdf(cv_data, str(cv_path))
        except Exception as e:
            print(f"  [warning] LaTeX generation failed: {e}")
            print("  [warning] Falling back to fpdf2.")
            from agents import _format_cv_for_review
            cv_pages = generate_pdf_from_markdown(_format_cv_for_review(state["cv_json"]), str(cv_path))
    else:
        cv_pages = generate_pdf_from_markdown(state.get("cv_markdown", ""), str(cv_path))
    print(f"  CV saved to {cv_path} ({cv_pages} page{'s' if cv_pages > 1 else ''})")

    # Cover letter: use LaTeX, fall back to fpdf2
    try:
        # Get contact info from CV data
        if state.get("cv_json"):
            cv_info = _json.loads(state["cv_json"])
            cl_name = cv_info.get("name", candidate_name)
            cl_email = cv_info.get("email", "")
            cl_phone = cv_info.get("phone", "")
            cl_location = cv_info.get("location", "")
        else:
            cl_name = candidate_name
            cl_email = ""
            cl_phone = ""
            cl_location = ""
        cl_pages = generate_cover_letter_pdf(
            cl_name, cl_email, cl_phone, cl_location,
            state["cover_letter_markdown"],
            str(cl_path),
        )
    except Exception as e:
        print(f"  [warning] LaTeX cover letter failed: {e}")
        print("  [warning] Falling back to fpdf2.")
        cl_pages = generate_pdf_from_markdown(state["cover_letter_markdown"], str(cl_path))
    print(f"  Cover letter saved to {cl_path} ({cl_pages} page{'s' if cl_pages > 1 else ''})")

    # ── Log to Google Sheets via MCP ──────────────────────────
    final_score = state.get("final_score", 50.0)
    final_recommendation = state.get("final_recommendation", "STRATEGIC APPLY")
    sheets.log_application(run_id, state, final_score, final_recommendation)

    # ── Run Summary ───────────────────────────────────────────
    logger.print_summary()
    logger.save()

    print("Done! Check the output/ directory for your PDFs.")


# ── Gap analysis with borderline re-run ──────────────────────

def _run_gap_analysis(client, state, logger):
    """Run gap analysis, parse decomposed scores, and re-run if borderline (45-65).

    Returns (score, recommendation) tuple.
    """
    print("\n[Step 2/6] Analyzing fit (hiring manager perspective)...")
    metrics = logger.start_step("gap_analysis")
    state["gap_analysis"] = run_step(
        client, SYSTEM_PROMPT,
        STEP_GAP_ANALYSIS.format(
            job_description=state["job_description"],
            company_research=state["company_research"],
            role_analysis=state["role_analysis"],
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
                role_analysis=state["role_analysis"],
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

    # Use the LLM to generate only the new content to append
    print("\nUpdating master list with your answers...")
    metrics = logger.start_step("gap_update") if logger else None
    new_content = run_step(
        client, SYSTEM_PROMPT,
        STEP_GAP_UPDATE.format(user_answers=answers_text),
        metrics=metrics, step_name="gap_update",
    )
    if logger:
        logger.finish_step()

    # Append to a dedicated section — never rewrite the file
    new_content = new_content.strip()
    if new_content and new_content != "NO_UPDATE":
        current = master_list_path.read_text(encoding="utf-8")
        clarifications_header = "## Candidate Clarifications"
        if clarifications_header not in current:
            # First addition: create the section
            append_block = f"\n\n---\n\n{clarifications_header}\n\n{new_content}\n"
        else:
            # Section already exists: append below it
            append_block = f"\n{new_content}\n"
        master_list_path.write_text(current + append_block, encoding="utf-8")
        print("Master list updated (appended to Candidate Clarifications).")
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


def _build_pdf_filenames(candidate_name: str, state: dict) -> tuple[str, str]:
    """Build descriptive PDF filenames like Candidate_Name_CV_Company_Role.pdf."""
    import re

    name_part = candidate_name.replace(" ", "_")
    company = ""
    role_abbrev = ""

    job = state.get("job_description", "")
    research = state.get("company_research", "")

    # ── Company name ──────────────────────────────────────────────────────────
    # Best source: company_research — the model writes "**Company:** Name, ..."
    # Match both "- Company:" and "- **Company:**" (bold markdown) variants.
    m = re.search(r'[-*]\s*\**Company:\**\s*\[?([A-Za-z0-9][A-Za-z0-9 .&\'-]{1,40}?)(?:\s*[,\(\[]|$)', research, re.MULTILINE)
    if m:
        company = m.group(1).strip()

    # Fallback: role_analysis often has "## CompanyName — Role Title"
    if not company:
        role_analysis = state.get("role_analysis", "")
        m = re.search(r'(?:##|###)\s*([A-Z][A-Za-z0-9 .&\'-]{1,30}?)\s*[—–-]', role_analysis)
        if m:
            company = m.group(1).strip()

    # ── Role abbreviation ─────────────────────────────────────────────────────
    role_map = {
        "senior product manager": "SPM",
        "product manager": "PM",
        "senior pm": "SPM",
        "head of product": "HoP",
        "director of product": "DoP",
        "vp of product": "VPP",
        "chief product officer": "CPO",
        "group product manager": "GPM",
        "principal product manager": "PPM",
        "staff product manager": "StaffPM",
        "product lead": "PL",
        "product owner": "PO",
    }
    job_lower = job.lower()
    for role_title, abbrev in sorted(role_map.items(), key=lambda x: -len(x[0])):
        if role_title in job_lower:
            role_abbrev = abbrev
            break

    # ── Clean up ──────────────────────────────────────────────────────────────
    company = re.sub(r'[^\w\s]', '', company).strip().replace(" ", "_")
    if not company:
        company = "Company"
    if not role_abbrev:
        role_abbrev = "PM"

    cv_name = f"{name_part}_CV_{company}_{role_abbrev}.pdf"
    cl_name = f"{name_part}_Cover_Letter_{company}_{role_abbrev}.pdf"
    return cv_name, cl_name


def _strip_code_fences(text: str) -> str:
    """Strip markdown code fences (```markdown ... ```) from model output."""
    import re
    # Remove opening ```markdown or ``` and closing ```
    stripped = re.sub(r'^```\w*\n', '', text.strip())
    stripped = re.sub(r'\n```\s*$', '', stripped)
    return stripped.strip()


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
