"""Clinical text understanding: biomedical NER + negation + abbreviations +
demographics / vitals / labs.

Backend "scispacy" uses a spaCy model trained on BC5CDR (diseases and
chemicals/drugs), the scispaCy abbreviation detector (Schwartz-Hearst) and
NegEx clinical negation via negspacy. Without those packages it degrades to
the deterministic regex layer, which always runs.
"""

from __future__ import annotations

import re
import threading
import warnings
from typing import Any

from pydantic import BaseModel, Field


class Entity(BaseModel):
    text: str
    label: str  # DISEASE | CHEMICAL
    negated: bool = False
    expansion: str | None = None
    start: int
    end: int


class Measurement(BaseModel):
    name: str
    value: float
    unit: str | None = None
    text: str


class ClinicalFindings(BaseModel):
    backend: str
    age: int | None = None
    sex: str | None = None
    conditions: list[str] = Field(default_factory=list)
    negated_conditions: list[str] = Field(default_factory=list)
    medications: list[str] = Field(default_factory=list)
    negated_medications: list[str] = Field(default_factory=list)
    abbreviations: dict[str, str] = Field(default_factory=dict)
    measurements: list[Measurement] = Field(default_factory=list)
    entities: list[Entity] = Field(default_factory=list)

    def measurement(self, name: str) -> float | None:
        return next((m.value for m in self.measurements if m.name == name), None)


# ------------------------------------------------------------- regex layer
_AGE = re.compile(r"\b(\d{1,3})[- ]?(?:year|yr|y)s?[- ]?old\b|\bage[d:]?\s*(\d{1,3})\b|\b(\d{1,3})\s*(?:yo|y/o)\b|\b(\d{1,3})\s*(?:M|F)\b", re.I)
_SEX = [(re.compile(r"\b(woman|female|lady|girl|she|her|mrs|ms)\b|\b\d{1,3}\s*F\b", re.I), "female"),
        (re.compile(r"\b(man|male|gentleman|boy|he|his|mr)\b|\b\d{1,3}\s*M\b", re.I), "male")]

_V = r"(\d+(?:\.\d+)?)"
MEASURES: list[tuple[str, re.Pattern[str], str | None]] = [
    ("creatinine_mg_dl", re.compile(rf"\b(?:serum\s+)?(?:creatinine|creat|Cr|SCr)\b\s*(?:of|is|was|:|=)?\s*{_V}\s*(?:mg/dl)?", re.I), "mg/dL"),
    ("creatinine_umol_l", re.compile(rf"\b(?:creatinine|creat|Cr|SCr)\b\s*(?:of|is|was|:|=)?\s*{_V}\s*(?:µmol/l|umol/l|micromol/l)", re.I), "µmol/L"),
    ("egfr", re.compile(rf"\beGFR\b\s*(?:of|is|was|:|=)?\s*{_V}", re.I), "mL/min/1.73m²"),
    ("heart_rate_bpm", re.compile(rf"\b(?:HR|heart rate|pulse)\b\s*(?:of|is|was|:|=)?\s*{_V}", re.I), "bpm"),
    ("systolic_bp", re.compile(r"\b(?:BP|blood pressure)\b\s*(?:of|is|was|:|=)?\s*(\d{2,3})\s*/\s*\d{2,3}", re.I), "mmHg"),
    ("diastolic_bp", re.compile(r"\b(?:BP|blood pressure)\b\s*(?:of|is|was|:|=)?\s*\d{2,3}\s*/\s*(\d{2,3})", re.I), "mmHg"),
    ("respiratory_rate", re.compile(rf"\b(?:RR|resp(?:iratory)? rate)\b\s*(?:of|is|was|:|=)?\s*{_V}", re.I), "/min"),
    ("oxygen_saturation_pct", re.compile(rf"\b(?:SpO2|SaO2|O2 sat(?:uration)?|sats?)\b\s*(?:of|is|was|:|=)?\s*{_V}\s*%?", re.I), "%"),
    ("temperature_c", re.compile(rf"\b(?:T|temp(?:erature)?)\b\s*(?:of|is|was|:|=)?\s*{_V}\s*°?\s*C\b", re.I), "°C"),
    ("weight_kg", re.compile(rf"\b(?:weight|wt|weighs|weighing)\b\s*(?:of|is|was|:|=)?\s*{_V}\s*kg|\b{_V}\s*kg\b", re.I), "kg"),
    ("height_cm", re.compile(rf"\b(?:height|ht)\b\s*(?:of|is|was|:|=)?\s*{_V}\s*cm|\b{_V}\s*cm\s+tall", re.I), "cm"),
    ("inr", re.compile(rf"\bINR\b\s*(?:of|is|was|:|=)?\s*{_V}", re.I), None),
    ("bilirubin_mg_dl", re.compile(rf"\b(?:total\s+)?bili(?:rubin)?\b\s*(?:of|is|was|:|=)?\s*{_V}", re.I), "mg/dL"),
    ("albumin_g_dl", re.compile(rf"\balbumin\b\s*(?:of|is|was|:|=)?\s*{_V}", re.I), "g/dL"),
    ("sodium", re.compile(rf"\b(?:Na\+?|sodium)\b\s*(?:of|is|was|:|=)?\s*{_V}", re.I), "mmol/L"),
    ("potassium", re.compile(rf"\b(?:K\+?|potassium)\b\s*(?:of|is|was|:|=)?\s*{_V}", re.I), "mmol/L"),
    ("chloride", re.compile(rf"\b(?:Cl-?|chloride)\b\s*(?:of|is|was|:|=)?\s*{_V}", re.I), "mmol/L"),
    ("bicarbonate", re.compile(rf"\b(?:HCO3-?|bicarb(?:onate)?|CO2)\b\s*(?:of|is|was|:|=)?\s*{_V}", re.I), "mmol/L"),
    ("glucose_mg_dl", re.compile(rf"\b(?:glucose|BG|blood sugar)\b\s*(?:of|is|was|:|=)?\s*{_V}", re.I), "mg/dL"),
    ("hba1c_pct", re.compile(rf"\b(?:HbA1c|A1c)\b\s*(?:of|is|was|:|=)?\s*{_V}\s*%?", re.I), "%"),
    ("hemoglobin_g_dl", re.compile(rf"\b(?:Hb|Hgb|ha?emoglobin)\b\s*(?:of|is|was|:|=)?\s*{_V}", re.I), "g/dL"),
    ("platelets_10e9_l", re.compile(rf"\b(?:plt|platelets?)\b\s*(?:count\s*)?(?:of|is|was|:|=)?\s*{_V}", re.I), "×10⁹/L"),
    ("ast_u_l", re.compile(rf"\bAST\b\s*(?:of|is|was|:|=)?\s*{_V}", re.I), "U/L"),
    ("alt_u_l", re.compile(rf"\bALT\b\s*(?:of|is|was|:|=)?\s*{_V}", re.I), "U/L"),
    ("total_cholesterol_mg_dl", re.compile(rf"\b(?:total cholesterol|TC)\b\s*(?:of|is|was|:|=)?\s*{_V}", re.I), "mg/dL"),
    ("hdl_mg_dl", re.compile(rf"\bHDL(?:-C)?\b\s*(?:of|is|was|:|=)?\s*{_V}", re.I), "mg/dL"),
    ("ldl_mg_dl", re.compile(rf"\bLDL(?:-C)?\b\s*(?:of|is|was|:|=)?\s*{_V}", re.I), "mg/dL"),
    ("calcium_mg_dl", re.compile(rf"\b(?:Ca|calcium)\b\s*(?:of|is|was|:|=)?\s*{_V}", re.I), "mg/dL"),
    ("qt_ms", re.compile(rf"\bQT\b\s*(?:interval\s*)?(?:of|is|was|:|=)?\s*{_V}\s*ms", re.I), "ms"),
]


def extract_demographics(text: str) -> tuple[int | None, str | None]:
    age = None
    m = _AGE.search(text)
    if m:
        age = int(next(g for g in m.groups() if g))
        age = age if 0 < age < 120 else None
    sex = None
    for pattern, label in _SEX:
        if pattern.search(text):
            sex = label
            break
    return age, sex


def extract_measurements(text: str) -> list[Measurement]:
    out: list[Measurement] = []
    seen: set[str] = set()
    for name, pattern, unit in MEASURES:
        m = pattern.search(text)
        if not m or name in seen:
            continue
        raw = next(g for g in m.groups() if g)
        out.append(Measurement(name=name, value=float(raw), unit=unit, text=m.group(0).strip()))
        seen.add(name)
    umol = next((x for x in out if x.name == "creatinine_umol_l"), None)
    if umol is not None:
        # "creatinine 115 µmol/L" also matches the unit-less mg/dL pattern; the explicit SI unit wins.
        out = [x for x in out if not (x.name == "creatinine_mg_dl" and x.value == umol.value)]
        if not any(x.name == "creatinine_mg_dl" for x in out):
            out.append(Measurement(name="creatinine_mg_dl", value=round(umol.value / 88.4, 2), unit="mg/dL",
                                   text=umol.text + " (converted)"))
    return out


# ------------------------------------------------------------ NER backend
_NEG_TRIGGER = re.compile(r"^(?:denies|denied|no|not|without|negative for|free of)\s+", re.I)
# Commas followed by these words usually start a new, affirmed clause ("no stroke, on metformin").
_TERMINATIONS = [", on", ", taking", ", with", ", has", ", but", ", started", ", reports", ", currently", ", now", ";"]


_PIPELINES: dict[str, Any] = {}  # loaded spaCy pipelines, shared across instances (loading takes seconds)
_PIPELINE_LOCK = threading.Lock()


class ClinicalNLP:
    def __init__(self, model: str = "en_ner_bc5cdr_md", enabled: bool = True):
        self.model_name = model
        self.enabled = enabled
        self._nlp = None
        self._error: str | None = None

    @property
    def status(self) -> dict[str, Any]:
        return {"component": "clinical_ner", "model": self.model_name, "loaded": self._nlp is not None, "error": self._error,
                "backend": f"scispacy:{self.model_name}" if self._nlp is not None else "rules"}

    def _load(self):
        if self._nlp is not None or self._error or not self.enabled:
            return self._nlp
        with _PIPELINE_LOCK:
            if self._nlp is not None or self._error:
                return self._nlp
            if self.model_name in _PIPELINES:
                self._nlp = _PIPELINES[self.model_name]
                return self._nlp
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    import spacy
                    from negspacy.negation import Negex  # noqa: F401  (registers the "negex" factory)
                    from negspacy.termsets import termset
                    from scispacy.abbreviation import AbbreviationDetector  # noqa: F401

                    nlp = spacy.load(self.model_name)
                    nlp.add_pipe("abbreviation_detector")
                    ts = termset("en_clinical")
                    ts.add_patterns({"termination": _TERMINATIONS})
                    nlp.add_pipe("negex", config={"neg_termset": ts.get_patterns(), "ent_types": ["DISEASE", "CHEMICAL"]})
                self._nlp = _PIPELINES[self.model_name] = nlp
            except Exception as exc:  # missing optional deps or model
                self._error = f"{exc.__class__.__name__}: {exc}"[:300]
        return self._nlp

    def analyze(self, text: str) -> ClinicalFindings:
        age, sex = extract_demographics(text)
        findings = ClinicalFindings(backend="rules", age=age, sex=sex, measurements=extract_measurements(text))
        nlp = self._load()
        if nlp is None:
            return findings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            doc = nlp(text[:100_000])
        findings.backend = f"scispacy:{self.model_name}"
        abbrevs = {a.text: a._.long_form.text for a in doc._.abbreviations}
        findings.abbreviations = abbrevs
        for ent in doc.ents:
            surface = ent.text
            negated = bool(ent._.negex)
            trigger = _NEG_TRIGGER.match(surface)
            if trigger:  # the NER span swallowed the negation cue ("Denies fever")
                surface, negated = surface[trigger.end():], True
            findings.entities.append(Entity(text=surface, label=ent.label_, negated=negated,
                                            expansion=abbrevs.get(ent.text), start=ent.start_char, end=ent.end_char))
        for ent in findings.entities:
            name = ent.expansion or ent.text
            bucket = (("negated_conditions" if ent.negated else "conditions") if ent.label == "DISEASE"
                      else ("negated_medications" if ent.negated else "medications"))
            values = getattr(findings, bucket)
            if name.lower() not in (v.lower() for v in values):
                values.append(name)
        return findings


# ------------------------------------------------- findings → calculators
_ALIASES = {
    "creatinine_mg_dl": "creatinine_mg_dl", "weight_kg": "weight_kg", "height_cm": "height_cm", "inr": "inr",
    "bilirubin_mg_dl": "bilirubin_mg_dl", "albumin_g_dl": "albumin_g_dl", "sodium_mmol_l": "sodium", "sodium": "sodium",
    "chloride": "chloride", "bicarbonate": "bicarbonate", "glucose_mg_dl": "glucose_mg_dl", "calcium_mg_dl": "calcium_mg_dl",
    "ast_u_l": "ast_u_l", "alt_u_l": "alt_u_l", "platelets_10e9_l": "platelets_10e9_l", "heart_rate_bpm": "heart_rate_bpm",
    "oxygen_saturation_pct": "oxygen_saturation_pct", "systolic_bp": "systolic_bp", "qt_ms": "qt_ms",
    "total_cholesterol_mg_dl": "total_cholesterol_mg_dl", "hdl_mg_dl": "hdl_mg_dl",
}
_CONDITION_FLAGS = {
    "hypertension": re.compile(r"hypertension|\bHTN\b", re.I),
    "diabetes": re.compile(r"diabet|\bT2DM\b|\bDM\b", re.I),
    "congestive_heart_failure": re.compile(r"heart failure|\bCHF\b|\bHF(rEF|pEF)?\b|cardiomyopathy", re.I),
    "stroke_tia_thromboembolism": re.compile(r"stroke|\bTIA\b|transient ischa?emic|embol", re.I),
    "vascular_disease": re.compile(r"myocardial infarction|\bMI\b|peripheral arter|\bPAD\b|aortic plaque", re.I),
}


def prefill_calculator(calc_name: str, findings: ClinicalFindings) -> tuple[dict[str, Any], list[str]]:
    """Map extracted findings onto a calculator's inputs; returns (params, missing_required)."""
    from .calculators import REGISTRY

    calc = REGISTRY[calc_name]
    fields = calc.inputs.model_fields
    params: dict[str, Any] = {}
    if "age" in fields and findings.age is not None:
        params["age"] = findings.age
    if "sex" in fields and findings.sex:
        params["sex"] = findings.sex
    for m in findings.measurements:
        key = next((f for f, src in _ALIASES.items() if src == m.name and f in fields), None)
        if key:
            params[key] = m.value
    affirmed = " ; ".join(findings.conditions)
    negated = " ; ".join(findings.negated_conditions)
    for flag, pattern in _CONDITION_FLAGS.items():
        if flag in fields:
            if pattern.search(affirmed):
                params[flag] = True
            elif pattern.search(negated):
                params[flag] = False
    missing = [name for name, f in fields.items() if f.is_required() and name not in params]
    return params, missing
