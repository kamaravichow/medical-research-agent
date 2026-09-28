"""Evidence arithmetic that LLMs routinely get wrong: Bayes with likelihood
ratios, and absolute effects (ARR/NNT) from trial results."""

from __future__ import annotations

import math

from pydantic import BaseModel, Field, model_validator

Z95 = 1.959964


class DiagnosticIn(BaseModel):
    pretest_probability: float = Field(..., gt=0, lt=1, description="0–1, e.g. 0.15 for 15%")
    sensitivity: float | None = Field(None, gt=0, le=1)
    specificity: float | None = Field(None, ge=0, lt=1)
    lr_positive: float | None = Field(None, gt=0)
    lr_negative: float | None = Field(None, gt=0)
    result: str = Field("both", pattern="^(positive|negative|both)$")

    @model_validator(mode="after")
    def _need_accuracy(self):
        if self.lr_positive is None and self.lr_negative is None and (self.sensitivity is None or self.specificity is None):
            raise ValueError("Give sensitivity+specificity or at least one likelihood ratio")
        return self


def _post(pre: float, lr: float) -> float:
    odds = pre / (1 - pre) * lr
    return odds / (1 + odds)


def diagnostic_probability(p: DiagnosticIn) -> dict:
    lr_pos, lr_neg = p.lr_positive, p.lr_negative
    if p.sensitivity is not None and p.specificity is not None:
        lr_pos = lr_pos or (p.sensitivity / (1 - p.specificity) if p.specificity < 1 else math.inf)
        lr_neg = lr_neg or ((1 - p.sensitivity) / p.specificity if p.specificity > 0 else math.inf)
    out: dict = {"pretest_probability": p.pretest_probability, "lr_positive": lr_pos, "lr_negative": lr_neg}
    if lr_pos is not None and p.result in ("positive", "both"):
        out["posttest_if_positive"] = round(_post(p.pretest_probability, lr_pos), 4) if math.isfinite(lr_pos) else 1.0
    if lr_neg is not None and p.result in ("negative", "both"):
        out["posttest_if_negative"] = round(_post(p.pretest_probability, lr_neg), 4)
    if p.sensitivity is not None and p.specificity is not None:
        prev, se, sp = p.pretest_probability, p.sensitivity, p.specificity
        out["ppv"] = round(se * prev / (se * prev + (1 - sp) * (1 - prev)), 4)
        out["npv"] = round(sp * (1 - prev) / (sp * (1 - prev) + (1 - se) * prev), 4)
    strength = []
    for label, lr in (("positive", lr_pos), ("negative", lr_neg)):
        if lr is None or not math.isfinite(lr):
            continue
        mag = max(lr, 1 / lr)
        strength.append(f"LR{'+' if label == 'positive' else '−'} {lr:.2f} "
                        + ("(large, often conclusive)" if mag >= 10 else "(moderate)" if mag >= 5 else "(small)" if mag >= 2 else "(minimal)"))
    out["interpretation"] = "; ".join(strength)
    return out


class EffectIn(BaseModel):
    control_risk: float | None = Field(None, gt=0, lt=1, description="Event risk in control arm (0–1) or baseline risk")
    treatment_risk: float | None = Field(None, ge=0, lt=1)
    control_events: int | None = Field(None, ge=0)
    control_total: int | None = Field(None, gt=0)
    treatment_events: int | None = Field(None, ge=0)
    treatment_total: int | None = Field(None, gt=0)
    relative_risk: float | None = Field(None, gt=0, description="RR (or HR as an approximation) to apply to control_risk")
    hazard_ratio: float | None = Field(None, gt=0, description="HR applied as 1-(1-baseline)^HR")
    rr_ci: tuple[float, float] | None = Field(None, description="95% CI of RR/HR, to propagate to ARR/NNT")
    timeframe: str | None = Field(None, description="e.g. '2 years' (reported with the NNT)")


def _arr_to_nnt(arr: float) -> float:
    # round before ceil so 1/0.02 = 50.000000000000004 stays 50
    return math.inf if abs(arr) < 1e-12 else round(1 / abs(arr), 6)


def treatment_effect(p: EffectIn) -> dict:
    ci = None
    if p.control_events is not None and p.control_total and p.treatment_events is not None and p.treatment_total:
        cr, tr = p.control_events / p.control_total, p.treatment_events / p.treatment_total
        se = math.sqrt(cr * (1 - cr) / p.control_total + tr * (1 - tr) / p.treatment_total)
        ci = (cr - tr - Z95 * se, cr - tr + Z95 * se)
        source = "event counts"
    elif p.control_risk is not None and p.treatment_risk is not None:
        cr, tr = p.control_risk, p.treatment_risk
        source = "arm risks"
    elif p.control_risk is not None and (p.relative_risk or p.hazard_ratio):
        cr = p.control_risk
        if p.hazard_ratio:
            tr = 1 - (1 - cr) ** p.hazard_ratio
            conv = lambda h: cr - (1 - (1 - cr) ** h)  # noqa: E731
            source = "baseline risk × HR"
        else:
            tr = cr * p.relative_risk  # type: ignore[operator]
            conv = lambda r: cr - cr * r  # noqa: E731
            source = "baseline risk × RR"
        if p.rr_ci:
            ci = tuple(sorted((conv(p.rr_ci[1]), conv(p.rr_ci[0]))))
    else:
        raise ValueError("Give event counts, both arm risks, or control_risk with relative_risk/hazard_ratio")

    arr = cr - tr
    rr = tr / cr
    out = {
        "source": source,
        "control_risk": round(cr, 4),
        "treatment_risk": round(tr, 4),
        "absolute_risk_reduction": round(arr, 4),
        "relative_risk": round(rr, 3),
        "relative_risk_reduction": round(1 - rr, 3),
    }
    kind = "NNT" if arr > 0 else "NNH"
    nnt = _arr_to_nnt(arr)
    out[kind.lower()] = math.ceil(nnt) if math.isfinite(nnt) else None
    when = f" over {p.timeframe}" if p.timeframe else ""
    text = (f"ARR {arr * 100:.1f} percentage points ({cr * 100:.1f}% → {tr * 100:.1f}%), RRR {(1 - rr) * 100:.0f}%; "
            f"{kind} {out[kind.lower()]}{when}.")
    if ci:
        lo, hi = ci
        out["arr_95ci"] = (round(lo, 4), round(hi, 4))
        if lo > 0 or hi < 0:
            out["nnt_95ci"] = tuple(sorted((math.ceil(_arr_to_nnt(hi)), math.ceil(_arr_to_nnt(lo)))))
            text += f" 95% CI of ARR {lo * 100:.1f} to {hi * 100:.1f} points ({kind} {out['nnt_95ci'][0]}–{out['nnt_95ci'][1]})."
        else:
            text += f" 95% CI of ARR {lo * 100:.1f} to {hi * 100:.1f} points crosses zero: NNT not significant (NNTB to NNTH)."
    out["interpretation"] = text
    return out
