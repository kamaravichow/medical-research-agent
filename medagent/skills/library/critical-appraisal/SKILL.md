---
name: critical-appraisal
title: Critical appraisal
description: Appraise a specific paper or trial. Cover design, PICO, bias domains, precision, and GRADE-style certainty, using the PICO and effect-size extraction models on the actual abstract.
triggers:
  - '\b(apprais(e|al)|critique|critically|journal club|how (good|strong|reliable)|trust(worthy)?)\b'
  - '\b(bias|confound(ing|ers)?|limitations?|validity|methodolog(y|ical)|quality of (the )?evidence|GRADE)\b'
  - '\b(PMID|doi:|NCT\d{8}|this (study|trial|paper|meta-analysis))\b'
tools: [get_article, read_source, extract_pico, extract_effect_sizes, treatment_effect, get_trial_details]
---
# Critical appraisal

## Procedure
1. Retrieve the full record with `get_article`. If it is open access and methods detail matters, use `read_source` with
   focus="randomisation allocation concealment blinding attrition" (RCT) or "confounding adjustment" (observational).
2. Run `extract_pico` and `extract_effect_sizes` on it. Quote the extracted PICO and estimates, and correct them from the text when the model misparsed.
3. If a registration (NCT) is cited, `get_trial_details` shows whether the **pre-registered primary outcome**
   matches the reported one. Outcome switching is a red flag.

## Checklist by design
**RCT (RoB 2 domains):** randomisation and allocation concealment; deviations from intended intervention (blinding, ITT vs per-protocol);
missing outcome data (attrition, differential loss); outcome measurement (blinded assessors, objective endpoint);
selective reporting (registry vs paper). Also: early stopping for benefit, and a fragile result where only a few events would flip significance.
**Observational (ROBINS-I thinking):** confounding by indication, immortal-time bias, selection, exposure misclassification,
and residual confounding. Ask whether the adjusted estimate stays robust (E-value, if reported).
**Meta-analysis:** search comprehensiveness, heterogeneity (I², prediction interval), small-study effects,
quality of the included trials, and whether one large trial dominates.
**Diagnostic accuracy:** spectrum, reference standard applied to all, blinding, and whether the population matches the clinical use.

## Certainty (GRADE-style)
Start at high for RCTs and low for observational studies. Rate down for risk of bias, inconsistency, indirectness, imprecision
(CI crosses a clinically important threshold or no effect) and publication bias. Rate up for a large effect or a dose-response.
State the final certainty (high / moderate / low / very low) and the reasons.

## Output
- **Verdict** in one sentence: what the study shows and how much to trust it.
- A PICO table, the main effect with CI, ARR and NNT (via `treatment_effect`), a bias table (domain | concern | why), and the certainty rating.
