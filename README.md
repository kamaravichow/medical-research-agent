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

## What the previews show

The previews are designed to be scanned the way clinicians read papers:

- **Result cards** start with a level-of-evidence badge (LoE 1 = guideline, systematic review or meta-analysis … LoE 5 = opinion), then the title, journal, year, **sample size** and citation count. Below that is the **authors' conclusion**, so you get the bottom line first. Preprints are marked as not peer reviewed, and retracted papers are flagged in red and ranked last.
- **Evidence mix bar** and **level-of-evidence facets** show at a glance whether a topic has meta-analyses and RCTs or only observational data.
- **Article preview**: a key-facts strip (design, level, n, citations, access), the conclusion in a highlighted box, the structured abstract split into its own sections (Background / Methods / Results / Conclusions), MeSH terms, and one-click links to PubMed, PMC full text, PDF and DOI. It also has **Read here**, which uses TinyFish Fetch to pull the full text inline with the passages most relevant to your query at the top, plus a copy-ready Vancouver citation.
- **Trial preview**: a colour-coded recruitment status, phase, enrolment, start and primary-completion dates, whether results are posted, arms, the primary outcome, eligibility, and a site list by country.
- **Drug view**: the boxed warning is drawn as a black box, as on the FDA label. Indications, dosing and contraindications are open by default. A FAERS bar chart shows the most-reported reactions, with a note that these counts are not incidence.
- **Ask**: a live activity log of each search the agent runs, an answer that streams in, numbered citations you can hover to preview, and a numbered source list.
- **Library**: save papers (press `s`) and export them as RIS or BibTeX, or copy a reference list.
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
```

**Agent tools:** `search_literature`, `find_new_research`, `search_clinical_trials`, `get_trial_details`, `drug_label`, `drug_adverse_events`, `get_article`, `search_web` (TinyFish Search: guidelines, regulatory, news, papers), `read_source` (TinyFish Fetch).

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
| GET/POST/DELETE | `/api/watch`, `/api/watch/{id}/digest` | Watched topics |
| GET/POST/DELETE | `/api/library` | Saved papers |

## Tests

```bash
pytest
```

The suite runs offline. Provider HTTP calls are mocked with `respx` using payloads shaped like the real APIs, TinyFish is replaced with a fake that has the SDK's interface, and the agent loop is driven by a scripted chat model.

## Limitations

- The level-of-evidence label is an automatic triage aid based on indexed publication types and wording. It is not a GRADE or risk-of-bias appraisal. The UI says so in its footer.
- Sample sizes are pulled from the abstract text with pattern matching and can be wrong for complex designs.
- FAERS counts are spontaneous reports. They do not establish causation or incidence.
- MedAgent supports clinical decision-making. It does not replace clinical judgement, local protocols, or the full source documents.
