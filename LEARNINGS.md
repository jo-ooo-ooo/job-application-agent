# Learnings

Building a job application agent from scratch as a PM learning agent architecture.

The agent runs a multi-step pipeline: parallel research, gap analysis, project selection, CV/cover letter writing, critic review loop, and PDF generation. It does real web searches, reads my CV files, scores fit, and iteratively improves output before producing the final documents.

V2 extends it into an application tracker: all runs are stored in a local SQLite database, a REST API exposes the data, and a DB MCP server gives Claude Desktop direct access to application context — JD, company research, gap analysis, previous interview rounds — for mock interview prep sessions.

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

## Structured output is the right abstraction for document generation

The first version of CV construction asked the model to output markdown. That worked for display, but PDF generation was a problem: `fpdf2` rendered plain text with no formatting, the output looked amateur, and getting the model to produce well-structured markdown consistently was fragile.

The fix was to change the output contract entirely. The model now outputs JSON matching a `CVData` dataclass. That JSON gets rendered into a LaTeX template via Jinja2, then compiled with `pdflatex` to produce a properly typeset PDF. Separation of concerns: the model handles content selection and framing, the template handles layout.

---

## Multi-agent patterns: what worked and what didn't

### Parallel research agents

Company research and role analysis are independent — they both need only the job description and produce different outputs. Running them in parallel with `ThreadPoolExecutor` was straightforward.

### Writer/critic review loop

The critic reviews the CV and cover letter from a hiring manager's perspective, and the writer revises based on feedback. This loop runs up to 3 iterations.

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

## Hallucination has multiple failure modes — vague instructions don't fix them

During testing, the model hallucinated in two distinct places that required different fixes:

**Skills hallucination** — The model invented plausible-sounding skills not in the master list: `contribution margin analysis`, `predictive modelling`, `content ranking & recommendation algorithms`. These sound reasonable for a PM profile, which is exactly why they're dangerous. The fix was to add an explicit rule referencing the Skills section of the master list — but that still wasn't enough on its own.

**Experience hallucination** — More dangerous. During the critic revision loop, when asked to revise the CV JSON, the model invented an entire fake company — a plausible-sounding one that fit the candidate's background, but one they never worked at. It replaced a real company that was absent from the model's context at the time.

The first version of hallucination prevention added rules like "never invent companies" and "only use skills from the master list." These didn't work. The model follows the instruction directionally but still fills gaps with plausible content when the real information is absent from its context.

Two things actually work:

**1. Inject the allowed set explicitly as structured data.** The CV scaffold parses the master list into a `CVScaffold` object — company names, titles, dates, locations, project URLs, skill tokens — and serialises it as JSON directly into the prompt. The model is told: "copy these fields exactly." This is fundamentally different from "don't invent": instead of an open-ended prohibition, the model has a closed list to copy from.

**2. Validate deterministically after generation.** After the model produces CV JSON, a post-generation check compares every company, title, date, project name, GitHub URL, and skill token against the scaffold. Any mismatch triggers an auto-fix, with the scaffold re-injected so the model has the correct values in front of it.

The key insight: LLMs are bad at "don't do X" and good at "here is the exact value, copy it." Structured injection + deterministic validation is more reliable than prompt engineering alone.

A harder version of the same problem: validation that appears to work but silently isn't. The scaffold check was running after every pipeline step — but when the model wrapped its output in code fences, the JSON parsing failed quietly, the validation was skipped entirely, and the pipeline continued with no warning. The PDFs were generated with hallucinated content and 5 side projects instead of 3, and the guardrails said nothing. The fix: normalise model output at the point it's written to state, so every downstream reader gets clean data without needing to defend itself individually.

---

## Tool control matters

The model has access to `web_search`, `read_file`, and `generate_pdf` tools. But during CV and cover letter construction, the model would proactively call `generate_pdf` — sometimes 5 times in a row, trying to fit the output on one page. Each call added commentary ("PDF saved to...") that polluted the actual CV markdown.

The fix: `exclude_tools` parameter on `run_step()`. Writing steps exclude `generate_pdf`, so the model just outputs clean markdown. PDF generation happens as a separate final step.

This cut CV construction from 7 API calls ($0.29, 86s) to 2 API calls ($0.05, 27s).

---

## Checkpointing matters more for expensive pipelines

A full run costs $0.50-1.50 and takes 5-15 minutes. If it crashes at step 5 (CV construction), I've lost most of my spend. So I added checkpointing to handle rate limit exhaustion, network drops, overloaded errors, or the user closing the terminal.

The implementation is simple — save the state dict to JSON after every step, load it back on `--resume`. Backward compatibility matters: when the schema changes (like removing `manager_name` and adding `role_analysis`), the checkpoint loader handles missing/extra fields gracefully.

---

## Evaluation: defining what "good" means

Setting up the eval framework forced me to define what "good" means concretely:
- CV word count in range (100-800)
- JD keyword match above a threshold
- Guardrails passing
- Research completeness (has required sections)
- Role analysis completeness (must-haves, nice-to-haves, key signals)
- Critic loop effectiveness (did it run, approve, find actionable issues?)
- LLM-as-judge relevance scores

I also ran a round of eval to see whether I could swap company research from Sonnet to Haiku to save cost. Haiku costs 5x less and runs 2x faster. But Haiku only gives you facts, while Sonnet adds interpretation — layoff context, valuation concerns, what the role means strategically. That extra context is exactly what feeds into gap analysis and CV tailoring downstream.

I also ran a prompt A/B test: reframing the gap analysis prompt from "hiring manager screening" to "candidate-first coaching." The setup: run both prompts on 7 JDs, score each with an LLM judge (Haiku), compare scores and inspect outputs. The current prompt scored slightly higher on average (3.6 vs 3.3), but the result was mostly ties — not a clear signal either way.

The honest limitations of LLM-as-judge: it scores "does this look like good gap analysis?" not "did this actually help the candidate get an interview?" Small samples mean any 1-2 swing flips the conclusion. The real signal isn't which prompt scored higher — it's whether the output *reads* differently in ways you can verify. The current prompt produced more specific, JD-grounded analysis. That's a qualitative judgment, not a score.

LLM-as-judge evals are useful for catching regressions and spotting obvious quality differences. They're not reliable for small, directional improvements where the margin is within the judge's noise floor. For writing quality specifically, human review of a few outputs is more informative than a numeric score.

---

## Append-only updates prevent silent truncation

The gap update step originally asked the model to output the entire master list with new content added inline. For a 25k-character file, the model sometimes truncated the output — silently dropping the tail of the file. There was no error, no warning; content just disappeared.

The fix: the model only outputs the *new lines to add*. The code reads the existing file, appends the new block to a `## Candidate Clarifications` section, and writes back. The original content is never touched.

Never ask a model to rewrite a large file. Rewrite outputs are both expensive and fragile. Append-only is safer, cheaper, and easier to audit.

---

## MCP integration

MCP (Model Context Protocol) connects external tools to the agent via stdio transport. I used it in two places:

**Google Sheets** — logs each application run automatically after PDF generation. The server runs as a subprocess; the client discovers tools at runtime. I also evaluated LinkedIn and Glassdoor MCP servers but decided against them — ToS violations, account ban risk, and GDPR concerns made them too risky for a personal tool.

**Claude Desktop interview prep** — the SQLite database is exposed as an MCP server, giving Claude Desktop direct access to application context. When I mention a company I'm interviewing at, Claude loads the JD, gap analysis, and previous prep rounds automatically and starts the session. Notes are stored back to the DB at the end, so each round builds on the last.

The decision to use Claude Desktop as the interview prep surface rather than building a dedicated UI: the prep loop is conversational — the agent asks a question, I answer, it coaches. Claude Desktop already does this natively.

---

## v2: from CLI tool to application tracker

The CLI works well for a single application. But once you have 20+ runs at different stages — some waiting for reply, some in screening, some in interview — the limitation becomes clear: there's no way to see all applications at once or navigate between them.

### Keeping the CLI while adding a database

The constraint was explicit: keep the CLI working and don't lose the existing 20 checkpoints. The solution was to write to both — checkpoint files unchanged for CLI resume, plus a SQLite database for everything that needs to query across runs. `migrate.py` imports existing checkpoints on first setup.

The data model has two tables: `applications` (pipeline outputs, status, score) and `rounds` (interview prep, transcripts, notes per round). Status transitions: draft → cv_ready → applied → screening → interview → offer/rejected. The `--log-outcome` CLI flag updates status from the terminal without running the pipeline.

---

## What's next

- **Interview prep agent** — structured prompting for HR screening, HM interview, case study prep. Each round type has different coaching logic.
- **Cross-round continuity** — HR transcript → HM prep. The `rounds` table already supports this; the prep agent needs to read previous rounds before generating the next.
- **Web UI** — minimal dashboard: application list, status, trigger prep, review outputs. Built on top of the existing FastAPI layer.

---

## What I'd do differently

**Start with eval.** I built the core agent first, then added evaluation later. That meant I was flying blind for the first 20+ runs. Defining "good" upfront forces you to think about what the system is actually supposed to do — and surfaces edge cases before they become production incidents.

**Save every output, not just scores.** The first version of eval only saved metrics — word counts, scores. Not the actual text. That made model comparisons impossible after the fact. Every run should save the full output for every step.

**Test the integration seams, not just the units.** Most of the serious bugs in this project — the guardrail bypass, the hallucinated company that slipped through — weren't in any individual function. They were in how the pieces connected. Unit tests caught individual functions working correctly; the failures happened at the boundaries between them. A few integration tests that exercise the full path from model output to validation result would have caught these earlier.
