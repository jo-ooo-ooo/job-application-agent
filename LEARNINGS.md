# Learnings

Building a job application agent from scratch as a PM learning agent architecture.

The agent runs a multi-step pipeline: parallel research, gap analysis, project selection, CV/cover letter writing, critic review loop, and PDF generation. It does real web searches, reads my CV files, scores fit, and iteratively improves output before producing the final documents.

I built it iteratively. First just making it work, then adding production patterns one at a time.

---

## Why this project

Setting buzzwords aside, I wanted to understand what an agent actually is. After several rounds of asking AI "what is an agent?" and "what's the difference between an LLM prompt and an agent?" and still not feeling like I understood, the easiest way was to get my hands dirty and build one myself.

I also wanted to build something genuinely useful — I might start job searching soon, so an agent that removes the repetitive, time-consuming work in the application process seemed like the right fit.

Turns out those two goals teach each other. Every time something went wrong in production (wrong output, hallucinated content, a crash mid-run), I had to add a real engineering pattern to fix it: guardrails, checkpointing, evaluation. I didn't just learn what makes an agent an agent, but also how to make a production-grade one — how to balance cost and quality, and what best practices actually look like in practice.

---

## The most important architectural decision: stateless steps

Each step gets only the state it needs, injected as a formatted string. No step sees the full conversation history. The result of each step is stored as structured state; the next step only receives the most relevant summary.

Stateless steps mean each step is independently testable, reproducible, and replaceable. You can run `cv_construction` ten times against the same cached state. That's what makes evaluation possible.

---

## Multi-agent patterns: what worked and what didn't

### Parallel research agents

Company research and role analysis are independent — they both need only the job description and produce different outputs. Running them in parallel with `ThreadPoolExecutor` was straightforward.

### Writer/critic review loop

The critic reviews the CV and cover letter from a hiring manager's perspective, and the writer revises based on feedback. This loop runs up to 3 iterations.

**What I learned:**

The critic loop is only as good as its observability. In early versions, the loop was a black box — it printed "Completed in 3 rounds" but I couldn't tell whether the critic approved or just hit max iterations. The fix: structured `CriticResult` that tracks per-round feedback, parsed issues, and word count deltas. Now I can see exactly what the critic found and whether revisions addressed it.

### Patterns I considered but didn't use

**Orchestrator agent** — A meta-agent that decides which step to run next. Overkill for a fixed pipeline. The pipeline order is deterministic, so a simple sequential orchestrator in `main.py` is cleaner and more debuggable.

**Debate pattern** — Two agents argue for/against applying. Interesting in theory, but the gap analysis already provides honest scoring across 5 dimensions. A debate would add cost without changing the decision — the score already tells you whether to apply.

**Hiring manager research agent** — Researching the interviewer via LinkedIn/web. Moved this to a future interview prep agent. During the application phase, you rarely know who the hiring manager is. That info comes from the interview invite.

---

## Decomposed scoring and structured output

During testing, I noticed the scoring and recommendation were sometimes inconsistent. In one run it told me to apply; in the next, it said the gap was too large. I couldn't tell why.

The fix: ask the model to score five dimensions independently (technical skills, seniority, domain experience, leadership, culture fit), then compute the weighted total in code.

When the score is in the borderline range (45-65), it automatically re-runs and averages. One run could be 58, the other 62 — both are in the range, so the average is more meaningful than either.

---

## Guardrails: warn-only is useless

The guardrails caught real issues: empty output, missing candidate name, word count violations, gap analysis with only 2 dimension scores instead of 5.

But the first implementation was warn-only — it printed warnings and continued. During a test run, the critic loop produced a 31-word CV with no name and no headers, and the guardrails just printed warnings and generated a broken PDF.

The fix: guardrails as a safety net *after* the critic loop. If structural issues are detected, the model is asked to fix them using the specific warning messages as instructions. This catches problems the critic missed.

---

## Tool control matters

The model has access to `web_search`, `read_file`, and `generate_pdf` tools. But during CV and cover letter construction, the model would proactively call `generate_pdf` — sometimes 5 times in a row, trying to fit the output on one page. Each call added commentary ("PDF saved to...") that polluted the actual CV markdown.

The fix: `exclude_tools` parameter on `run_step()`. Writing steps exclude `generate_pdf`, so the model just outputs clean markdown. PDF generation happens as a separate final step.

This cut CV construction from 7 API calls ($0.29, 86s) to 2 API calls ($0.05, 27s).

---

## MCP integration: lessons from Google Sheets

MCP (Model Context Protocol) connects the agent to Google Sheets for application tracking. The server runs as a subprocess with stdio transport; the client discovers tools at runtime.

I also evaluated LinkedIn and Glassdoor MCP servers but decided against them — ToS violations, account ban risk, and GDPR concerns made them too risky for a personal tool.

---

## Evaluation

Setting up the eval framework forced me to define what "good" means concretely:
- CV word count in range (100-800)
- JD keyword match above a threshold
- Guardrails passing
- Research completeness (has required sections)
- Role analysis completeness (must-haves, nice-to-haves, key signals)
- Critic loop effectiveness (did it run, approve, find actionable issues?)
- LLM-as-judge relevance scores

I also ran a round of eval to see whether I could swap company research from Sonnet to Haiku to save cost. Haiku costs 5x less and runs 2x faster. But Haiku only gives you facts, while Sonnet adds interpretation — layoff context, valuation concerns, what the role means strategically. That extra context is exactly what feeds into gap analysis and CV tailoring downstream.

---

## Checkpointing matters more for expensive pipelines

A full run costs $0.50-1.50 and takes 5-15 minutes. If it crashes at step 5 (CV construction), I've lost most of my spend. So I added checkpointing to handle rate limit exhaustion, network drops, overloaded errors, or the user closing the terminal.

The implementation is simple — save the state dict to JSON after every step, load it back on `--resume`. Backward compatibility matters: when the schema changes (like removing `manager_name` and adding `role_analysis`), the checkpoint loader handles missing/extra fields gracefully.

---

## What I'd do differently

**Start with eval.** I built the core agent first, then added evaluation later. That meant I was flying blind for the first 20+ runs.

**Save every output, not just scores.** The first version of eval only saved metrics — word counts, scores. Not the actual text. That made model comparisons impossible after the fact. Every run should save the full output for every step.

---

## What's next

V2 is complete: multi-agent workflow (parallel research, writer/critic loop), MCP integration, observability improvements, expanded evaluation.

V3 directions:
- **Interview prep agent** — deep research on interviewer, product, culture, and company strategy. Triggered when you get an interview invite and know the hiring manager's name.
- **Multi-model routing** — use Haiku for cheap steps, Sonnet for core writing, Opus for complex analysis.
- **Batch processing** — run against a saved jobs list from a spreadsheet.
