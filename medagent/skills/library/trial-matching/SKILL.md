---
name: trial-matching
title: Clinical trial matching
description: Find recruiting trials for a patient and check eligibility criterion by criterion against the case features extracted by the NER model.
triggers:
  - '\b(clinical trials?|studies recruiting|recruiting|enrol(l)?(ing|ment)?|eligib(le|ility)|trial options?|NCT\d{8})\b'
  - '\b(experimental|investigational|phase (i{1,3}|[123])|compassionate use|expanded access)\b'
entity_signals: [DISEASE]
tools: [analyze_clinical_text, search_clinical_trials, get_trial_details, search_literature]
---
# Clinical trial matching

## Procedure
1. `analyze_clinical_text` on the patient description: age, sex, diagnosis, prior therapies (medications),
   key labs (eGFR, bilirubin, platelets) and negated conditions.
2. `search_clinical_trials` with `condition` plus, where given, `intervention`, `location` and `recruiting_only=true`.
   Run 2–3 variants (broader condition terms, drug class) because registry wording varies.
3. Shortlist up to 5 by phase, status and proximity. Call `get_trial_details` on each.
4. For each shortlisted trial, check the eligibility text against the patient:
   | Criterion | Patient | Status (met / not met / unknown) |
   Common exclusions to check: organ function thresholds, prior lines of therapy, brain metastases,
   performance status, pregnancy, and concurrent medications.
5. Rank as "likely eligible", "possibly (needs X)" or "ineligible (reason)".

## Output
- One card per trial: NCT, title, phase, status, sponsor, nearest sites, primary outcome, and the eligibility table.
- Say plainly that final eligibility is decided by the study team, and list the facts they will need.
