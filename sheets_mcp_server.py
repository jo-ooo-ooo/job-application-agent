"""Google Sheets MCP server — exposes append_row tool.

Runs as a subprocess via stdio transport. Uses Application Default Credentials
(ADC) set up via `gcloud auth application-default login`.

Usage:
    python3 sheets_mcp_server.py   (started automatically by mcp_client.py)
"""

import os

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

SHEET_ID = os.getenv("GOOGLE_SHEETS_ID", "")

mcp = FastMCP("google-sheets")


@mcp.tool()
def append_row(
    date: str,
    company: str,
    role: str,
    score: str,
    recommendation: str,
    status: str,
    run_id: str,
    notes: str = "",
    link: str = "",
) -> str:
    """Append a job application row to the Google Sheet."""
    if not SHEET_ID:
        return "Error: GOOGLE_SHEETS_ID not set in environment"

    try:
        import gspread
        from google.auth import default

        credentials, _ = default(
            scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        gc = gspread.authorize(credentials)
        sheet = gc.open_by_key(SHEET_ID).sheet1
        row = [date, company, role, link, score, recommendation, status, notes, run_id]
        sheet.append_row(row)
        return f"Logged: {company} — {role} (score: {score}, {recommendation})"
    except Exception as e:
        import traceback
        return f"Error appending row: {e}\n{traceback.format_exc()}"


if __name__ == "__main__":
    mcp.run()
