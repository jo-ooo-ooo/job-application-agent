#!/usr/bin/env python3
"""Evaluation runner — measure output quality across sample JDs.

Three modes:
  python3 eval/eval.py --logs                          Analyze past run logs (no API calls)
  python3 eval/eval.py --dataset eval/jobs/            Run full pipeline on sample JDs
  python3 eval/eval.py --step cv_construction --dataset eval/jobs/  Evaluate a single step only
"""

import argparse
import importlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path so we can import from the main package
sys.path.insert(0, str(Path(__file__).parent.parent))

import anthropic
from dotenv import load_dotenv

import agent
from agent import run_step
from run_logger import RunLogger, LOGS_DIR, PRICING

VALID_MODELS = ["claude-opus-4-6", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"]
MODEL_SHORTCUTS = {"opus": "claude-opus-4-6", "sonnet": "claude-sonnet-4-6", "haiku": "claude-haiku-4-5-20251001"}
from prompts import (
    SYSTEM_PROMPT,
    STEP_COMPANY_RESEARCH,
    STEP_GAP_ANALYSIS,
    STEP_PROJECT_SELECTION,
    STEP_CV_CONSTRUCTION,
    STEP_COVER_LETTER,
)
from scoring import parse_dimension_scores, compute_weighted_score, get_recommendation
from guardrails import extract_candidate_name
from eval_criteria import run_all_checks
from tools import PROJECT_DIR

load_dotenv()

EVAL_RESULTS_DIR = Path(__file__).parent / "results"

# Steps in pipeline order, with their prompt template and required state keys
PIPELINE_STEPS = [
    {
        "name": "company_research",
        "prompt": STEP_COMPANY_RESEARCH,
        "format_keys": ["job_description"],
        "output_key": "company_research",
    },
    {
        "name": "gap_analysis",
        "prompt": STEP_GAP_ANALYSIS,
        "format_keys": ["job_description", "company_research"],
        "output_key": "gap_analysis",
    },
    {
        "name": "project_selection",
        "prompt": STEP_PROJECT_SELECTION,
        "format_keys": ["job_description", "company_research", "gap_analysis"],
        "output_key": "project_selection",
    },
    {
        "name": "cv_construction",
        "prompt": STEP_CV_CONSTRUCTION,
        "format_keys": ["job_description", "company_research", "project_selection", "manager_research"],
        "output_key": "cv_markdown",
    },
    {
        "name": "cover_letter",
        "prompt": STEP_COVER_LETTER,
        "format_keys": ["job_description", "company_research", "gap_analysis", "manager_research"],
        "output_key": "cover_letter_markdown",
    },
]


# ── Mode 1: Analyze past logs ─────────────────────────────────

def analyze_logs():
    """Read all JSON files from logs/ and print summary stats."""
    if not LOGS_DIR.exists():
        print("No logs/ directory found. Run the agent first to generate logs.")
        return

    log_files = sorted(LOGS_DIR.glob("run_*.json"))
    if not log_files:
        print("No run log files found in logs/.")
        return

    print(f"\nFound {len(log_files)} run logs")
    print("=" * 70)

    all_runs = []
    for lf in log_files:
        try:
            data = json.loads(lf.read_text(encoding="utf-8"))
            all_runs.append(data)
        except (json.JSONDecodeError, OSError) as e:
            print(f"  Skipping {lf.name}: {e}")

    if not all_runs:
        print("No valid log files found.")
        return

    # Per-step aggregation
    step_stats = {}  # step_name -> {tokens_in, tokens_out, cost, latency, retries, count}
    for run in all_runs:
        for step in run.get("steps", []):
            name = step["step"]
            if name not in step_stats:
                step_stats[name] = {
                    "input_tokens": [], "output_tokens": [], "cost": [],
                    "latency": [], "retries": [], "errors": 0,
                }
            s = step_stats[name]
            s["input_tokens"].append(step.get("input_tokens", 0))
            s["output_tokens"].append(step.get("output_tokens", 0))
            s["cost"].append(step.get("cost_usd", 0))
            s["latency"].append(step.get("latency_seconds", 0))
            s["retries"].append(step.get("retries", 0))
            if step.get("error"):
                s["errors"] += 1

    # Print per-step summary
    print(f"\n{'Step':<25} {'Runs':>5} {'Avg Tokens':>14} {'Avg Cost':>10} {'Avg Time':>9} {'Retries':>8} {'Errors':>7}")
    print("-" * 80)
    for name, s in sorted(step_stats.items()):
        n = len(s["cost"])
        avg_in = sum(s["input_tokens"]) // n
        avg_out = sum(s["output_tokens"]) // n
        avg_cost = sum(s["cost"]) / n
        avg_lat = sum(s["latency"]) / n
        total_retries = sum(s["retries"])
        print(
            f"  {name:<23} {n:>5} {avg_in:>7,}+{avg_out:<6,} "
            f"${avg_cost:>8.4f} {avg_lat:>7.1f}s {total_retries:>7} {s['errors']:>7}"
        )

    # Per-run totals
    print(f"\n{'Run':<25} {'Cost':>10} {'Tokens':>16} {'Time':>9} {'Steps':>6} {'Failed':>7}")
    print("-" * 75)
    costs = []
    for run in all_runs:
        ts = run.get("timestamp", "?")[:19]
        cost = run.get("total_cost_usd", 0)
        tokens = f"{run.get('total_input_tokens', 0):,}+{run.get('total_output_tokens', 0):,}"
        latency = run.get("total_latency_seconds", 0)
        steps = len(run.get("steps", []))
        failed = run.get("failed_steps", 0)
        costs.append(cost)
        print(f"  {ts:<23} ${cost:>8.4f} {tokens:>16} {latency:>7.1f}s {steps:>6} {failed:>7}")

    # Trend
    if len(costs) >= 2:
        direction = "UP" if costs[-1] > costs[0] else "DOWN" if costs[-1] < costs[0] else "FLAT"
        print(f"\nCost trend: {direction} (first: ${costs[0]:.4f}, latest: ${costs[-1]:.4f})")

    print(f"\nTotal across all runs: ${sum(costs):.4f}")


# ── Mode 2: Full pipeline on dataset ──────────────────────────

def run_pipeline_for_jd(client, jd_text, jd_name, logger):
    """Run the full pipeline for a single JD. Returns state dict."""
    state = {
        "job_description": jd_text,
        "manager_name": "",
        "company_research": "",
        "manager_research": "No hiring manager specified — skipping.",
        "gap_analysis": "",
        "project_selection": "",
        "cv_markdown": "",
        "cover_letter_markdown": "",
    }

    for step_info in PIPELINE_STEPS:
        step_name = step_info["name"]
        print(f"  [{jd_name}] Running {step_name}...")

        format_args = {k: state[k] for k in step_info["format_keys"]}
        user_message = step_info["prompt"].format(**format_args)

        metrics = logger.start_step(f"{jd_name}_{step_name}")
        try:
            result = run_step(
                client, SYSTEM_PROMPT, user_message,
                metrics=metrics, step_name=step_name,
            )
            state[step_info["output_key"]] = result
            logger.finish_step()
        except Exception as e:
            logger.finish_step(error=str(e))
            print(f"  [{jd_name}] ERROR in {step_name}: {e}")
            break

    return state


def save_state(state, jd_name):
    """Save pipeline state for a JD to eval_results/<jd_name>/state.json."""
    out_dir = EVAL_RESULTS_DIR / jd_name
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "state.json"
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return path


def load_state(jd_name):
    """Load cached state for a JD. Returns None if not found."""
    path = EVAL_RESULTS_DIR / jd_name / "state.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def get_candidate_name():
    """Extract candidate name from CV template, or return empty string."""
    template_path = PROJECT_DIR / "cvs" / "template_standard.md"
    if template_path.exists():
        return extract_candidate_name(template_path.read_text(encoding="utf-8"))
    return ""


def eval_dataset(dataset_dir, skip_judge=False):
    """Run full pipeline on all JDs in dataset_dir, evaluate, and print summary."""
    dataset_path = Path(dataset_dir)
    if not dataset_path.exists():
        print(f"Error: Dataset directory '{dataset_dir}' not found.")
        sys.exit(1)

    jd_files = sorted(dataset_path.glob("*.txt"))
    if not jd_files:
        print(f"No .txt files found in {dataset_dir}")
        sys.exit(1)

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY not set.")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)
    candidate_name = get_candidate_name()
    logger = RunLogger()

    print(f"\nEVAL: Running full pipeline on {len(jd_files)} JDs")
    print("=" * 60)

    all_results = {}
    all_checks = {}
    all_outputs = {}

    for jd_file in jd_files:
        jd_name = jd_file.stem
        jd_text = jd_file.read_text(encoding="utf-8")
        print(f"\n--- {jd_name}: {jd_text[:80].strip()}... ---")

        # Run pipeline
        state = run_pipeline_for_jd(client, jd_text, jd_name, logger)

        # Save state for per-step eval later
        save_state(state, jd_name)

        # Run eval criteria
        judge_client = None if skip_judge else client
        checks = run_all_checks(state, client=judge_client, candidate_name=candidate_name)
        all_checks[jd_name] = checks
        all_results[jd_name] = state

        # Save key outputs for later comparison
        all_outputs[jd_name] = {
            "company_research": state.get("company_research", ""),
            "gap_analysis": state.get("gap_analysis", ""),
            "project_selection": state.get("project_selection", ""),
            "cv_markdown": state.get("cv_markdown", ""),
            "cover_letter_markdown": state.get("cover_letter_markdown", ""),
        }

        # Print per-JD results
        for c in checks:
            print(f"    {c['name']:<25} {c['score']}/{c['max_score']}  {c['detail'][:60]}")

    # Print aggregate summary
    _print_summary_table(all_checks, jd_files)

    # Print cost summary
    logger.print_summary()
    logger.save()

    # Save eval results
    _save_eval_results(all_checks, logger, outputs=all_outputs)


# ── Mode 3: Single step evaluation ────────────────────────────

def eval_step(step_name, dataset_dir, compare_module=None, skip_judge=False):
    """Evaluate a single step across all JDs, optionally comparing prompt versions."""
    dataset_path = Path(dataset_dir)
    jd_files = sorted(dataset_path.glob("*.txt"))
    if not jd_files:
        print(f"No .txt files found in {dataset_dir}")
        sys.exit(1)

    # Validate step name
    step_info = None
    step_index = None
    for i, s in enumerate(PIPELINE_STEPS):
        if s["name"] == step_name:
            step_info = s
            step_index = i
            break
    if not step_info:
        valid = [s["name"] for s in PIPELINE_STEPS]
        print(f"Unknown step '{step_name}'. Valid steps: {', '.join(valid)}")
        sys.exit(1)

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY not set.")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)
    candidate_name = get_candidate_name()
    logger = RunLogger()

    # Load alternative prompts if comparing
    alt_prompt = None
    if compare_module:
        alt_prompts_mod = _load_prompts_module(compare_module)
        # Look for the matching prompt constant
        prompt_attr = f"STEP_{step_name.upper()}"
        alt_prompt = getattr(alt_prompts_mod, prompt_attr, None)
        if not alt_prompt:
            print(f"Warning: {compare_module} has no '{prompt_attr}'. Skipping comparison.")
            compare_module = None

    print(f"\nEVAL STEP: {step_name} on {len(jd_files)} JDs")
    if compare_module:
        print(f"  Comparing with: {compare_module}")
    print("=" * 60)

    all_checks_current = {}
    all_checks_compare = {}
    all_outputs_current = {}
    all_outputs_compare = {}

    for jd_file in jd_files:
        jd_name = jd_file.stem
        jd_text = jd_file.read_text(encoding="utf-8")
        print(f"\n--- {jd_name} ---")

        # Load or build prerequisite state
        state = load_state(jd_name)
        if state is None:
            print(f"  No cached state for {jd_name}. Running prerequisite steps...")
            state = _run_prerequisites(client, jd_text, step_index, jd_name, logger)
            save_state(state, jd_name)
        else:
            print(f"  Using cached state for {jd_name}")
            # Ensure JD text is current
            state["job_description"] = jd_text

        # Run the target step with current prompts
        print(f"  Running {step_name} (current prompts)...")
        format_args = {k: state[k] for k in step_info["format_keys"]}
        user_message = step_info["prompt"].format(**format_args)

        metrics = logger.start_step(f"{jd_name}_{step_name}")
        result = run_step(client, SYSTEM_PROMPT, user_message, metrics=metrics, step_name=step_name)
        state[step_info["output_key"]] = result
        logger.finish_step()
        all_outputs_current[jd_name] = result

        judge_client = None if skip_judge else client
        checks = run_all_checks(state, client=judge_client, candidate_name=candidate_name, step=step_name)
        all_checks_current[jd_name] = checks

        for c in checks:
            print(f"    [current] {c['name']:<25} {c['score']}/{c['max_score']}")

        # Run comparison if requested
        if alt_prompt:
            print(f"  Running {step_name} (compare prompts)...")
            alt_message = alt_prompt.format(**format_args)
            metrics = logger.start_step(f"{jd_name}_{step_name}_compare")
            alt_result = run_step(client, SYSTEM_PROMPT, alt_message, metrics=metrics, step_name=step_name)
            logger.finish_step()
            all_outputs_compare[jd_name] = alt_result

            alt_state = dict(state)
            alt_state[step_info["output_key"]] = alt_result
            alt_checks = run_all_checks(alt_state, client=judge_client, candidate_name=candidate_name, step=step_name)
            all_checks_compare[jd_name] = alt_checks

            for c in alt_checks:
                print(f"    [compare] {c['name']:<25} {c['score']}/{c['max_score']}")

    # Summary
    print("\n" + "=" * 60)
    print(f"STEP EVAL SUMMARY: {step_name}")
    print("=" * 60)
    _print_summary_table(all_checks_current, jd_files, label="Current")

    if all_checks_compare:
        _print_summary_table(all_checks_compare, jd_files, label="Compare")

    logger.print_summary()
    _save_eval_results(all_checks_current, logger, label=f"step_{step_name}", outputs=all_outputs_current)


def _run_prerequisites(client, jd_text, target_step_index, jd_name, logger):
    """Run all pipeline steps before the target step to build up state."""
    state = {
        "job_description": jd_text,
        "manager_name": "",
        "company_research": "",
        "manager_research": "No hiring manager specified — skipping.",
        "gap_analysis": "",
        "project_selection": "",
        "cv_markdown": "",
        "cover_letter_markdown": "",
    }

    for i in range(target_step_index):
        step_info = PIPELINE_STEPS[i]
        step_name = step_info["name"]
        print(f"    [prereq] Running {step_name}...")

        format_args = {k: state[k] for k in step_info["format_keys"]}
        user_message = step_info["prompt"].format(**format_args)

        metrics = logger.start_step(f"{jd_name}_prereq_{step_name}")
        try:
            result = run_step(
                client, SYSTEM_PROMPT, user_message,
                metrics=metrics, step_name=step_name,
            )
            state[step_info["output_key"]] = result
            logger.finish_step()
        except Exception as e:
            logger.finish_step(error=str(e))
            print(f"    [prereq] ERROR in {step_name}: {e}")
            break

    return state


def _load_prompts_module(module_path):
    """Load a Python module from a file path (for --compare)."""
    spec = importlib.util.spec_from_file_location("alt_prompts", module_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── Output formatting ─────────────────────────────────────────

def _print_summary_table(all_checks, jd_files, label=None):
    """Print aggregate summary table across all JDs."""
    if not all_checks:
        return

    header = f"EVAL RESULTS — {len(jd_files)} jobs"
    if label:
        header += f" ({label})"
    print(f"\n{header}")
    print("-" * 55)

    # Collect check names from first JD
    first_jd = next(iter(all_checks.values()))
    check_names = [c["name"] for c in first_jd]

    print(f"  {'Metric':<28} {'avg':>8} {'min':>6} {'max':>6}")
    print("-" * 55)

    for check_name in check_names:
        scores = []
        max_score = 0
        for jd_checks in all_checks.values():
            for c in jd_checks:
                if c["name"] == check_name:
                    scores.append(c["score"])
                    max_score = c["max_score"]
                    break

        if not scores:
            continue

        avg = sum(scores) / len(scores)

        # Format based on check type
        if max_score == 1:
            # Pass/fail — show as fraction
            passed = sum(scores)
            print(f"  {check_name:<28} {passed}/{len(scores):>5}     -      -")
        elif max_score == 5:
            # LLM judge — show as X/5
            print(f"  {check_name:<28} {avg:.1f}/5  {min(scores):>5}  {max(scores):>5}")
        elif max_score == 100:
            # Percentage
            print(f"  {check_name:<28} {avg:.0f}%   {min(scores):>5}% {max(scores):>5}%")
        else:
            # Numeric (word counts etc)
            print(f"  {check_name:<28} {avg:.0f}    {min(scores):>5}  {max(scores):>5}")

    print("-" * 55)


def _save_eval_results(all_checks, logger, label=None, outputs=None):
    """Save eval results to eval_results/eval_<timestamp>.json."""
    EVAL_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"eval_{label}_{timestamp}.json" if label else f"eval_{timestamp}.json"

    data = {
        "timestamp": datetime.now().isoformat(),
        "model": agent.MODEL,
        "total_cost_usd": round(logger.total_cost, 5),
        "total_input_tokens": logger.total_input_tokens,
        "total_output_tokens": logger.total_output_tokens,
        "jobs": {},
    }

    for jd_name, checks in all_checks.items():
        job_data = {
            "checks": [
                {"name": c["name"], "score": c["score"], "max_score": c["max_score"], "detail": c["detail"]}
                for c in checks
            ],
        }
        if outputs and jd_name in outputs:
            job_data["output"] = outputs[jd_name]
        data["jobs"][jd_name] = job_data

    path = EVAL_RESULTS_DIR / filename
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"\nEval results saved to {path}")


# ── CLI ───────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Evaluate job application agent output quality",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  python3 eval.py --logs                                   Analyze past run logs
  python3 eval.py --dataset eval_jobs/                     Full pipeline eval
  python3 eval.py --dataset eval_jobs/ --skip-judge        Skip LLM judge (free)
  python3 eval.py --step cv_construction --dataset eval_jobs/  Single step eval
  python3 eval.py --step cv_construction --dataset eval_jobs/ --compare prompts_v2.py
  python3 eval.py --step cv_construction --dataset eval_jobs/ --model opus
  python3 eval.py --step cv_construction --dataset eval_jobs/ --model haiku
""",
    )
    parser.add_argument("--logs", action="store_true", help="Analyze past run logs (no API calls)")
    parser.add_argument("--dataset", type=str, help="Directory with JD text files")
    parser.add_argument("--step", type=str, help="Evaluate a single pipeline step")
    parser.add_argument("--compare", type=str, help="Alternative prompts file for comparison")
    parser.add_argument("--model", type=str, help="Model to use: opus, sonnet, haiku (or full model ID)")
    parser.add_argument("--skip-judge", action="store_true", help="Skip LLM-as-judge checks (saves tokens)")

    args = parser.parse_args()

    if not args.logs and not args.dataset:
        parser.print_help()
        sys.exit(1)

    # Override model if specified
    if args.model:
        model_id = MODEL_SHORTCUTS.get(args.model.lower(), args.model)
        if model_id not in VALID_MODELS:
            print(f"Unknown model '{args.model}'. Valid: opus, sonnet, haiku (or full model ID)")
            sys.exit(1)
        agent.MODEL = model_id
        print(f"Using model: {model_id}")

    if args.logs:
        analyze_logs()
    elif args.step and args.dataset:
        eval_step(args.step, args.dataset, compare_module=args.compare, skip_judge=args.skip_judge)
    elif args.dataset:
        eval_dataset(args.dataset, skip_judge=args.skip_judge)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
