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
