"""Structured CV data model — dataclasses for typed CV content + JSON parsing."""

import json
import re
from dataclasses import dataclass, field


@dataclass
class Experience:
    title: str
    company: str
    location: str
    dates: str
    bullets: list[str]
    company_description: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "Experience":
        return cls(
            title=d["title"],
            company=d["company"],
            location=d["location"],
            dates=d["dates"],
            bullets=d["bullets"],
            company_description=d.get("company_description", ""),
        )


@dataclass
class SideProject:
    name: str
    bullets: list[str]
    github_url: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "SideProject":
        return cls(
            name=d["name"],
            bullets=d["bullets"],
            github_url=d.get("github_url", ""),
        )


@dataclass
class CVData:
    name: str
    email: str
    phone: str
    location: str
    title_tagline: str
    skills: dict[str, list[str]]
    experience: list[Experience]
    education: dict[str, str]
    linkedin: str = ""
    side_projects: list[SideProject] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "CVData":
        return cls(
            name=d["name"],
            email=d["email"],
            phone=d["phone"],
            location=d["location"],
            title_tagline=d["title_tagline"],
            skills=d["skills"],
            experience=[Experience.from_dict(e) for e in d["experience"]],
            education=d["education"],
            linkedin=d.get("linkedin", ""),
            side_projects=[SideProject.from_dict(p) for p in d.get("side_projects", [])],
        )


def parse_cv_json(raw: str) -> CVData:
    """Parse raw LLM output (possibly wrapped in code fences) into CVData.

    Raises ValueError if JSON is invalid or missing required fields.
    """
    cleaned = re.sub(r'^```\w*\n', '', raw.strip())
    cleaned = re.sub(r'\n```\s*$', '', cleaned)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse CV JSON: {e}")

    return CVData.from_dict(data)
