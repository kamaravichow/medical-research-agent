"""LangChain tools the agent can call. Each returns compact, citation-numbered
text for the model and records the full objects in the SourceRegistry."""

from __future__ import annotations

import re
from typing import Literal

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field
from tinyfish import SDKError as TinyFishSDKError

from .harness import ResearchHarness
from .models import Article, SearchFilters, StudyDesign, WebResult
from .providers.base import ProviderError
from .providers.tinyfish import TinyFishNotConfigured
from .sources import SourceRegistry, brief_article, brief_trial, brief_web


def _clip(text: str | None, n: int) -> str:
    if not text:
        return "—"
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= n else text[:n].rsplit(" ", 1)[0] + "…"


class LiteratureArgs(BaseModel):
    query: str = Field(..., description="PubMed-style query. Use MeSH-friendly terms and AND/OR, e.g. 'SGLT2 inhibitors AND heart failure with preserved ejection fraction'.")
    year_from: int | None = Field(None, description="Earliest publication year.")
    study_designs: list[StudyDesign] = Field(default_factory=list, description="Restrict to designs, e.g. ['meta_analysis','systematic_review','rct','guideline'].")
    open_access_only: bool = False
    include_preprints: bool = True
    max_results: int = Field(12, ge=1, le=30)


class NewResearchArgs(BaseModel):
    topic: str
    days: int = Field(30, ge=1, le=365, description="Look-back window in days.")
    max_results: int = Field(12, ge=1, le=30)


class TrialArgs(BaseModel):
    condition: str | None = Field(None, description="Disease or condition, e.g. 'glioblastoma'.")
    intervention: str | None = Field(None, description="Drug, device or procedure.")
    keywords: str | None = Field(None, description="Other free-text terms.")
    location: str | None = Field(None, description="City, state or country for recruiting sites.")
    recruiting_only: bool = False
    phases: list[Literal["PHASE1", "PHASE2", "PHASE3", "PHASE4", "EARLY_PHASE1"]] = Field(default_factory=list)
    max_results: int = Field(10, ge=1, le=25)


class NctArgs(BaseModel):
    nct_id: str = Field(..., pattern=r"(?i)^NCT\d{8}$")


class DrugArgs(BaseModel):
    drug: str = Field(..., description="Generic or brand name, e.g. 'apixaban'.")


class ArticleArgs(BaseModel):
    identifier: str = Field(..., description="PMID (e.g. '38012345'), 'doi:10.xxxx/…', or a citation number like '[3]'.")


class WebArgs(BaseModel):
    query: str
    kind: Literal["guidelines", "web", "news", "regulatory", "papers"] = Field(
        "guidelines",
        description="guidelines = WHO/NICE/CDC/USPSTF/specialty societies; regulatory = FDA/EMA/MHRA; news = medical news; papers = scholarly web index.",
    )
    days: int | None = Field(None, ge=1, le=3650, description="Only results from the last N days.")
    max_results: int = Field(8, ge=1, le=15)


class ReadArgs(BaseModel):
    target: str = Field(..., description="A URL, or a citation number like '[4]' to read that source's full page.")
    focus: str | None = Field(None, description="What to look for on the page; returns the most relevant passages first.")


def build_tools(harness: ResearchHarness, registry: SourceRegistry) -> list[BaseTool]:
    """Tools bound to one harness and one conversation's citation registry."""

    def register_articles(articles: list[Article]) -> str:
        if not articles:
            return "No matching articles. Try broader terms, synonyms, or drop filters."
        return "\n".join(brief_article(registry.add(a), a) for a in articles)

    async def search_literature(query: str, year_from: int | None = None, study_designs: list[StudyDesign] | None = None,
                                open_access_only: bool = False, include_preprints: bool = True, max_results: int = 12) -> str:
        filters = SearchFilters(year_from=year_from, designs=study_designs or [], open_access_only=open_access_only,
                                include_preprints=include_preprints, max_results=max_results)
        bundle = await harness.search(query, filters, sources=("pubmed", "europepmc", "openalex"))
        failed = [p for p in bundle.providers if not p.ok]
        note = ("\n(Unavailable sources: " + ", ".join(f"{p.provider}: {p.error}" for p in failed) + ")") if failed else ""
        counts = ", ".join(f"{k}={v}" for k, v in sorted(bundle.evidence_counts.items()))
        return f"Ranked by evidence level, recency and citations. Designs: {counts or 'none'}\n" + register_articles(bundle.articles) + note

    async def find_new_research(topic: str, days: int = 30, max_results: int = 12) -> str:
        bundle = await harness.whats_new(topic, days=days, limit=max_results, include_news=False)
        lines = [f"Newest records from the last {days} days (newest first):", register_articles(bundle.articles)]
        if bundle.trials:
            lines.append("Recently updated trials:")
            lines += [brief_trial(registry.add(t), t) for t in bundle.trials[:5]]
        return "\n".join(lines)

    async def search_clinical_trials(condition: str | None = None, intervention: str | None = None, keywords: str | None = None,
                                     location: str | None = None, recruiting_only: bool = False,
                                     phases: list[str] | None = None, max_results: int = 10) -> str:
        trials = await harness.trials(condition=condition, intervention=intervention, term=keywords, location=location,
                                      recruiting_only=recruiting_only, phases=phases or None, limit=max_results)
        if not trials:
            return "No registered trials matched."
        return "\n".join(brief_trial(registry.add(t), t) for t in trials)

    async def get_trial_details(nct_id: str) -> str:
        t = await harness.trial(nct_id)
        n = registry.add(t)
        return (brief_trial(n, t) + f"\n    Summary: {_clip(t.summary, 900)}"
                + f"\n    Eligibility ({t.sex or 'all'}, {t.min_age or '?'}–{t.max_age or '?'}): {_clip(t.eligibility, 1500)}")

    async def drug_label(drug: str) -> str:
        label, _, _ = await harness.drug(drug)
        if not label:
            return f"No FDA label found for '{drug}'. It may be non-US, OTC-monograph, or spelled differently."
        n = registry.add(label)
        name = ", ".join(label.brand_names[:3] or label.generic_names[:1])
        return "\n".join([
            f"[{n}] FDA label: {name} ({', '.join(label.generic_names[:2])}) — {label.manufacturer or '?'}; effective {label.effective_date or '?'}",
            f"    BOXED WARNING: {_clip(label.boxed_warning, 700)}",
            f"    Indications: {_clip(label.indications, 700)}",
            f"    Dosing: {_clip(label.dosage, 900)}",
            f"    Contraindications: {_clip(label.contraindications, 500)}",
            f"    Warnings: {_clip(label.warnings, 700)}",
            f"    Interactions: {_clip(label.interactions, 600)}",
            f"    Specific populations: {_clip(label.pregnancy, 500)}",
        ])

    async def drug_adverse_events(drug: str) -> str:
        summary = (await harness.openfda.adverse_events(drug))
        top = ", ".join(f"{r.term} ({r.count:,})" for r in summary.top_reactions[:15]) or "none"
        return (f"FAERS for {drug}: {summary.total_reports or 0:,} reports ({summary.serious_reports or 0:,} serious).\n"
                f"Most reported reactions: {top}\nCaveat: {summary.caveat}")

    async def get_article(identifier: str) -> str:
        ref = re.fullmatch(r"\[?(\d{1,3})\]?", identifier.strip())
        art: Article | None = None
        if ref and int(ref.group(1)) <= len(registry) and len(identifier.strip()) <= 5:
            record = registry.get(int(ref.group(1)))
            if isinstance(record, Article):
                art = record
                if art.pmid and not art.sections:
                    art = await harness.article(f"pmid:{art.pmid}") or art
        if art is None:
            art = await harness.article(identifier)
        if art is None:
            return f"No article found for {identifier}."
        n = registry.add(art)
        sections = "\n".join(f"    {s.label.upper()}: {s.text}" for s in art.sections) or f"    {art.abstract or 'No abstract available.'}"
        extras = []
        if art.mesh_terms:
            extras.append("MeSH: " + "; ".join(art.mesh_terms[:12]))
        if art.publication_types:
            extras.append("Types: " + "; ".join(art.publication_types))
        return f"{brief_article(n, art)}\n  Full abstract:\n{sections}\n  " + "\n  ".join(extras)

    async def search_web(query: str, kind: str = "guidelines", days: int | None = None, max_results: int = 8) -> str:
        results = await harness.web(query, kind=kind, days=days, limit=max_results)
        if not results:
            return "No web results."
        out = []
        for r in results:
            n = registry.add(r)
            out.append(brief_web(n, r) if isinstance(r, WebResult) else brief_article(n, r))
        return "\n".join(out)

    async def read_source(target: str, focus: str | None = None) -> str:
        url = target.strip()
        ref = re.fullmatch(r"\[?(\d{1,3})\]?", url)
        if ref:
            record = registry.get(int(ref.group(1)))
            if record is None:
                return f"No source {target} in this conversation."
            if isinstance(record, Article):
                url = (f"https://pmc.ncbi.nlm.nih.gov/articles/{record.pmcid}/" if record.pmcid
                       else record.pdf_url or record.url or (f"https://doi.org/{record.doi}" if record.doi else ""))
            else:
                url = getattr(record, "url", "") or ""
        if not url.startswith("http"):
            return "Give a full URL or a citation number."
        pages = await harness.read([url], focus=focus, max_chars=9000)
        page = pages[0] if pages else None
        if page is None or page.error:
            return f"Could not read {url}: {page.error if page else 'no content'}"
        if not ref:
            n = registry.add(WebResult(id=f"web:{url}", title=page.title or url, url=url, site=url.split('/')[2],
                                       snippet=page.description or "", date=page.published_date))
            label = f"[{n}]"
        else:
            label = f"[{ref.group(1)}]"
        body = ("Most relevant passages:\n- " + "\n- ".join(page.highlights) + "\n\n") if page.highlights else ""
        return f"{label} {page.title or url} ({page.published_date or 'undated'})\n{body}Page text:\n{page.text or ''}"

    specs = [
        (search_literature, LiteratureArgs, "search_literature",
         "Federated search of PubMed, Europe PMC (incl. medRxiv/bioRxiv preprints) and OpenAlex. Returns de-duplicated papers graded by "
         "study design / level of evidence (LoE 1 = guideline/SR/MA … 5 = opinion) with the authors' conclusion. Use first for most questions."),
        (find_new_research, NewResearchArgs, "find_new_research",
         "What was published or indexed in the last N days on a topic (PubMed + preprints + recently updated trials), newest first."),
        (search_clinical_trials, TrialArgs, "search_clinical_trials",
         "Search ClinicalTrials.gov for registered studies; filter by condition, intervention, location, phase and recruiting status."),
        (get_trial_details, NctArgs, "get_trial_details", "Full record for one NCT id: summary, eligibility, outcomes, sites."),
        (drug_label, DrugArgs, "drug_label",
         "FDA prescribing label (openFDA/DailyMed): boxed warning, indications, dosing, contraindications, interactions, pregnancy."),
        (drug_adverse_events, DrugArgs, "drug_adverse_events", "Top reported reactions in FDA FAERS for a drug (signal detection only)."),
        (get_article, ArticleArgs, "get_article", "Full structured abstract, MeSH terms and publication types for a PMID, DOI or citation number."),
        (search_web, WebArgs, "search_web",
         "TinyFish web search. Default kind='guidelines' searches guideline bodies and specialty societies; also regulatory notices, news, or papers."),
        (read_source, ReadArgs, "read_source",
         "TinyFish fetch: read the full text of a URL or cited source (open-access full text, guideline pages, label PDFs). Pass `focus` to get the key passages."),
    ]

    tools: list[BaseTool] = []
    for fn, schema, name, description in specs:
        tools.append(StructuredTool.from_function(
            coroutine=_guard(fn), name=name, description=description, args_schema=schema,
        ))
    return tools


def _guard(fn):
    """Turn provider outages into text the model can react to instead of a crashed run."""
    async def wrapper(**kwargs):
        try:
            return await fn(**kwargs)
        except TinyFishNotConfigured as exc:
            return f"Unavailable: {exc} Use search_literature / other tools instead."
        except TinyFishSDKError as exc:
            return f"Web tool error (TinyFish): {exc}. Fall back to the literature tools."
        except (ProviderError, ValueError) as exc:
            return f"Tool error: {exc}. Try again with different parameters or another tool."
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper
