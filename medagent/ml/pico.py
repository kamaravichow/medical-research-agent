"""PICO extraction (Population, Intervention, Comparator, Outcome).

Backends, in order of preference:
  1. A token-classification transformer fine-tuned on EBM-NLP
     (default kamalkraj/BioELECTRA-PICO, ~110M params, F1≈0.74 on EBM-NLP).
  2. A deterministic rule extractor over the abstract's own wording
     ("randomly assigned to X or Y", "patients with ...", "primary outcome was ...")
     augmented with biomedical NER entities.
"""

from __future__ import annotations

import re
import threading
from typing import Any

from pydantic import BaseModel, Field


class PICO(BaseModel):
    backend: str
    population: list[str] = Field(default_factory=list)
    intervention: list[str] = Field(default_factory=list)
    comparator: list[str] = Field(default_factory=list)
    outcomes: list[str] = Field(default_factory=list)
    sample_size: int | None = None
    design_hint: str | None = None


def _dedupe(items: list[str], limit: int = 6) -> list[str]:
    out: list[str] = []
    for item in items:
        item = re.sub(r"\s+", " ", item).strip(" ,.;:")
        item = item.lstrip("(")
        if item.count("(") > item.count(")"):
            item += ")"
        elif item.endswith(")") and item.count(")") > item.count("("):
            item = item[:-1]
        if len(item) < 3:
            continue
        if not any(item.lower() in o.lower() or o.lower() in item.lower() for o in out):
            out.append(item)
    return out[:limit]


# ------------------------------------------------------------------ rules
_ASSIGN = re.compile(
    r"(?:randomly\s+)?(?:assigned|allocated|randomi[sz]ed)\s+(?:[^.;]{0,220}?\s)?(?:in a \d:\d ratio\s+)?to\s+(?:receive\s+)?"
    r"(?P<a>[^.;]{3,120}?)\s+(?:or|versus|vs\.?|compared with)\s+(?:to\s+)?(?:receive\s+)?(?P<b>[^.;,]{3,80})", re.I)
_VERSUS = re.compile(r"(?P<a>\b[\w-]+(?:\s[\w-]+){0,4})\s+(?:versus|vs\.?|compared with|compared to)\s+(?P<b>[\w-]+(?:\s[\w-]+){0,4})", re.I)
_POP = re.compile(
    r"\b(?:(?:adult|pediatric|paediatric|elderly|older|hospitali[sz]ed|critically ill|consecutive|eligible)\s+)?"
    r"(?:patients|participants|adults|children|women|men|infants|individuals|people|persons|subjects)\s+"
    r"(?:(?:aged|age)\s[^,.;]{2,30}\s)?(?:with|who|undergoing|admitted|presenting|at|hospitali[sz]ed)\s+(?P<p>[^.;]{4,140})", re.I)
_POP_END = re.compile(r"\s+(?:to receive|to be|to either|were|was|who were|in a \d:\d ratio)\b|\s+to\s+(?=[a-z]+(?:\s|\())", re.I)
_OUTCOME = re.compile(r"\b(?:primary|secondary|main|co-primary)\s+(?:efficacy\s+|safety\s+)?(?:outcome|end\s?point)s?\s+(?:was|were|is|included|:)\s+(?P<o>[^.;]{4,200})", re.I)


def rule_pico(text: str, entities: list[Any] | None = None) -> PICO:
    from ..evidence import extract_sample_size

    pico = PICO(backend="rules")
    for m in _ASSIGN.finditer(text):
        pico.intervention.append(m.group("a"))
        pico.comparator.append(m.group("b"))
    if not pico.intervention:
        for m in _VERSUS.finditer(text):
            pico.intervention.append(m.group("a"))
            pico.comparator.append(m.group("b"))
            break
    pico.population = [_POP_END.split(m.group("p"))[0] for m in _POP.finditer(text)]
    pico.outcomes = [m.group("o") for m in _OUTCOME.finditer(text)]
    if entities:
        chems = [e.text for e in entities if e.label == "CHEMICAL" and not e.negated]
        dis = [e.expansion or e.text for e in entities if e.label == "DISEASE" and not e.negated]
        if not pico.intervention and chems:
            pico.intervention = chems[:2]
        if not pico.population and dis:
            pico.population = [f"patients with {dis[0]}"]
    if re.search(r"placebo", text, re.I) and not any("placebo" in c.lower() for c in pico.comparator):
        pico.comparator.append("placebo")
    pico.population, pico.intervention = _dedupe(pico.population, 3), _dedupe(pico.intervention, 4)
    pico.comparator, pico.outcomes = _dedupe(pico.comparator, 3), _dedupe(pico.outcomes, 4)
    pico.sample_size = extract_sample_size(text)
    if re.search(r"randomi[sz]ed|randomly assigned", text, re.I):
        pico.design_hint = "randomised"
    elif re.search(r"cohort|retrospective|registry", text, re.I):
        pico.design_hint = "observational"
    return pico


# ------------------------------------------------------------ transformer
_LABEL_MAP = {"PAR": "population", "POP": "population", "P": "population", "INT": "intervention", "I": "intervention",
              "COMP": "comparator", "C": "comparator", "OUT": "outcomes", "O": "outcomes"}


class PICOExtractor:
    def __init__(self, model: str | None = "kamalkraj/BioELECTRA-PICO", enabled: bool = True, pipeline_factory=None):
        self.model_name = model
        self.enabled = enabled and bool(model)
        self._pipe = None
        self._error: str | None = None
        self._factory = pipeline_factory  # injectable for tests
        self._lock = threading.Lock()

    @property
    def status(self) -> dict[str, Any]:
        return {"component": "pico", "model": self.model_name, "loaded": self._pipe is not None, "error": self._error,
                "backend": f"transformers:{self.model_name}" if self._pipe is not None else "rules"}

    def _load(self):
        if self._pipe is not None or self._error or not self.enabled:
            return self._pipe
        with self._lock:
            if self._pipe is None and not self._error:
                try:
                    if self._factory is not None:
                        self._pipe = self._factory(self.model_name)
                    else:
                        from transformers import pipeline

                        self._pipe = pipeline("token-classification", model=self.model_name, aggregation_strategy="simple")
                except Exception as exc:
                    self._error = f"{exc.__class__.__name__}: {exc}"[:300]
        return self._pipe

    def extract(self, text: str, entities: list[Any] | None = None) -> PICO:
        rules = rule_pico(text, entities)
        pipe = self._load()
        if pipe is None:
            return rules
        try:
            spans = pipe(text[:4000])
        except Exception as exc:
            self._error = f"inference: {exc}"[:300]
            return rules
        found: dict[str, list[str]] = {"population": [], "intervention": [], "comparator": [], "outcomes": []}
        for span in spans:
            label = str(span.get("entity_group") or span.get("entity") or "").upper()
            label = re.sub(r"^[BI]-", "", label)
            key = next((v for k, v in _LABEL_MAP.items() if label == k or label.endswith(k)), None)
            if key and float(span.get("score", 1)) >= 0.5:
                found[key].append(str(span.get("word", "")).replace(" ##", "").replace("##", ""))
        model_pico = PICO(backend=f"transformers:{self.model_name}",
                          population=_dedupe(found["population"], 3), intervention=_dedupe(found["intervention"], 4),
                          comparator=_dedupe(found["comparator"], 3), outcomes=_dedupe(found["outcomes"], 5),
                          sample_size=rules.sample_size, design_hint=rules.design_hint)
        # EBM-NLP merges comparator into intervention; keep the rule-based split when the model has none.
        if not model_pico.comparator:
            model_pico.comparator = rules.comparator
        for key in ("population", "intervention", "outcomes"):
            if not getattr(model_pico, key):
                setattr(model_pico, key, getattr(rules, key))
        return model_pico
