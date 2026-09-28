---
name: risk-scores
title: Risk scores and clinical calculators
description: Compute validated prediction rules and equations (eGFR, CrCl, CHA₂DS₂-VASc, HAS-BLED, HEART, Wells, PERC, CURB-65, qSOFA, MELD-Na, Child-Pugh, FIB-4, ASCVD PCE, QTc, anion gap, corrected Na and Ca) with the deterministic calculator engine.
triggers:
  - '\b(score|calculat(e|or)|risk of|estimate(d)? risk|stratif(y|ication)|predict(ed|ion)?)\b'
  - '\b(egfr|crcl|creatinine clearance|cha2?ds2|has-?bled|heart score|wells|perc|curb-?65|qsofa|meld|child[- ]pugh|fib-?4|ascvd|pooled cohort|qtc|anion gap|corrected (sodium|calcium)|bmi|bsa)\b'
tools: [list_calculators, run_calculator, analyze_clinical_text, diagnostic_probability, treatment_effect]
---
# Risk scores and clinical calculators

## Rules
- **Never do clinical arithmetic in text.** Every score, eGFR, CrCl, risk percentage and corrected value must come from
  `run_calculator`. If a tool rejects the inputs, fix them from its error message. Do not work around it by hand.
- Call `list_calculators` if unsure of the name or inputs. If the user pasted a case, `analyze_clinical_text` pre-fills the inputs.
- Report the score, its category, **the inputs used**, and the calculator's caveats (the tool returns them).
  Doctors need to see what went in to trust what came out.
- Check that the population fits: PCE only for ages 40–79 in primary prevention; CHA₂DS₂-VASc not for valvular AF;
  PERC only when pre-test probability is already low; Wells for outpatient/ED; qSOFA is a prognostic prompt, not a sepsis screen.
- Missing inputs: ask, or run the calculation under explicit assumptions and show how the result changes (best and worst case).
- A score informs a decision; it does not make it. Pair each result with the guideline action threshold the tool reports,
  and search for the guideline if the user asks what to do next.

## Chaining with statistics
- Pre-test probability from a score (e.g. Wells) → `diagnostic_probability` with the test's sensitivity, specificity or LRs.
- A patient's baseline risk (e.g. 10-year ASCVD 12%) plus a trial HR or RR → `treatment_effect` gives a personalised ARR and NNT.
