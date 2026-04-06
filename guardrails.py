"""Output guardrails — runtime checks on LLM-generated content before it ships.

These catch problems that unit tests can't: hallucinated experience,
missing candidate info, word count violations, etc.
"""

from __future__ import annotations
import re


def validate_cv(cv_markdown: str, candidate_name: str, max_words: int = 800) -> list[str]:
    """Validate a generated CV. Returns a list of warning strings (empty = all good)."""
    warnings = []

    if not cv_markdown or len(cv_markdown.strip()) < 50:
        warnings.append("CV is empty or too short.")
        return warnings

    # 1. Candidate name must appear in the CV
    if candidate_name and candidate_name.lower() not in cv_markdown.lower():
        warnings.append(
            f"CV does not contain the candidate's name ('{candidate_name}'). "
            "The model may have hallucinated a different person."
        )

    # 2. Word count check
    word_count = len(cv_markdown.split())
    if word_count > max_words:
        warnings.append(
            f"CV is {word_count} words (max {max_words}). "
            "It may be too long for a 1-1.5 page PDF."
        )
    if word_count < 100:
        warnings.append(f"CV is only {word_count} words — suspiciously short.")

    # 3. Must have section headers (## headings)
    headers = re.findall(r'^##\s+.+', cv_markdown, re.MULTILINE)
    if len(headers) < 2:
        warnings.append(
            f"CV has only {len(headers)} section headers. "
            "Expected at least 2 (e.g., Experience, Education)."
        )

    # 4. Check for placeholder text the model sometimes leaves in
    placeholder_patterns = [
        r'\[your name\]', r'\[company\]', r'\[insert', r'\[placeholder',
        r'\[TODO\]', r'\[fill in\]', r'\[add ', r'XX/XXXX',
    ]
    for pattern in placeholder_patterns:
        if re.search(pattern, cv_markdown, re.IGNORECASE):
            warnings.append(f"CV contains placeholder text matching: {pattern}")

    # 5. Contact info should exist (email or phone pattern)
    has_email = bool(re.search(r'[\w.+-]+@[\w-]+\.[\w.]+', cv_markdown))
    has_phone = bool(re.search(r'[\d\s\-().+]{7,}', cv_markdown))
    if not has_email and not has_phone:
        warnings.append("CV has no email or phone number. Contact info may be missing.")

    return warnings


def validate_cover_letter(
    cl_markdown: str,
    candidate_name: str,
    max_words: int = 500,
) -> list[str]:
    """Validate a generated cover letter. Returns a list of warning strings."""
    warnings = []

    if not cl_markdown or len(cl_markdown.strip()) < 50:
        warnings.append("Cover letter is empty or too short.")
        return warnings

    word_count = len(cl_markdown.split())

    # 1. Word count
    if word_count > max_words:
        warnings.append(
            f"Cover letter is {word_count} words (max {max_words}). Too long."
        )
    if word_count < 50:
        warnings.append(f"Cover letter is only {word_count} words — too short.")

    # 2. Candidate name in sign-off
    if candidate_name and candidate_name.lower() not in cl_markdown.lower():
        warnings.append(
            f"Cover letter does not contain the candidate's name ('{candidate_name}'). "
            "Sign-off may be missing or wrong."
        )

    # 3. Check for placeholder text
    placeholder_patterns = [
        r'\[your name\]', r'\[company name\]', r'\[insert', r'\[placeholder',
        r'\[TODO\]', r'\[hiring manager\]',
    ]
    for pattern in placeholder_patterns:
        if re.search(pattern, cl_markdown, re.IGNORECASE):
            warnings.append(f"Cover letter contains placeholder text: {pattern}")

    # 4. Generic flattery detection
    generic_phrases = [
        "I am writing to express my interest",
        "I am excited to apply",
        "I believe I am a perfect fit",
        "I would be a great asset",
    ]
    generic_count = sum(
        1 for phrase in generic_phrases
        if phrase.lower() in cl_markdown.lower()
    )
    if generic_count >= 2:
        warnings.append(
            f"Cover letter uses {generic_count} generic phrases. "
            "It may sound too templated."
        )

    return warnings


def validate_gap_analysis(gap_text: str) -> list[str]:
    """Validate gap analysis output has the expected structure."""
    warnings = []

    if not gap_text or len(gap_text.strip()) < 50:
        warnings.append("Gap analysis is empty or too short.")
        return warnings

    # Must contain scoring lines
    score_pattern = r'\d+/10'
    score_matches = re.findall(score_pattern, gap_text)
    if len(score_matches) < 3:
        warnings.append(
            f"Gap analysis has only {len(score_matches)} dimension scores "
            "(expected 5). The model may not have followed the scoring format."
        )

    return warnings


def validate_cv_structured(cv_data: dict, candidate_name: str, max_total_bullets: int = 30) -> list[str]:
    """Validate structured CV data (dict from JSON). Returns list of warning strings."""
    warnings = []

    if not cv_data:
        warnings.append("CV data is empty.")
        return warnings

    # 1. Name check
    name_in_cv = cv_data.get("name", "")
    if candidate_name and candidate_name.lower() not in name_in_cv.lower():
        warnings.append(
            f"CV name ('{name_in_cv}') does not match candidate name ('{candidate_name}'). "
            "The model may have hallucinated a different person."
        )

    # 2. Contact info
    if not cv_data.get("email") and not cv_data.get("phone"):
        warnings.append("CV has no email or phone number. Contact info may be missing.")

    # 3. Experience must exist
    experience = cv_data.get("experience", [])
    if not experience:
        warnings.append("CV has no experience entries.")

    # 4. Total bullet count (proxy for page length)
    total_bullets = sum(len(exp.get("bullets", [])) for exp in experience)
    for proj in cv_data.get("side_projects", []):
        total_bullets += len(proj.get("bullets", []))
    if total_bullets > max_total_bullets:
        warnings.append(
            f"CV has {total_bullets} total bullets (max {max_total_bullets}). "
            "It will likely exceed 1 page."
        )

    # 5. Placeholder detection in all text fields
    placeholder_patterns = [
        r'\[your name\]', r'\[company\]', r'\[insert', r'\[placeholder',
        r'\[TODO\]', r'\[fill in\]', r'\[add ', r'XX/XXXX',
    ]
    all_text = _collect_all_text(cv_data)
    for pattern in placeholder_patterns:
        if re.search(pattern, all_text, re.IGNORECASE):
            warnings.append(f"CV contains placeholder text matching: {pattern}")

    # 6. Skills section: too many categories or narrative sentences in skill items
    skills = cv_data.get("skills", {})
    if isinstance(skills, dict):
        if len(skills) > 5:
            warnings.append(
                f"Skills section has {len(skills)} categories (max 5). Merge related groups."
            )
        for cat, items in skills.items():
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, str) and (len(item) > 60 or ";" in item):
                        warnings.append(
                            f"Skill item in '{cat}' reads as a sentence, not a tag: \"{item[:80]}\""
                        )

    return warnings


def _collect_all_text(cv_data: dict) -> str:
    """Collect all text from structured CV data for validation."""
    parts = [
        cv_data.get("name", ""),
        cv_data.get("title_tagline", ""),
    ]
    for exp in cv_data.get("experience", []):
        parts.append(exp.get("title", ""))
        parts.append(exp.get("company", ""))
        parts.extend(exp.get("bullets", []))
    for proj in cv_data.get("side_projects", []):
        parts.append(proj.get("name", ""))
        parts.extend(proj.get("bullets", []))
    return " ".join(parts)


def extract_candidate_name(template_content: str) -> str:
    """Extract the candidate's name from the CV template (first H1 heading)."""
    match = re.search(r'^#\s+(.+)', template_content, re.MULTILINE)
    if match:
        name = match.group(1).strip()
        # Strip any markdown formatting
        name = name.replace("**", "").replace("*", "").strip()
        return name
    return ""


def format_warnings(warnings: list[str], label: str) -> str:
    """Format warnings for terminal display. Returns empty string if no warnings."""
    if not warnings:
        return ""
    lines = [f"\n{'!'*50}", f"  GUARDRAIL WARNINGS — {label}", "!" * 50]
    for w in warnings:
        lines.append(f"  ⚠ {w}")
    lines.append("")
    return "\n".join(lines)


def validate_cv_against_scaffold(cv_dict: dict, scaffold: "CVScaffold") -> list[str]:
    """Validate generated CV dict against the parsed master list scaffold.

    Three deterministic checks:
    1. Experience — all skeleton roles present; company/title/location/dates match.
    2. Side projects — selected name+github_url pairs exist in catalogue.
    3. Skills — every token exists in the master list inventory.

    Returns a list of warning strings (empty = pass).
    """
    from cv_scaffold import CVScaffold  # local import avoids circular dependency
    warnings = []

    # ── 1. Experience ──────────────────────────────────────────────────────
    generated_experience = cv_dict.get("experience", [])
    generated_by_company = {
        e.get("company", "").strip(): e
        for e in generated_experience
        if e.get("company", "").strip()
    }

    for skeleton in scaffold.experience_skeletons:
        if skeleton.company not in generated_by_company:
            warnings.append(
                f"Experience: role at '{skeleton.company}' is missing. "
                "All professional experience from the master list must be included."
            )
            continue

        gen = generated_by_company[skeleton.company]

        gen_title = gen.get("title", "").strip()
        if gen_title.lower() != skeleton.title.lower():
            warnings.append(
                f"Experience '{skeleton.company}': title mismatch. "
                f"Expected '{skeleton.title}', got '{gen_title}'."
            )

        gen_location = gen.get("location", "").strip()
        if gen_location.lower() != skeleton.location.lower():
            warnings.append(
                f"Experience '{skeleton.company}': location mismatch. "
                f"Expected '{skeleton.location}', got '{gen_location}'."
            )

        gen_dates = _normalize_dates(gen.get("dates", ""))
        ref_dates = _normalize_dates(skeleton.dates)
        if gen_dates != ref_dates:
            warnings.append(
                f"Experience '{skeleton.company}': dates mismatch. "
                f"Expected '{skeleton.dates}', got '{gen.get('dates', '')}'."
            )

    scaffold_companies = {s.company for s in scaffold.experience_skeletons}
    for exp in generated_experience:
        company = exp.get("company", "").strip()
        if company and company not in scaffold_companies:
            warnings.append(
                f"Experience: '{company}' is not in the master list — "
                "never invent companies."
            )

    # ── 2. Side projects ───────────────────────────────────────────────────
    generated_projects = cv_dict.get("side_projects", [])
    ref_by_name = {ref.name: ref for ref in scaffold.side_project_refs}

    n = len(generated_projects)
    if n < 2 or n > 4:
        warnings.append(f"Side projects: {n} selected (expected 2-4).")

    for proj in generated_projects:
        gen_name = proj.get("name", "").strip()
        if gen_name not in ref_by_name:
            warnings.append(
                f"Side project '{gen_name}' is not in the master list — "
                "project names must be copied exactly."
            )
            continue
        ref = ref_by_name[gen_name]
        if ref.github_url:
            gen_url = proj.get("github_url", "").strip()
            if gen_url != ref.github_url:
                warnings.append(
                    f"Side project '{gen_name}': github_url mismatch. "
                    f"Expected '{ref.github_url}', got '{gen_url}'."
                )

    # ── 3. Skills ──────────────────────────────────────────────────────────
    generated_skills: dict = cv_dict.get("skills", {})
    for tokens in generated_skills.values():
        if not isinstance(tokens, list):
            continue
        for token in tokens:
            token = token.strip()
            if token and token not in scaffold.skills_inventory:
                warnings.append(
                    f"Skill '{token}' is not in the master list inventory."
                )

    return warnings


def _normalize_dates(dates_str: str) -> str:
    """Normalize date strings for comparison.

    Collapses any dash/en-dash/em-dash variant (with optional spaces) to ' - '.
    This lets 'Sep 2022 -- Oct 2025' (LaTeX) match 'Sep 2022 - Oct 2025' (master list).
    """
    return re.sub(r'\s*[-—–]+\s*', ' - ', dates_str.strip())
