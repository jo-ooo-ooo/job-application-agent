"""Job application DB MCP server — exposes read/write tools for Claude Desktop.

Claude Desktop uses this to look up application context (JD, company research,
gap analysis, previous rounds) and store prep notes during mock interview sessions.

Registered in: ~/Library/Application Support/Claude/claude_desktop_config.json

Run manually to test:
    python3 mcp_db_server.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from mcp.server.fastmcp import FastMCP
from db import (
    list_applications,
    get_application,
    get_rounds,
    create_round,
    update_round,
)

mcp = FastMCP("job-applications")


@mcp.tool()
def list_jobs() -> str:
    """List all job applications with run_id, company, role, status, and score.
    Use this first to find the run_id for a specific company.
    """
    apps = list_applications()
    if not apps:
        return "No applications found in database."
    lines = []
    for a in apps:
        score = f"  score={a['score']}" if a["score"] else ""
        company = a["company"] or "(unknown)"
        role = a["role"] or "(no role)"
        lines.append(f"- {a['id']}  {company}  |  {role}  |  {a['status']}{score}")
    return "\n".join(lines)


@mcp.tool()
def find_application(company_or_role: str) -> str:
    """Search applications by company name or role title (case-insensitive).
    Returns matching run_ids and status. Use this when the user mentions a company name.
    """
    apps = list_applications()
    query = company_or_role.lower()
    matches = [
        a for a in apps
        if query in (a["company"] or "").lower()
        or query in (a["role"] or "").lower()
    ]
    if not matches:
        return f"No applications found matching '{company_or_role}'."
    lines = []
    for a in matches:
        score = f"  score={a['score']}" if a["score"] else ""
        lines.append(
            f"run_id={a['id']}  company={a['company']}  role={a['role']}  status={a['status']}{score}"
        )
    return "\n".join(lines)


@mcp.tool()
def get_application_detail(run_id: str) -> str:
    """Get full application context: job description, company research, role analysis, gap analysis.
    Call this before starting a mock interview session to load the candidate's prep material.
    """
    app = get_application(run_id)
    if not app:
        return f"Application '{run_id}' not found. Use list_jobs() to see available run_ids."
    sections = [
        f"# {app['company'] or '(unknown)'} — {app['role'] or '(no role)'}",
        f"Status: {app['status']}",
        f"Score: {app['score']}",
        f"\n## Job Description\n{app['job_description'] or '(empty)'}",
        f"\n## Company Research\n{app['company_research'] or '(empty)'}",
        f"\n## Role Analysis\n{app['role_analysis'] or '(empty)'}",
        f"\n## Gap Analysis\n{app['gap_analysis'] or '(empty)'}",
    ]
    return "\n".join(sections)


@mcp.tool()
def get_interview_rounds(run_id: str) -> str:
    """Get all interview rounds for an application — prep content, transcripts, notes.
    Call this to see what was covered in previous rounds before starting the next one.
    """
    rounds = get_rounds(run_id)
    if not rounds:
        return f"No rounds found for '{run_id}'. This will be the first round."
    lines = []
    for r in rounds:
        lines.append(f"\n## {r['type']} round — {r['status']} (id: {r['id']})")
        if r["prep_content"]:
            lines.append(f"### Prep Content\n{r['prep_content']}")
        if r["transcript"]:
            lines.append(f"### Transcript\n{r['transcript']}")
        if r["notes"]:
            lines.append(f"### Notes\n{r['notes']}")
        if r["transcript_analysis"]:
            lines.append(f"### Analysis\n{r['transcript_analysis']}")
    return "\n".join(lines)


@mcp.tool()
def save_prep_notes(run_id: str, round_type: str, prep_content: str, notes: str = "") -> str:
    """Save prep content for a new interview round.

    round_type: hr | hiring_manager | case_study | panel | other
    prep_content: the full prep material generated during the session
    notes: optional scheduling or context notes (e.g. 'Monday 10am with Sarah')

    Call this at the end of a prep session to persist what was covered.
    """
    app = get_application(run_id)
    if not app:
        return f"Application '{run_id}' not found."
    valid_types = {"hr", "hiring_manager", "case_study", "panel", "other"}
    if round_type not in valid_types:
        return f"Invalid round_type '{round_type}'. Valid: {', '.join(sorted(valid_types))}"
    kwargs = {"prep_content": prep_content}
    if notes:
        kwargs["notes"] = notes
    round_id = create_round(run_id, round_type, **kwargs)
    return f"Saved prep for {app['company']} — {round_type} round. round_id={round_id}"


@mcp.tool()
def update_prep_notes(round_id: str, notes: str = "", transcript_analysis: str = "") -> str:
    """Update notes or transcript analysis on an existing round.

    Use this after a mock session to store:
    - notes: topics covered, areas to improve, what the user answered well
    - transcript_analysis: patterns in answers, questions to revisit next round

    This feeds cross-round continuity — HM prep reads what was flagged in HR.
    """
    fields = {}
    if notes:
        fields["notes"] = notes
    if transcript_analysis:
        fields["transcript_analysis"] = transcript_analysis
    if not fields:
        return "Nothing to update — provide notes or transcript_analysis."
    update_round(round_id, **fields)
    return f"Updated round {round_id}."


if __name__ == "__main__":
    mcp.run()
