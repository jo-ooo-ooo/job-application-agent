"""Output guardrails — runtime checks on LLM-generated content before it ships.

These catch problems that unit tests can't: hallucinated experience,
missing candidate info, word count violations, etc.
"""

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
