"""OpenAlex (free, no key): broad scholarly index used for citation counts and
as a third search source for papers outside MEDLINE."""

from __future__ import annotations

from typing import Any

import httpx

from ..models import Article, SearchFilters
from .base import get_json

BASE = "https://api.openalex.org"


def rebuild_abstract(inverted: dict[str, list[int]] | None) -> str | None:
    if not inverted:
        return None
    positions: list[tuple[int, str]] = [(pos, word) for word, locs in inverted.items() for pos in locs]
    return " ".join(word for _, word in sorted(positions)) or None


def to_article(work: dict[str, Any], rank: int, total: int) -> Article:
    doi = (work.get("doi") or "").replace("https://doi.org/", "") or None
    ids = work.get("ids") or {}
    pmid = (ids.get("pmid") or "").rstrip("/").rsplit("/", 1)[-1] or None
    pmcid = (ids.get("pmcid") or "").rstrip("/").rsplit("/", 1)[-1] or None
    location = work.get("primary_location") or {}
    source = location.get("source") or {}
    oa = work.get("open_access") or {}
    work_type = (work.get("type") or "").lower()
    pub_types = {"review": ["Review"], "preprint": ["Preprint"], "editorial": ["Editorial"], "letter": ["Letter"]}.get(work_type, [])
    best_oa = work.get("best_oa_location") or {}
    return Article(
        id=f"pmid:{pmid}" if pmid else (f"doi:{doi.lower()}" if doi else f"openalex:{work.get('id', '').rsplit('/', 1)[-1]}"),
        source="openalex",
        title=(work.get("display_name") or work.get("title") or "(untitled)").rstrip("."),
        authors=[a["author"]["display_name"] for a in work.get("authorships", [])[:12] if (a.get("author") or {}).get("display_name")],
        journal=source.get("display_name"),
        year=work.get("publication_year"),
        pub_date=work.get("publication_date"),
        doi=doi,
        pmid=pmid,
        pmcid=pmcid,
        url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else (work.get("doi") or location.get("landing_page_url")),
        pdf_url=best_oa.get("pdf_url"),
        abstract=rebuild_abstract(work.get("abstract_inverted_index")),
        publication_types=pub_types,
        keywords=[k.get("display_name") for k in work.get("keywords", []) if k.get("display_name")][:8],
        open_access=bool(oa.get("is_oa")),
        is_preprint=work_type == "preprint",
        is_retracted=bool(work.get("is_retracted")),
        cited_by=work.get("cited_by_count"),
        score=1 - rank / max(total, 1),
    )


class OpenAlexClient:
    name = "openalex"

    def __init__(self, client: httpx.AsyncClient, email: str | None = None):
        self._client = client
        self._email = email

    def _params(self, extra: dict[str, Any]) -> dict[str, Any]:
        if self._email:
            extra["mailto"] = self._email
        return extra

    async def search(self, query: str, *, filters: SearchFilters | None = None, limit: int = 20) -> list[Article]:
        flt = ["type:article|review|preprint"]
        if filters:
            if filters.year_from:
                flt.append(f"from_publication_date:{filters.year_from}-01-01")
            if filters.year_to:
                flt.append(f"to_publication_date:{filters.year_to}-12-31")
            if filters.open_access_only:
                flt.append("is_oa:true")
        params = self._params({"search": query, "filter": ",".join(flt), "per_page": min(limit, 50)})
        data = await get_json(self._client, f"{BASE}/works", params=params, provider=self.name)
        works = data.get("results", [])
        return [to_article(w, i, len(works)) for i, w in enumerate(works)]

    async def citation_counts(self, dois: list[str]) -> dict[str, int]:
        """Look up cited_by_count for up to 50 DOIs in one call."""
        dois = [d.lower() for d in dois if d][:50]
        if not dois:
            return {}
        params = self._params({"filter": "doi:" + "|".join(dois), "per_page": 50, "select": "doi,cited_by_count"})
        data = await get_json(self._client, f"{BASE}/works", params=params, provider=self.name)
        return {
            (w.get("doi") or "").replace("https://doi.org/", "").lower(): int(w.get("cited_by_count") or 0)
            for w in data.get("results", [])
        }
