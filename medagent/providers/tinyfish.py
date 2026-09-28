"""TinyFish Search + Fetch: the agent's window onto the open web.

Used for what the bibliographic APIs don't index well: clinical practice
guidelines (NICE, USPSTF, WHO, specialty societies), regulatory notices, medical
news, and full-text reading of any page or open-access article.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Literal
from urllib.parse import urlparse

from ..models import Article, FetchedPage, WebResult

# Publishers doctors treat as authoritative, grouped into the tier shown on the card.
AUTHORITY_TIERS: dict[str, str] = {
    # Guideline / public-health bodies
    "who.int": "Guideline body",
    "nice.org.uk": "Guideline body",
    "cdc.gov": "Guideline body",
    "uspreventiveservicestaskforce.org": "Guideline body",
    "sign.ac.uk": "Guideline body",
    "nhs.uk": "Guideline body",
    "ecdc.europa.eu": "Guideline body",
    "canada.ca": "Guideline body",
    "nhmrc.gov.au": "Guideline body",
    "idsociety.org": "Specialty society",
    "acc.org": "Specialty society",
    "heart.org": "Specialty society",
    "escardio.org": "Specialty society",
    "diabetesjournals.org": "Specialty society",
    "kdigo.org": "Specialty society",
    "ginasthma.org": "Specialty society",
    "goldcopd.org": "Specialty society",
    "nccn.org": "Specialty society",
    "asco.org": "Specialty society",
    "esmo.org": "Specialty society",
    "acog.org": "Specialty society",
    "aap.org": "Specialty society",
    "aafp.org": "Specialty society",
    "thoracic.org": "Specialty society",
    "gastro.org": "Specialty society",
    "rheumatology.org": "Specialty society",
    "eular.org": "Specialty society",
    "aan.com": "Specialty society",
    "psychiatry.org": "Specialty society",
    "cochranelibrary.com": "Evidence synthesis",
    # Regulators
    "fda.gov": "Regulator",
    "ema.europa.eu": "Regulator",
    "mhra.gov.uk": "Regulator",
    # Government / reference
    "nih.gov": "Government / NIH",
    "medlineplus.gov": "Government / NIH",
    # Major journals
    "nejm.org": "Major journal",
    "thelancet.com": "Major journal",
    "jamanetwork.com": "Major journal",
    "bmj.com": "Major journal",
    "annals.org": "Major journal",
    "nature.com": "Major journal",
    "ahajournals.org": "Major journal",
    "medrxiv.org": "Preprint server",
    "biorxiv.org": "Preprint server",
}

GUIDELINE_DOMAINS = [d for d, tier in AUTHORITY_TIERS.items() if tier in ("Guideline body", "Specialty society", "Evidence synthesis")]
REGULATOR_DOMAINS = [d for d, tier in AUTHORITY_TIERS.items() if tier == "Regulator"]
LOW_QUALITY_DOMAINS = ["pinterest.com", "quora.com", "reddit.com", "facebook.com", "tiktok.com", "youtube.com"]

SearchKind = Literal["web", "guidelines", "news", "papers", "regulatory"]


def site_of(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def authority_for(url: str) -> str | None:
    host = site_of(url)
    for domain, tier in AUTHORITY_TIERS.items():
        if host == domain or host.endswith("." + domain):
            return tier
    return None


class TinyFishNotConfigured(RuntimeError):
    pass


class TinyFishClient:
    name = "tinyfish"

    def __init__(self, api_key: str | None, *, client=None):
        self._api_key = api_key
        self._client = client  # injectable for tests

    @property
    def enabled(self) -> bool:
        return bool(self._api_key) or self._client is not None

    def _sdk(self):
        if self._client is None:
            if not self._api_key:
                raise TinyFishNotConfigured("TINYFISH_API_KEY is not set; web search and page fetch are disabled.")
            from tinyfish import AsyncTinyFish

            self._client = AsyncTinyFish(api_key=self._api_key, timeout=60.0, max_retries=2)
        return self._client

    async def search(
        self,
        query: str,
        *,
        kind: SearchKind = "web",
        days: int | None = None,
        year_from: int | None = None,
        include_domains: list[str] | None = None,
        limit: int = 10,
    ) -> list[WebResult | Article]:
        sdk = self._sdk()
        kwargs: dict = {
            "purpose": "Clinician looking for trustworthy, current medical evidence and guidance.",
        }
        domain_type = {"news": "news", "papers": "research_paper"}.get(kind, "web")
        kwargs["domain_type"] = domain_type
        if include_domains:
            kwargs["include_domains"] = ",".join(include_domains)
        elif kind == "guidelines":
            kwargs["include_domains"] = ",".join(GUIDELINE_DOMAINS)
        elif kind == "regulatory":
            kwargs["include_domains"] = ",".join(REGULATOR_DOMAINS)
        else:
            kwargs["exclude_domains"] = ",".join(LOW_QUALITY_DOMAINS)
        if days:
            kwargs["after_date"] = (date.today() - timedelta(days=days)).isoformat()
        if year_from and domain_type == "research_paper":
            kwargs["pub_year_min"] = year_from
        if kind == "guidelines" and "guideline" not in query.lower():
            query = f"{query} guideline recommendations"

        response = await sdk.search.query(query, **kwargs)
        out: list[WebResult | Article] = []
        for r in response.results[:limit]:
            if domain_type == "research_paper":
                out.append(Article(
                    id=f"web:{r.url}",
                    source="tinyfish",
                    title=r.title,
                    authors=r.authors or [],
                    journal=r.venue or r.publisher,
                    year=r.year,
                    pub_date=r.date,
                    url=r.url,
                    pdf_url=r.pdf_url,
                    abstract=r.snippet,
                    cited_by=r.cited_by_count,
                    open_access=bool(r.pdf_url),
                    is_preprint=any(p in site_of(r.url) for p in ("medrxiv", "biorxiv", "arxiv", "researchsquare", "ssrn")),
                    score=1 - (r.position - 1) / max(len(response.results), 1),
                ))
            else:
                out.append(WebResult(
                    id=f"web:{r.url}",
                    title=r.title,
                    url=r.url,
                    site=r.site_name or site_of(r.url),
                    snippet=r.snippet,
                    date=r.date,
                    authority=authority_for(r.url),
                    kind="guideline" if kind == "guidelines" else ("news" if kind == "news" else kind),
                ))
        return out

    async def fetch(self, urls: list[str], *, focus: str | None = None, max_chars: int = 12000) -> list[FetchedPage]:
        """Fetch clean markdown for up to 10 URLs; `focus` requests query-ranked highlights."""
        from tinyfish import PermissionDeniedError

        sdk = self._sdk()
        urls = urls[:10]
        kwargs: dict = {"format": "markdown", "purpose": "Read medical content to answer a clinician's question."}
        if focus:
            kwargs["highlights"] = {"query": focus, "max_snippets": 6, "include_full_page_text": True}
        try:
            response = await sdk.fetch.get_contents(urls, **kwargs)
        except PermissionDeniedError:
            # Highlights is a beta feature; accounts without it still get the full text.
            kwargs.pop("highlights", None)
            response = await sdk.fetch.get_contents(urls, **kwargs)
        pages = [
            FetchedPage(
                url=r.url,
                final_url=r.final_url,
                title=r.title,
                description=r.description,
                published_date=r.published_date,
                author=r.author,
                text=(r.text or "")[:max_chars] or None,
                highlights=[h.text for h in sorted(r.highlights or [], key=lambda h: h.rank)],
            )
            for r in response.results
        ]
        pages += [FetchedPage(url=e.url, error=e.error) for e in response.errors]
        return pages
