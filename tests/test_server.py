import pytest
from fastapi.testclient import TestClient

from medagent.models import Article
from medagent.server import create_app


@pytest.fixture
def client(harness):
    with TestClient(create_app(harness=harness)) as c:
        yield c


def test_ui_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "MedAgent Evidence Desk" in r.text
    assert client.get("/static/app.js").status_code == 200


def test_health(client):
    body = client.get("/api/health").json()
    assert body["tinyfish"] is True and "PubMed" in body["sources"]


def test_search_endpoint(client):
    r = client.post("/api/search", json={"query": "sglt2 heart failure", "filters": {"year_from": 2020}})
    assert r.status_code == 200
    body = r.json()
    assert body["articles"] and body["articles"][0]["evidence_level"] in (1, 2)
    assert body["evidence_counts"]


def test_trials_requires_a_query(client):
    assert client.get("/api/trials").status_code == 422
    assert client.get("/api/trials", params={"condition": "MI", "recruiting": True}).json()[0]["nct_id"] == "NCT01234567"


def test_drug_and_read(client):
    body = client.get("/api/drug/apixaban").json()
    assert body["label"]["generic_names"] == ["APIXABAN"]
    page = client.post("/api/read", json={"url": "https://example.org"}).json()
    assert page["text"].startswith("# Results")


def test_library_export_and_watch_digest(client):
    a = Article(id="pmid:1", source="pubmed", title="Trial X", authors=["Smith J"], year=2023, pmid="1")
    assert client.post("/api/library", json=a.model_dump(mode="json")).json()["count"] == 1
    lib = client.get("/api/library").json()
    ris = client.post("/api/export", json={"articles": lib, "format": "ris"})
    assert "TI  - Trial X" in ris.text
    topic = client.post("/api/watch", json={"query": "heart failure", "days": 30}).json()
    first = client.get(f"/api/watch/{topic['id']}/digest").json()
    assert first["new_ids"]
    second = client.get(f"/api/watch/{topic['id']}/digest").json()
    assert second["new_ids"] == []  # already seen
    assert client.delete(f"/api/watch/{topic['id']}").json()["ok"]


def test_calculator_endpoints(client):
    cat = client.get("/api/calculators").json()
    assert any(c["name"] == "ckd_epi_2021" for c in cat)
    r = client.post("/api/calculators/ckd_epi_2021", json={"inputs": {"age": 50, "sex": "female", "creatinine_mg_dl": 1.0}})
    assert r.status_code == 200 and r.json()["value"] == 69
    assert client.post("/api/calculators/ckd_epi_2021", json={"inputs": {"age": 50}}).status_code == 422


def test_ml_endpoints(client):
    a = client.post("/api/analyze", json={"text": "66-year-old man, creatinine 1.0 mg/dL, weight 80 kg"}).json()
    assert a["findings"]["age"] == 66 and a["prefill"]["cockcroft_gault"]["missing"] == []
    ap = client.post("/api/appraise", json={"text": "We randomly assigned 300 patients with sepsis to drug A or placebo. "
                                                     "Mortality HR 0.8 (95% CI 0.65 to 0.98)."}).json()
    assert ap["pico"]["sample_size"] == 300 and ap["effects"]["effects"][0]["significant"] is True
    d = client.post("/api/stats/diagnostic", json={"pretest_probability": 0.3, "sensitivity": 0.95, "specificity": 0.9}).json()
    assert 0.7 < d["posttest_if_positive"] < 0.85
    assert client.post("/api/stats/effect", json={"control_risk": 0.2}).status_code == 422
    skills = client.get("/api/skills").json()
    assert len(skills) == 9
    health = client.get("/api/health").json()
    assert {m["component"] for m in health["ml"]} >= {"clinical_ner", "pico", "reranker", "calculators"}
