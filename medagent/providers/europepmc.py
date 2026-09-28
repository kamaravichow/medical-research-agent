"""Europe PMC REST API (free, no key). Adds preprints (medRxiv/bioRxiv/Research
Square), PMC full-text links and citation counts on top of MEDLINE."""

from __future__ import annotations

import re
from typing import Any, Literal

import httpx

from ..models import Article, SearchFilters, Section, StudyDesign
from .base import get_json, strip_tags, to_int

BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest"

DESIGN_FILTERS: dict[StudyDesign, str] = {
    StudyDesign.GUIDELINE: 'PUB_TYPE:"guideline"',
    StudyDesign.META_ANALYSIS: 'PUB_TYPE:"meta-analysis"',
    StudyDesign.SYSTEMATIC_REVIEW: 'PUB_TYPE:"systematic-review"',
    StudyDesign.RCT: 'PUB_TYPE:"randomized controlled trial"',
    StudyDesign.CLINICAL_TRIAL: 'PUB_TYPE:"clinical trial"',
    StudyDesign.CASE_REPORT: 'PUB_TYPE:"case reports"',
    StudyDesign.NARRATIVE_REVIEW: 'PUB_TYPE:"review"',
    StudyDesign.PREPRINT: "SRC:PPR",
}


def build_query(query: str, filters: SearchFilters | None = None, *, preprints_only: bool = False,
                since: str | None = None) -> str:
    q = f"({query})"
    if filters:
        if filters.year_from or filters.year_to:
            q += f" AND PUB_YEAR:[{filters.year_from or 1800} TO {filters.year_to or 3000}]"
        design_terms = [DESIGN_FILTERS[d] for d in filters.designs if d in DESIGN_FILTERS]
        if design_terms:
            q += " AND (" + " OR ".join(design_terms) + ")"
        if filters.open_access_only:
            q += " AND OPEN_ACCESS:y"
        if not filters.include_preprints and not preprints_only:
            q += " NOT SRC:PPR"
    if preprints_only:
        q += " AND SRC:PPR"
    if since:
        q += f" AND FIRST_PDATE:[{since} TO 3000-12-31]"
    return q


_H = re.compile(r"<h\d>(.*?)</h\d>", re.I | re.S)


def parse_sections(abstract_html: str | None) -> list[Section]:
    """Europe PMC marks structured-abstract headings with <h4> tags."""
    if not abstract_html or not _H.search(abstract_html):
        return []
    pieces = _H.split(abstract_html)
    sections: list[Section] = []
    # pieces = [preamble, label1, text1, label2, text2, ...]
    for label, body in zip(pieces[1::2], pieces[2::2]):
        text = strip_tags(body)
        clean_label = (strip_tags(label) or "").rstrip(":").title()
        if text and clean_label:
            sections.append(Section(label=clean_label, text=text))
    return sections


def to_article(item: dict[str, Any], rank: int, total: int) -> Article:
    source = item.get("source", "")
    pmid = item.get("pmid")
    doi = item.get("doi")
    ext_id = item.get("id")
    is_preprint = source == "PPR"
    url = None
    pdf_url = None
    for ft in (item.get("fullTextUrlList") or {}).get("fullTextUrl", []):
        style = ft.get("documentStyle")
        if style == "pdf" and ft.get("availabilityCode") in ("OA", "F") and not pdf_url:
            pdf_url = ft.get("url")
        if style == "html" and not url:
            url = ft.get("url")
    if pmid:
        url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
    elif not url:
        url = f"https://europepmc.org/article/{source}/{ext_id}" if source and ext_id else (f"https://doi.org/{doi}" if doi else None)
    journal = ((item.get("journalInfo") or {}).get("journal") or {}).get("isoabbreviation") \
        or ((item.get("journalInfo") or {}).get("journal") or {}).get("title") \
        or item.get("journalTitle")
    if is_preprint:
        journal = (item.get("bookOrReportDetails") or {}).get("publisher") or item.get("publisher") or journal or "Preprint"
    abstract_html = item.get("abstractText")
    sections = parse_sections(abstract_html)
    pub_types = list((item.get("pubTypeList") or {}).get("pubType", []))
    if is_preprint and "Preprint" not in pub_types:
        pub_types.append("Preprint")
    mesh = [m.get("descriptorName") for m in (item.get("meshHeadingList") or {}).get("meshHeading", []) if m.get("descriptorName")]
    authors = [a.get("fullName") for a in (item.get("authorList") or {}).get("author", []) if a.get("fullName")]
    if not authors and item.get("authorString"):
        authors = [a.strip() for a in item["authorString"].rstrip(".").split(",") if a.strip()]
    art_id = f"pmid:{pmid}" if pmid else (f"doi:{doi.lower()}" if doi else f"epmc:{source}:{ext_id}")
    return Article(
        id=art_id,
        source="europepmc",
        title=(strip_tags(item.get("title")) or "(untitled)").rstrip("."),
        authors=authors,
        journal=journal,
        year=to_int(item.get("pubYear")),
        pub_date=item.get("firstPublicationDate"),
        doi=doi,
        pmid=pmid,
        pmcid=item.get("pmcid"),
        url=url,
        pdf_url=pdf_url,
        abstract=strip_tags(abstract_html),
        sections=sections,
        publication_types=pub_types,
        mesh_terms=mesh,
        keywords=list((item.get("keywordList") or {}).get("keyword", [])),
        open_access=item.get("isOpenAccess") == "Y",
        is_preprint=is_preprint,
        is_retracted="retracted publication" in [p.lower() for p in pub_types],
        cited_by=item.get("citedByCount"),
        score=1 - rank / max(total, 1),
    )


class EuropePMCClient:
    name = "europepmc"

    def __init__(self, client: httpx.AsyncClient):
        self._client = client

    async def search(
        self,
        query: str,
        *,
        filters: SearchFilters | None = None,
        limit: int = 20,
        sort: Literal["relevance", "date", "cited"] = "relevance",
        preprints_only: bool = False,
        since: str | None = None,
    ) -> list[Article]:
        params: dict[str, Any] = {
            "query": build_query(query, filters, preprints_only=preprints_only, since=since),
            "format": "json",
            "resultType": "core",
            "pageSize": min(limit, 100),
        }
        if sort == "date":
            params["sort"] = "P_PDATE_D desc"
        elif sort == "cited":
            params["sort"] = "CITED desc"
        data = await get_json(self._client, f"{BASE}/search", params=params, provider=self.name)
        items = (data.get("resultList") or {}).get("result", [])
        return [to_article(item, i, len(items)) for i, item in enumerate(items)]
