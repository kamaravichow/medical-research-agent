import httpx

from medagent.models import SearchFilters, StudyDesign


async def test_federated_search_merges_grades_and_ranks(harness):
    bundle = await harness.search("SGLT2 inhibitors heart failure")
    ids = [a.id for a in bundle.articles]
    assert len(ids) == len(set(ids))
    # PubMed + Europe PMC copies of 38000001 merged; OpenAlex copy of 38000002 merged by PMID
    assert set(ids) == {"pmid:38000001", "pmid:38000002", "doi:10.1101/2025.01.01.25000001"}
    rct = next(a for a in bundle.articles if a.id == "pmid:38000001")
    assert rct.design is StudyDesign.RCT and rct.cited_by == 1500 and "europepmc" in rct.also_in
    assert rct.sample_size == 5988 and rct.bottom_line.startswith("Empagliflozin reduced")
    ma = next(a for a in bundle.articles if a.id == "pmid:38000002")
    assert ma.design is StudyDesign.META_ANALYSIS and ma.cited_by == 900
    assert bundle.articles[0].evidence_level <= bundle.articles[-1].evidence_level
    assert bundle.trials[0].nct_id == "NCT01234567"
    assert bundle.web[0].authority == "Guideline body"
    assert all(p.ok for p in bundle.providers)


async def test_search_survives_provider_outage(harness, mock_apis):
    mock_apis.get(url__regex=r"https://api\.openalex\.org/works.*").mock(return_value=httpx.Response(400))
    bundle = await harness.search("x y", sources=("pubmed", "openalex"))
    status = {p.provider: p for p in bundle.providers}
    assert status["pubmed"].ok and not status["openalex"].ok and "HTTP 400" in status["openalex"].error
    assert bundle.articles


async def test_filters_applied_client_side(harness):
    bundle = await harness.search("x y", SearchFilters(include_preprints=False, designs=[StudyDesign.RCT]))
    assert [a.id for a in bundle.articles] == ["pmid:38000001"]


async def test_whats_new_sorts_newest_first(harness):
    bundle = await harness.whats_new("heart failure", days=30)
    dates = [a.pub_date or str(a.year) for a in bundle.articles]
    assert dates == sorted(dates, reverse=True)
    assert bundle.trials and bundle.trials[0].last_update.startswith("2099")


async def test_drug_lookup(harness):
    label, events, statuses = await harness.drug("apixaban")
    assert label.brand_names == ["ELIQUIS"]
    assert events.total_reports == 5000 and events.top_reactions[0].term == "Haemorrhage"
    assert all(s.ok for s in statuses)


async def test_openfda_404_is_empty_not_error(harness, mock_apis):
    mock_apis.get(url__regex=r"https://api\.fda\.gov/drug/label\.json.*").mock(return_value=httpx.Response(404, json={"error": {}}))
    label, _, statuses = await harness.drug("notadrug")
    assert label is None and all(s.ok for s in statuses)


async def test_tinyfish_guideline_search_scopes_domains(harness, fake_tinyfish):
    results = await harness.web("heart failure", kind="guidelines")
    call = fake_tinyfish.search_calls[-1]
    assert "nice.org.uk" in call["include_domains"] and call["domain_type"] == "web"
    assert "guideline" in call["query"]
    assert results[0].kind == "guideline"


async def test_tinyfish_fetch_with_highlights(harness, fake_tinyfish):
    pages = await harness.read(["https://example.org/a"], focus="hazard ratio")
    assert pages[0].highlights == ["HR 0.79 (95% CI 0.69-0.90)"]
    assert fake_tinyfish.fetch_calls[-1]["highlights"]["query"] == "hazard ratio"
