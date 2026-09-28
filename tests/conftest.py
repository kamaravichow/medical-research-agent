from __future__ import annotations

import re
from types import SimpleNamespace

import httpx
import pytest
import respx

from medagent.config import Settings
from medagent.harness import ResearchHarness

from . import fixtures as fx


class FakeTinyFish:
    """Stands in for tinyfish.AsyncTinyFish (same method names and result shapes)."""

    def __init__(self):
        self.search_calls: list[dict] = []
        self.fetch_calls: list[dict] = []
        self.search = SimpleNamespace(query=self._query)
        self.fetch = SimpleNamespace(get_contents=self._get_contents)

    async def _query(self, query, **kwargs):
        self.search_calls.append({"query": query, **kwargs})
        result = SimpleNamespace(
            position=1, site_name="nice.org.uk", title="Chronic heart failure in adults: diagnosis and management (NG106)",
            url="https://www.nice.org.uk/guidance/ng106", snippet="Offer an SGLT2 inhibitor to people with HFrEF…",
            date="2025-09-01", authors=None, venue=None, publisher=None, year=None, cited_by_count=None, pdf_url=None,
        )
        return SimpleNamespace(query=query, results=[result], total_results=1, page=0)

    async def _get_contents(self, urls, **kwargs):
        self.fetch_calls.append({"urls": urls, **kwargs})
        results = [SimpleNamespace(
            url=u, final_url=u, title="Full text", description="desc", published_date="2024-03-04", author=None,
            text="# Results\nThe hazard ratio was 0.79.", highlights=[SimpleNamespace(text="HR 0.79 (95% CI 0.69-0.90)", rank=1)],
        ) for u in urls]
        return SimpleNamespace(results=results, errors=[])


@pytest.fixture
def settings(tmp_path):
    # Deterministic fallbacks by default; tests that exercise the real NER model use `ner` below.
    return Settings(MEDAGENT_DATA_DIR=tmp_path, TINYFISH_API_KEY="tf-test", MEDAGENT_MODEL="anthropic:claude-sonnet-5",
                    MEDAGENT_ML="rules")


@pytest.fixture
def mock_apis():
    with respx.mock(assert_all_called=False) as router:
        router.get(url__regex=r".*/esearch\.fcgi.*").mock(return_value=httpx.Response(200, json=fx.PUBMED_ESEARCH))
        router.get(url__regex=r".*/efetch\.fcgi.*").mock(return_value=httpx.Response(200, text=fx.PUBMED_XML))
        router.get(url__regex=r"https://www\.ebi\.ac\.uk/europepmc/.*").mock(return_value=httpx.Response(200, json=fx.EUROPEPMC))
        router.get(url__regex=r"https://api\.openalex\.org/works.*").mock(return_value=httpx.Response(200, json=fx.OPENALEX))
        router.get(url__regex=r"https://clinicaltrials\.gov/api/v2/studies/NCT\d+.*").mock(return_value=httpx.Response(200, json=fx.CT_STUDY))
        router.get(url__regex=r"https://clinicaltrials\.gov/api/v2/studies\?.*").mock(return_value=httpx.Response(200, json=fx.CLINICALTRIALS))
        router.get(url__regex=r"https://api\.fda\.gov/drug/label\.json.*").mock(return_value=httpx.Response(200, json=fx.FDA_LABEL))

        def events(request: httpx.Request):
            if "count=" in str(request.url):
                return httpx.Response(200, json=fx.FDA_EVENTS_COUNT)
            return httpx.Response(200, json=fx.FDA_EVENTS_TOTAL)

        router.get(url__regex=re.escape("https://api.fda.gov/drug/event.json") + ".*").mock(side_effect=events)
        yield router


@pytest.fixture
def fake_tinyfish():
    return FakeTinyFish()


@pytest.fixture
async def harness(settings, mock_apis, fake_tinyfish):
    h = ResearchHarness(settings, tinyfish_client=fake_tinyfish)
    yield h
    await h.aclose()


def _scispacy_available() -> bool:
    try:
        import importlib.util

        return all(importlib.util.find_spec(m) for m in ("scispacy", "negspacy", "en_ner_bc5cdr_md"))
    except Exception:
        return False


requires_ner = pytest.mark.skipif(not _scispacy_available(), reason="scispaCy + en_ner_bc5cdr_md not installed")


@pytest.fixture(scope="session")
def ner():
    from medagent.ml.nlp import ClinicalNLP

    return ClinicalNLP("en_ner_bc5cdr_md")
