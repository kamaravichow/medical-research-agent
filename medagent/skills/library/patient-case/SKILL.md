---
name: patient-case
title: Patient case work-up
description: Structure a clinical vignette before researching it. Extract demographics, conditions, medications, negated findings, vitals and labs with the clinical NER model, then compute every score the data allows.
triggers:
  - '\b\d{1,3}[- ]?(year|yr)s?[- ]?old\b'
  - '\b\d{1,3}\s?(yo|y/o|M|F)\b'
  - '\b(presents?|presenting|admitted|history of|PMH|on examination|labs? (show|reveal))\b'
  - '\bmy patient\b'
entity_signals: [DISEASE, CHEMICAL]
min_entities: 3
tools: [analyze_clinical_text, run_calculator, list_calculators, search_literature, search_web]
---
# Patient case work-up

Use this whenever the question describes a specific patient.

## Steps
1. **Structure the case first.** Call `analyze_clinical_text` on the vignette, exactly as the user wrote it.
   It returns age, sex, affirmed and **negated** conditions and medications, expanded abbreviations,
   vitals and labs, and which calculators can already be run with those values.
   - Treat negated findings ("denies chest pain", "no prior stroke") as pertinent negatives. Never list them as problems.
   - If the model missed something obvious in the text, trust the text and say what you added.
2. **Compute; never estimate.** For each calculator the analysis says is ready (or nearly ready), call `run_calculator`.
   Ask for, or state as an assumption, any missing input. Do not guess lab values.
   Typical sets:
   - AF → `cha2ds2_vasc`, `has_bled`, plus `cockcroft_gault` if there is an anticoagulant question
   - Renal dosing → `cockcroft_gault` (drug labels) and `ckd_epi_2021` (CKD staging)
   - Chest pain → `heart_score`. Suspected PE → `wells_pe`, then `perc` if pre-test probability is low
   - Pneumonia → `curb65`. Suspected sepsis → `qsofa` (as a prognostic prompt, not a screen)
   - Cirrhosis → `child_pugh`, `meld_na`. MASLD or hepatitis → `fib4`
   - Primary prevention, age 40–79 → `ascvd_pce`
3. **Frame the question** as PICO for this patient, then load the matching skill
   (therapy-evidence, diagnostic-reasoning, drug-dosing-safety) and research it.
4. **Individualise.** Say where this patient differs from the trial or guideline population
   (age, eGFR, pregnancy, frailty, comorbidity). Those differences are the caveats that matter.

## Output additions
- A short **Case summary** line: age/sex, key problems, key negatives, relevant labs.
- A **Scores** table: | Score | Value | Category | Inputs used |. Every value must come from a `run_calculator` result.
- End with the decision points, not orders. For example: "anticoagulation indicated per CHA₂DS₂-VASc 4; choice of agent depends on CrCl 38 mL/min…".
