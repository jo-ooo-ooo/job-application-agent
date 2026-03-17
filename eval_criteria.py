"""Evaluation criteria — automated checks + LLM-as-judge scoring.

Each check returns a dict: { name, score, max_score, detail }
Automated checks are free (no API calls). LLM-as-judge checks use Haiku for speed/cost.
"""

import re
import anthropic
from guardrails import validate_cv, validate_cover_letter, validate_gap_analysis
from scoring import parse_dimension_scores

JUDGE_MODEL = "claude-haiku-4-5-20251001"


# ── Automated checks (deterministic, free) ────────────────────

def score_parse_success(state: dict) -> dict:
    """Did all 5 scoring dimensions parse from gap analysis?"""
    gap = state.get("gap_analysis", "")
    scores = parse_dimension_scores(gap)
    count = len(scores)
    return {
        "name": "Score parse success",
        "score": count,
        "max_score": 5,
        "detail": f"{count}/5 dimensions parsed",
    }


def cv_word_count(state: dict) -> dict:
    """Is CV within 100-800 words?"""
    cv = state.get("cv_markdown", "")
    count = len(cv.split()) if cv else 0
    in_range = 100 <= count <= 800
    return {
        "name": "CV word count",
        "score": count,
        "max_score": 800,
        "detail": f"{count} words {'(OK)' if in_range else '(OUT OF RANGE)'}",
    }


def cl_word_count(state: dict) -> dict:
    """Is cover letter within 50-500 words?"""
    cl = state.get("cover_letter_markdown", "")
    count = len(cl.split()) if cl else 0
    in_range = 50 <= count <= 500
    return {
        "name": "CL word count",
        "score": count,
        "max_score": 500,
        "detail": f"{count} words {'(OK)' if in_range else '(OUT OF RANGE)'}",
    }


def guardrail_pass(state: dict, candidate_name: str = "") -> dict:
    """Does CV/CL pass all guardrail checks?"""
    cv_warnings = validate_cv(state.get("cv_markdown", ""), candidate_name)
    cl_warnings = validate_cover_letter(state.get("cover_letter_markdown", ""), candidate_name)
    gap_warnings = validate_gap_analysis(state.get("gap_analysis", ""))
    total_warnings = len(cv_warnings) + len(cl_warnings) + len(gap_warnings)
    passed = total_warnings == 0
    details = []
    if cv_warnings:
        details.append(f"CV: {cv_warnings}")
    if cl_warnings:
        details.append(f"CL: {cl_warnings}")
    if gap_warnings:
        details.append(f"Gap: {gap_warnings}")
    return {
        "name": "Guardrail pass",
        "score": 1 if passed else 0,
        "max_score": 1,
        "detail": "All passed" if passed else "; ".join(details),
    }


def keyword_match(state: dict) -> dict:
    """What % of JD keywords appear in the CV?"""
    jd = state.get("job_description", "").lower()
    cv = state.get("cv_markdown", "").lower()

    if not jd or not cv:
        return {"name": "JD keyword match", "score": 0, "max_score": 100, "detail": "Missing JD or CV"}

    # Extract meaningful keywords from JD (3+ char words, skip common words)
    stop_words = {
        "the", "and", "for", "are", "with", "you", "our", "will", "this",
        "that", "from", "your", "have", "has", "been", "they", "their",
        "about", "what", "which", "when", "where", "who", "how", "all",
        "can", "but", "not", "one", "also", "more", "some", "other",
        "into", "than", "its", "over", "such", "only", "new", "most",
        "any", "may", "should", "would", "could", "each", "these",
        "role", "work", "team", "experience", "including", "across",
    }
    jd_words = set(re.findall(r'\b[a-z]{3,}\b', jd)) - stop_words
    if not jd_words:
        return {"name": "JD keyword match", "score": 0, "max_score": 100, "detail": "No keywords extracted"}

    matched = sum(1 for w in jd_words if w in cv)
    pct = round(matched / len(jd_words) * 100)

    return {
        "name": "JD keyword match",
        "score": pct,
        "max_score": 100,
        "detail": f"{matched}/{len(jd_words)} keywords ({pct}%)",
    }


# ── LLM-as-judge checks (costs tokens, uses Haiku) ───────────

def _judge(client: anthropic.Anthropic, prompt: str) -> tuple[int, str]:
    """Run an LLM-as-judge evaluation. Returns (score 1-5, explanation)."""
    response = client.messages.create(
        model=JUDGE_MODEL,
        max_tokens=256,
        temperature=0,
        messages=[{"role": "user", "content": prompt}],
    )
    text = response.content[0].text.strip()

    # Extract score — look for "Score: X" or just a leading digit
    m = re.search(r'(?:score|rating)[:\s]*(\d)', text, re.IGNORECASE)
    if not m:
        m = re.match(r'^(\d)', text)
    score = int(m.group(1)) if m else 3  # default to 3 if unparseable
    score = max(1, min(5, score))

    return score, text


def judge_cv_relevance(client: anthropic.Anthropic, state: dict) -> dict:
    """Rate 1-5: How well does this CV address the specific requirements in the JD?"""
    prompt = f"""Rate 1-5: How well does this CV address the specific requirements in the job description?

JOB DESCRIPTION:
{state.get('job_description', '')[:2000]}

CV:
{state.get('cv_markdown', '')[:2000]}

Respond with:
Score: X
Explanation: (1-2 sentences)"""

    score, detail = _judge(client, prompt)
    return {"name": "CV relevance (judge)", "score": score, "max_score": 5, "detail": detail}


def judge_cl_specificity(client: anthropic.Anthropic, state: dict) -> dict:
    """Rate 1-5: How specific is this cover letter to the company (vs generic)?"""
    prompt = f"""Rate 1-5: How specific is this cover letter to the company and role (vs being generic)?

JOB DESCRIPTION:
{state.get('job_description', '')[:2000]}

COVER LETTER:
{state.get('cover_letter_markdown', '')[:2000]}

Respond with:
Score: X
Explanation: (1-2 sentences)"""

    score, detail = _judge(client, prompt)
    return {"name": "CL specificity (judge)", "score": score, "max_score": 5, "detail": detail}


def judge_gap_accuracy(client: anthropic.Anthropic, state: dict) -> dict:
    """Rate 1-5: How accurate and honest is this gap analysis?"""
    prompt = f"""Rate 1-5: How accurate and honest is this gap analysis? Does it identify real gaps vs strengths?

JOB DESCRIPTION:
{state.get('job_description', '')[:2000]}

GAP ANALYSIS:
{state.get('gap_analysis', '')[:2000]}

Respond with:
Score: X
Explanation: (1-2 sentences)"""

    score, detail = _judge(client, prompt)
    return {"name": "Gap accuracy (judge)", "score": score, "max_score": 5, "detail": detail}


# ── Which checks apply to which steps ─────────────────────────

STEP_CHECKS = {
    "company_research": [],  # No automated quality checks yet
    "gap_analysis": ["score_parse_success", "judge_gap_accuracy"],
    "project_selection": [],
    "cv_construction": ["cv_word_count", "cv_guardrail", "keyword_match", "judge_cv_relevance"],
    "cover_letter": ["cl_word_count", "cl_guardrail", "judge_cl_specificity"],
}

ALL_AUTOMATED = {
    "score_parse_success": score_parse_success,
    "cv_word_count": cv_word_count,
    "cl_word_count": cl_word_count,
    "keyword_match": keyword_match,
}

ALL_JUDGE = {
    "judge_cv_relevance": judge_cv_relevance,
    "judge_cl_specificity": judge_cl_specificity,
    "judge_gap_accuracy": judge_gap_accuracy,
}


def cv_guardrail(state: dict, candidate_name: str = "") -> dict:
    """Does CV pass guardrail checks?"""
    warnings = validate_cv(state.get("cv_markdown", ""), candidate_name)
    return {
        "name": "CV guardrail",
        "score": 1 if not warnings else 0,
        "max_score": 1,
        "detail": "Passed" if not warnings else "; ".join(warnings),
    }


def cl_guardrail(state: dict, candidate_name: str = "") -> dict:
    """Does cover letter pass guardrail checks?"""
    warnings = validate_cover_letter(state.get("cover_letter_markdown", ""), candidate_name)
    return {
        "name": "CL guardrail",
        "score": 1 if not warnings else 0,
        "max_score": 1,
        "detail": "Passed" if not warnings else "; ".join(warnings),
    }


ALL_AUTOMATED["cv_guardrail"] = cv_guardrail
ALL_AUTOMATED["cl_guardrail"] = cl_guardrail


# ── Runners ───────────────────────────────────────────────────

def run_automated_checks(state: dict, candidate_name: str = "") -> list[dict]:
    """Run all automated (free) checks. Returns list of result dicts."""
    return [
        score_parse_success(state),
        cv_word_count(state),
        cl_word_count(state),
        guardrail_pass(state, candidate_name),
        keyword_match(state),
    ]


def run_judge_checks(client: anthropic.Anthropic, state: dict) -> list[dict]:
    """Run all LLM-as-judge checks. Returns list of result dicts."""
    return [
        judge_cv_relevance(client, state),
        judge_cl_specificity(client, state),
        judge_gap_accuracy(client, state),
    ]


def run_all_checks(state: dict, client: anthropic.Anthropic = None, candidate_name: str = "", step: str = None) -> list[dict]:
    """Run checks. If step is specified, only run checks relevant to that step."""
    if step and step in STEP_CHECKS:
        relevant = STEP_CHECKS[step]
        results = []
        for check_name in relevant:
            if check_name in ALL_AUTOMATED:
                fn = ALL_AUTOMATED[check_name]
                # Pass candidate_name to guardrail checks
                import inspect
                if "candidate_name" in inspect.signature(fn).parameters:
                    results.append(fn(state, candidate_name))
                else:
                    results.append(fn(state))
            elif check_name in ALL_JUDGE and client:
                results.append(ALL_JUDGE[check_name](client, state))
        return results

    # Full pipeline: run everything
    results = run_automated_checks(state, candidate_name)
    if client:
        results.extend(run_judge_checks(client, state))
    return results
