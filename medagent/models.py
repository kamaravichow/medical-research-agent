"""Normalised records returned by every provider.

Every provider maps its own payload onto these models so the ranking code, the
agent tools and the web previews only ever deal with one shape per kind of
record.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class StudyDesign(str, Enum):
    GUIDELINE = "guideline"
    META_ANALYSIS = "meta_analysis"
    SYSTEMATIC_REVIEW = "systematic_review"
    RCT = "rct"
    CLINICAL_TRIAL = "clinical_trial"
    COHORT = "cohort"
    CASE_CONTROL = "case_control"
    CROSS_SECTIONAL = "cross_sectional"
    CASE_REPORT = "case_report"
    NARRATIVE_REVIEW = "narrative_review"
    OPINION = "opinion"
    PREPRINT = "preprint"
    OTHER = "other"


class Section(BaseModel):
    """One labelled part of a structured abstract (BACKGROUND, METHODS, ...)."""

    label: str
    text: str


class Article(BaseModel):
    """A research paper from PubMed, Europe PMC, OpenAlex or the web."""

    id: str = Field(..., description="Stable key, e.g. 'pmid:123', 'doi:10.x/y'")
    source: str = Field(..., description="Provider that returned it")
    title: str
    authors: list[str] = Field(default_factory=list)
    journal: str | None = None
    year: int | None = None
    pub_date: str | None = None
    doi: str | None = None
    pmid: str | None = None
    pmcid: str | None = None
    url: str | None = None
    pdf_url: str | None = None
    abstract: str | None = None
    sections: list[Section] = Field(default_factory=list)
    publication_types: list[str] = Field(default_factory=list)
    mesh_terms: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    open_access: bool = False
    is_preprint: bool = False
    is_retracted: bool = False
    cited_by: int | None = None

    # Filled in by medagent.evidence.annotate()
    design: StudyDesign = StudyDesign.OTHER
    evidence_level: int = 5
    sample_size: int | None = None
    bottom_line: str | None = None
    score: float = 0.0
    also_in: list[str] = Field(default_factory=list, description="Other providers that returned it")


class TrialLocation(BaseModel):
    facility: str | None = None
    city: str | None = None
    country: str | None = None
    status: str | None = None


class Trial(BaseModel):
    """A registered study from ClinicalTrials.gov."""

    id: str
    nct_id: str
    title: str
    official_title: str | None = None
    status: str | None = None
    phases: list[str] = Field(default_factory=list)
    study_type: str | None = None
    conditions: list[str] = Field(default_factory=list)
    interventions: list[str] = Field(default_factory=list)
    sponsor: str | None = None
    enrollment: int | None = None
    start_date: str | None = None
    primary_completion_date: str | None = None
    last_update: str | None = None
    has_results: bool = False
    summary: str | None = None
    primary_outcomes: list[str] = Field(default_factory=list)
    eligibility: str | None = None
    min_age: str | None = None
    max_age: str | None = None
    sex: str | None = None
    locations: list[TrialLocation] = Field(default_factory=list)
    url: str


class DrugLabel(BaseModel):
    """Key sections of an FDA structured product label (openFDA)."""

    id: str
    brand_names: list[str] = Field(default_factory=list)
    generic_names: list[str] = Field(default_factory=list)
    manufacturer: str | None = None
    route: list[str] = Field(default_factory=list)
    pharm_class: list[str] = Field(default_factory=list)
    boxed_warning: str | None = None
    indications: str | None = None
    dosage: str | None = None
    contraindications: str | None = None
    warnings: str | None = None
    adverse_reactions: str | None = None
    interactions: str | None = None
    pregnancy: str | None = None
    renal_hepatic: str | None = None
    effective_date: str | None = None
    url: str | None = None


class AdverseEventCount(BaseModel):
    term: str
    count: int


class AdverseEventSummary(BaseModel):
    """Most-reported reactions for a drug in FAERS (openFDA)."""

    drug: str
    total_reports: int | None = None
    serious_reports: int | None = None
    top_reactions: list[AdverseEventCount] = Field(default_factory=list)
    caveat: str = (
        "FAERS reports are spontaneous and unverified; counts do not establish causation or incidence."
    )


class WebResult(BaseModel):
    """A TinyFish web/news/paper search hit (guidelines, society pages, news)."""

    id: str
    title: str
    url: str
    site: str
    snippet: str
    date: str | None = None
    authority: str | None = Field(None, description="Recognised publisher tier, e.g. 'guideline body'")
    kind: str = "web"


class FetchedPage(BaseModel):
    """Clean text of a page pulled with TinyFish Fetch."""

    url: str
    final_url: str | None = None
    title: str | None = None
    description: str | None = None
    published_date: str | None = None
    author: str | None = None
    text: str | None = None
    highlights: list[str] = Field(default_factory=list)
    error: str | None = None


class SearchFilters(BaseModel):
    year_from: int | None = None
    year_to: int | None = None
    designs: list[StudyDesign] = Field(default_factory=list)
    open_access_only: bool = False
    include_preprints: bool = True
    max_results: int = Field(25, ge=1, le=100)


class ProviderStatus(BaseModel):
    provider: str
    ok: bool
    count: int = 0
    ms: int = 0
    error: str | None = None


class SearchBundle(BaseModel):
    """Everything a federated search returned, ready for previews."""

    query: str
    articles: list[Article] = Field(default_factory=list)
    trials: list[Trial] = Field(default_factory=list)
    web: list[WebResult] = Field(default_factory=list)
    providers: list[ProviderStatus] = Field(default_factory=list)
    evidence_counts: dict[str, int] = Field(default_factory=dict)
