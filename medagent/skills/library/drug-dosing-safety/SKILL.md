---
name: drug-dosing-safety
title: Drug dosing and safety
description: Dosing, renal and hepatic adjustment, contraindications, interactions, pregnancy and lactation, and adverse effects. Built on the FDA label, with Cockcroft-Gault and Child-Pugh computed deterministically.
triggers:
  - '\b(dos(e|es|ing|age)|mg|titrat(e|ion)|loading|maintenance|max(imum)? dose|how much)\b'
  - '\b(renal(ly)?|kidney|CrCl|eGFR|dialysis|hepatic|liver|child[- ]pugh)\b.*\b(adjust|dose|dosing|safe)\b'
  - '\b(interact(ion|s)?|contraindicat(ed|ion))\b'
  - '\b(safe|safety|use|using|take|taking|exposure|prescrib\w*)\b.{0,40}\b(pregnan\w*|breast ?feeding|lactation)'
  - '\b(side effects?|adverse (effects?|events?|reactions?)|toxicity|black box|boxed warning|QT)\b'
entity_signals: [CHEMICAL]
tools: [drug_label, drug_adverse_events, run_calculator, analyze_clinical_text, search_literature, search_web]
---
# Drug dosing and safety

## Procedure
1. **Label first**: call `drug_label` for each drug (generic name). The FDA label is the primary source for dosing,
   the boxed warning, contraindications and specific populations. Quote the label wording for doses.
2. **Renal function**: if kidney function matters, compute it. Never estimate it.
   - Use `run_calculator("cockcroft_gault", …)` for label-based dosing. Most FDA renal tables use CrCl.
     Pass `height_cm` so the tool can apply ideal or adjusted body weight, and report which weight was used.
   - Use `ckd_epi_2021` for CKD staging. Say explicitly when the two disagree near a dosing threshold.
   - DOAC example: apixaban dose reduction uses ≥2 of age ≥80, weight ≤60 kg, Cr ≥1.5 mg/dL, not CrCl alone.
     Apply the label's actual criteria.
3. **Hepatic function**: `child_pugh` when the label has Child-Pugh-based recommendations.
4. **Interactions**: read the label's drug-interactions section. Name the mechanism (CYP3A4, P-gp, QT, serotonergic,
   additive bleeding) and the practical action (avoid, reduce dose, monitor). For QT risk with a known QT, run `qtc`.
5. **Pregnancy and lactation**: summarise the label's risk summary and search for current society guidance if the label is thin.
6. **Adverse events**: the label's adverse-reactions section gives trial incidence. `drug_adverse_events` (FAERS) gives
   spontaneous reports only. Never present FAERS counts as rates.

## Guardrails
- State the patient-specific inputs used (weight, CrCl, age).
- Flag narrow-therapeutic-index drugs (warfarin, digoxin, lithium, aminoglycosides, vancomycin, phenytoin) and advise level monitoring.
- If the label and guidelines differ (e.g. off-label dosing), present both and say which is which.
- Do not write prescriptions. Present the dosing options the label and the evidence support.
