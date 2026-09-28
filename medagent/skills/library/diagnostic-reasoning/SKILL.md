---
name: diagnostic-reasoning
title: Diagnostic reasoning and test interpretation
description: Differential diagnosis, pre-test probability, and test choice and interpretation, using likelihood ratios and Bayes (deterministic diagnostic_probability) plus guideline work-up pathways.
triggers:
  - '\b(diagnos(is|e|tic)|differential|ddx|work[- ]?up|rule (in|out)|cause of|causes|etiology|aetiology)\b'
  - '\b(sensitivity|specificity|likelihood ratio|LR\+?|PPV|NPV|pre-?test|post-?test|false (positive|negative))\b'
  - '\b(test(ing)?|screen(ing)?|imaging|biomarker|d-?dimer|troponin|ct|mri|ultrasound)\b.*\b(for|to (rule|exclude|detect))\b'
entity_signals: [DISEASE]
tools: [analyze_clinical_text, run_calculator, diagnostic_probability, search_literature, search_web]
---
# Diagnostic reasoning

## Procedure
1. **Differential**: organise it as most likely, can't-miss (life-threatening or time-critical), and treatable-if-found.
   Keep can't-miss diagnoses on the list until they are explicitly excluded.
2. **Pre-test probability**: use a validated rule where one exists (`run_calculator`: wells_pe, perc, heart_score, curb65…).
   Otherwise use a published prevalence in a comparable setting, cited. State it as a number.
3. **Test characteristics**: find sensitivity and specificity from a diagnostic-accuracy meta-analysis
   (`search_literature` for "<test> <condition> diagnostic accuracy meta-analysis"). Prefer data from a spectrum like this patient's.
4. **Post-test probability**: call `diagnostic_probability` with the pre-test probability and sens/spec or LRs.
   Report both the positive-result and the negative-result probability, and compare them with the test and treatment thresholds.
   - LR+ >10 or LR− <0.1 usually changes management. LRs of 2–5 or 0.2–0.5 rarely do on their own.
5. **Next step**: follow the guideline pathway (`search_web(kind="guidelines")`), e.g. Wells → D-dimer or CTPA,
   HEART → discharge or observation. Name where the pathway branches.

## Pitfalls to call out
- Spectrum bias: accuracy data from high-prevalence referral settings overstate PPV in primary care.
- Serial tests are not independent, so don't multiply LRs from correlated tests.
- Incidentalomas and overdiagnosis in screening questions: give numbers needed to screen and the false-positive rate.
