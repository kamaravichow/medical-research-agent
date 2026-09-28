"""Function-calling tools backed by specialised medical ML models and
deterministic clinical calculators. Their outputs are reproducible, so the
LLM quotes numbers instead of generating them."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from .ml import calculators, prefill_calculator
from .ml.calculators import CalculatorError
from .ml.effects import extract_effects
from .ml.stats import DiagnosticIn, EffectIn, diagnostic_probability, treatment_effect
from .models import Article

if TYPE_CHECKING:
    from .harness import ResearchHarness
    from .skills import SkillRegistry, SkillState
    from .sources import SourceRegistry


class ClinicalTextArgs(BaseModel):
    text: str = Field(..., min_length=3, description="The clinical vignette or note, verbatim.")


class SourceTextArgs(BaseModel):
    source: str = Field(..., description="A citation number like '[3]', a PMID, 'doi:…', or raw abstract/results text.")


class ListCalcArgs(BaseModel):
    category: str | None = Field(None, description="Optional filter: Kidney, Cardiology, Pulmonary, Critical care, Hepatology, Labs, General.")


class RunCalcArgs(BaseModel):
    name: str = Field(..., description="Calculator name from list_calculators, e.g. 'cha2ds2_vasc', 'cockcroft_gault', 'ckd_epi_2021'.")
    inputs: dict[str, Any] = Field(..., description="Inputs exactly as named in the calculator schema.")


class LoadSkillArgs(BaseModel):
    name: str = Field(..., description="Skill name from the available-skills list.")


def _fmt(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str, separators=(", ", ": "))


def ml_specs(harness: "ResearchHarness", registry: "SourceRegistry", state: "SkillState | None",
             skills: "SkillRegistry | None") -> list[tuple]:
    hub = harness.ml

    async def resolve_text(source: str) -> tuple[str, str]:
        """Return (text, label) for a citation number, identifier or raw text."""
        s = source.strip()
        ref = re.fullmatch(r"\[?(\d{1,3})\]?", s)
        art: Article | None = None
        if ref and len(s) <= 5:
            record = registry.get(int(ref.group(1)))
            if record is None:
                raise ValueError(f"No source {s} in this conversation")
            if isinstance(record, Article):
                art = record
                if art.pmid and not art.sections:
                    art = await harness.article(f"pmid:{art.pmid}") or art
            else:
                text = getattr(record, "summary", None) or getattr(record, "snippet", None) or ""
                return text, f"[{ref.group(1)}]"
        elif re.fullmatch(r"\d{6,9}", s) or s.lower().startswith(("pmid:", "doi:")):
            art = await harness.article(s)
            if art is None:
                raise ValueError(f"No article found for {s}")
        if art is not None:
            n = registry.add(art)
            return f"{art.title}. {art.abstract or ''}", f"[{n}]"
        return s, "text"

    async def analyze_clinical_text(text: str) -> str:
        f = await hub.analyze(text)
        ready, partial = [], []
        for name in calculators.REGISTRY:
            params, missing = prefill_calculator(name, f)
            if not params:
                continue
            if not missing:
                ready.append({"calculator": name, "inputs": params})
            elif len(missing) <= 2 and len(params) >= 2:
                partial.append({"calculator": name, "have": params, "missing": missing})
        out = {
            "model": f.backend,
            "age": f.age, "sex": f.sex,
            "conditions": f.conditions, "pertinent_negatives": f.negated_conditions,
            "medications": f.medications, "negated_medications": f.negated_medications,
            "abbreviations": f.abbreviations,
            "measurements": {m.name: m.value for m in f.measurements},
            "calculators_ready": ready[:8],
            "calculators_missing_inputs": partial[:8],
        }
        note = ("" if f.backend != "rules" else
                "\nNote: biomedical NER model not installed; conditions/medications were not extracted, only demographics, vitals and labs.")
        return "Clinical NLP analysis:\n" + _fmt(out) + note + (
            "\nFor boolean criteria (e.g. hypertension=true), confirm them against the text before running calculators.")

    async def extract_pico(source: str) -> str:
        text, label = await resolve_text(source)
        pico = await hub.extract_pico(text)
        return f"PICO for {label} (model: {pico.backend}):\n" + _fmt(pico.model_dump(exclude={"backend"}))

    async def extract_effect_sizes(source: str) -> str:
        text, label = await resolve_text(source)
        report = extract_effects(text)
        if not (report.effects or report.nnt or report.arm_percentages):
            return f"No effect estimates found in {label}. Use read_source for full-text results."
        rows = [
            {"measure": e.measure, "estimate": e.value, "ci": [e.ci_low, e.ci_high] if e.ci_low is not None else None,
             "p": e.p_value, "significant": e.significant, "verbatim": e.text}
            for e in report.effects
        ]
        return f"Effect estimates in {label} (deterministic extraction; verbatim spans included):\n" + _fmt(
            {"effects": rows, "nnt": report.nnt, "arm_event_rates": report.arm_percentages})

    async def list_calculators(category: str | None = None) -> str:
        lines = []
        for c in calculators.REGISTRY.values():
            if category and c.category.lower() != category.lower():
                continue
            fields = []
            for fname, f in c.inputs.model_fields.items():
                ann = getattr(f.annotation, "__name__", str(f.annotation)).replace("typing.", "")
                fields.append(f"{fname}{'' if f.is_required() else '?'}:{ann}")
            lines.append(f"- {c.name} [{c.category}] {c.title}: {c.description}\n    inputs: {', '.join(fields)}")
        return "\n".join(lines) or "No calculators in that category."

    async def run_calculator(name: str, inputs: dict[str, Any]) -> str:
        try:
            result = calculators.run(name, inputs)
        except CalculatorError as exc:
            return f"Calculator error: {exc}"
        return (f"{result.title}: {result.value:g}{(' ' + result.unit) if result.unit else ''}"
                f"{(' — ' + result.band) if result.band else ''}\n{result.interpretation}\n"
                f"Inputs: {_fmt(result.inputs)}\n"
                + (f"Details: {_fmt(result.details)}\n" if result.details else "")
                + f"Reference: {calculators.REGISTRY[name].reference}\n"
                + (f"Caveats: {' | '.join(result.caveats)}" if result.caveats else ""))

    async def diagnostic_probability_tool(**kwargs) -> str:
        return "Bayesian post-test probability:\n" + _fmt(diagnostic_probability(DiagnosticIn(**kwargs)))

    async def treatment_effect_tool(**kwargs) -> str:
        return "Absolute treatment effect:\n" + _fmt(treatment_effect(EffectIn(**kwargs)))

    async def load_skill(name: str) -> str:
        if skills is None:
            return "Skills are not enabled."
        skill = skills.get(name)
        if skill is None:
            return f"Unknown skill '{name}'. Available: {', '.join(skills.skills)}"
        if state is not None and name not in state.loaded:
            state.loaded.append(name)
        return f"Loaded skill '{name}'. Follow these instructions:\n\n{skill.instructions()}"

    calc_names = ", ".join(sorted(calculators.REGISTRY))
    specs = [
        (analyze_clinical_text, ClinicalTextArgs, "analyze_clinical_text",
         "Specialised clinical NLP (scispaCy BC5CDR NER + NegEx negation + abbreviation expansion + vitals/labs extraction). "
         "Use first on any patient vignette: returns age, sex, affirmed vs NEGATED conditions and drugs, labs, and which calculators can be run."),
        (extract_pico, SourceTextArgs, "extract_pico",
         "PICO extraction model (BioELECTRA-PICO trained on EBM-NLP, rule fallback) over an abstract: population, intervention, comparator, outcomes, n."),
        (extract_effect_sizes, SourceTextArgs, "extract_effect_sizes",
         "Deterministic extraction of HR/OR/RR/RD/MD with 95% CI, p-values, NNTs and arm event rates from an abstract, with verbatim spans."),
        (list_calculators, ListCalcArgs, "list_calculators", "List validated clinical calculators and their input schemas."),
        (run_calculator, RunCalcArgs, "run_calculator",
         f"Run a validated clinical calculator deterministically. NEVER compute scores yourself. Available: {calc_names}."),
        (diagnostic_probability_tool, DiagnosticIn, "diagnostic_probability",
         "Bayes: post-test probability from pre-test probability and sensitivity/specificity or likelihood ratios; also PPV/NPV."),
        (treatment_effect_tool, EffectIn, "treatment_effect",
         "ARR, RRR, NNT/NNH with 95% CI from event counts or arm risks, or apply an RR/HR to a patient's baseline risk."),
    ]
    if skills is not None:
        specs.append((load_skill, LoadSkillArgs, "load_skill",
                      "Load a specialised clinical skill (playbook) by name when the question needs one that is not active."))
    return specs
