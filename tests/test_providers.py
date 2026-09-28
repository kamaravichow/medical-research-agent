from medagent.models import SearchFilters, StudyDesign
from medagent.providers.clinicaltrials import to_trial
from medagent.providers.europepmc import build_query, to_article as epmc_article
from medagent.providers.openalex import rebuild_abstract, to_article as oa_article
from medagent.providers.openfda import to_label
from medagent.providers.pubmed import build_term, parse_pubmed_xml

from . import fixtures as fx


def test_parse_pubmed_structured_abstract():
    arts = parse_pubmed_xml(fx.PUBMED_XML)
    assert [a.pmid for a in arts] == ["38000001", "38000002"]
    rct = arts[0]
    assert rct.title.startswith("Empagliflozin in Heart Failure") and "randomized" in rct.title
    assert rct.journal == "N Engl J Med" and rct.year == 2024 and rct.pub_date == "2024-03-04"
    assert rct.doi == "10.1056/NEJMoa0000001" and rct.pmcid == "PMC9000001" and rct.open_access
    assert [s.label for s in rct.sections] == ["Background", "Methods", "Results", "Conclusions"]
    assert rct.authors == ["Anker SD", "EMPEROR-Preserved Investigators"]
    assert "Randomized Controlled Trial" in rct.publication_types
    assert rct.mesh_terms == ["Heart Failure"]
    ma = arts[1]
    assert ma.year == 2022 and ma.doi.startswith("10.1016/")


def test_pubmed_term_filters():
    term = build_term("sepsis", SearchFilters(year_from=2020, designs=[StudyDesign.RCT, StudyDesign.META_ANALYSIS], open_access_only=True))
    assert '("2020"[dp] : "3000"[dp])' in term
    assert "randomized controlled trial[pt]" in term and "meta-analysis[pt]" in term
    assert "free full text[sb]" in term


def test_europepmc_preprint_and_sections():
    item = fx.EUROPEPMC["resultList"]["result"][1]
    art = epmc_article(item, 1, 2)
    assert art.is_preprint and art.journal == "medRxiv" and art.open_access
    assert [s.label for s in art.sections] == ["Background", "Methods", "Conclusions"]
    assert "Preprint" in art.publication_types
    assert build_query("x", SearchFilters(include_preprints=False)).endswith("NOT SRC:PPR")


def test_openalex_mapping():
    art = oa_article(fx.OPENALEX["results"][0], 0, 1)
    assert art.pmid == "38000002" and art.cited_by == 900 and art.abstract == "Five trials pooled."
    assert rebuild_abstract(None) is None


def test_trial_mapping():
    t = to_trial(fx.CT_STUDY)
    assert t.nct_id == "NCT01234567" and t.phases == ["Phase 3"] and t.enrollment == 6500
    assert t.interventions == ["Drug: Empagliflozin"] and t.locations[0].city == "Boston"
    assert t.url == "https://clinicaltrials.gov/study/NCT01234567"


def test_label_mapping():
    label = to_label(fx.FDA_LABEL["results"][0])
    assert label.generic_names == ["APIXABAN"] and label.effective_date == "2024-01-15"
    assert label.boxed_warning.startswith("WARNING") and "setid=abc-123" in label.url
