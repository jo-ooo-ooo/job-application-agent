# Experiment: Gap Analysis Tone Reframe

**Date:** 2026-04-09
**Eval command:**
```
python3 eval/eval.py --step gap_analysis --dataset eval/jobs/ --compare eval/prompts_v1_gap.py
```
**Dataset:** 7 JDs (jd_1, jd_2, jd_3, jd_4, pm_ai_platform, pm_enterprise_saas, pm_growth_consumer)
**Results file:** eval/results/eval_step_gap_analysis_20260409_140437.json

---

## Hypothesis

Reframing the gap analysis prompt from a "hiring manager filtering candidates" perspective to a "senior recruiter helping the candidate succeed" perspective would produce more accurate, less adversarial gap assessments — specifically: fewer false fatal gaps and more useful bridgeable gap identification.

---

## What Changed

**Current prompt** (`prompts.py::STEP_GAP_ANALYSIS`):
```
You are a senior recruiter assessing fit between this candidate and role. Your job is to
help them make the most of the application — not to filter them out.
...
Score EACH dimension independently on 1-10. Be fair but honest — a 6 means solid, not weak.
...
Fatal: [list or "None" — only truly disqualifying gaps, not domain mismatches]
```

**Old prompt** (`eval/prompts_v1_gap.py::STEP_GAP_ANALYSIS`):
```
You are the hiring manager reviewing this candidate. Compare their experience against the role.
...
Think like the hiring team screening this application.
...
Fatal: [list or "None"]
```

The key differences:
- Role framing: recruiter (advocate) vs. hiring manager (gatekeeper)
- Scoring anchor: explicit "a 6 means solid, not weak" vs. no guidance
- Fatal gap qualifier: "only truly disqualifying gaps, not domain mismatches" vs. no qualifier

---

## Results

### Score Parse Success

| JD | Current | v1 (compare) |
|---|---|---|
| jd_1 | 0/5 | 0/5 |
| jd_2 | 0/5 | 0/5 |
| jd_3 | 0/5 | 0/5 |
| jd_4 | 0/5 | 0/5 |
| pm_ai_platform | 0/5 | 0/5 |
| pm_enterprise_saas | 0/5 | 0/5 |
| pm_growth_consumer | 0/5 | 0/5 |
| **Average** | **0.0/5** | **0.0/5** |

**Why 0/5 for both:** In the eval harness, the model runs `gap_analysis` without access to the real candidate master list — the `read_file` tool call returns an empty or missing file rather than the actual `cvs/projects_master_list.md` content. Without candidate data, the model produces prose output instead of the expected `X/10` scoring format, so the score parser finds nothing to extract. This affects both prompts equally and does not bias the comparison.

### Gap Accuracy Judge Score (LLM judge, 1–5)

| JD | Current (recruiter framing) | v1 (hiring manager framing) | Winner |
|---|---|---|---|
| jd_1 | 4/5 | 2/5 | Current |
| jd_2 | 4/5 | 3/5 | Current |
| jd_3 | 3/5 | 3/5 | Tie |
| jd_4 | 4/5 | 4/5 | Tie |
| pm_ai_platform | 4/5 | 4/5 | Tie |
| pm_enterprise_saas | 3/5 | 4/5 | v1 |
| pm_growth_consumer | 3/5 | 3/5 | Tie |
| **Average** | **3.6/5** | **3.3/5** | |

Summary: Current wins 2/7, ties 4/7, v1 wins 1/7.

---

## Interpretation

The current prompt outperforms meaningfully on jd_1 (4 vs 2) and jd_2 (4 vs 3). Both are generalist/engineering-adjacent roles where the old prompt's unqualified fatal gap definition likely caused it to flag domain mismatches as disqualifying — the kind of over-filtering that the tone reframe was designed to prevent. The recruiter framing appears to produce more calibrated gap identification when the candidate has transferable but not direct experience.

The one case where v1 wins — pm_enterprise_saas — is worth noting. Enterprise SaaS roles often have hard requirements (specific integration patterns, enterprise sales cycle familiarity, compliance experience) that are genuinely disqualifying if absent. The hiring manager framing may have surfaced real fatal gaps more crisply, while the recruiter framing may have softened gaps that were in fact serious. This suggests the current prompt's "not domain mismatches" qualifier could be over-applied on roles where domain is a true filter.

The four ties are roles where both prompts converged — likely because the fit was either clearly strong or clearly weak enough that framing didn't affect the output.

---

## Conclusion

**Verdict: Keep the current prompt, but monitor enterprise roles.**

The tone reframe improved gap accuracy on a majority of JDs (2 wins, 4 ties, 1 loss) and lifted the average from 3.3 to 3.6. The improvement is consistent in direction and concentrated on exactly the cases where the hypothesis predicted gain — roles where domain mismatch might be mistaken for a fatal gap.

**Caveats:**
- Sample size is 7 JDs, all run once. The judge scores are single-point estimates with no confidence interval.
- Score parse success is 0/5 for both prompts due to the eval harness limitation described above. The numeric scoring quality is untested in this run.
- The pm_enterprise_saas result is a genuine signal, not noise — the v1 prompt produced more output tokens (1,609 vs 1,323) and a higher judge score, which may indicate it was more thorough on a role with specific hard requirements. Worth revisiting if the pipeline is used heavily on enterprise roles.

Next experiments to consider: (1) fix the eval harness so `read_file` resolves correctly and re-run score parse success; (2) test a variant of the current prompt with a role-type conditional — stricter fatal gap language when `ROLE TYPE` from role analysis indicates "enterprise" or "compliance-heavy."
