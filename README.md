# Job Application Agent

An AI agent that takes a job description and produces a tailored CV and cover letter — researching the company, scoring fit, asking clarifying questions, and auto-fixing quality issues before output.

Built to explore how production-grade agent patterns apply to a real personal use case.

---

## What it does

```
Input: job description URL or text
         ↓
Step 1: Company & role research (web search)
Step 2: Hiring manager research (web search)
Step 3: Gap analysis — scores fit across 5 dimensions, asks questions
Step 4: Project selection — picks best-fit experience from master list
Step 5: CV construction — tailored, ATS-optimized markdown CV
Step 6: Cover letter — specific to company, addresses gaps honestly
Step 7: PDF generation
         ↓
Output: cv.pdf + cover_letter.pdf
```

Two human gates: after gap analysis (proceed?), and after seeing the CV/cover letter (approve, revise, or quit).

---

## Technical features

**Reliability**
- Per-step temperature control (0 for analytical steps, 0.3-0.4 for creative ones)
- Decomposed scoring — model scores 5 dimensions independently, code computes weighted total (removes anchoring bias)
- Borderline re-run — scores in 45-65 range trigger a second assessment and average

**Observability**
- Per-step token counts, cost, latency, tool calls, and retry counts
- Full run logs saved as JSON in `logs/`

**Guardrails**
- Runtime validation on CV (name, word count, headers, contact info, placeholders) and cover letter (length, generic phrases)
- Auto-fix loop: fires the model again with the specific warnings, up to 2 retries

**Evaluation**
- Three modes: `--logs` (analyze past runs), `--dataset` (full pipeline), `--step` (single step with cached state)
- `--model` flag to compare Haiku / Sonnet / Opus on any step
- LLM-as-judge scoring (Haiku) + automated checks (word count, keyword match, guardrail pass)
- Outputs saved per run for after-the-fact comparison

**Checkpointing**
- State saved to `checkpoints/` after every step
- `--resume` flag to continue from where a crashed run left off

**Testing**
- 90 unit tests across scoring, question parser, guardrails, path security, and checkpoint logic

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

# 3. Add your CV files
cp cvs_examples/template_standard_example.md cvs/template_standard.md
cp cvs_examples/projects_master_list_example.md cvs/projects_master_list.md
# Fill in your actual experience
```

---

## Usage

```bash
# Run with a job description file
python3 main.py --job eval_jobs/jd_1.txt

# Run with a URL
python3 main.py --job https://linkedin.com/jobs/view/...

# Resume a crashed run
python3 main.py --resume

# Evaluate output quality
python3 eval.py --logs
python3 eval.py --dataset eval_jobs/
python3 eval.py --step cv_construction --dataset eval_jobs/ --model haiku
```

---

## Project structure

```
agent.py           Core agent loop — stateless steps, retry logic, tool execution
main.py            Orchestration — pipeline, user gates, checkpointing
prompts.py         All step prompts with {placeholders} for state injection
scoring.py         Decomposed scoring — parse dimensions, compute weighted total
guardrails.py      Runtime validation + auto-fix
run_logger.py      Per-step metrics (tokens, cost, latency, tools, retries)
checkpoint.py      Save/load pipeline state for resume
eval.py            Evaluation runner — 3 modes, multi-model, LLM-as-judge
eval_criteria.py   Scoring criteria — automated checks + LLM-as-judge prompts
tools.py           Tool definitions (web_search, read_file, generate_pdf)
pdf_generator.py   Markdown → PDF via fpdf2
```

---

## Requirements

- Python 3.9+
- `anthropic`, `fpdf2`, `requests`, `beautifulsoup4`, `python-dotenv`, `markdown`
- Anthropic API key
- Brave Search API key (optional)
