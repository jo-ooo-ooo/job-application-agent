# Learnings

Building a job application agent from scratch as a PM learning agent architecture.

The agent runs a 7-step pipeline: company research → gap analysis → project selection → CV → cover letter → PDF. It does real web searches, reads my CV files, and scores fit before writing anything.

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

## Decomposed scoring and structured output

During testing, I noticed the scoring and recommendation were sometimes inconsistent. In one run it told me to apply; in the next, it said the gap was too large. I couldn't tell why.

The fix: ask the model to score five dimensions independently (technical skills, seniority, domain experience, leadership, culture fit), then compute the weighted total in code.

When the score is in the borderline range (45-65), it automatically re-runs and averages. One run could be 58, the other 62 — both are in the range, so the average is more meaningful than either.

---

## Guardrails and the auto-fix loop

The guardrails caught issues: empty output, word count violations, CV doesn't contain the candidate's name, and gap analysis only has 2 dimension scores instead of 5.

The auto-fix loop (retry with the specific warnings) resolved most issues. But it also revealed something about prompting: if the output is wrong in the same way twice, it's usually a prompt problem.

---

## Evaluation

Setting up the eval framework forced me to define what "good" means concretely:
- CV word count in range (100-800)
- JD keyword match above a threshold
- Guardrails passing
- LLM-as-judge relevance score

I also ran a round of eval to see whether I could swap company research from Sonnet to Haiku to save cost. Haiku costs 5x less and runs 2x faster. But Haiku only gives you facts, while Sonnet adds interpretation — layoff context, valuation concerns, what the role means strategically. That extra context is exactly what feeds into gap analysis and CV tailoring downstream.

---

## Checkpointing matters more for expensive pipelines

A full run costs $0.50-1.00 and takes 10 minutes. If it crashes at step 5 (CV construction, the most expensive step), I've lost most of my spend. So I added checkpointing to handle rate limit exhaustion, network drops, or the user closing the terminal.

The implementation is simple — save the state dict to JSON after every step, load it back on `--resume`.

---

## What I'd do differently

**Start with eval.** I built the core agent first, then added evaluation later. That meant I was flying blind for the first 20+ runs. 

**Save every output, not just scores.** The first version of eval only saved metrics — word counts, scores. Not the actual text. That made model comparisons impossible after the fact. Every run should save the full output for every step.

---

## What's next

V1 is complete: observability, reliability, testing, guardrails, evaluation, checkpointing.

V2 directions: improving prompts, multi-model routing, parallel execution, and integrations — job tracking, application form autofill, batch processing from a saved jobs list.

The reason I want to continue with this project specifically: job applications are a domain I understand well and have strong opinions on. That makes it easier to evaluate quality, spot bad outputs, and design the right abstractions. 

V2 will be where the more advanced patterns come in: multi-agent workflows, parallel execution, multi-model routing, and external integrations. I'm particularly interested in what breaks when you move from a single orchestrator to multiple coordinating agents.
