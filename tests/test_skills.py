import pytest

from medagent.skills import SkillRegistry, SkillState, parse_skill, skills_prompt
from medagent.sources import SourceRegistry
from medagent.tools import build_tools


@pytest.fixture(scope="module")
def skills():
    return SkillRegistry()


def test_library_loads_and_is_well_formed(skills):
    assert set(skills.skills) == {"patient-case", "therapy-evidence", "critical-appraisal", "drug-dosing-safety", "risk-scores",
                                  "diagnostic-reasoning", "trial-matching", "guideline-synthesis", "literature-surveillance"}
    for s in skills.skills.values():
        assert s.description and s.triggers and len(s.body) > 400


async def test_every_skill_tool_exists(skills, harness):
    names = {t.name for t in build_tools(harness, SourceRegistry(), SkillState(), skills)}
    for s in skills.skills.values():
        assert set(s.tools) <= names, (s.name, set(s.tools) - names)


@pytest.mark.parametrize("question,labels,expected", [
    ("72-year-old woman with AF and CKD, creatinine 1.4. Which DOAC dose?", ["DISEASE", "DISEASE", "CHEMICAL"], {"patient-case", "drug-dosing-safety"}),
    ("Does colchicine reduce cardiovascular events after MI?", ["CHEMICAL", "DISEASE"], {"therapy-evidence"}),
    ("Appraise PMID 38000001 for risk of bias", [], {"critical-appraisal"}),
    ("What do ESC and ACC guidelines recommend for HFpEF?", ["DISEASE"], {"guideline-synthesis"}),
    ("Sensitivity of D-dimer to rule out PE in pregnancy", ["CHEMICAL", "DISEASE"], {"diagnostic-reasoning"}),
    ("Recruiting trials for glioblastoma near Boston", ["DISEASE"], {"trial-matching"}),
    ("Calculate HAS-BLED for my patient", [], {"risk-scores"}),
    ("What's new this month in Alzheimer's disease?", ["DISEASE"], {"literature-surveillance"}),
])
def test_routing(skills, question, labels, expected):
    got = {m.skill.name for m in skills.route(question, labels)}
    assert expected <= got, got


def test_no_skill_for_small_talk(skills):
    assert skills.route("hello there", []) == []


def test_prompt_includes_active_and_loaded(skills):
    active = skills.route("Calculate HAS-BLED", [])
    text = skills_prompt(skills, active, loaded=["trial-matching"])
    assert "## Skill: Risk scores" in text and "## Skill: Clinical trial matching" in text
    assert "- guideline-synthesis:" in text  # index of all skills


def test_custom_skill_dir_overrides(tmp_path):
    d = tmp_path / "my-skill"
    d.mkdir()
    (d / "SKILL.md").write_text("---\nname: my-skill\ndescription: Local protocol.\ntriggers: ['\\bprotocol\\b']\n---\n# Local\nUse our sepsis protocol.")
    reg = SkillRegistry([tmp_path])
    assert reg.route("what is our protocol", [])[0].skill.name == "my-skill"
    with pytest.raises(ValueError):
        (d / "SKILL.md").write_text("no front matter")
        parse_skill(d / "SKILL.md")
