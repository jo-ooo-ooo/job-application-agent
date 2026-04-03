"""CV scaffold — parse the master list into fixed anchors for LLM grounding.

Separates immutable facts (company, title, dates, location, project name,
github_url) from variable content (bullets, skill groupings) so that
validate_cv_against_scaffold() can enforce the former deterministically.
"""

from __future__ import annotations
import re
from dataclasses import dataclass, field


@dataclass
class ExperienceSkeleton:
    """Fixed identity fields for one professional role.

    The model may NOT change any of these fields in the generated CV.
    Bullets and company_description remain model-controlled.
    """
    title: str
    company: str
    location: str
    dates: str


@dataclass
class SideProjectRef:
    """Fixed identity fields for one side project.

    The model selects 2-4 from the full catalogue. For each selected project,
    name and github_url must match exactly.
    """
    name: str
    github_url: str


@dataclass
class CVScaffold:
    """Complete scaffold parsed from projects_master_list.md.

    experience_skeletons: ALL roles — model must include every one.
    side_project_refs:    full catalogue — model picks a subset of 2-4.
    skills_inventory:     flat set of every valid skill token — model cannot
                          introduce tokens absent from this set.
    """
    experience_skeletons: list[ExperienceSkeleton]
    side_project_refs: list[SideProjectRef]
    skills_inventory: set[str]


def parse_scaffold(master_list_text: str) -> CVScaffold:
    """Parse projects_master_list.md into a CVScaffold.

    Raises ValueError if any required section is missing or empty.
    """
    experience_skeletons = _parse_experience(master_list_text)
    side_project_refs = _parse_side_projects(master_list_text)
    skills_inventory = _parse_skills_inventory(master_list_text)

    if not experience_skeletons:
        raise ValueError("No professional experience entries found in master list.")
    if not skills_inventory:
        raise ValueError("No skills found in master list.")

    return CVScaffold(
        experience_skeletons=experience_skeletons,
        side_project_refs=side_project_refs,
        skills_inventory=skills_inventory,
    )


def _get_section_text(text: str, h2_title: str) -> str:
    """Extract text belonging to a specific H2 section (up to the next H2)."""
    match = re.search(
        rf'^## {re.escape(h2_title)}.*?$', text, re.MULTILINE | re.IGNORECASE
    )
    if not match:
        return ""
    start = match.end()
    next_h2 = re.search(r'^## ', text[start:], re.MULTILINE)
    end = start + next_h2.start() if next_h2 else len(text)
    return text[start:end]


def _parse_experience(text: str) -> list[ExperienceSkeleton]:
    """Parse the '## Professional Experience' section."""
    section = _get_section_text(text, "Professional Experience")
    skeletons = []

    for block in re.split(r'^(?=### )', section, flags=re.MULTILINE):
        # Header: '### Title — Company' (em dash U+2014, or hyphen variants)
        header = re.match(r'^### (.+?)\s*[—\-–]+\s*(.+)$', block, re.MULTILINE)
        if not header:
            continue
        title = header.group(1).strip()
        company = header.group(2).strip()

        # Location and dates: '*Location | Start - End*'
        loc_date = re.search(r'^\*([^|*]+?)\s*\|\s*([^*]+?)\*', block, re.MULTILINE)
        if not loc_date:
            continue
        location = loc_date.group(1).strip()
        dates = loc_date.group(2).strip()

        skeletons.append(ExperienceSkeleton(
            title=title, company=company, location=location, dates=dates,
        ))
    return skeletons


def _parse_side_projects(text: str) -> list[SideProjectRef]:
    """Parse the '## Side Projects' section."""
    section = _get_section_text(text, "Side Projects")
    refs = []

    for block in re.split(r'^(?=### )', section, flags=re.MULTILINE):
        header = re.match(r'^### (.+)$', block, re.MULTILINE)
        if not header:
            continue
        name = header.group(1).strip()

        github = re.search(r'^\*\*GitHub:\*\*\s*(https?://\S+)', block, re.MULTILINE)
        github_url = github.group(1).strip() if github else ""

        refs.append(SideProjectRef(name=name, github_url=github_url))
    return refs


def _parse_skills_inventory(text: str) -> set[str]:
    """Build a flat set of every skill token from the Skills section.

    Source lines look like:
        **Category Name:** token1, token2, token3
    """
    section = _get_section_text(text, "Skills")
    inventory: set[str] = set()

    for match in re.finditer(r'^\*\*[^*]+\*\*[:\s]+(.+)$', section, re.MULTILINE):
        for token in match.group(1).split(","):
            cleaned = token.strip()
            if cleaned:
                inventory.add(cleaned)
    return inventory
