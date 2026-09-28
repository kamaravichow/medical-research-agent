import pytest

from medagent.skills import SkillRegistry, SkillState
from medagent.sources import SourceRegistry
from medagent.tools import build_tools

from .conftest import requires_ner


@pytest.fixture
def tools(harness):
    return {t.name: t for t in build_tools(harness, SourceRegistry(), SkillState(), SkillRegistry())}


async def test_run_calculator_tool(tools):
    out = await tools["run_calculator"].ainvoke({"name": "cha2ds2_vasc", "inputs": {"age": 80, "sex": "male", "hypertension": True}})
    assert out.startswith("CHA₂DS₂-VASc: 3") and "Reference: Lip GY" in out and "Caveats:" in out
    bad = await tools["run_calculator"].ainvoke({"name": "cha2ds2_vasc", "inputs": {"sex": "male"}})
    assert bad.startswith("Calculator error") and "Required: age, sex" in bad
    listing = await tools["list_calculators"].ainvoke({"category": "Kidney"})
    assert "ckd_epi_2021" in listing and "cockcroft_gault" in listing and "heart_score" not in listing


async def test_stats_tools(tools):
    dx = await tools["diagnostic_probability"].ainvoke({"pretest_probability": 0.1, "lr_negative": 0.05})
    assert '"posttest_if_negative": 0.0055' in dx
    fx = await tools["treatment_effect"].ainvoke({"control_risk": 0.171, "treatment_risk": 0.138})
    assert '"nnt": 31' in fx
    err = await tools["treatment_effect"].ainvoke({"control_risk": 0.2})
    assert "error" in err.lower()


async def test_effects_and_pico_on_cited_source(tools):
    await tools["search_literature"].ainvoke({"query": "sglt2"})
    eff = await tools["extract_effect_sizes"].ainvoke({"source": "38000001"})
    assert '"measure": "HR"' in eff and "0.69" in eff and "13.8% vs 17.1%" in eff
    pico = await tools["extract_pico"].ainvoke({"source": "38000001"})
    assert '"sample_size": 5988' in pico and "empagliflozin" in pico.lower()
    art = await tools["get_article"].ainvoke({"identifier": "38000001"})
    assert "Extracted effect estimates: HR 0.79 (95% CI 0.69–0.9)" in art


async def test_analyze_tool_rules_backend(tools):
    out = await tools["analyze_clinical_text"].ainvoke({"text": "80-year-old man, creatinine 1.1, weight 70 kg"})
    assert '"age": 80' in out and '"calculator": "cockcroft_gault"' in out and "NER model not installed" in out


@requires_ner
async def test_analyze_tool_with_ner(harness, ner):
    harness.ml.nlp = ner
    tools = {t.name: t for t in build_tools(harness, SourceRegistry(), SkillState(), SkillRegistry())}
    out = await tools["analyze_clinical_text"].ainvoke({"text": "70-year-old woman with heart failure, denies syncope, on furosemide."})
    assert "scispacy" in out and '"pertinent_negatives": ["syncope"]' in out and "furosemide" in out


async def test_load_skill_tool(harness):
    state = SkillState()
    tools = {t.name: t for t in build_tools(harness, SourceRegistry(), state, SkillRegistry())}
    out = await tools["load_skill"].ainvoke({"name": "trial-matching"})
    assert out.startswith("Loaded skill 'trial-matching'") and state.loaded == ["trial-matching"]
    assert "Unknown skill" in await tools["load_skill"].ainvoke({"name": "nope"})
