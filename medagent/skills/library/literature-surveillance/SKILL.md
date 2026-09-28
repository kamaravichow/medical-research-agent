---
name: literature-surveillance
title: New research surveillance
description: What's new on a topic. Covers recently indexed papers, preprints, trial readouts and news, triaged into practice-changing, confirmatory and early signals.
triggers:
  - '\b(new|latest|recent(ly)?|emerging|update(s|d)?|this (year|month|week)|breakthrough|just published|readout|results announced)\b'
  - '\b(20[2-9]\d)\b.*\b(studies|trials?|data|evidence|research)\b'
  - '\b(preprints?|medrxiv|biorxiv|congress|conference|annual meeting|late[- ]breaking|presented at)\b'
tools: [find_new_research, search_web, search_literature, get_article, extract_effect_sizes, search_clinical_trials]
---
# New research surveillance

## Procedure
1. `find_new_research(topic, days=…)`: use 30 days by default, 90–365 for "this year" questions.
2. `search_web(kind="news", days=…)` for trial readouts presented at congresses but not yet indexed, and FDA/EMA actions
   (`kind="regulatory"`).
3. For each candidate, get the abstract (`get_article`) and its effect sizes (`extract_effect_sizes`).

## Triage every item into one of
- **Practice-changing**: large, well-conducted RCT or meta-analysis on a patient-important outcome, or a new approval or guideline.
- **Confirmatory**: consistent with existing evidence (e.g. a new trial in a new population).
- **Early signal**: phase 1–2, observational, subgroup, surrogate endpoint, or **preprint (not peer reviewed)**.
- **Safety alert**: regulatory warnings, withdrawals, retractions.

## Output
Newest first, grouped by the categories above. Give each item a one-line "what it shows" with its main effect size,
and a one-line "so what" for practice. Include date and source. Label preprints and congress abstracts clearly.
