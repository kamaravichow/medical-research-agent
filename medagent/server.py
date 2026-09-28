"""FastAPI app: JSON API + the clinician web UI (served from medagent/web)."""

from __future__ import annotations

import json
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from . import citations
from .ml import calculators, prefill_calculator
from .ml.calculators import CalculatorError
from .ml.effects import extract_effects
from .ml.stats import DiagnosticIn, EffectIn, diagnostic_probability, treatment_effect
from .skills import SkillRegistry
from .agent import AgentService
from .harness import ALL_SOURCES, ResearchHarness
from .models import Article, SearchFilters
from .providers.base import ProviderError
from .providers.tinyfish import TinyFishNotConfigured
from .store import Store, WatchTopic

WEB_DIR = Path(__file__).parent / "web"


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=2)
    filters: SearchFilters = Field(default_factory=SearchFilters)
    sources: list[str] = Field(default_factory=lambda: list(ALL_SOURCES))


class AskRequest(BaseModel):
    question: str = Field(..., min_length=3)
    conversation_id: str | None = None


class ReadRequest(BaseModel):
    url: str
    focus: str | None = None


class ExportRequest(BaseModel):
    articles: list[Article]
    format: Literal["ris", "bibtex", "vancouver"] = "ris"


class TextRequest(BaseModel):
    text: str = Field(..., min_length=3, max_length=50_000)


class CalcRequest(BaseModel):
    inputs: dict = Field(default_factory=dict)


class WatchRequest(BaseModel):
    query: str = Field(..., min_length=2)
    days: int = Field(30, ge=1, le=365)


def create_app(harness: ResearchHarness | None = None, agent_service: AgentService | None = None) -> FastAPI:
    state: dict = {}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        state["harness"] = harness or ResearchHarness()
        state["agent"] = agent_service
        state["store"] = Store(state["harness"].settings.data_dir)
        # Load the NER model before accepting requests. Loading holds the GIL for ~20 s, so doing it in the
        # background would stall every request made meanwhile; a slower start-up is the better trade.
        if state["harness"].settings.preload_models:
            await state["harness"].ml.warm()
        yield
        if harness is None:
            await state["harness"].aclose()

    app = FastAPI(title="MedAgent", version="0.1.0", lifespan=lifespan)

    def h() -> ResearchHarness:
        return state["harness"]

    def agent() -> AgentService:
        if state.get("agent") is None:
            state["agent"] = AgentService(h())
        return state["agent"]

    def upstream(exc: Exception) -> HTTPException:
        if isinstance(exc, TinyFishNotConfigured):
            return HTTPException(503, str(exc))
        return HTTPException(502, str(exc))

    # ------------------------------------------------------------ meta
    @app.get("/api/health")
    async def health():
        s = h().settings
        model_provider = s.model.split(":", 1)[0] if ":" in s.model else "anthropic"
        key_var = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "google_genai": "GOOGLE_API_KEY"}.get(model_provider)
        return {
            "ok": True,
            "model": s.model,
            "agent_ready": bool(os.environ.get(key_var)) if key_var else True,
            "tinyfish": h().tinyfish.enabled,
            "ncbi_key": bool(s.ncbi_api_key),
            "sources": ["PubMed", "Europe PMC", "OpenAlex", "ClinicalTrials.gov", "openFDA"] + (["TinyFish Search/Fetch"] if h().tinyfish.enabled else []),
            "ml": h().ml.status(),
        }

    # -------------------------------------------------- ML models / skills
    @app.get("/api/skills")
    async def list_skills():
        registry = agent().skills if state.get("agent") else SkillRegistry()
        return [{"name": sk.name, "title": sk.title, "description": sk.description, "tools": sk.tools}
                for sk in registry.skills.values()]

    @app.get("/api/calculators")
    async def list_calculators():
        return calculators.catalogue()

    @app.post("/api/calculators/{name}")
    async def run_calculator(name: str, req: CalcRequest):
        try:
            return calculators.run(name, req.inputs)
        except CalculatorError as exc:
            raise HTTPException(422, str(exc))

    @app.post("/api/analyze")
    async def analyze(req: TextRequest):
        """Clinical NER + negation + labs, and calculator inputs pre-filled from the text."""
        findings = await h().ml.analyze(req.text)
        prefills = {}
        for name in calculators.REGISTRY:
            params, missing = prefill_calculator(name, findings)
            if params:
                prefills[name] = {"inputs": params, "missing": missing}
        return {"findings": findings, "prefill": prefills}

    @app.post("/api/appraise")
    async def appraise(req: TextRequest):
        """PICO (transformer or rules) + deterministic effect-size extraction for an abstract."""
        pico = await h().ml.extract_pico(req.text)
        return {"pico": pico, "effects": extract_effects(req.text)}

    @app.post("/api/stats/diagnostic")
    async def stats_diagnostic(req: DiagnosticIn):
        return diagnostic_probability(req)

    @app.post("/api/stats/effect")
    async def stats_effect(req: EffectIn):
        try:
            return treatment_effect(req)
        except ValueError as exc:
            raise HTTPException(422, str(exc))

    # ---------------------------------------------------------- search
    @app.post("/api/search")
    async def search(req: SearchRequest):
        return await h().search(req.query, req.filters, sources=req.sources)

    @app.get("/api/new")
    async def whats_new(topic: str = Query(..., min_length=2), days: int = Query(30, ge=1, le=365), limit: int = Query(30, ge=1, le=60)):
        return await h().whats_new(topic, days=days, limit=limit)

    @app.get("/api/article")
    async def article(id: str = Query(..., description="pmid:123, 123, or doi:10.x/y")):
        try:
            art = await h().article(id)
        except ProviderError as exc:
            raise upstream(exc)
        if art is None:
            raise HTTPException(404, "Article not found")
        return art

    @app.get("/api/trials")
    async def trials(condition: str | None = None, intervention: str | None = None, term: str | None = None,
                     location: str | None = None, recruiting: bool = False, phase: list[str] = Query(default_factory=list),
                     limit: int = Query(20, ge=1, le=100)):
        try:
            return await h().trials(condition=condition, intervention=intervention, term=term, location=location,
                                    recruiting_only=recruiting, phases=phase or None, limit=limit)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        except ProviderError as exc:
            raise upstream(exc)

    @app.get("/api/trial/{nct_id}")
    async def trial(nct_id: str):
        try:
            return await h().trial(nct_id)
        except ProviderError as exc:
            raise upstream(exc)

    @app.get("/api/drug/{name}")
    async def drug(name: str):
        label, events, providers = await h().drug(name)
        return {"label": label, "events": events, "providers": providers}

    @app.get("/api/web")
    async def web(q: str = Query(..., min_length=2), kind: Literal["web", "guidelines", "news", "papers", "regulatory"] = "guidelines",
                  days: int | None = Query(None, ge=1, le=3650)):
        try:
            return await h().web(q, kind=kind, days=days)
        except Exception as exc:
            raise upstream(exc)

    @app.post("/api/read")
    async def read(req: ReadRequest):
        try:
            pages = await h().read([req.url], focus=req.focus)
        except Exception as exc:
            raise upstream(exc)
        if not pages:
            raise HTTPException(404, "Nothing returned")
        return pages[0]

    # ------------------------------------------------------------ agent
    @app.post("/api/ask")
    async def ask(req: AskRequest):
        try:
            return await agent().ask(req.question, req.conversation_id)
        except Exception as exc:
            raise HTTPException(500, str(exc))

    @app.post("/api/ask/stream")
    async def ask_stream(req: AskRequest):
        async def events():
            try:
                service = agent()
                async for event in service.stream(req.question, req.conversation_id):
                    yield {"event": event["type"], "data": json.dumps(event, default=str)}
            except Exception as exc:
                yield {"event": "error", "data": json.dumps({"type": "error", "message": f"{exc.__class__.__name__}: {exc}"})}
        return EventSourceResponse(events())

    @app.get("/api/conversation/{cid}/sources")
    async def conversation_sources(cid: str):
        return agent().sources(cid)

    # ----------------------------------------------------------- export
    @app.post("/api/export")
    async def export(req: ExportRequest):
        if req.format == "ris":
            return PlainTextResponse(citations.ris(req.articles), media_type="application/x-research-info-systems",
                                     headers={"Content-Disposition": 'attachment; filename="medagent.ris"'})
        if req.format == "bibtex":
            return PlainTextResponse(citations.bibtex(req.articles), media_type="application/x-bibtex",
                                     headers={"Content-Disposition": 'attachment; filename="medagent.bib"'})
        return PlainTextResponse("\n".join(f"{i}. {citations.vancouver(a)}" for i, a in enumerate(req.articles, 1)))

    # --------------------------------------------------------- watchlist
    @app.get("/api/watch")
    async def list_watch():
        return state["store"].load().topics

    @app.post("/api/watch")
    async def add_watch(req: WatchRequest):
        store: Store = state["store"]
        data = store.load()
        topic = WatchTopic(id=uuid.uuid4().hex[:10], query=req.query, days=req.days)
        data.topics.append(topic)
        store.save(data)
        return topic

    @app.delete("/api/watch/{topic_id}")
    async def delete_watch(topic_id: str):
        store: Store = state["store"]
        data = store.load()
        data.topics = [t for t in data.topics if t.id != topic_id]
        store.save(data)
        return {"ok": True}

    @app.get("/api/watch/{topic_id}/digest")
    async def watch_digest(topic_id: str):
        store: Store = state["store"]
        data = store.load()
        topic = next((t for t in data.topics if t.id == topic_id), None)
        if topic is None:
            raise HTTPException(404, "Unknown topic")
        bundle = await h().whats_new(topic.query, days=topic.days)
        seen = set(topic.seen_ids)
        new_ids = [a.id for a in bundle.articles if a.id not in seen]
        topic.seen_ids = list(dict.fromkeys(topic.seen_ids + [a.id for a in bundle.articles]))[-2000:]
        topic.last_checked = datetime.now(timezone.utc).isoformat(timespec="seconds")
        store.save(data)
        return {"topic": topic, "new_ids": new_ids, "bundle": bundle}

    # ----------------------------------------------------------- library
    @app.get("/api/library")
    async def library():
        return state["store"].load().library

    @app.post("/api/library")
    async def save_to_library(article: Article):
        store: Store = state["store"]
        data = store.load()
        if not any(a.id == article.id for a in data.library):
            data.library.insert(0, article)
            store.save(data)
        return {"ok": True, "count": len(data.library)}

    @app.delete("/api/library")
    async def remove_from_library(id: str):
        store: Store = state["store"]
        data = store.load()
        data.library = [a for a in data.library if a.id != id]
        store.save(data)
        return {"ok": True}

    # --------------------------------------------------------------- UI
    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(WEB_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
    return app


app = create_app()


def main() -> None:  # pragma: no cover
    import uvicorn

    uvicorn.run("medagent.server:app", host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8000")))

