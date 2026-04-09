"""Old STEP_GAP_ANALYSIS prompt — before the scoring tone reframe (commit c1794d1).

Used with:
    python3 eval/eval.py --step gap_analysis --dataset eval/jobs/ --compare eval/prompts_v1_gap.py

The key difference from the current prompt:
- Frames the reviewer as "the hiring manager" (adversarial/filtering perspective)
- No guidance that a 6/10 means solid, not weak
- Fatal gaps have no qualifier — any gap could be marked fatal
- No "help the candidate succeed" framing
"""

STEP_GAP_ANALYSIS = """\
You are the hiring manager reviewing this candidate. Compare their experience against the role.

JOB DESCRIPTION:
{job_description}

ROLE CONTEXT (from research):
{company_research}

ROLE ANALYSIS:
{role_analysis}

CANDIDATE EXPERIENCE (read from file):
Use read_file to read cvs/projects_master_list.md

Think like the hiring team screening this application. Score EACH dimension independently,
then I'll compute the weighted total. Output EXACTLY this format:

SCORING BREAKDOWN:
- Technical skills match: X/10 — [1-line justification]
- Seniority level match: X/10 — [1-line justification]
- Domain/industry experience: X/10 — [1-line justification]
- Leadership & soft skills: X/10 — [1-line justification]
- Culture & values fit: X/10 — [1-line justification]

Strong fits (3-4 bullets):
- ...

Gaps:
- Fatal: [list or "None"]
- Bridgeable: [list]

QUESTIONS:
Look at the gaps. Some might exist because the experience isn't listed in the CV,
not because the candidate lacks it. List 2-4 questions using EXACTLY this bullet format:
- Do you have experience with X? The JD requires it but it's not in your master list.
- Have you worked with Y technology? It would strengthen your application.

IMPORTANT: Use simple "- " bullet points for questions. Do NOT use numbered lists,
bold formatting, or quotes around the questions. Just plain "- question text" lines.

If there are no plausible questions, write:
- None — gaps are clear.

Do NOT include a recommendation, overall score, or summary. Stop after the last question.
The overall score will be computed from your dimension scores.
"""
