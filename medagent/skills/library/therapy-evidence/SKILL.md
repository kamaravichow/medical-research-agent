---
name: therapy-evidence
title: Treatment evidence
description: Answer "does X work / what is first-line / X vs Y" questions. Go guidelines first, then systematic reviews and RCTs, and report absolute effects (ARR, NNT) computed from the trial numbers.
triggers:
  - '\b(treat(ment|ing)?|therap(y|ies)|first[- ]line|second[- ]line|manage(ment)?|efficacy|effective(ness)?|benefit)\b'
  - '\b(vs\.?|versus|compared (with|to)|better than|superior|non-?inferior|switch)\b'
  - '\b(should (i|we)|is it (reasonable|worth)|indicated|start(ing)?|add(ing)?)\b'
  - '\b(reduce|prevent|improve)s?\b.*\b(mortality|events?|risk|outcomes?|symptoms?)\b'
entity_signals: [CHEMICAL]
tools: [search_web, search_literature, get_article, extract_pico, extract_effect_sizes, treatment_effect, search_clinical_trials]
---
# Treatment evidence

## Search strategy, in order
1. **Guidelines**: `search_web(kind="guidelines")` using the condition plus the intervention. Record the issuing body,
   the year, and the recommendation class and level of evidence (e.g. ACC/AHA Class 1, LOE A; GRADE strong/moderate).
2. **Syntheses**: `search_literature` with `study_designs=["meta_analysis","systematic_review"]`, `year_from` about 8 years back.
3. **Pivotal RCTs**: `search_literature` with `study_designs=["rct"]`. Name the landmark trials if you know them and confirm that they appear in the results.
4. If the guideline is older than the key trials, say so. The practice-changing evidence may postdate it.

## Extracting numbers (use the models, not memory)
- For each key trial or meta-analysis, call `extract_pico` and `extract_effect_sizes` on its abstract,
  passing a citation number such as "[3]". Report only estimates that appear in the tool output or the abstract.
- Convert relative effects into absolute effects with `treatment_effect`:
  - arm event counts or percentages → ARR, NNT and 95% CI
  - HR or RR plus a baseline risk (from the control arm, or the patient's own risk from `run_calculator`) → the patient's ARR and NNT
- Always give the NNT with its time frame ("NNT 19 over 2.3 years").
- Harms: report bleeding, adverse events and discontinuations the same way (NNH).

## Judging the result
- Whether the primary endpoint was met. Treat a secondary or subgroup finding as hypothesis-generating.
- Composite endpoints: which component drove the effect?
- Surrogate vs patient-important outcomes.
- Applicability: trial population vs this patient (age, eGFR, prior events, background therapy).

## Answer format
The **Key evidence** table needs these columns: | Study (year) | Design, LoE | Population, n | Intervention vs comparator | Effect (95% CI) | ARR / NNT | [n] |
