"""MCP client — connects to the Google Sheets MCP server via stdio transport.

The server runs as a subprocess (`sheets_mcp_server.py`). This client:
1. Starts the server process
2. Discovers available tools via list_tools()
3. Calls append_row() to log each application

Key MCP concepts demonstrated:
- stdio transport: server is a subprocess, client communicates via stdin/stdout
- Tool discovery: client doesn't hardcode tool names — it discovers them at runtime
- Client/server separation: server owns the Sheets credentials, client stays clean
"""

import asyncio
import re
import sys
from pathlib import Path

SERVER_SCRIPT = Path(__file__).parent / "sheets_mcp_server.py"


# ── Async helpers (thin wrappers around the MCP SDK) ──────────

async def _list_tools() -> list:
    """Connect to server and return list of available tool names."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=sys.executable, args=[str(SERVER_SCRIPT)])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()
            return [t.name for t in result.tools]


async def _call_tool(tool_name: str, arguments: dict) -> str:
    """Call a tool on the MCP server and return the text result."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=sys.executable, args=[str(SERVER_SCRIPT)])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)
            return result.content[0].text if result.content else ""


# ── Public client class ───────────────────────────────────────

class SheetsClient:
    """MCP client for Google Sheets — logs job applications.

    Usage:
        client = SheetsClient()
        if client.health_check():
            client.log_application(run_id, state, score, recommendation)
    """

    def __init__(self):
        self.available = False
        self.tools = []

    def health_check(self) -> bool:
        """Connect to MCP server and discover tools. Returns True if available."""
        try:
            self.tools = asyncio.run(_list_tools())
            self.available = True
            print(f"  [sheets] MCP connected — tools: {', '.join(self.tools)}")
            return True
        except Exception as e:
            print(f"  [sheets] MCP unavailable ({type(e).__name__}): {e}")
            self.available = False
            return False

    def log_application(
        self, run_id: str, state: dict, score: float, recommendation: str
    ) -> bool:
        """Append one row to the Job Applications Google Sheet.

        Never raises — returns False on any failure so the main pipeline
        continues even if Sheets logging is broken.
        """
        if not self.available:
            return False

        from datetime import date

        company, role = _extract_company_role(state)
        jd = state.get("job_description", "")
        link = jd if jd.startswith("http") else ""

        args = {
            "date": date.today().isoformat(),
            "company": company,
            "role": role,
            "score": str(round(score)),
            "recommendation": recommendation,
            "status": "Applied",
            "notes": "",
            "run_id": run_id,
            "link": link,
        }

        try:
            result = asyncio.run(_call_tool("append_row", args))
            print(f"  [sheets] {result}")
            return True
        except Exception as e:
            print(f"  [sheets] Log failed: {e}")
            return False


# ── Helpers ───────────────────────────────────────────────────

def _extract_company_role(state: dict) -> tuple:
    """Extract company name and role title from agent state.

    The company_research prompt produces structured output:
        - Company: [name, stage, ...]
        - Role: [level, team, ...]
    We parse those lines directly.
    """
    research = state.get("company_research", "")
    jd = state.get("job_description", "")

    # Company: match "- Company: [name, ...]" — take just the name before the comma
    company = "Unknown"
    m = re.search(r"[-*]\s*Company:\s*(.+)", research, re.IGNORECASE)
    if m:
        # "Acme Corp, Series B, 200 people, ..." → "Acme Corp"
        company = m.group(1).split(",")[0].strip().rstrip(".").replace("**", "")

    # Role: match "- Role: [level, team, ...]" — take the first segment
    role = "Unknown"
    m = re.search(r"[-*]\s*Role:\s*(.+)", research, re.IGNORECASE)
    if m:
        role = m.group(1).split(",")[0].strip().rstrip(".").replace("**", "")
    else:
        # Fall back to first non-URL line of job description
        for line in jd.split("\n"):
            line = line.strip()
            if 5 < len(line) < 100 and not line.startswith("http"):
                role = line
                break

    return company, role
