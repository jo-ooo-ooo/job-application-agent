"""Tests for structured CV data model and JSON parsing."""

import pytest
import json
from cv_data import CVData, Experience, SideProject, parse_cv_json


class TestCVData:
    def test_from_dict_complete(self):
        data = {
            "name": "Joyce Chen",
            "email": "ytchen37@gmail.com",
            "phone": "+49 160 4629745",
            "linkedin": "https://www.linkedin.com/in/yuntzuchen/",
            "location": "Berlin, Germany",
            "title_tagline": "Senior Product Manager | AI & Growth",
            "skills": {
                "Product": ["MVP scoping", "A/B testing", "roadmap ownership"],
                "Technical": ["SQL", "Python", "Claude Code"],
            },
            "experience": [
                {
                    "title": "Senior Product Manager",
                    "company": "Tourlane",
                    "location": "Berlin, Germany",
                    "dates": "Sep 2022 -- Oct 2025",
                    "company_description": "Leading European travel platform",
                    "bullets": [
                        "Led a Customer-Facing Squad, drove 20\\% uplift in lead conversion",
                        "Owned the digitalization roadmap, reducing cost per booking by 20\\%",
                    ],
                },
            ],
            "side_projects": [
                {
                    "name": "Film Festival Schedule Planner",
                    "github_url": "https://github.com/jo-ooo-ooo/plannale",
                    "bullets": [
                        "Built a Chrome extension for optimizing festival schedules",
                    ],
                },
            ],
            "education": {
                "degree": "BA in Advertising",
                "university": "Fudan University",
            },
        }
        cv = CVData.from_dict(data)
        assert cv.name == "Joyce Chen"
        assert cv.email == "ytchen37@gmail.com"
        assert len(cv.experience) == 1
        assert cv.experience[0].company == "Tourlane"
        assert len(cv.side_projects) == 1
        assert cv.side_projects[0].github_url == "https://github.com/jo-ooo-ooo/plannale"
        assert cv.education["degree"] == "BA in Advertising"

    def test_from_dict_missing_optional_fields(self):
        data = {
            "name": "Joyce Chen",
            "email": "ytchen37@gmail.com",
            "phone": "+49 160 4629745",
            "location": "Berlin, Germany",
            "title_tagline": "Senior PM",
            "skills": {"Product": ["A/B testing"]},
            "experience": [],
            "education": {"degree": "BA", "university": "University"},
        }
        cv = CVData.from_dict(data)
        assert cv.linkedin == ""
        assert cv.side_projects == []

    def test_from_dict_missing_required_field_raises(self):
        with pytest.raises(KeyError):
            CVData.from_dict({"name": "Joyce Chen"})


class TestParseCvJson:
    def test_parses_clean_json(self):
        raw = json.dumps({
            "name": "Joyce Chen",
            "email": "ytchen37@gmail.com",
            "phone": "+49 160 4629745",
            "location": "Berlin, Germany",
            "title_tagline": "Senior PM",
            "skills": {"Product": ["A/B testing"]},
            "experience": [],
            "education": {"degree": "BA", "university": "University"},
        })
        cv = parse_cv_json(raw)
        assert cv.name == "Joyce Chen"

    def test_parses_json_inside_code_fences(self):
        raw = '```json\n{"name": "Joyce Chen", "email": "a@b.com", "phone": "+1", "location": "Berlin", "title_tagline": "PM", "skills": {}, "experience": [], "education": {"degree": "BA", "university": "U"}}\n```'
        cv = parse_cv_json(raw)
        assert cv.name == "Joyce Chen"

    def test_parses_json_with_trailing_junk(self):
        """LLMs sometimes add --- or commentary after the JSON."""
        raw = '```json\n{"name": "Joyce Chen", "email": "a@b.com", "phone": "+1", "location": "Berlin", "title_tagline": "PM", "skills": {}, "experience": [], "education": {"degree": "BA", "university": "U"}}\n```\n\n---\n'
        cv = parse_cv_json(raw)
        assert cv.name == "Joyce Chen"

    def test_parses_json_with_leading_text(self):
        """LLMs sometimes add commentary before the JSON."""
        raw = 'Here is the CV:\n\n{"name": "Joyce Chen", "email": "a@b.com", "phone": "+1", "location": "Berlin", "title_tagline": "PM", "skills": {}, "experience": [], "education": {"degree": "BA", "university": "U"}}'
        cv = parse_cv_json(raw)
        assert cv.name == "Joyce Chen"

    def test_invalid_json_raises(self):
        with pytest.raises(ValueError, match="Failed to parse"):
            parse_cv_json("This is not JSON at all")

    def test_json_missing_required_field_raises(self):
        raw = json.dumps({"name": "Joyce"})
        with pytest.raises((KeyError, ValueError)):
            parse_cv_json(raw)


class TestExperience:
    def test_from_dict(self):
        data = {
            "title": "PM",
            "company": "Acme",
            "location": "Berlin",
            "dates": "2022 -- 2025",
            "bullets": ["Did things"],
        }
        exp = Experience.from_dict(data)
        assert exp.title == "PM"
        assert exp.company == "Acme"
        assert exp.company_description == ""

    def test_company_description_optional(self):
        data = {
            "title": "PM",
            "company": "Acme",
            "location": "Berlin",
            "dates": "2022 -- 2025",
            "company_description": "A cool company",
            "bullets": ["Did things"],
        }
        exp = Experience.from_dict(data)
        assert exp.company_description == "A cool company"


class TestSideProject:
    def test_from_dict(self):
        data = {
            "name": "Cool Project",
            "github_url": "https://github.com/user/repo",
            "bullets": ["Built something"],
        }
        sp = SideProject.from_dict(data)
        assert sp.name == "Cool Project"
        assert sp.github_url == "https://github.com/user/repo"

    def test_github_url_optional(self):
        data = {"name": "Project", "bullets": ["Did stuff"]}
        sp = SideProject.from_dict(data)
        assert sp.github_url == ""
