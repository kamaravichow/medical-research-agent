# MedAgent

A medical research agent and evidence workbench for clinicians. It is built on **LangChain**, uses **free biomedical APIs** for the literature, trials and drug data, and uses **TinyFish Search and Fetch** for guidelines, news and full-text reading.

A doctor can use it in three ways:

- **Search**: one query runs against PubMed, Europe PMC (including medRxiv and bioRxiv preprints), OpenAlex, ClinicalTrials.gov and guideline bodies at the same time. Results are merged, de-duplicated, graded by level of evidence and ranked in about a second. No LLM is involved.
- **Ask**: a LangChain agent plans its searches, reads what it needs, and writes a cited answer with a bottom line, an evidence table, guidelines, safety points, ongoing trials and evidence gaps.
- **Watch**: save a topic and get a digest of what is new since you last checked.

## Sources

| Source | What it provides | Cost / key |
|---|---|---|
| [PubMed E-utilities](https://www.ncbi.nlm.nih.gov/books/NBK25501/) | MEDLINE records, structured abstracts, MeSH, publication types | Free. Optional `NCBI_API_KEY` raises the limit from 3 to 10 req/s |
| [Europe PMC](https://europepmc.org/RestfulWebService) | Preprints (medRxiv, bioRxiv, Research Square), PMC full-text links, citation counts | Free, no key |
| [OpenAlex](https://docs.openalex.org) | Broad scholarly index, citation counts, open-access PDFs | Free, no key |
| [ClinicalTrials.gov v2](https://clinicaltrials.gov/data-api/api) | Registered trials, status, phase, eligibility, sites | Free, no key |
| [openFDA](https://open.fda.gov/apis/) | FDA drug labels (boxed warnings, dosing, interactions) and FAERS adverse-event counts | Free. Optional `OPENFDA_API_KEY` |
| [TinyFish](https://tinyfish.ai) Search | Guideline bodies (WHO, NICE, CDC, USPSTF, specialty societies), regulators, medical news | `TINYFISH_API_KEY` |
| TinyFish Fetch | Clean full text of any page or open-access article, with query-ranked highlights | `TINYFISH_API_KEY` |

Everything except TinyFish and the LLM works with no keys at all.

## Specialised skills and medical ML models

LLMs are good at planning and writing, but unreliable at clinical arithmetic, and they can paraphrase numbers into existence.
MedAgent hands those jobs to **specialised, predictable models** that the agent calls through function calling. The LLM quotes their outputs instead of generating them.

### ML models and deterministic engines (`medagent/ml/`)

| Tool the agent calls | Model / method | Fallback when not installed |
|---|---|---|
| `analyze_clinical_text` | scispaCy **`en_ner_bc5cdr_md`** (diseases and chemicals, trained on BC5CDR), **NegEx** clinical negation (negspacy), Schwartz-Hearst abbreviation detection, plus regex extraction of age, sex, vitals and labs | Regex layer only (demographics, vitals, labs) |
| `extract_pico` | **BioELECTRA-PICO** (`kamalkraj/BioELECTRA-PICO`, fine-tuned on EBM-NLP, F1≈0.74) | Rule extractor ("randomly assigned to X or Y", "patients with…", "primary outcome was…") |
| relevance ranking inside `search_literature` | **NCBI MedCPT Cross-Encoder** (`ncbi/MedCPT-Cross-Encoder`, PubMedBERT trained on 255M PubMed search-log pairs) | Okapi BM25 over title, abstract and MeSH |
| `extract_effect_sizes` | Deterministic extraction of HR/OR/RR/RD/MD/SMD with 95% CI, p-values, NNT and arm event rates, returned with the verbatim text span | — |
| `run_calculator`, `list_calculators` | 18 validated equations with typed input schemas, references and caveats (below) | — |
| `diagnostic_probability` | Bayes with sensitivity/specificity or likelihood ratios; PPV and NPV | — |
| `treatment_effect` | ARR, RRR, NNT/NNH with 95% CI from event counts, or a trial RR/HR applied to a patient's own baseline risk | — |

**Calculators:** CKD-EPI 2021 eGFR (race-free), Cockcroft-Gault (actual, ideal and adjusted weight), CHA₂DS₂-VASc (+ CHA₂DS₂-VA), HAS-BLED, HEART, 2013 Pooled Cohort Equations, QTc (Bazett and Fridericia), Wells PE, PERC, CURB-65, qSOFA, MELD-Na (OPTN 2016 rounding rules), Child-Pugh, FIB-4, BMI/BSA, albumin-corrected calcium, anion gap with delta ratio, and glucose-corrected sodium.
Tests check the equations against published worked examples. For instance, the PCE reproduces the 2013 guideline's example (2.1% / 3.0% / 5.3% / 6.1%), and CKD-EPI uses the NKF-published exponents (α = −0.241 female, −0.302 male).

All models load lazily, run in a worker thread, and fall back per component, so the app works with none of them installed. `/api/health` and the "ML models" indicator in the UI show which backend each component is using.

```bash
pip install -e ".[nlp]"            # scispaCy NER + NegEx (downloads the ~120 MB BC5CDR model)
pip install -e ".[ml]"             # + transformers/torch for MedCPT and BioELECTRA-PICO (downloaded from Hugging Face on first use)
MEDAGENT_ML=rules medagent serve   # force deterministic fallbacks only
```

### Skills (`medagent/skills/library/*/SKILL.md`)

Skills are clinical playbooks. Each is a folder with a `SKILL.md`: YAML front matter (name, description, triggers, entity signals, preferred tools) followed by Markdown instructions. This is the same layout Anthropic Agent Skills use.

| Skill | What it makes the agent do |
|---|---|
| `patient-case` | Structure the vignette with the NER model first (keeping pertinent negatives), then compute every score the data allows |
| `therapy-evidence` | Guidelines, then SR/MA, then RCTs; effect sizes from the abstract; ARR/NNT via `treatment_effect`; applicability |
| `critical-appraisal` | PICO, RoB 2 / ROBINS-I domains, outcome switching vs the registry, GRADE-style certainty |
| `drug-dosing-safety` | Label first; renal dosing with Cockcroft-Gault (label convention) vs CKD-EPI; Child-Pugh; interactions; FAERS caveats |
| `risk-scores` | Never compute scores in text; report inputs and caveats; check the population fits |
| `diagnostic-reasoning` | Differential including can't-miss diagnoses, numeric pre-test probability, LRs, post-test probability, guideline pathway |
| `trial-matching` | Criterion-by-criterion eligibility table against the extracted case features |
| `guideline-synthesis` | Compare societies with each body's own grading (ACC/AHA class/LOE, GRADE, USPSTF), and check currency |
| `literature-surveillance` | New research triaged into practice-changing, confirmatory, early signal and safety alert |

**How skills are chosen:** before each turn, a deterministic router scores every skill on keyword triggers and on the entity types the NER model found in the question (e.g. a drug name → the dosing skill). The top matches are injected into the system prompt by LangChain `dynamic_prompt` middleware. The agent sees an index of all skills and can call `load_skill` for any other one mid-run (progressive disclosure). The Ask view shows which skills were activated and why.

Add your own (e.g. a local sepsis protocol) by dropping a folder with a `SKILL.md` into a directory and passing it to `SkillRegistry([LIBRARY, Path("my_skills")])`. Later directories override built-in skills of the same name.

```bash
medagent skills                                   # list skills
medagent skills "Which DOAC dose for a 82-year-old woman, 55 kg, creatinine 1.6?"   # see routing
medagent calc cha2ds2_vasc age=78 sex=female hypertension=true diabetes=true
```

## What the previews show

The previews are designed to be scanned the way clinicians read papers:

- **Result cards** start with a level-of-evidence badge (LoE 1 = guideline, systematic review or meta-analysis … LoE 5 = opinion), then the title, journal, year, **sample size** and citation count. Below that is the **authors' conclusion**, so you get the bottom line first. Preprints are marked as not peer reviewed, and retracted papers are flagged in red and ranked last.
- **Evidence mix bar** and **level-of-evidence facets** show at a glance whether a topic has meta-analyses and RCTs or only observational data.
- **Article preview**: a key-facts strip (design, level, n, citations, access), the conclusion in a highlighted box, the structured abstract split into its own sections (Background / Methods / Results / Conclusions), MeSH terms, and one-click links to PubMed, PMC full text, PDF and DOI. It also has **Read here**, which uses TinyFish Fetch to pull the full text inline with the passages most relevant to your query at the top, plus a copy-ready Vancouver citation.
- **Trial preview**: a colour-coded recruitment status, phase, enrolment, start and primary-completion dates, whether results are posted, arms, the primary outcome, eligibility, and a site list by country.
- **Drug view**: the boxed warning is drawn as a black box, as on the FDA label. Indications, dosing and contraindications are open by default. A FAERS bar chart shows the most-reported reactions, with a note that these counts are not incidence.
- **Ask**: a live activity log of each search the agent runs, an answer that streams in, numbered citations you can hover to preview, and a numbered source list.
- **Library**: save papers (press `s`) and export them as RIS or BibTeX, or copy a reference list.
- **Extract PICO & effects** on any article preview: a PICO grid, plus a table of every reported effect estimate with its CI and whether it crosses the null.
- **Calculators**: forms generated from each calculator's schema, results colour-coded by risk band with the inputs used, the reference, and caveats. **Pre-fill from a case**: paste a note and the clinical NLP model fills in the forms, showing negated findings struck through and which calculators are ready.
- Keyboard: `/` search, `j`/`k` move through results, `s` save, `o` open.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env          # add ANTHROPIC_API_KEY and TINYFISH_API_KEY
medagent serve                # http://127.0.0.1:8000
```

The agent uses `anthropic:claude-sonnet-5` by default. Any LangChain `init_chat_model` string works through `MEDAGENT_MODEL`, for example `openai:gpt-5` after `pip install -e ".[openai]"`.

### CLI

```bash
medagent search "tenecteplase acute ischaemic stroke" --from 2019 -d meta_analysis -d rct
medagent new "GLP-1 receptor agonists" --days 14
medagent trials glioblastoma --location "Boston" --recruiting
medagent drug apixaban
medagent ask "Does colchicine reduce cardiovascular events after MI?"
```

### Python

```python
import asyncio
from medagent.harness import ResearchHarness
from medagent.agent import AgentService

async def main():
    async with ResearchHarness() as h:
        bundle = await h.search("SGLT2 inhibitors HFpEF")
        for a in bundle.articles[:5]:
            print(a.evidence_level, a.design.value, a.title, a.bottom_line)

        result = await AgentService(h).ask("What is first-line therapy for HFpEF?")
        print(result["answer"])

asyncio.run(main())
```

## Deploy with Docker

The `Dockerfile` builds a slim image that serves the web app with uvicorn on `$PORT` (default 8000), so it runs as-is on Render, Railway, Fly.io or Cloud Run.

```bash
docker build -t medagent .                          # lean image (~370 MB): rule-based fallbacks for the ML parts
docker build -t medagent --build-arg EXTRAS=nlp .   # + scispaCy NER and NegEx
docker build -t medagent --build-arg EXTRAS=ml .    # + MedCPT and BioELECTRA-PICO (CPU torch; needs 2 GB+ RAM)
docker run --env-file .env -p 8000:8000 medagent
```

**Render:** push the repo, then in the dashboard choose **New → Blueprint** and select it. `render.yaml` sets up a Docker web service with `/api/health` as the health check. Enter `ANTHROPIC_API_KEY`, `TINYFISH_API_KEY` and the other secrets when prompted. You can also create a plain **Web Service** with runtime *Docker* and add the same environment variables. Render passes environment variables to the build as build args, so setting `EXTRAS=nlp` there turns on the NER model.

Watch topics and the reading list are saved in `MEDAGENT_DATA_DIR` (`/app/data` in the image). Container disks are ephemeral, so attach a persistent disk at `/app/data` (on a paid Render plan) if you need them to survive redeploys.

## Architecture

```
medagent/
  providers/      async clients: pubmed, europepmc, openalex, clinicaltrials, openfda, tinyfish
  models.py       normalised Article / Trial / DrugLabel / WebResult records
  evidence.py     study-design classification, level of evidence, sample size, bottom line, de-dup, ranking
  harness.py      ResearchHarness: parallel federated search, "what's new", per-source status and timeouts
  sources.py      per-conversation citation registry ([n] numbers mapped to real records)
  tools.py        LangChain StructuredTools over the harness
  agent.py        create_agent() + system prompt + streaming AgentService (LangGraph checkpointer for follow-ups)
  server.py       FastAPI JSON API + SSE streaming + watchlist + library + export
  web/            the clinician UI (vanilla JS, no build step)
  cli.py          Typer CLI
  ml/             clinical NER, PICO, reranker, calculators, stats, effect-size extraction
  ml_tools.py     function-calling tools over the ML layer
  skills/         skill registry, router, and library/*/SKILL.md playbooks
```

**Agent tools:** `search_literature`, `find_new_research`, `search_clinical_trials`, `get_trial_details`, `drug_label`, `drug_adverse_events`, `get_article`, `search_web` (TinyFish Search: guidelines, regulatory, news, papers), `read_source` (TinyFish Fetch), plus the ML tools above and `load_skill`.

**Keeping citations honest.** Every record a tool returns is given a number in a per-conversation registry, and the model is told to cite only those numbers. The UI resolves each `[n]` back to the stored record, so a citation always points at a source the agent actually retrieved. If one provider fails, the tool returns that as text, and the agent carries on with the other tools.

**Ranking** combines evidence strength (45%), recency (30%), log-scaled citations (15%) and the provider's own relevance order (10%). Retracted papers are pushed to the bottom and preprints get a small penalty.

### HTTP API

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/search` | Federated search `{query, filters, sources}` |
| GET | `/api/new?topic=&days=` | Newest papers, preprints and updated trials |
| GET | `/api/article?id=pmid:…` | One paper with full abstract |
| GET | `/api/trials?condition=&intervention=&location=&recruiting=` | Trial search |
| GET | `/api/trial/{nct}` | One trial |
| GET | `/api/drug/{name}` | FDA label and FAERS summary |
| GET | `/api/web?q=&kind=guidelines` | TinyFish web search |
| POST | `/api/read` | TinyFish fetch `{url, focus}` |
| POST | `/api/ask/stream` | Agent, as server-sent events |
| POST | `/api/ask` | Agent, one JSON response |
| POST | `/api/export` | RIS / BibTeX / Vancouver |
| GET | `/api/calculators`, POST `/api/calculators/{name}` | Calculator catalogue (with JSON schemas) and runs |
| POST | `/api/analyze` | Clinical NER + negation + labs, with calculator pre-fill |
| POST | `/api/appraise` | PICO + effect-size extraction for an abstract |
| POST | `/api/stats/diagnostic`, `/api/stats/effect` | Bayes post-test probability; ARR/NNT |
| GET | `/api/skills` | Skill library |
| GET/POST/DELETE | `/api/watch`, `/api/watch/{id}/digest` | Watched topics |
| GET/POST/DELETE | `/api/library` | Saved papers |

## Tests

```bash
pytest
```

The suite runs offline. Provider HTTP calls are mocked with `respx` using payloads shaped like the real APIs, TinyFish is replaced with a fake that has the SDK's interface, and the agent loop is driven by a scripted chat model. The NER tests run the real scispaCy model when it is installed and are skipped otherwise. The transformer backends are tested through injected fakes of the same interface.

## Limitations

- The level-of-evidence label is an automatic triage aid based on indexed publication types and wording. It is not a GRADE or risk-of-bias appraisal. The UI says so in its footer.
- Sample sizes are pulled from the abstract text with pattern matching and can be wrong for complex designs.
- FAERS counts are spontaneous reports. They do not establish causation or incidence.
- NER, negation and PICO models make mistakes (e.g. the BC5CDR model can miss drug names, and NegEx handles lists and double negatives imperfectly). The agent is told to check boolean calculator inputs against the text, and the UI shows exactly what was extracted.
- Calculators are only as valid as their derivation populations. Each result carries that model's caveats.
- MedAgent supports clinical decision-making. It does not replace clinical judgement, local protocols, or the full source documents.
