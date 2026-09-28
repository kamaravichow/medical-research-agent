"""Evidence grading, de-duplication and ranking.

The grading is a pragmatic, transparent heuristic in the spirit of the Oxford
CEBM levels (1 = strongest, 5 = weakest). It is driven by indexed publication
types first (PubMed / Europe PMC tag these by hand), then by title/abstract
wording. It is a triage aid for scanning results quickly, not a formal
GRADE/risk-of-bias appraisal, and the UI labels it that way.
"""

from __future__ import annotations

import math
import re
from datetime import date

from .models import Article, StudyDesign

DESIGN_LEVEL: dict[StudyDesign, int] = {
    StudyDesign.GUIDELINE: 1,
    StudyDesign.META_ANALYSIS: 1,
    StudyDesign.SYSTEMATIC_REVIEW: 1,
    StudyDesign.RCT: 2,
    StudyDesign.CLINICAL_TRIAL: 3,
    StudyDesign.COHORT: 3,
    StudyDesign.CASE_CONTROL: 4,
    StudyDesign.CROSS_SECTIONAL: 4,
    StudyDesign.CASE_REPORT: 4,
    StudyDesign.NARRATIVE_REVIEW: 5,
    StudyDesign.OPINION: 5,
    StudyDesign.PREPRINT: 5,
    StudyDesign.OTHER: 5,
}

DESIGN_LABEL: dict[StudyDesign, str] = {
    StudyDesign.GUIDELINE: "Guideline",
    StudyDesign.META_ANALYSIS: "Meta-analysis",
    StudyDesign.SYSTEMATIC_REVIEW: "Systematic review",
    StudyDesign.RCT: "RCT",
    StudyDesign.CLINICAL_TRIAL: "Clinical trial (non-randomised)",
    StudyDesign.COHORT: "Cohort / observational",
    StudyDesign.CASE_CONTROL: "Case-control",
    StudyDesign.CROSS_SECTIONAL: "Cross-sectional",
    StudyDesign.CASE_REPORT: "Case report / series",
    StudyDesign.NARRATIVE_REVIEW: "Narrative review",
    StudyDesign.OPINION: "Editorial / opinion",
    StudyDesign.PREPRINT: "Preprint",
    StudyDesign.OTHER: "Other",
}

# Ordered: first match wins. Matched against lower-cased publication types.
_PUBTYPE_RULES: list[tuple[tuple[str, ...], StudyDesign]] = [
    (("practice guideline", "guideline", "consensus development conference"), StudyDesign.GUIDELINE),
    (("meta-analysis", "network meta-analysis"), StudyDesign.META_ANALYSIS),
    (("systematic review",), StudyDesign.SYSTEMATIC_REVIEW),
    (("randomized controlled trial", "pragmatic clinical trial", "equivalence trial"), StudyDesign.RCT),
    (("clinical trial, phase", "clinical trial", "controlled clinical trial"), StudyDesign.CLINICAL_TRIAL),
    (("observational study", "cohort", "multicenter study", "comparative study", "validation study"), StudyDesign.COHORT),
    (("case-control",), StudyDesign.CASE_CONTROL),
    (("case reports", "case report"), StudyDesign.CASE_REPORT),
    (("preprint",), StudyDesign.PREPRINT),
    (("editorial", "comment", "letter", "news", "interview"), StudyDesign.OPINION),
    (("review",), StudyDesign.NARRATIVE_REVIEW),
]

# Fallback when publication types are missing (web/OpenAlex/preprints).
_TEXT_RULES: list[tuple[re.Pattern[str], StudyDesign]] = [
    (re.compile(r"\b(clinical practice guideline|guideline|consensus statement|recommendations? (from|of) the)\b"), StudyDesign.GUIDELINE),
    (re.compile(r"\b(meta-?analys[ie]s|network meta)\b"), StudyDesign.META_ANALYSIS),
    (re.compile(r"\b(systematic review|umbrella review)\b"), StudyDesign.SYSTEMATIC_REVIEW),
    (re.compile(r"\b(randomi[sz]ed|randomly assigned|double-blind|placebo-controlled)\b"), StudyDesign.RCT),
    (re.compile(r"\b(phase (i{1,3}|[123])|single-arm|open-label trial)\b"), StudyDesign.CLINICAL_TRIAL),
    (re.compile(r"\b(cohort|registry|retrospective|prospective|observational|target trial emulation)\b"), StudyDesign.COHORT),
    (re.compile(r"\bcase-control\b"), StudyDesign.CASE_CONTROL),
    (re.compile(r"\bcross-sectional\b"), StudyDesign.CROSS_SECTIONAL),
    (re.compile(r"\b(case report|case series|we report a|we present a)\b"), StudyDesign.CASE_REPORT),
    (re.compile(r"\b(narrative review|scoping review|state of the art|review of the literature)\b"), StudyDesign.NARRATIVE_REVIEW),
]

_N_PATTERNS = [
    re.compile(r"\b[nN]\s*=\s*(\d{1,3}(?:[,\s]\d{3})+|\d+)"),
    re.compile(
        r"\b(\d{1,3}(?:,\d{3})+|\d{2,7})\s+(?:adult\s+|pediatric\s+|paediatric\s+|eligible\s+|consecutive\s+)?"
        r"(?:patients|participants|subjects|individuals|women|men|children|infants|adults|people|persons|cases)\b"
    ),
    re.compile(r"\b(\d{1,3}(?:,\d{3})+|\d{2,7})\s+(?:randomi[sz]ed|enrolled|included)\b"),
    re.compile(r"\b(?:total of|enrolled|randomi[sz]ed|included)\s+(\d{1,3}(?:,\d{3})+|\d{2,7})\b"),
]

_CONCLUSION_LABELS = ("conclusion", "conclusions", "interpretation", "implications", "summary", "findings")


def classify(article: Article) -> StudyDesign:
    if article.is_preprint and not article.publication_types:
        text_design = _classify_text(article)
        return text_design if text_design is not StudyDesign.OTHER else StudyDesign.PREPRINT
    types = [t.lower() for t in article.publication_types]
    for needles, design in _PUBTYPE_RULES:
        if any(needle in t for t in types for needle in needles):
            # "Review" is often co-tagged with SR/MA; the text can still upgrade it.
            if design is StudyDesign.NARRATIVE_REVIEW:
                text_design = _classify_text(article)
                if text_design in (StudyDesign.SYSTEMATIC_REVIEW, StudyDesign.META_ANALYSIS, StudyDesign.GUIDELINE):
                    return text_design
            return design
    return _classify_text(article)


def _classify_text(article: Article) -> StudyDesign:
    # Title is the strongest signal; abstract methods second.
    title = (article.title or "").lower()
    for pattern, design in _TEXT_RULES:
        if pattern.search(title):
            return design
    body = (article.abstract or "").lower()[:1500]
    for pattern, design in _TEXT_RULES:
        if design is StudyDesign.GUIDELINE:
            continue  # "guideline" in an abstract body is usually a citation, not the paper type
        if pattern.search(body):
            return design
    return StudyDesign.PREPRINT if article.is_preprint else StudyDesign.OTHER


def extract_sample_size(text: str | None) -> int | None:
    if not text:
        return None
    best: int | None = None
    for pattern in _N_PATTERNS:
        for match in pattern.finditer(text):
            try:
                value = int(re.sub(r"[,\s]", "", match.group(1)))
            except ValueError:
                continue
            if 5 <= value <= 50_000_000 and not (1900 <= value <= 2100 and "patients" not in match.group(0)):
                best = value if best is None else max(best, value)
    return best


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")


def bottom_line(article: Article, max_chars: int = 320) -> str | None:
    """The 'BLUF' shown first on a preview card: the authors' conclusion."""
    for section in article.sections:
        if any(label in section.label.lower() for label in _CONCLUSION_LABELS):
            return _clip(section.text, max_chars)
    if not article.abstract:
        return None
    abstract = article.abstract.strip()
    match = re.search(r"(?i)\b(conclusions?|interpretation)\s*[:.]\s*(.+)$", abstract, re.S)
    if match:
        return _clip(match.group(2), max_chars)
    sentences = _SENTENCE_SPLIT.split(abstract)
    tail = " ".join(sentences[-2:]) if len(sentences) > 2 else abstract
    return _clip(tail, max_chars)


def _clip(text: str, max_chars: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars].rsplit(" ", 1)[0]
    return cut.rstrip(",;:") + "…"


def annotate(article: Article) -> Article:
    article.design = classify(article)
    article.evidence_level = DESIGN_LEVEL[article.design]
    if article.sample_size is None:
        methods = " ".join(s.text for s in article.sections if s.label.lower() in ("methods", "results", "findings"))
        article.sample_size = extract_sample_size(methods or article.abstract)
    if article.bottom_line is None:
        article.bottom_line = bottom_line(article)
    return article


def _norm_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    doi = doi.strip().lower()
    doi = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:)", "", doi)
    return doi or None


def _norm_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", title.lower())[:120]


def dedupe(articles: list[Article]) -> list[Article]:
    """Merge the same paper returned by several providers, keeping the richest record."""
    merged: list[Article] = []
    index: dict[str, Article] = {}
    for art in articles:
        keys = [k for k in (
            f"pmid:{art.pmid}" if art.pmid else None,
            f"doi:{_norm_doi(art.doi)}" if art.doi else None,
            f"title:{_norm_title(art.title)}" if len(art.title) > 20 else None,
        ) if k]
        existing = next((index[k] for k in keys if k in index), None)
        if existing is None:
            merged.append(art)
            existing = art
        else:
            _merge_into(existing, art)
        for k in keys:
            index[k] = existing
    return merged


def _merge_into(base: Article, other: Article) -> None:
    if other.source != base.source and other.source not in base.also_in:
        base.also_in.append(other.source)
    for field in ("journal", "year", "pub_date", "doi", "pmid", "pmcid", "pdf_url", "url"):
        if getattr(base, field) in (None, "") and getattr(other, field):
            setattr(base, field, getattr(other, field))
    if len(other.abstract or "") > len(base.abstract or ""):
        base.abstract = other.abstract
    if len(other.sections) > len(base.sections):
        base.sections = other.sections
    if not base.authors and other.authors:
        base.authors = other.authors
    for field in ("publication_types", "mesh_terms", "keywords"):
        merged = list(dict.fromkeys(getattr(base, field) + getattr(other, field)))
        setattr(base, field, merged)
    base.open_access = base.open_access or other.open_access
    base.is_retracted = base.is_retracted or other.is_retracted
    base.is_preprint = base.is_preprint and other.is_preprint
    if other.cited_by is not None:
        base.cited_by = max(base.cited_by or 0, other.cited_by)
    if base.pmid:
        base.id = f"pmid:{base.pmid}"


def score(article: Article, today: date | None = None) -> float:
    """Blend evidence strength, recency, citations and query rank (higher = better)."""
    today = today or date.today()
    strength = (6 - article.evidence_level) / 5  # 1.0 .. 0.2
    if article.year:
        age = max(0, today.year - article.year)
        recency = math.exp(-age / 6)  # half-weight at ~4 years
    else:
        recency = 0.3
    citations = math.log1p(article.cited_by or 0) / math.log1p(2000)
    value = 0.45 * strength + 0.3 * recency + 0.15 * min(citations, 1.0) + 0.1 * article.score
    if article.is_retracted:
        value -= 1.0
    if article.is_preprint:
        value -= 0.05
    if article.sample_size and article.sample_size >= 1000:
        value += 0.03
    return round(value, 4)


def rank(articles: list[Article], today: date | None = None) -> list[Article]:
    """`article.score` should hold a 0..1 provider relevance on input; it is replaced by the final score."""
    for art in articles:
        art.score = score(art, today)
    return sorted(articles, key=lambda a: a.score, reverse=True)


def design_label(design: StudyDesign) -> str:
    return DESIGN_LABEL[design]
