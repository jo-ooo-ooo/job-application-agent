"""Tool definitions and implementations for the job application agent."""

import os
import json
import requests
from pathlib import Path

from pdf_generator import generate_pdf_from_markdown

PROJECT_DIR = Path(__file__).parent.resolve()
OUTPUT_DIR = PROJECT_DIR / "output"

# Tool schemas for the Anthropic API
TOOL_DEFINITIONS = [
    {
        "name": "web_search",
        "description": (
            "Search the web for information about a company, role, or person. "
            "Returns top search result snippets."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query",
                }
            },
            "required": ["query"],
        },
    },
    {
        "name": "read_file",
        "description": (
            "Read a local file. Use this to read CV templates and the projects master list. "
            "Paths are relative to the project directory."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path relative to the project directory (e.g., 'cvs/template_standard.md')",
                }
            },
            "required": ["path"],
        },
    },
    {
        "name": "generate_pdf",
        "description": (
            "Generate a PDF from markdown content. Saves the PDF to the output directory."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "Markdown content to convert to PDF",
                },
                "filename": {
                    "type": "string",
                    "description": "Output filename (e.g., 'cv.pdf' or 'cover_letter.pdf')",
                },
            },
            "required": ["content", "filename"],
        },
    },
]


def execute_tool(tool_name: str, tool_input: dict) -> str:
    """Execute a tool and return the result as a string."""
    if tool_name == "web_search":
        return _web_search(tool_input["query"])
    elif tool_name == "read_file":
        return _read_file(tool_input["path"])
    elif tool_name == "generate_pdf":
        return _generate_pdf(tool_input["content"], tool_input["filename"])
    else:
        return f"Error: Unknown tool '{tool_name}'"


def _web_search(query: str) -> str:
    """Search the web using Brave Search API."""
    api_key = os.getenv("BRAVE_API_KEY", "")
    if not api_key:
        return _fallback_web_search(query)

    try:
        resp = requests.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers={"X-Subscription-Token": api_key, "Accept": "application/json"},
            params={"q": query, "count": 5},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        results = []
        for item in data.get("web", {}).get("results", [])[:5]:
            title = item.get("title", "")
            description = item.get("description", "")
            url = item.get("url", "")
            results.append(f"**{title}**\n{description}\nURL: {url}")

        if not results:
            return f"No results found for: {query}"
        return "\n\n---\n\n".join(results)

    except requests.RequestException as e:
        return f"Search API error: {e}. Falling back to basic search.\n\n" + _fallback_web_search(query)


def _fallback_web_search(query: str) -> str:
    """Fallback search using DuckDuckGo HTML (no API key needed)."""
    try:
        resp = requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            headers={"User-Agent": "Mozilla/5.0 (compatible; JobAppAgent/1.0)"},
            timeout=10,
        )
        resp.raise_for_status()

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "html.parser")
        results = []
        for result in soup.select(".result")[:5]:
            title_el = result.select_one(".result__title")
            snippet_el = result.select_one(".result__snippet")
            title = title_el.get_text(strip=True) if title_el else ""
            snippet = snippet_el.get_text(strip=True) if snippet_el else ""
            if title or snippet:
                results.append(f"**{title}**\n{snippet}")

        if not results:
            return f"No results found for: {query}"
        return "\n\n---\n\n".join(results)

    except Exception as e:
        return f"Fallback search also failed: {e}. Please provide information manually."


def _read_file(path: str) -> str:
    """Read a file, restricted to the project directory."""
    resolved = (PROJECT_DIR / path).resolve()
    if not str(resolved).startswith(str(PROJECT_DIR)):
        return f"Error: Access denied. Path must be within the project directory."

    if not resolved.exists():
        return f"Error: File not found: {path}"

    try:
        return resolved.read_text(encoding="utf-8")
    except Exception as e:
        return f"Error reading file: {e}"


def _generate_pdf(content: str, filename: str) -> str:
    """Generate a PDF from markdown content."""
    OUTPUT_DIR.mkdir(exist_ok=True)

    if not filename.endswith(".pdf"):
        filename += ".pdf"

    # Sanitize filename
    safe_name = "".join(c for c in filename if c.isalnum() or c in "._-")
    output_path = OUTPUT_DIR / safe_name

    try:
        pages = generate_pdf_from_markdown(content, str(output_path))
        result = f"PDF generated: {output_path}"
        if pages > 1:
            result += f"\nWARNING: PDF is {pages} pages. Target is 1 page."
        return result
    except Exception as e:
        return f"Error generating PDF: {e}"
