"""Deterministic extraction of reported effect estimates from abstracts.

Pulls hazard/odds/risk ratios, mean differences, NNTs, p-values and per-arm
percentages with their confidence intervals, so the model quotes numbers that
are verbatim in the source instead of recalling them.
"""

from __future__ import annotations

import re

from pydantic import BaseModel

_NUM = r"[−–-]?\d+(?:\.\d+)?"
_MEASURES = {  # full names are case-insensitive; abbreviations must be upper-case ("or 4" is not an odds ratio)
    "HR": r"(?:(?:adjusted\s+|pooled\s+)?hazard\s+ratio|(?-i:a?HR))",
    "OR": r"(?:(?:adjusted\s+|pooled\s+)?odds\s+ratio|(?-i:a?OR))",
    "RR": r"(?:(?:adjusted\s+|pooled\s+)?(?:relative\s+risk|risk\s+ratio|rate\s+ratio)|(?-i:a?RR|IRR))",
    "RD": r"(?:(?:absolute\s+)?(?:risk\s+difference|absolute\s+risk\s+reduction)|(?-i:ARR|RD))",
    "MD": r"(?:standardi[sz]ed\s+mean\s+difference|weighted\s+mean\s+difference|mean\s+difference|(?-i:SMD|WMD|MD))",
}
_CI = rf"(?:(?P<level>\d{{2}})\s*%\s*(?:confidence\s+interval|CI|CrI|credible\s+interval)(?:\s*\[CI\])?\s*[,:=]?\s*)?[\[(]?\s*(?P<lo>{_NUM})\s*(?:to|–|—|-|,)\s*(?P<hi>{_NUM})\s*[\])]?"
_EST = rf"(?P<measure>{'|'.join(f'(?:{v})' for v in _MEASURES.values())})\s*(?:\(|,|:|=|of|was)?\s*(?P<value>{_NUM})"
_UNIT = r"(?:\s*(?:mm\s*Hg|%|kg|points?|mg/dL|mmol/L|days?|weeks?|months?|percentage\s+points?|ml/min(?:/1\.73\s*m2)?))?"
PATTERN = re.compile(rf"\b{_EST}{_UNIT}\s*(?:[;,(\[]\s*)?(?:{_CI})?", re.I)
P_VALUE = re.compile(r"\b[Pp]\s*(?P<op>[<>=≤≥])\s*(?P<p>0?\.\d+|\d(?:\.\d+)?\s*[×x]\s*10\s*[−-]\s*\d+)")
NNT = re.compile(r"\b(?P<kind>NNT|NNH|number needed to (?:treat|harm))\s*(?:\(|,|:|=|was|of)?\s*(?P<value>\d+(?:\.\d+)?)", re.I)
ARMS = re.compile(r"(?P<a>\d{1,2}(?:\.\d+)?)\s*%\s*(?:\([^)]{0,30}\)\s*)?(?:vs\.?|versus|and|compared with)\s*(?P<b>\d{1,2}(?:\.\d+)?)\s*%", re.I)


class Effect(BaseModel):
    measure: str
    value: float
    ci_low: float | None = None
    ci_high: float | None = None
    ci_level: int | None = None
    p_value: str | None = None
    significant: bool | None = None
    text: str


class EffectReport(BaseModel):
    effects: list[Effect]
    nnt: list[str]
    arm_percentages: list[str]


def _num(s: str) -> float:
    return float(s.replace("−", "-").replace("–", "-"))


def _canonical(measure: str) -> str:
    m = measure.lower()
    for key, pattern in _MEASURES.items():
        if re.fullmatch(pattern, measure, re.I):
            return "SMD" if key == "MD" and ("standard" in m or m == "smd") else key
    return measure.upper()


def extract_effects(text: str) -> EffectReport:
    effects: list[Effect] = []
    for m in PATTERN.finditer(text):
        measure = _canonical(m.group("measure"))
        value = _num(m.group("value"))
        lo = _num(m.group("lo")) if m.group("lo") else None
        hi = _num(m.group("hi")) if m.group("hi") else None
        if lo is not None and hi is not None and lo > hi:
            lo, hi = hi, lo
        if lo is not None and hi is not None and not (lo <= value <= hi):
            lo = hi = None  # the "CI" match was something else
        tail = text[m.end(): m.end() + 40]
        pm = P_VALUE.search(tail)
        null = 0.0 if measure in ("RD", "MD", "SMD") else 1.0
        significant = None if lo is None else not (lo <= null <= hi)
        if measure in ("HR", "OR", "RR") and value <= 0:
            continue
        effects.append(Effect(
            measure=measure, value=value, ci_low=lo, ci_high=hi,
            ci_level=int(m.group("level")) if m.group("level") else (95 if lo is not None else None),
            p_value=f"P{pm.group('op')}{pm.group('p')}" if pm else None, significant=significant,
            text=text[m.start(): m.end() + (pm.end() if pm else 0)].strip(" ;,"),
        ))
    nnts = [f"{m.group('kind').upper() if len(m.group('kind')) == 3 else m.group('kind')} {m.group('value')}" for m in NNT.finditer(text)]
    arms = [f"{m.group('a')}% vs {m.group('b')}%" for m in ARMS.finditer(text)]
    return EffectReport(effects=effects, nnt=nnts, arm_percentages=arms)
