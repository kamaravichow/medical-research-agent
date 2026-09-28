"""ResearchHarness: one object that owns every provider client.

The web app, the CLI and the LangChain tools all go through this class, so a
search from the UI, the command line or the agent returns the same ranked,
de-duplicated, evidence-graded records.
"""

from __future__ import annotations

import asyncio
import time
from collections import Counter
from datetime import date, timedelta
from typing import Awaitable, Iterable

from . import evidence
from .config import Settings, get_settings
from .models import (
    AdverseEventSummary,
    Article,
    DrugLabel,
    FetchedPage,
    ProviderStatus,
    SearchBundle,
    SearchFilters,
    Trial,
    WebResult,
)
from .providers import (
    ClinicalTrialsClient,
    EuropePMCClient,
    OpenAlexClient,
    OpenFDAClient,
    ProviderError,
    PubMedClient,
    TinyFishClient,
    make_client,
)
from .providers.tinyfish import TinyFishNotConfigured

ARTICLE_SOURCES = ("pubmed", "europepmc", "openalex")
ALL_SOURCES = ARTICLE_SOURCES + ("clinicaltrials", "guidelines")


class ResearchHarness:
    def __init__(self, settings: Settings | None = None, *, tinyfish_client=None):
        self.settings = settings or get_settings()
        self.http = make_client(self.settings.http_timeout)
        s = self.settings
        self.pubmed = PubMedClient(self.http, api_key=s.ncbi_api_key, email=s.ncbi_email, tool=s.tool)
        self.europepmc = EuropePMCClient(self.http)
        self.openalex = OpenAlexClient(self.http, email=s.ncbi_email)
        self.trials_api = ClinicalTrialsClient(self.http)
        self.openfda = OpenFDAClient(self.http, api_key=s.openfda_api_key)
        self.tinyfish = TinyFishClient(s.tinyfish_api_key, client=tinyfish_client)

    async def aclose(self) -> None:
        await self.http.aclose()

    async def __aenter__(self) -> "ResearchHarness":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()

    # ------------------------------------------------------------------ utils
    @staticmethod
    async def _timed(name: str, coro: Awaitable, statuses: list[ProviderStatus], timeout: float = 25.0):
        start = time.perf_counter()
        try:
            result = await asyncio.wait_for(coro, timeout)
        except (ProviderError, TinyFishNotConfigured, ValueError) as exc:
            statuses.append(ProviderStatus(provider=name, ok=False, ms=_ms(start), error=str(exc)))
            return None
        except asyncio.TimeoutError:
            statuses.append(ProviderStatus(provider=name, ok=False, ms=_ms(start), error="timed out"))
            return None
        except Exception as exc:  # a provider bug must not sink the whole search
            statuses.append(ProviderStatus(provider=name, ok=False, ms=_ms(start), error=f"{exc.__class__.__name__}: {exc}"))
            return None
        statuses.append(ProviderStatus(provider=name, ok=True, ms=_ms(start), count=len(result) if hasattr(result, "__len__") else 1))
        return result

    async def _enrich_citations(self, articles: list[Article]) -> None:
        missing = [a.doi for a in articles if a.doi and a.cited_by is None][:50]
        if not missing:
            return
        try:
            counts = await asyncio.wait_for(self.openalex.citation_counts(missing), 8)
        except Exception:
            return
        for art in articles:
            if art.doi and art.cited_by is None:
                art.cited_by = counts.get(art.doi.lower())

    @staticmethod
    def _apply_filters(articles: Iterable[Article], filters: SearchFilters) -> list[Article]:
        out = []
        for a in articles:
            if filters.year_from and a.year and a.year < filters.year_from:
                continue
            if filters.year_to and a.year and a.year > filters.year_to:
                continue
            if filters.designs and a.design not in filters.designs:
                continue
            if filters.open_access_only and not a.open_access:
                continue
            if not filters.include_preprints and a.is_preprint:
                continue
            out.append(a)
        return out

    # ----------------------------------------------------------------- search
    async def search(
        self,
        query: str,
        filters: SearchFilters | None = None,
        sources: Iterable[str] = ALL_SOURCES,
    ) -> SearchBundle:
        """Federated search: fan out to every source at once, merge, grade and rank."""
        filters = filters or SearchFilters()
        sources = set(sources)
        per_source = min(filters.max_results, 40)
        statuses: list[ProviderStatus] = []
        tasks: dict[str, Awaitable] = {}
        if "pubmed" in sources:
            tasks["pubmed"] = self._timed("pubmed", self.pubmed.search(query, filters=filters, limit=per_source), statuses)
        if "europepmc" in sources:
            tasks["europepmc"] = self._timed("europepmc", self.europepmc.search(query, filters=filters, limit=per_source), statuses)
        if "openalex" in sources:
            tasks["openalex"] = self._timed("openalex", self.openalex.search(query, filters=filters, limit=min(per_source, 20)), statuses)
        if "clinicaltrials" in sources:
            tasks["clinicaltrials"] = self._timed("clinicaltrials", self.trials_api.search(term=query, limit=8), statuses)
        if "guidelines" in sources and self.tinyfish.enabled:
            tasks["guidelines"] = self._timed("tinyfish", self.tinyfish.search(query, kind="guidelines", limit=8), statuses)

        results = dict(zip(tasks, await asyncio.gather(*tasks.values())))
        articles: list[Article] = []
        for name in ARTICLE_SOURCES:
            articles.extend(results.get(name) or [])
        merged = [evidence.annotate(a) for a in evidence.dedupe(articles)]
        merged = self._apply_filters(merged, filters)
        await self._enrich_citations(merged)
        ranked = evidence.rank(merged)[: filters.max_results]
        counts = Counter(a.design.value for a in ranked)
        return SearchBundle(
            query=query,
            articles=ranked,
            trials=results.get("clinicaltrials") or [],
            web=[w for w in (results.get("guidelines") or []) if isinstance(w, WebResult)],
            providers=statuses,
            evidence_counts=dict(counts),
        )

    async def whats_new(self, topic: str, days: int = 30, limit: int = 30, include_news: bool = True) -> SearchBundle:
        """Newest research on a topic: freshly indexed PubMed records, preprints and news."""
        statuses: list[ProviderStatus] = []
        since = (date.today() - timedelta(days=days)).isoformat()
        tasks = {
            "pubmed": self._timed("pubmed", self.pubmed.search(topic, limit=limit, sort="pub_date", days=days), statuses),
            "europepmc": self._timed("europepmc", self.europepmc.search(topic, limit=limit, sort="date", since=since), statuses),
            "trials": self._timed("clinicaltrials", self.trials_api.search(term=topic, limit=10, sort_recent=True), statuses),
        }
        if include_news and self.tinyfish.enabled:
            tasks["news"] = self._timed("tinyfish", self.tinyfish.search(f"{topic} study", kind="news", days=days, limit=8), statuses)
        results = dict(zip(tasks, await asyncio.gather(*tasks.values())))
        articles = [evidence.annotate(a) for a in evidence.dedupe((results.get("pubmed") or []) + (results.get("europepmc") or []))]
        articles.sort(key=lambda a: (a.pub_date or str(a.year or "")), reverse=True)
        cutoff = since
        trials = [t for t in (results.get("trials") or []) if (t.last_update or "") >= cutoff[:7]]
        return SearchBundle(
            query=topic,
            articles=articles[:limit],
            trials=trials,
            web=[w for w in (results.get("news") or []) if isinstance(w, WebResult)],
            providers=statuses,
            evidence_counts=dict(Counter(a.design.value for a in articles[:limit])),
        )

    # ------------------------------------------------------------ one-offs
    async def article(self, key: str) -> Article | None:
        """Look up a single paper by 'pmid:…', bare PMID, or 'doi:…'."""
        key = key.strip()
        if key.lower().startswith("pmid:") or key.isdigit():
            pmid = key.split(":", 1)[-1]
            found = await self.pubmed.fetch([pmid])
        else:
            doi = key.split(":", 1)[-1] if key.lower().startswith("doi:") else key
            found = await self.europepmc.search(f'DOI:"{doi}"', limit=1)
        if not found:
            return None
        art = evidence.annotate(found[0])
        await self._enrich_citations([art])
        return art

    async def trials(self, **kwargs) -> list[Trial]:
        return await self.trials_api.search(**kwargs)

    async def trial(self, nct_id: str) -> Trial:
        return await self.trials_api.get(nct_id)

    async def drug(self, name: str) -> tuple[DrugLabel | None, AdverseEventSummary | None, list[ProviderStatus]]:
        statuses: list[ProviderStatus] = []
        labels, events = await asyncio.gather(
            self._timed("openfda-label", self.openfda.label(name), statuses),
            self._timed("openfda-faers", self.openfda.adverse_events(name), statuses),
        )
        return (labels[0] if labels else None), events, statuses

    async def web(self, query: str, kind: str = "web", days: int | None = None, limit: int = 10) -> list[WebResult | Article]:
        results = await self.tinyfish.search(query, kind=kind, days=days, limit=limit)  # type: ignore[arg-type]
        return [evidence.annotate(r) if isinstance(r, Article) else r for r in results]

    async def read(self, urls: list[str], focus: str | None = None, max_chars: int = 12000) -> list[FetchedPage]:
        return await self.tinyfish.fetch(urls, focus=focus, max_chars=max_chars)


def _ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)
