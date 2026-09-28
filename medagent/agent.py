"""The LangChain research agent and a streaming session wrapper for the UI."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any, AsyncIterator

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver

from .config import Settings
from .harness import ResearchHarness
from .sources import SourceRegistry
from .tools import build_tools

SYSTEM_PROMPT = """\
You are MedAgent, a medical research assistant for practising clinicians. Today is {today}.
Your reader is a busy doctor: be precise, quantitative and brief. Never pad.

How to work
- Always search before answering; never answer from memory alone. Run several targeted searches
  in parallel when a question has distinct parts (efficacy, safety, guidelines, ongoing trials).
- Prefer the highest level of evidence (LoE 1 guidelines / systematic reviews / meta-analyses,
  then RCTs). Go lower only when that is all there is, and say so.
- For treatment questions, check current guidelines with search_web(kind="guidelines").
- For drugs, use drug_label for dosing/contraindications/boxed warnings; FAERS counts are signals,
  not incidence.
- For "what's new" questions use find_new_research. Label preprints as not peer reviewed.
- Use get_article or read_source when a conclusion needs effect sizes or methods you do not yet have.
- Stop searching once the evidence is sufficient; do not exceed ~8 tool calls unless necessary.

How to answer (Markdown)
**Bottom line** — 2–4 sentences answering the question directly, with the strength of evidence.
**Key evidence** — a table: | Study | Design (LoE) | Population / n | Finding (effect size, CI) | [n] |
**Guidelines** — what current guidance recommends and who issued it (omit if none found).
**Safety & practical points** — dosing, contraindications, monitoring, interactions when relevant.
**Ongoing / new research** — relevant trials or recent preprints (omit if none).
**Caveats & gaps** — conflicting results, limitations, populations not studied.

Rules
- Cite with the bracketed numbers the tools gave you, e.g. [3] or [2][5]. Cite ONLY those numbers;
  never invent a study, number, or citation. If you did not find something, say so.
- Report effect sizes with CIs and absolute numbers (ARR/NNT) where the source gives them.
- Flag retracted papers and preprints explicitly.
- You support clinical decision-making; you do not replace clinical judgement or local protocols.
  Do not give patient-specific orders. Mention this only once, briefly, when relevant.
"""


def make_model(settings: Settings) -> BaseChatModel:
    kwargs: dict[str, Any] = {"max_tokens": 4096}
    if settings.temperature is not None:
        kwargs["temperature"] = settings.temperature
    return init_chat_model(settings.model, **kwargs)


def build_agent(harness: ResearchHarness, registry: SourceRegistry, model: BaseChatModel | None = None, checkpointer=None):
    model = model or make_model(harness.settings)
    return create_agent(
        model,
        tools=build_tools(harness, registry),
        system_prompt=SYSTEM_PROMPT.format(today=date.today().isoformat()),
        checkpointer=checkpointer,
        name="medagent",
    )


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(b.get("text", "") if isinstance(b, dict) and b.get("type") in (None, "text") else (b if isinstance(b, str) else "")
                       for b in content)
    return ""


@dataclass
class Conversation:
    id: str
    registry: SourceRegistry = field(default_factory=SourceRegistry)
    agent: Any = None


class AgentService:
    """Keeps one agent + citation registry per conversation and streams UI events.

    Events: {"type": "status"|"tool_start"|"tool_end"|"token"|"sources"|"answer"|"error", ...}
    """

    def __init__(self, harness: ResearchHarness, model: BaseChatModel | None = None):
        self.harness = harness
        self._model = model
        self._checkpointer = InMemorySaver()
        self._conversations: dict[str, Conversation] = {}

    def _conversation(self, conversation_id: str | None) -> Conversation:
        cid = conversation_id or uuid.uuid4().hex[:12]
        conv = self._conversations.get(cid)
        if conv is None:
            conv = Conversation(id=cid)
            model = self._model or make_model(self.harness.settings)
            conv.agent = build_agent(self.harness, conv.registry, model=model, checkpointer=self._checkpointer)
            self._conversations[cid] = conv
        return conv

    def sources(self, conversation_id: str) -> list[dict[str, Any]]:
        conv = self._conversations.get(conversation_id)
        return conv.registry.to_payload() if conv else []

    async def ask(self, question: str, conversation_id: str | None = None) -> dict[str, Any]:
        answer = ""
        cid = None
        sources: list[dict[str, Any]] = []
        async for event in self.stream(question, conversation_id):
            if event["type"] == "status":
                cid = event["conversation_id"]
            elif event["type"] == "answer":
                answer = event["text"]
            elif event["type"] == "sources":
                sources.extend(event["items"])
            elif event["type"] == "error":
                raise RuntimeError(event["message"])
        return {"conversation_id": cid, "answer": answer, "sources": sources}

    async def stream(self, question: str, conversation_id: str | None = None) -> AsyncIterator[dict[str, Any]]:
        conv = self._conversation(conversation_id)
        yield {"type": "status", "conversation_id": conv.id, "message": "Planning searches…"}
        config = {"configurable": {"thread_id": conv.id}, "recursion_limit": 40}
        sent = len(conv.registry)
        final = ""
        try:
            async for mode, chunk in conv.agent.astream(
                {"messages": [HumanMessage(question)]}, config=config, stream_mode=["messages", "updates"]
            ):
                if mode == "messages":
                    message, _meta = chunk
                    if isinstance(message, AIMessageChunk):
                        text = _text_of(message.content)
                        if text:
                            yield {"type": "token", "text": text}
                    continue
                for node, update in (chunk or {}).items():
                    for message in (update or {}).get("messages", []) if isinstance(update, dict) else []:
                        if isinstance(message, AIMessage):
                            for call in message.tool_calls:
                                yield {"type": "tool_start", "id": call["id"], "name": call["name"], "args": call["args"]}
                            if not message.tool_calls:
                                final = _text_of(message.content)
                        elif isinstance(message, ToolMessage):
                            text = _text_of(message.content)
                            yield {"type": "tool_end", "id": message.tool_call_id, "name": message.name,
                                   "preview": text[:280], "chars": len(text)}
                            if len(conv.registry) > sent:
                                yield {"type": "sources", "items": conv.registry.to_payload(since=sent)}
                                sent = len(conv.registry)
        except Exception as exc:  # surface model/auth errors to the UI instead of a dead stream
            yield {"type": "error", "message": f"{exc.__class__.__name__}: {exc}"}
            return
        if len(conv.registry) > sent:
            yield {"type": "sources", "items": conv.registry.to_payload(since=sent)}
        yield {"type": "answer", "text": final, "conversation_id": conv.id}
