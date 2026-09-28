"""PubMed via NCBI E-utilities (free; 3 req/s without a key, 10 req/s with one)."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Literal

import httpx

from ..models import Article, SearchFilters, Section, StudyDesign
from .base import get_json, request, to_int

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

# PubMed publication-type filters for each design the UI lets doctors pick.
DESIGN_FILTERS: dict[StudyDesign, str] = {
    StudyDesign.GUIDELINE: "(guideline[pt] OR practice guideline[pt])",
    StudyDesign.META_ANALYSIS: "meta-analysis[pt]",
    StudyDesign.SYSTEMATIC_REVIEW: "systematic review[pt]",
    StudyDesign.RCT: "randomized controlled trial[pt]",
    StudyDesign.CLINICAL_TRIAL: "clinical trial[pt]",
    StudyDesign.COHORT: "(observational study[pt] OR cohort studies[mh])",
    StudyDesign.CASE_CONTROL: "case-control studies[mh]",
    StudyDesign.CROSS_SECTIONAL: "cross-sectional studies[mh]",
    StudyDesign.CASE_REPORT: "case reports[pt]",
    StudyDesign.NARRATIVE_REVIEW: "review[pt]",
}


def build_term(query: str, filters: SearchFilters | None = None) -> str:
    term = f"({query})"
    if not filters:
        return term
    if filters.year_from or filters.year_to:
        start = filters.year_from or 1800
        end = filters.year_to or 3000
        term += f' AND ("{start}"[dp] : "{end}"[dp])'
    design_terms = [DESIGN_FILTERS[d] for d in filters.designs if d in DESIGN_FILTERS]
    if design_terms:
        term += " AND (" + " OR ".join(design_terms) + ")"
    if filters.open_access_only:
        term += " AND free full text[sb]"
    return term


class PubMedClient:
    name = "pubmed"

    def __init__(self, client: httpx.AsyncClient, api_key: str | None = None, email: str | None = None, tool: str = "medagent"):
        self._client = client
        self._common: dict[str, str] = {"tool": tool}
        if api_key:
            self._common["api_key"] = api_key
        if email:
            self._common["email"] = email

    async def search_ids(
        self,
        query: str,
        *,
        filters: SearchFilters | None = None,
        limit: int = 20,
        sort: Literal["relevance", "pub_date"] = "relevance",
        days: int | None = None,
    ) -> tuple[list[str], int]:
        params: dict[str, str | int] = {
            **self._common,
            "db": "pubmed",
            "term": build_term(query, filters),
            "retmode": "json",
            "retmax": limit,
            "sort": sort,
        }
        if days:
            # Entrez date = when the record entered PubMed: the right clock for "what's new".
            params.update({"reldate": days, "datetype": "edat"})
        data = await get_json(self._client, f"{EUTILS}/esearch.fcgi", params=params, provider=self.name)
        result = data.get("esearchresult", {})
        return list(result.get("idlist", [])), int(result.get("count", 0) or 0)

    async def fetch(self, pmids: list[str]) -> list[Article]:
        if not pmids:
            return []
        params = {**self._common, "db": "pubmed", "id": ",".join(pmids), "retmode": "xml"}
        response = await request(self._client, "GET", f"{EUTILS}/efetch.fcgi", params=params, provider=self.name)
        articles = parse_pubmed_xml(response.text)
        order = {pmid: i for i, pmid in enumerate(pmids)}
        articles.sort(key=lambda a: order.get(a.pmid or "", 1_000_000))
        for i, art in enumerate(articles):
            art.score = 1 - i / max(len(articles), 1)
        return articles

    async def search(self, query: str, *, filters: SearchFilters | None = None, limit: int = 20,
                     sort: Literal["relevance", "pub_date"] = "relevance", days: int | None = None) -> list[Article]:
        ids, _ = await self.search_ids(query, filters=filters, limit=limit, sort=sort, days=days)
        return await self.fetch(ids)


def _text(el: ET.Element | None) -> str:
    return " ".join("".join(el.itertext()).split()) if el is not None else ""


def parse_pubmed_xml(xml_text: str) -> list[Article]:
    root = ET.fromstring(xml_text)
    articles: list[Article] = []
    for node in root.iter("PubmedArticle"):
        citation = node.find("MedlineCitation")
        if citation is None:
            continue
        pmid = _text(citation.find("PMID"))
        art = citation.find("Article")
        if art is None:
            continue
        title = _text(art.find("ArticleTitle")).rstrip(".") or "(untitled)"

        sections: list[Section] = []
        parts: list[str] = []
        for abstract_text in art.findall("Abstract/AbstractText"):
            text = _text(abstract_text)
            if not text:
                continue
            label = abstract_text.get("Label") or abstract_text.get("NlmCategory")
            if label:
                sections.append(Section(label=label.title(), text=text))
                parts.append(f"{label.upper()}: {text}")
            else:
                parts.append(text)

        authors: list[str] = []
        for author in art.findall("AuthorList/Author"):
            collective = author.findtext("CollectiveName")
            if collective:
                authors.append(collective)
                continue
            last = author.findtext("LastName")
            initials = author.findtext("Initials") or ""
            if last:
                authors.append(f"{last} {initials}".strip())

        journal = art.find("Journal")
        journal_name = None
        year = None
        pub_date = None
        if journal is not None:
            journal_name = journal.findtext("ISOAbbreviation") or journal.findtext("Title")
            pd = journal.find("JournalIssue/PubDate")
            if pd is not None:
                year = to_int(pd.findtext("Year")) or to_int((pd.findtext("MedlineDate") or "")[:4])
                pub_date = " ".join(x for x in (pd.findtext("Year"), pd.findtext("Month"), pd.findtext("Day")) if x) or pd.findtext("MedlineDate")
        article_date = art.find("ArticleDate")
        if article_date is not None:
            y, m, d = (article_date.findtext(k) for k in ("Year", "Month", "Day"))
            if y and m and d:
                pub_date = f"{y}-{m.zfill(2)}-{d.zfill(2)}"
                year = year or to_int(y)

        pub_types = [_text(pt) for pt in art.findall("PublicationTypeList/PublicationType")]
        mesh = [_text(m.find("DescriptorName")) for m in citation.findall("MeshHeadingList/MeshHeading")]
        keywords = [_text(k) for k in citation.findall("KeywordList/Keyword")]

        doi = pmcid = None
        for aid in node.findall("PubmedData/ArticleIdList/ArticleId"):
            kind = aid.get("IdType")
            if kind == "doi":
                doi = _text(aid)
            elif kind == "pmc":
                pmcid = _text(aid)
        if doi is None:
            for eloc in art.findall("ELocationID"):
                if eloc.get("EIdType") == "doi":
                    doi = _text(eloc)

        retracted = any(t.lower() in ("retracted publication", "retraction of publication") for t in pub_types)
        articles.append(Article(
            id=f"pmid:{pmid}",
            source="pubmed",
            title=title,
            authors=authors,
            journal=journal_name,
            year=year,
            pub_date=pub_date,
            doi=doi,
            pmid=pmid,
            pmcid=pmcid,
            url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            abstract="\n".join(parts) or None,
            sections=sections,
            publication_types=pub_types,
            mesh_terms=[m for m in mesh if m],
            keywords=[k for k in keywords if k],
            open_access=pmcid is not None,
            is_retracted=retracted,
        ))
    return articles
