"""Decomposed scoring — parses dimension scores and computes weighted totals.

The model scores each dimension independently. This module:
1. Parses the scores from the model's output
2. Computes a deterministic weighted total
3. Determines the recommendation (STRONG APPLY / APPLY / LIGHT APPLY / SKIP)
"""

import re

# Weights for each dimension (must sum to 1.0)
# Adjust these based on what matters most for the roles you apply to
DIMENSION_WEIGHTS = {
    "technical_skills": 0.25,
    "seniority_level": 0.20,
    "domain_experience": 0.25,
    "leadership_soft_skills": 0.15,
    "culture_values": 0.15,
}

# Score → recommendation thresholds
THRESHOLDS = {
    "STRONG APPLY": 75,   # Great fit — full effort, prioritise
    "APPLY": 55,          # Good enough — standard run
    "LIGHT APPLY": 35,    # Stretch/reach — use --quick, address gaps in cover letter
    "SKIP": 0,            # Genuinely wrong fit (wrong level, wrong function entirely)
}

# Map dimension label variations to standard keys
DIMENSION_ALIASES = {
    "technical skills match": "technical_skills",
    "technical skills": "technical_skills",
    "technical match": "technical_skills",
    "seniority level match": "seniority_level",
    "seniority level": "seniority_level",
    "seniority match": "seniority_level",
    "domain/industry experience": "domain_experience",
    "domain experience": "domain_experience",
    "industry experience": "domain_experience",
    "domain/industry": "domain_experience",
    "leadership & soft skills": "leadership_soft_skills",
    "leadership and soft skills": "leadership_soft_skills",
    "leadership/soft skills": "leadership_soft_skills",
    "leadership": "leadership_soft_skills",
    "soft skills": "leadership_soft_skills",
    "culture & values fit": "culture_values",
    "culture and values fit": "culture_values",
    "culture/values fit": "culture_values",
    "culture fit": "culture_values",
    "culture & values": "culture_values",
}


def parse_dimension_scores(gap_text: str) -> dict:
    """Parse dimension scores from the gap analysis output.

    Looks for lines like:
    - Technical skills match: 7/10 — justification text
    - Seniority level match: 8/10 — justification text

    Returns dict like:
    {
        "technical_skills": {"score": 7, "justification": "..."},
        "seniority_level": {"score": 8, "justification": "..."},
        ...
    }
    """
    scores = {}

    for line in gap_text.split("\n"):
        line = line.strip().lstrip("- ")
        # Match pattern: "Label: X/10" with optional justification
        m = re.match(r'^(.+?):\s*(\d+)/10(?:\s*[-—]\s*(.+))?$', line)
        if not m:
            continue

        label = m.group(1).strip().lower()
        label = label.replace("**", "")  # strip bold markers

        score = int(m.group(2))
        justification = m.group(3).strip() if m.group(3) else ""

        # Map to standard key
        key = DIMENSION_ALIASES.get(label)
        if key:
            scores[key] = {"score": score, "justification": justification}

    return scores


def compute_weighted_score(dimension_scores: dict) -> float:
    """Compute weighted total from dimension scores (0-100 scale)."""
    total = 0
    weight_sum = 0

    for key, weight in DIMENSION_WEIGHTS.items():
        if key in dimension_scores:
            total += dimension_scores[key]["score"] * weight
            weight_sum += weight

    if weight_sum == 0:
        return 0

    # Normalize in case some dimensions are missing, then scale to 0-100
    return (total / weight_sum) * 10


def get_recommendation(score: float) -> str:
    """Get recommendation based on score."""
    if score >= THRESHOLDS["STRONG APPLY"]:
        return "STRONG APPLY"
    elif score >= THRESHOLDS["APPLY"]:
        return "APPLY"
    elif score >= THRESHOLDS["LIGHT APPLY"]:
        return "LIGHT APPLY"
    else:
        return "SKIP"


def is_borderline(score: float) -> bool:
    """Check if the score is in the borderline range that warrants re-assessment."""
    return 40 <= score <= 60


def format_score_summary(dimension_scores: dict, weighted_score: float, recommendation: str) -> str:
    """Format a nice terminal summary of the scoring breakdown."""
    lines = []
    lines.append("")
    lines.append("=" * 50)
    lines.append("SCORING BREAKDOWN (computed by code, not the model)")
    lines.append("=" * 50)

    dimension_labels = {
        "technical_skills": "Technical skills",
        "seniority_level": "Seniority level",
        "domain_experience": "Domain/industry",
        "leadership_soft_skills": "Leadership & soft skills",
        "culture_values": "Culture & values fit",
    }

    for key, weight in DIMENSION_WEIGHTS.items():
        label = dimension_labels.get(key, key)
        if key in dimension_scores:
            s = dimension_scores[key]["score"]
            bar = "#" * s + "." * (10 - s)
            pct = int(weight * 100)
            lines.append(f"  {label:<24} [{bar}] {s}/10  (weight: {pct}%)")
        else:
            lines.append(f"  {label:<24} [..........] ?/10  (missing)")

    lines.append("-" * 50)
    lines.append(f"  Weighted total: {weighted_score:.0f}/100 — {recommendation}")
    lines.append("")

    return "\n".join(lines)
