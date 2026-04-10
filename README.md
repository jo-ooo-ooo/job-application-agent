# Job Application Agent

An AI agent that takes a job description and produces a tailored CV and cover letter. It researches the company, analyzes the role, scores fit, asks clarifying questions, and runs a writer/critic review loop before generating output.

Built as a PM exploring agent architecture hands-on — every production pattern (guardrails, checkpointing, evaluation, multi-agent coordination) was added to solve a real problem that came up during use.

V2 (in progress) extends the agent into a full application tracker: a SQLite database stores all runs, a REST API exposes them, and a DB MCP server gives Claude Desktop direct access to application context — JD, gap analysis, previous rounds — for mock interview prep sessions.

---

## What it does

```
Input: job description (URL, file, or text)
         |
Step 1: Company research + Role analysis  [parallel agents]
Step 2: Gap analysis — scores fit across 5 dimensions, asks questions
Step 3: Project selection — picks best-fit experience from master list
Step 4: CV construction — tailored, structured JSON (CVData)
Step 5: Cover letter — specific to company, addresses gaps honestly
         |
     Critic review loop  [writer/critic agents, up to 3 rounds]
     Guardrail auto-fix  [structural validation + model fix]
         |
Step 6: PDF generation  [LaTeX via pdflatex, fpdf2 fallback]
Step 7: Google Sheets log  [MCP → append row with score, recommendation, run_id]
         |
Output: Candidate_Name_CV_Company_Role.pdf + Candidate_Name_Cover_Letter_Company_Role.pdf
```

Two human gates: after gap analysis (proceed?), and after seeing the CV/cover letter (approve, revise, or quit).

All runs are stored in a local SQLite database (`data/applications.db`) alongside checkpoint files. A FastAPI layer exposes the data for the upcoming web UI and interview prep agent.

---

## Architecture

### Multi-agent workflow

**Parallel research agents** — Company research and role analysis run concurrently via `ThreadPoolExecutor`. Each agent is fault-isolated: if one fails, the other still returns its result.

**Writer/critic review loop** — After the CV and cover letter are drafted, a critic agent reviews them from a hiring manager's perspective. If not approved, the writer revises based on specific feedback. Loops until approved or max 3 iterations. Returns structured results: approval status, per-round issues, word count deltas.

### Reliability

- Stateless steps — each step gets only the state it needs, no conversation history
- Per-step temperature control (0 for analytical, 0.3-0.4 for creative)
- Decomposed scoring — model scores 5 dimensions independently, code computes weighted total
- Borderline re-run — scores in 45-65 range trigger a second assessment and average
- Retry with exponential backoff for rate limits, overloaded errors, and connection failures

### Observability

- Per-step token counts, cost, latency, tool calls, and retry counts
- Critic loop summary: approval status, issues found per round, revision word count changes
- Full run logs saved as JSON in `logs/`
- Google Sheets integration via MCP for application tracking

### PDF generation

CV and cover letter are generated as LaTeX PDFs using Jake's Resume template (sb2nov/resume, MIT). The agent outputs structured JSON (`CVData` dataclass), which is rendered via Jinja2 into `.tex` files and compiled with `pdflatex`. Falls back to `fpdf2` if LaTeX compilation fails. Output filenames include candidate name, company, and role abbreviation: `Candidate_Name_CV_Company_Role.pdf`.

Requires TexLive: `brew install --cask mactex-no-gui`

### Guardrails

- Runtime validation on CV (name, word count, headers, contact info, placeholders)
- Cover letter validation (length, name, generic phrases)
- Gap analysis validation (scoring dimensions present)
- Auto-fix: if guardrails fail after critic loop, model is asked to fix specific issues
- **CV scaffold system**: fixed facts (company names, titles, dates, locations, project URLs, skill inventory) are parsed from the master list and injected into the CV construction prompt as structured JSON. The model must copy these fields exactly. A deterministic post-generation check validates every field — any mismatch triggers an auto-fix with the scaffold facts re-injected.

### Evaluation

- Three modes: `--logs` (analyze past runs), `--dataset` (full pipeline), `--step` (single step)
- `--model` flag to compare Haiku / Sonnet / Opus on any step
- `--compare <prompts_file>` flag for A/B prompt testing — runs both versions on each JD, scores each with LLM-as-judge, prints side-by-side results
- Automated checks: word count, keyword match, guardrail pass, research completeness, critic effectiveness
- LLM-as-judge scoring (Haiku): CV relevance, CL specificity, gap accuracy, research quality, role analysis quality
- Synthetic JD fixtures in `eval/jobs/` for repeatable eval without personal data

### Data model

All pipeline runs are persisted to a local SQLite database (`data/applications.db`, gitignored) alongside the existing JSON checkpoint files. The DB stores two tables: `applications` (full pipeline outputs, status, score) and `rounds` (interview prep, transcripts, notes). Checkpoint files are still written on every step for CLI resume support — the DB write is best-effort alongside them.

`migrate.py` imports existing checkpoints into the DB on first setup.

### FastAPI layer

A local REST API (`api/app.py`) exposes the database for the upcoming web UI and interview prep tooling:

- `GET /applications` — list all applications (summary fields)
- `GET /applications/{id}` — full detail including rounds
- `PATCH /applications/{id}` — update status, applied_at, role, jd_url
- `POST /applications/{id}/rounds` — create an interview round
- `PATCH /applications/{id}/rounds/{round_id}` — update round content

Start with: `uvicorn api.app:app --port 8000`

### MCP integration

Two MCP servers via stdio transport:

**Google Sheets** (`sheets_mcp_server.py`) — logs each application to a tracking spreadsheet after CV generation. Called automatically by the pipeline.

**Job Applications DB** (`mcp_db_server.py`) — exposes the SQLite database to Claude Desktop. Six tools: `list_jobs`, `find_application`, `get_application_detail`, `get_interview_rounds`, `save_prep_notes`, `update_prep_notes`. Enables Claude Desktop to run mock interview sessions with full application context — JD, gap analysis, previous round prep — loaded automatically.

Register in `~/Library/Application Support/Claude/claude_desktop_config.json` to use with Claude Desktop.

---

## Setup

```bash
# 1. Clone and install
git clone <repo-url>
pip install -r requirements.txt

# 2. Configure API keys
cp .env.example .env
# Add ANTHROPIC_API_KEY (required)
# Add BRAVE_API_KEY (optional — falls back to DuckDuckGo)
# Add GOOGLE_SHEETS_ID (optional — for application tracking)

# 3. Add your CV files
cp examples/template_standard_example.md cvs/template_standard.md
cp examples/projects_master_list_example.md cvs/projects_master_list.md
# Fill in your actual experience
```

---

## Usage

```bash
# Run with a job description file
python3 main.py --job jd.txt

# Run with a URL
python3 main.py --job https://linkedin.com/jobs/view/...

# Run with pasted text
python3 main.py --job "Senior PM at Acme Corp..."

# Resume a crashed/interrupted run
python3 main.py --resume

# Update application status in DB
python3 main.py --log-outcome <run_id> applied
python3 main.py --log-outcome <run_id> screening
python3 main.py --log-outcome <run_id> interview

# Migrate existing checkpoints into SQLite DB (run once on first setup)
python3 migrate.py --dry-run   # preview
python3 migrate.py             # import

# Start the local API
uvicorn api.app:app --reload --port 8000

# Evaluate output quality
python3 eval/eval.py --logs
python3 eval/eval.py --dataset eval/jobs/
python3 eval/eval.py --step cv_construction --dataset eval/jobs/ --model haiku

# Run tests
python3 -m pytest tests/ -v
```

---

## Project structure

```
main.py              Orchestration — pipeline, user gates, checkpointing, --log-outcome
agent.py             Core agent loop — stateless steps, retry logic, tool execution
agents.py            Multi-agent coordination — parallel research, critic loop
prompts.py           All step prompts with {placeholders} for state injection
scoring.py           Decomposed scoring — parse dimensions, compute weighted total
guardrails.py        Runtime validation + scaffold validation + auto-fix
cv_scaffold.py       Parse master list into frozen facts (companies, projects, skills)
run_logger.py        Per-step metrics (tokens, cost, latency, tools, retries)
checkpoint.py        Save/load pipeline state for resume + dual-write to DB
tools.py             Tool definitions (web_search, read_file, generate_pdf)
cv_data.py           Structured CV data model (CVData, Experience, SideProject dataclasses)
latex_generator.py   LaTeX PDF generation — Jinja2 rendering + pdflatex compilation
pdf_generator.py     Markdown to PDF via fpdf2 (fallback)
db.py                SQLite data model — Application + Round tables, CRUD
migrate.py           One-time migration of existing checkpoints into SQLite DB
mcp_client.py        MCP client for Google Sheets integration
sheets_mcp_server.py MCP server — exposes append_row tool for Sheets logging
mcp_db_server.py     MCP server — exposes DB tools for Claude Desktop interview prep

api/app.py           FastAPI app — REST endpoints for applications and rounds
templates/           LaTeX templates for CV and cover letter (Jake's Resume base)
tests/               Unit tests (200+ tests)
eval/                Evaluation framework — automated checks + LLM-as-judge
examples/            Example CV templates for setup
```

---

## Requirements

- Python 3.10+
- `anthropic`, `fpdf2`, `jinja2`, `requests`, `beautifulsoup4`, `python-dotenv`, `markdown`
- `fastapi`, `uvicorn` — for the local REST API
- `mcp`, `gspread`, `google-auth` — for MCP servers (Sheets + Claude Desktop)
- Anthropic API key
- TexLive for LaTeX PDF generation: `brew install --cask mactex-no-gui`
- Brave Search API key (optional)
- Google Cloud credentials (optional, for Sheets logging)
