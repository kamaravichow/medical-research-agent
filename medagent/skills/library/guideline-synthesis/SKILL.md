---
name: guideline-synthesis
title: Guideline synthesis
description: Compare what major guidelines recommend (ACC/AHA, ESC, NICE, WHO, USPSTF, IDSA, KDIGO, ADA…), with recommendation strength, evidence level, publication year and points of disagreement.
triggers:
  - '\b(guidelines?|recommend(ation|ations|ed|s)?|consensus|position statement|society|NICE|ESC|ACC|AHA|USPSTF|WHO|IDSA|KDIGO|ADA|GOLD|GINA|NCCN|ASCO)\b'
  - '\b(standard of care|current practice|what do (the )?(guidelines|societies) say)\b'
tools: [search_web, read_source, search_literature]
---
# Guideline synthesis

## Procedure
1. Run `search_web(kind="guidelines")` 1–3 times (condition; condition + intervention; the society name if the user named one).
2. Open the most relevant guideline pages with `read_source(focus=<the specific question>)` so that you quote the actual
   recommendation text and its grading, not a summary.
3. Search `search_literature` with `study_designs=["guideline"]` to catch guidelines published in journals.
4. Check currency: note the year of each guideline and search for major trials published afterwards
   (`find_new_research` or `search_literature` with `year_from`). If newer evidence exists, say what it would likely change.

## Reporting the strength of a recommendation
Use each body's own grading, verbatim:
- ACC/AHA: Class 1 / 2a / 2b / 3 (no benefit or harm); LOE A, B-R, B-NR, C-LD, C-EO
- ESC: Class I / IIa / IIb / III; level A / B / C
- GRADE (WHO, NICE, IDSA, KDIGO, …): strong / conditional (weak); certainty high / moderate / low / very low
- USPSTF: A / B / C / D / I

## Output
A comparison table: | Body (year) | Recommendation | Strength / evidence | Notes (population, thresholds) | [n] |.
Then **Agreement** and **Disagreement** (and the likely reasons: different evidence cut-off dates, health-system context, values).
