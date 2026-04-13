"""Tests for cv_scaffold — parser and scaffold validator."""

import pytest
from cv_scaffold import (
    parse_scaffold,
    ExperienceSkeleton,
    SideProjectRef,
    CVScaffold,
    _parse_experience,
    _parse_side_projects,
    _parse_skills_inventory,
)
from guardrails import validate_cv_against_scaffold, _normalize_dates


# ── Fixtures ──────────────────────────────────────────────────────────────────

MINIMAL_MASTER_LIST = """\
## Skills (complete inventory)

**Product Strategy:** MVP scoping, A/B testing, roadmap ownership
**Technical:** SQL, Python

---

## Side Projects (Built with AI)

### Cool Chrome Extension
**GitHub:** https://github.com/user/cool-ext
- Does something useful

### Data Pipeline Tool
**GitHub:** https://github.com/user/pipeline
- Processes data

---

## Professional Experience

### Senior Product Manager — Acme Corp
*London, UK | Jan 2020 - Dec 2023*

Some description.

- Bullet one
- Bullet two

### Product Manager — Beta Ltd
*Berlin, Germany | Jun 2017 - Dec 2019*

- Bullet one
"""

SCAFFOLD = parse_scaffold(MINIMAL_MASTER_LIST)


# ── _normalize_dates ──────────────────────────────────────────────────────────

class TestNormalizeDates:
    def test_single_hyphen_unchanged(self):
        assert _normalize_dates("Jan 2020 - Dec 2023") == "Jan 2020 - Dec 2023"

    def test_double_hyphen_normalized(self):
        assert _normalize_dates("Jan 2020 -- Dec 2023") == "Jan 2020 - Dec 2023"

    def test_em_dash_normalized(self):
        assert _normalize_dates("Jan 2020 \u2014 Dec 2023") == "Jan 2020 - Dec 2023"

    def test_strips_whitespace(self):
        assert _normalize_dates("  Jan 2020 - Dec 2023  ") == "Jan 2020 - Dec 2023"


# ── parse_scaffold ────────────────────────────────────────────────────────────

class TestParseScaffold:
    def test_experience_count(self):
        assert len(SCAFFOLD.experience_skeletons) == 2

    def test_experience_fields_acme(self):
        acme = next(s for s in SCAFFOLD.experience_skeletons if s.company == "Acme Corp")
        assert acme.title == "Senior Product Manager"
        assert acme.location == "London, UK"
        assert acme.dates == "Jan 2020 - Dec 2023"

    def test_experience_fields_beta(self):
        beta = next(s for s in SCAFFOLD.experience_skeletons if s.company == "Beta Ltd")
        assert beta.title == "Product Manager"
        assert beta.location == "Berlin, Germany"

    def test_side_project_count(self):
        assert len(SCAFFOLD.side_project_refs) == 2

    def test_side_project_fields(self):
        ext = next(r for r in SCAFFOLD.side_project_refs if "Chrome" in r.name)
        assert ext.name == "Cool Chrome Extension"
        assert ext.github_url == "https://github.com/user/cool-ext"

    def test_skills_inventory_tokens(self):
        assert "MVP scoping" in SCAFFOLD.skills_inventory
        assert "A/B testing" in SCAFFOLD.skills_inventory
        assert "SQL" in SCAFFOLD.skills_inventory
        assert "roadmap ownership" in SCAFFOLD.skills_inventory

    def test_skills_inventory_excludes_category_names(self):
        assert "Product Strategy" not in SCAFFOLD.skills_inventory
        assert "Technical" not in SCAFFOLD.skills_inventory

    def test_missing_experience_raises(self):
        text = MINIMAL_MASTER_LIST.replace("## Professional Experience", "## Other Section")
        with pytest.raises(ValueError, match="No professional experience"):
            parse_scaffold(text)

    def test_missing_skills_raises(self):
        text = MINIMAL_MASTER_LIST.replace("## Skills (complete inventory)", "## Other")
        with pytest.raises(ValueError, match="No skills found"):
            parse_scaffold(text)

    def test_project_without_github_url(self):
        text = MINIMAL_MASTER_LIST.replace(
            "**GitHub:** https://github.com/user/pipeline\n", ""
        )
        scaffold = parse_scaffold(text)
        pipeline = next(r for r in scaffold.side_project_refs if "Pipeline" in r.name)
        assert pipeline.github_url == ""

    def test_compound_title_parsed(self):
        text = MINIMAL_MASTER_LIST + "\n### Growth PM / Marketing Manager — Corp C\n*City, Country | Mar 2015 - Jan 2017*\n"
        scaffold = parse_scaffold(text)
        corp_c = next((s for s in scaffold.experience_skeletons if s.company == "Corp C"), None)
        assert corp_c is not None
        assert corp_c.title == "Growth PM / Marketing Manager"


# ── validate_cv_against_scaffold ─────────────────────────────────────────────

def _make_cv(experience=None, side_projects=None, skills=None) -> dict:
    return {
        "name": "Test Candidate",
        "email": "test@example.com",
        "phone": "+1 234 567",
        "location": "London, UK",
        "title_tagline": "Senior PM",
        "skills": skills or {"Product": ["MVP scoping", "A/B testing"]},
        "experience": experience or [
            {
                "title": "Senior Product Manager",
                "company": "Acme Corp",
                "location": "London, UK",
                "dates": "Jan 2020 -- Dec 2023",
                "bullets": ["Did something impactful"],
            },
            {
                "title": "Product Manager",
                "company": "Beta Ltd",
                "location": "Berlin, Germany",
                "dates": "Jun 2017 -- Dec 2019",
                "bullets": ["Did another thing"],
            },
        ],
        "side_projects": side_projects or [
            {
                "name": "Cool Chrome Extension",
                "github_url": "https://github.com/user/cool-ext",
                "bullets": ["Built something"],
            },
            {
                "name": "Data Pipeline Tool",
                "github_url": "https://github.com/user/pipeline",
                "bullets": ["Processed data"],
            },
        ],
        "education": {"degree": "BSc", "university": "Example University"},
    }


class TestValidateCvAgainstScaffold:

    def test_valid_cv_no_warnings(self):
        assert validate_cv_against_scaffold(_make_cv(), SCAFFOLD) == []

    def test_dates_double_hyphen_accepted(self):
        # LaTeX -- format should match master list single hyphen after normalization
        warnings = validate_cv_against_scaffold(_make_cv(), SCAFFOLD)
        assert not any("dates" in w for w in warnings)

    # ── Experience ────────────────────────────────────────────────────────

    def test_missing_role(self):
        exp = [e for e in _make_cv()["experience"] if e["company"] == "Acme Corp"]
        warnings = validate_cv_against_scaffold(_make_cv(experience=exp), SCAFFOLD)
        assert any("Beta Ltd" in w and "missing" in w for w in warnings)

    def test_hallucinated_company(self):
        exp = _make_cv()["experience"] + [{
            "title": "PM", "company": "Ghost Corp",
            "location": "Nowhere", "dates": "Jan 2015 -- Dec 2016",
            "bullets": ["Made up"],
        }]
        warnings = validate_cv_against_scaffold(_make_cv(experience=exp), SCAFFOLD)
        assert any("Ghost Corp" in w and "not in the master list" in w for w in warnings)

    def test_wrong_title(self):
        exp = _make_cv()["experience"]
        exp[0] = {**exp[0], "title": "VP of Product"}
        warnings = validate_cv_against_scaffold(_make_cv(experience=exp), SCAFFOLD)
        assert any("Acme Corp" in w and "title" in w for w in warnings)

    def test_wrong_location(self):
        exp = _make_cv()["experience"]
        exp[0] = {**exp[0], "location": "New York, USA"}
        warnings = validate_cv_against_scaffold(_make_cv(experience=exp), SCAFFOLD)
        assert any("Acme Corp" in w and "location" in w for w in warnings)

    def test_wrong_dates(self):
        exp = _make_cv()["experience"]
        exp[0] = {**exp[0], "dates": "Mar 2021 -- Dec 2023"}
        warnings = validate_cv_against_scaffold(_make_cv(experience=exp), SCAFFOLD)
        assert any("Acme Corp" in w and "dates" in w for w in warnings)

    # ── Side projects ─────────────────────────────────────────────────────

    def test_too_few_side_projects(self):
        projs = [_make_cv()["side_projects"][0]]
        warnings = validate_cv_against_scaffold(_make_cv(side_projects=projs), SCAFFOLD)
        assert any("2-3" in w for w in warnings)

    def test_too_many_side_projects(self):
        # Model outputting 4+ projects should be flagged — limit is 2-3
        base = _make_cv()["side_projects"]
        four_projects = base + base  # 4 entries (names will fail name check, but count check fires first)
        warnings = validate_cv_against_scaffold(_make_cv(side_projects=four_projects), SCAFFOLD)
        assert any("2-3" in w for w in warnings)

    def test_hallucinated_project_name(self):
        projs = _make_cv()["side_projects"]
        projs[0] = {**projs[0], "name": "Invented Project"}
        warnings = validate_cv_against_scaffold(_make_cv(side_projects=projs), SCAFFOLD)
        assert any("Invented Project" in w and "not in the master list" in w for w in warnings)

    def test_wrong_github_url(self):
        projs = _make_cv()["side_projects"]
        projs[0] = {**projs[0], "github_url": "https://github.com/wrong/url"}
        warnings = validate_cv_against_scaffold(_make_cv(side_projects=projs), SCAFFOLD)
        assert any("github_url" in w for w in warnings)

    # ── Skills ────────────────────────────────────────────────────────────

    def test_invented_skill_flagged(self):
        skills = {"Product": ["MVP scoping", "predictive modelling"]}
        warnings = validate_cv_against_scaffold(_make_cv(skills=skills), SCAFFOLD)
        assert any("predictive modelling" in w for w in warnings)

    def test_valid_skills_no_warning(self):
        skills = {"Product": ["MVP scoping", "SQL"]}
        warnings = validate_cv_against_scaffold(_make_cv(skills=skills), SCAFFOLD)
        assert not any("inventory" in w for w in warnings)

    def test_empty_skills_no_crash(self):
        warnings = validate_cv_against_scaffold(_make_cv(skills={}), SCAFFOLD)
        assert not any("inventory" in w for w in warnings)
