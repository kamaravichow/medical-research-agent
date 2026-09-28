from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from medagent.agent import AgentService
from medagent.sources import SourceRegistry
from medagent.tools import build_tools


class ScriptedModel(BaseChatModel):
    """Replays a fixed list of AI messages; enough to drive the agent loop offline."""

    script: list[AIMessage]
    calls: int = 0

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Any, **kwargs: Any):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        msg = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        return ChatResult(generations=[ChatGeneration(message=msg)])


async def test_tools_register_citations(harness):
    registry = SourceRegistry()
    tools = {t.name: t for t in build_tools(harness, registry)}
    out = await tools["search_literature"].ainvoke({"query": "SGLT2 heart failure"})
    assert "[1]" in out and "LoE" in out and len(registry) == 3
    again = await tools["search_literature"].ainvoke({"query": "SGLT2 heart failure"})
    assert len(registry) == 3 and "[1]" in again  # same papers keep their numbers
    trial = await tools["get_trial_details"].ainvoke({"nct_id": "NCT01234567"})
    assert "[4] NCT01234567" in trial and "Eligibility" in trial
    label = await tools["drug_label"].ainvoke({"drug": "apixaban"})
    assert "BOXED WARNING" in label
    read = await tools["read_source"].ainvoke({"target": "[1]", "focus": "hazard ratio"})
    assert read.startswith("[1]") and "HR 0.79" in read
    art = await tools["get_article"].ainvoke({"identifier": "38000001"})
    assert "CONCLUSIONS:" in art


async def test_tool_errors_become_text(harness, mock_apis):
    import httpx

    mock_apis.get(url__regex=r"https://clinicaltrials\.gov/api/v2/studies/NCT\d+.*").mock(return_value=httpx.Response(500))
    tools = {t.name: t for t in build_tools(harness, SourceRegistry())}
    out = await tools["get_trial_details"].ainvoke({"nct_id": "NCT09999999"})
    assert out.startswith("Tool error")


async def test_agent_stream_emits_tools_sources_and_answer(harness):
    model = ScriptedModel(script=[
        AIMessage(content="", tool_calls=[{"name": "search_literature", "args": {"query": "SGLT2 HFpEF"}, "id": "call_1"}]),
        AIMessage(content="**Bottom line** Empagliflozin reduced HF hospitalisation [1]."),
    ])
    service = AgentService(harness, model=model)
    events = [e async for e in service.stream("Do SGLT2 inhibitors help HFpEF?")]
    kinds = [e["type"] for e in events]
    assert kinds[0] == "status" and "tool_start" in kinds and "tool_end" in kinds and "sources" in kinds
    assert events[-1]["type"] == "answer" and "[1]" in events[-1]["text"]
    sources = [s for e in events if e["type"] == "sources" for s in e["items"]]
    assert sources[0]["n"] == 1 and sources[0]["kind"] == "article"

    # follow-up in the same conversation keeps the registry
    cid = events[0]["conversation_id"]
    model.calls = 1
    result = await service.ask("And in HFrEF?", conversation_id=cid)
    assert result["conversation_id"] == cid and len(service.sources(cid)) == 3


class CapturingModel(ScriptedModel):
    seen: list = []

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen.append(messages)
        return super()._generate(messages, stop, run_manager, **kwargs)


async def test_skills_routed_and_injected_into_system_prompt(harness):
    model = CapturingModel(seen=[], script=[
        AIMessage(content="", tool_calls=[{"name": "run_calculator", "id": "c1",
                                            "args": {"name": "has_bled", "inputs": {"age_over_65": True, "antiplatelet_or_nsaid": True, "labile_inr": True}}}]),
        AIMessage(content="", tool_calls=[{"name": "load_skill", "id": "c2", "args": {"name": "drug-dosing-safety"}}]),
        AIMessage(content="HAS-BLED is 3 (high)."),
    ])
    service = AgentService(harness, model=model)
    events = [e async for e in service.stream("Calculate the HAS-BLED score for my patient on warfarin")]
    skills_ev = next(e for e in events if e["type"] == "skills")
    assert "risk-scores" in [s["name"] for s in skills_ev["items"]]
    first_system = model.seen[0][0].content
    assert "## Skill: Risk scores" in first_system and "run_calculator" in first_system
    assert "## Skill: Drug dosing" not in first_system
    # load_skill takes effect on the next model call
    assert "## Skill: Drug dosing and safety" in model.seen[-1][0].content
    tool_out = next(e for e in events if e["type"] == "tool_end" and e["name"] == "run_calculator")
    assert "HAS-BLED: 3" in tool_out["preview"]
