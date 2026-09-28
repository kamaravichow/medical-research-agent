from datetime import date

from medagent import citations, evidence
from medagent.models import Article, Section, StudyDesign


def art(**kw):
    base = dict(id=kw.pop("id", "x"), source=kw.pop("source", "pubmed"), title=kw.pop("title", "A study of things in people"))
    return Article(**base, **kw)


def test_classify_by_publication_type():
    assert evidence.classify(art(publication_types=["Meta-Analysis", "Review"])) is StudyDesign.META_ANALYSIS
    assert evidence.classify(art(publication_types=["Randomized Controlled Trial"])) is StudyDesign.RCT
    assert evidence.classify(art(publication_types=["Practice Guideline"])) is StudyDesign.GUIDELINE
    assert evidence.classify(art(publication_types=["Case Reports"])) is StudyDesign.CASE_REPORT


def test_review_upgraded_by_title():
    a = art(title="Statins for primary prevention: a systematic review", publication_types=["Review"])
    assert evidence.classify(a) is StudyDesign.SYSTEMATIC_REVIEW


def test_classify_by_text_and_preprint():
    assert evidence.classify(art(abstract="Patients were randomly assigned to drug or placebo.")) is StudyDesign.RCT
    assert evidence.classify(art(is_preprint=True, title="Some early data")) is StudyDesign.PREPRINT
    assert evidence.classify(art(is_preprint=True, title="A retrospective cohort of 900 patients")) is StudyDesign.COHORT


def test_sample_size():
    assert evidence.extract_sample_size("We randomly assigned 5988 patients to") == 5988
    assert evidence.extract_sample_size("A registry of 45,210 patients") == 45210
    assert evidence.extract_sample_size("(n = 1,204)") == 1204
    assert evidence.extract_sample_size("Published in 2021 by the group") is None


def test_bottom_line_prefers_conclusion_section():
    a = art(sections=[Section(label="Results", text="HR 0.8"), Section(label="Conclusions", text="Drug X helped.")])
    assert evidence.bottom_line(a) == "Drug X helped."
    b = art(abstract="Background text. Methods text. CONCLUSION: It works well.")
    assert evidence.bottom_line(b) == "It works well."


def test_dedupe_merges_and_keeps_richest():
    a = art(id="pmid:1", pmid="1", doi="10.1/abc", title="Same trial of drug X in heart failure", abstract="short")
    b = art(id="doi:10.1/abc", source="europepmc", doi="https://doi.org/10.1/ABC", title="Same trial of drug X in heart failure",
            abstract="a much longer abstract text", cited_by=50, open_access=True)
    merged = evidence.dedupe([a, b])
    assert len(merged) == 1
    m = merged[0]
    assert m.abstract == "a much longer abstract text" and m.cited_by == 50 and m.open_access and m.also_in == ["europepmc"]


def test_rank_prefers_strong_recent_evidence_and_sinks_retractions():
    today = date(2026, 1, 1)
    ma = evidence.annotate(art(id="1", publication_types=["Meta-Analysis"], year=2024))
    old_case = evidence.annotate(art(id="2", publication_types=["Case Reports"], year=2001))
    retracted = evidence.annotate(art(id="3", publication_types=["Meta-Analysis"], year=2025, is_retracted=True))
    ranked = evidence.rank([old_case, retracted, ma], today)
    assert [a.id for a in ranked] == ["1", "2", "3"]


def test_citation_formats():
    a = art(title="Trial X", authors=["Smith J", "Doe A"], journal="BMJ", year=2023, doi="10.1/x", pmid="9")
    assert citations.vancouver(a) == "Smith J, Doe A. Trial X. BMJ. 2023. doi:10.1/x. PMID: 9."
    assert "TY  - JOUR" in citations.ris([a]) and "AU  - Doe A" in citations.ris([a])
    assert citations.bibtex([a]).startswith("@article{smith2023trial,")
