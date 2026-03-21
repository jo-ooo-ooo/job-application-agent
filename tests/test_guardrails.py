"""Unit tests for guardrails — runtime output validation."""

import pytest
from guardrails import (
    validate_cv,
    validate_cover_letter,
    validate_gap_analysis,
    extract_candidate_name,
    format_warnings,
)


# ── validate_cv ───────────────────────────────────────────────

class TestValidateCV:
    GOOD_CV = (
        "# Jane Doe\n"
        "jane@email.com | +49 123 456 | Berlin, Germany\n\n"
        "## Experience\n"
        "**Senior Product Manager, Company A** (2022-Present)\n"
        "- Led platform migration serving 2M users across 5 markets\n"
        "- Drove 30% improvement in deployment frequency through CI/CD overhaul\n"
        "- Managed cross-functional team of 12 engineers and 3 designers\n"
        "- Defined product roadmap aligned with company OKRs and growth targets\n\n"
        "**Product Manager, Company B** (2019-2022)\n"
        "- Shipped real-time analytics dashboard used by 500 enterprise customers\n"
        "- Reduced churn by 15% through data-driven feature prioritization\n"
        "- Collaborated with sales and CS to identify top customer pain points\n\n"
        "## Education\n"
        "MSc Computer Science, University of Example (2019)\n"
        "BSc Information Systems, Another University (2017)\n\n"
        "## Skills\n"
        "Product Strategy, Agile, SQL, Python, Stakeholder Management, A/B Testing\n"
    )

    def test_good_cv_no_warnings(self):
        assert validate_cv(self.GOOD_CV, "Jane Doe") == []

    def test_missing_name(self):
        cv = self.GOOD_CV.replace("Jane Doe", "John Doe")
        warnings = validate_cv(cv, "Jane Doe")
        assert any("name" in w.lower() for w in warnings)

    def test_too_long(self):
        long_cv = self.GOOD_CV + " word" * 800
        warnings = validate_cv(long_cv, "Jane Doe", max_words=800)
        assert any("words" in w for w in warnings)

    def test_too_short(self):
        warnings = validate_cv("# Name\nShort", "Name")
        assert any("short" in w.lower() for w in warnings)

    def test_empty(self):
        warnings = validate_cv("", "Name")
        assert any("empty" in w.lower() for w in warnings)

    def test_placeholder_detected(self):
        cv = self.GOOD_CV + "\n[Insert your experience here]"
        warnings = validate_cv(cv, "Jane Doe")
        assert any("placeholder" in w.lower() for w in warnings)

    def test_missing_contact_info(self):
        cv = "# Jane Doe\n\n## Experience\nDid things\n\n## Education\nStudied"
        warnings = validate_cv(cv, "Jane Doe")
        assert any("contact" in w.lower() or "email" in w.lower() for w in warnings)

    def test_too_few_headers(self):
        cv = "# Jane Doe\njane@email.com\nJust one big block of text with enough words to not be short"
        warnings = validate_cv(cv, "Jane Doe")
        assert any("header" in w.lower() for w in warnings)


# ── validate_cover_letter ─────────────────────────────────────

class TestValidateCoverLetter:
    GOOD_CL = (
        "Dear Hiring Manager,\n\n"
        "I am reaching out regarding the Senior PM role at Acme Corp. "
        "Having led cross-functional teams of up to 12 engineers across "
        "platform migration and analytics products, I bring deep experience "
        "in product strategy, stakeholder alignment, and data-driven "
        "prioritization that maps directly to what your team needs.\n\n"
        "At Company A, I drove a platform migration serving 2M users that "
        "improved deployment frequency by 30%. At Company B, I shipped a "
        "real-time analytics dashboard for 500 enterprise customers and "
        "reduced churn by 15% through systematic feature prioritization.\n\n"
        "What excites me about Acme is your focus on developer experience "
        "and the scale of the infrastructure challenges your team tackles. "
        "My background in platform products aligns well, though I recognize "
        "I would need to ramp up on your specific domain of cloud-native tooling.\n\n"
        "I would welcome the chance to discuss how my experience could "
        "contribute to your team's goals.\n\n"
        "Best regards,\nJane Doe"
    )

    def test_good_letter_no_warnings(self):
        assert validate_cover_letter(self.GOOD_CL, "Jane Doe") == []

    def test_missing_name(self):
        cl = self.GOOD_CL.replace("Jane Doe", "")
        warnings = validate_cover_letter(cl, "Jane Doe")
        assert any("name" in w.lower() for w in warnings)

    def test_too_long(self):
        long_cl = self.GOOD_CL + " word" * 500
        warnings = validate_cover_letter(long_cl, "Jane Doe", max_words=500)
        assert any("words" in w.lower() or "long" in w.lower() for w in warnings)

    def test_too_short(self):
        warnings = validate_cover_letter("Hi, hire me.", "Name")
        assert any("short" in w.lower() for w in warnings)

    def test_empty(self):
        warnings = validate_cover_letter("", "Name")
        assert any("empty" in w.lower() for w in warnings)

    def test_placeholder_detected(self):
        cl = self.GOOD_CL + "\n[Insert company name]"
        warnings = validate_cover_letter(cl, "Jane Doe")
        assert any("placeholder" in w.lower() for w in warnings)

    def test_generic_phrases(self):
        cl = (
            "I am writing to express my interest in this role. "
            "I believe I am a perfect fit for your team. "
            "Best,\nJane Doe"
        )
        warnings = validate_cover_letter(cl, "Jane Doe")
        assert any("generic" in w.lower() for w in warnings)

    def test_one_generic_phrase_ok(self):
        """One generic phrase is fine, we only warn at 2+."""
        cl = (
            "I am writing to express my interest in this role. "
            "My background in platform PM makes me well-suited. "
            "Best,\nJane Doe"
        )
        warnings = validate_cover_letter(cl, "Jane Doe")
        assert not any("generic" in w.lower() for w in warnings)


# ── validate_gap_analysis ─────────────────────────────────────

class TestValidateGapAnalysis:
    GOOD_GAP = (
        "SCORING BREAKDOWN:\n"
        "- Technical skills match: 7/10 — solid\n"
        "- Seniority level match: 8/10 — fine\n"
        "- Domain/industry experience: 5/10 — gap\n"
        "- Leadership & soft skills: 9/10 — strong\n"
        "- Culture & values fit: 6/10 — ok\n"
    )

    def test_good_analysis(self):
        assert validate_gap_analysis(self.GOOD_GAP) == []

    def test_too_few_scores(self):
        text = "- Technical skills match: 7/10 — ok\nSome other text"
        warnings = validate_gap_analysis(text)
        assert any("dimension scores" in w for w in warnings)

    def test_empty(self):
        warnings = validate_gap_analysis("")
        assert any("empty" in w.lower() for w in warnings)


# ── extract_candidate_name ────────────────────────────────────

class TestExtractCandidateName:
    def test_simple_name(self):
        assert extract_candidate_name("# Jane Doe\nSome content") == "Jane Doe"

    def test_bold_name(self):
        assert extract_candidate_name("# **Jane Doe**\nContent") == "Jane Doe"

    def test_no_h1(self):
        assert extract_candidate_name("## Section\nNo name here") == ""

    def test_empty(self):
        assert extract_candidate_name("") == ""


# ── format_warnings ───────────────────────────────────────────

class TestFormatWarnings:
    def test_no_warnings_empty_string(self):
        assert format_warnings([], "CV") == ""

    def test_warnings_formatted(self):
        output = format_warnings(["Bad thing happened"], "CV")
        assert "GUARDRAIL" in output
        assert "CV" in output
        assert "Bad thing happened" in output
