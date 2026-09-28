"""Validated clinical prediction rules and equations.

Deterministic: the same inputs always give the same output, so the agent calls
these through function calling instead of doing clinical arithmetic in text.
Every calculator has a typed input schema (which becomes the tool/JSON schema),
a primary reference, and caveats about the population it was validated in.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

Sex = Literal["female", "male"]


class CalcResult(BaseModel):
    calculator: str
    title: str
    value: float
    unit: str | None = None
    band: str | None = Field(None, description="Risk / severity category the value falls in")
    interpretation: str
    details: dict[str, Any] = Field(default_factory=dict)
    inputs: dict[str, Any] = Field(default_factory=dict)
    reference: str
    caveats: list[str] = Field(default_factory=list)


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


@dataclass
class Calculator:
    name: str
    title: str
    category: str
    description: str
    inputs: type[_In]
    fn: Callable[[Any], CalcResult]
    reference: str
    caveats: list[str] = field(default_factory=list)

    def schema(self) -> dict[str, Any]:
        return self.inputs.model_json_schema()

    def run(self, params: dict[str, Any]) -> CalcResult:
        parsed = self.inputs.model_validate(params)
        result = self.fn(parsed)
        result.inputs = parsed.model_dump()
        result.caveats = self.caveats + result.caveats
        return result


REGISTRY: dict[str, Calculator] = {}


def calculator(name: str, title: str, category: str, description: str, inputs: type[_In], reference: str,
               caveats: list[str] | None = None):
    def register(fn: Callable[[Any], CalcResult]):
        REGISTRY[name] = Calculator(name, title, category, description, inputs, fn, reference, caveats or [])
        return fn
    return register


class CalculatorError(ValueError):
    pass


def run(name: str, params: dict[str, Any]) -> CalcResult:
    calc = REGISTRY.get(name)
    if calc is None:
        raise CalculatorError(f"Unknown calculator '{name}'. Available: {', '.join(sorted(REGISTRY))}")
    try:
        return calc.run(params)
    except ValidationError as exc:
        problems = "; ".join(f"{'.'.join(str(p) for p in e['loc']) or 'input'}: {e['msg']}" for e in exc.errors())
        required = [k for k, v in calc.inputs.model_fields.items() if v.is_required()]
        raise CalculatorError(f"{name}: invalid inputs ({problems}). Required: {', '.join(required)}") from exc


def _r(x: float, nd: int = 1) -> float:
    return round(x + 0.0, nd)


# ============================================================ kidney
class CkdEpiIn(_In):
    age: int = Field(..., ge=18, le=120, description="Years")
    sex: Sex
    creatinine_mg_dl: float = Field(..., gt=0.1, lt=25, description="Standardised serum creatinine, mg/dL (µmol/L ÷ 88.4)")


def _ckd_stage(egfr: float) -> str:
    for cut, stage in ((90, "G1"), (60, "G2"), (45, "G3a"), (30, "G3b"), (15, "G4")):
        if egfr >= cut:
            return stage
    return "G5"


@calculator("ckd_epi_2021", "eGFR (CKD-EPI 2021, race-free)", "Kidney",
            "Estimated GFR from serum creatinine, age and sex; KDIGO G-stage.", CkdEpiIn,
            "Inker LA et al. N Engl J Med 2021;385:1737-49 (NKF/ASN recommended equation).",
            ["Not valid in AKI / non-steady-state creatinine, extremes of muscle mass, or pregnancy.",
             "For drug dosing many labels still use Cockcroft-Gault creatinine clearance."])
def ckd_epi_2021(p: CkdEpiIn) -> CalcResult:
    female = p.sex == "female"
    kappa, alpha = (0.7, -0.241) if female else (0.9, -0.302)
    ratio = p.creatinine_mg_dl / kappa
    egfr = 142 * min(ratio, 1) ** alpha * max(ratio, 1) ** -1.200 * 0.9938 ** p.age * (1.012 if female else 1)
    stage = _ckd_stage(egfr)
    return CalcResult(calculator="ckd_epi_2021", title="eGFR (CKD-EPI 2021)", value=_r(egfr, 0), unit="mL/min/1.73m²",
                      band=stage, interpretation=f"eGFR {egfr:.0f} mL/min/1.73m², KDIGO category {stage} "
                      "(CKD requires persistence >3 months and/or markers of kidney damage).",
                      details={"creatinine_umol_l": _r(p.creatinine_mg_dl * 88.4, 0)},
                      reference="Inker LA et al. NEJM 2021;385:1737-49")


class CockcroftIn(_In):
    age: int = Field(..., ge=18, le=120)
    sex: Sex
    weight_kg: float = Field(..., gt=20, lt=400, description="Actual body weight")
    creatinine_mg_dl: float = Field(..., gt=0.1, lt=25)
    height_cm: float | None = Field(None, gt=100, lt=250, description="Optional; enables ideal/adjusted body-weight estimates")


@calculator("cockcroft_gault", "Creatinine clearance (Cockcroft-Gault)", "Kidney",
            "CrCl for renal drug dosing, with actual, ideal and adjusted body weight variants.", CockcroftIn,
            "Cockcroft DW, Gault MH. Nephron 1976;16:31-41. IBW: Devine 1974.",
            ["Most FDA renal-dosing tables were derived with Cockcroft-Gault; check the label for the weight to use.",
             "Overestimates clearance in obesity when actual weight is used; unreliable in unstable renal function."])
def cockcroft_gault(p: CockcroftIn) -> CalcResult:
    def crcl(weight: float) -> float:
        value = (140 - p.age) * weight / (72 * p.creatinine_mg_dl)
        return value * 0.85 if p.sex == "female" else value

    details: dict[str, Any] = {"crcl_actual_weight": _r(crcl(p.weight_kg))}
    value = crcl(p.weight_kg)
    note = "using actual body weight"
    if p.height_cm:
        inches_over_60 = max(0.0, p.height_cm / 2.54 - 60)
        ibw = (50 if p.sex == "male" else 45.5) + 2.3 * inches_over_60
        adjbw = ibw + 0.4 * (p.weight_kg - ibw)
        details.update(ideal_body_weight_kg=_r(ibw), adjusted_body_weight_kg=_r(adjbw),
                       crcl_ideal_weight=_r(crcl(min(ibw, p.weight_kg))), crcl_adjusted_weight=_r(crcl(adjbw)))
        if p.weight_kg > 1.2 * ibw:
            value, note = crcl(adjbw), "using adjusted body weight (actual weight >120% of ideal)"
        elif p.weight_kg >= ibw:
            value, note = crcl(ibw), "using ideal body weight"
    band = ">=60" if value >= 60 else "30-59" if value >= 30 else "15-29" if value >= 15 else "<15"
    return CalcResult(calculator="cockcroft_gault", title="Creatinine clearance (Cockcroft-Gault)", value=_r(value), unit="mL/min",
                      band=band, interpretation=f"CrCl ≈ {value:.0f} mL/min {note}.", details=details,
                      reference="Cockcroft & Gault, Nephron 1976")


# ======================================================= cardiology
class Cha2ds2In(_In):
    age: int = Field(..., ge=18, le=120)
    sex: Sex
    congestive_heart_failure: bool = False
    hypertension: bool = False
    diabetes: bool = False
    stroke_tia_thromboembolism: bool = False
    vascular_disease: bool = Field(False, description="Prior MI, peripheral artery disease or aortic plaque")


# Adjusted annual stroke rate (%) by score, Lip GY et al. Chest 2010 (Euro Heart Survey).
_CHA2DS2_STROKE = {0: 0.0, 1: 1.3, 2: 2.2, 3: 3.2, 4: 4.0, 5: 6.7, 6: 9.8, 7: 9.6, 8: 6.7, 9: 15.2}


@calculator("cha2ds2_vasc", "CHA₂DS₂-VASc", "Cardiology",
            "Stroke risk in non-valvular atrial fibrillation; also reports sex-neutral CHA₂DS₂-VA (ESC 2024).", Cha2ds2In,
            "Lip GY et al. Chest 2010;137:263-72. 2023 ACC/AHA/ACCP/HRS AF guideline; 2024 ESC AF guideline (CHA₂DS₂-VA).",
            ["Not for valvular AF (moderate-severe mitral stenosis or mechanical valve): anticoagulate regardless.",
             "Annual stroke rates are historical cohort estimates without anticoagulation; contemporary rates are lower."])
def cha2ds2_vasc(p: Cha2ds2In) -> CalcResult:
    age_pts = 2 if p.age >= 75 else 1 if p.age >= 65 else 0
    va = (p.congestive_heart_failure + p.hypertension + p.diabetes + 2 * p.stroke_tia_thromboembolism
          + p.vascular_disease + age_pts)
    score = va + (1 if p.sex == "female" else 0)
    male_equiv = va  # the sex category is a risk modifier, not a risk factor on its own
    if male_equiv >= 2:
        band, rec = "high", "Oral anticoagulation recommended (DOAC preferred over warfarin in eligible patients)."
    elif male_equiv == 1:
        band, rec = "intermediate", "Oral anticoagulation is reasonable; individualise with bleeding risk and preference."
    else:
        band, rec = "low", "Anticoagulation generally not recommended."
    return CalcResult(calculator="cha2ds2_vasc", title="CHA₂DS₂-VASc", value=score, unit="points", band=band,
                      interpretation=f"CHA₂DS₂-VASc {score} (CHA₂DS₂-VA {va}). {rec}",
                      details={"cha2ds2_va": va, "annual_stroke_rate_pct_lip_2010": _CHA2DS2_STROKE.get(score)},
                      reference="Lip 2010; ACC/AHA 2023; ESC 2024")


class HasBledIn(_In):
    uncontrolled_hypertension: bool = Field(False, description="SBP >160 mmHg")
    abnormal_renal_function: bool = Field(False, description="Dialysis, transplant, Cr >2.26 mg/dL")
    abnormal_liver_function: bool = Field(False, description="Cirrhosis or bilirubin >2×ULN with AST/ALT >3×ULN")
    prior_stroke: bool = False
    bleeding_history_or_predisposition: bool = False
    labile_inr: bool = Field(False, description="Time in therapeutic range <60% (only if on warfarin)")
    age_over_65: bool = False
    antiplatelet_or_nsaid: bool = False
    alcohol_8_or_more_drinks_week: bool = False


@calculator("has_bled", "HAS-BLED", "Cardiology", "1-year major bleeding risk on anticoagulation in AF.", HasBledIn,
            "Pisters R et al. Chest 2010;138:1093-100.",
            ["A high score flags modifiable risk factors to address; it is not by itself a reason to withhold anticoagulation."])
def has_bled(p: HasBledIn) -> CalcResult:
    score = sum(p.model_dump().values())
    band = "high" if score >= 3 else "moderate" if score == 2 else "low"
    return CalcResult(calculator="has_bled", title="HAS-BLED", value=score, unit="points", band=band,
                      interpretation=f"HAS-BLED {score}: {band} bleeding risk"
                      + (". Review modifiable factors (BP, antiplatelets/NSAIDs, alcohol, labile INR) and follow up closely." if score >= 3 else "."),
                      reference="Pisters 2010")


class HeartIn(_In):
    history: Literal[0, 1, 2] = Field(..., description="0 slightly, 1 moderately, 2 highly suspicious")
    ecg: Literal[0, 1, 2] = Field(..., description="0 normal, 1 non-specific repolarisation, 2 significant ST deviation")
    age: int = Field(..., ge=18, le=120)
    risk_factor_count: int = Field(..., ge=0, le=10, description="HTN, hypercholesterolaemia, DM, obesity (BMI>30), smoking, family history")
    known_atherosclerotic_disease: bool = Field(False, description="Prior MI, PCI/CABG, stroke/TIA, or PAD")
    troponin: Literal[0, 1, 2] = Field(..., description="0 ≤ normal limit, 1 1–3× limit, 2 >3× limit")


@calculator("heart_score", "HEART score", "Cardiology", "6-week MACE risk in ED chest pain.", HeartIn,
            "Six AJ, Backus BE, Kelder JC. Neth Heart J 2008;16:191-6; Backus BE et al. Int J Cardiol 2013;168:2153-8.",
            ["For undifferentiated chest pain in the ED; not for STEMI or haemodynamically unstable patients."])
def heart_score(p: HeartIn) -> CalcResult:
    age_pts = 2 if p.age >= 65 else 1 if p.age >= 45 else 0
    rf_pts = 2 if (p.risk_factor_count >= 3 or p.known_atherosclerotic_disease) else 1 if p.risk_factor_count >= 1 else 0
    score = p.history + p.ecg + age_pts + rf_pts + p.troponin
    if score <= 3:
        band, text = "low", "Low risk (~1–2% 6-week MACE); early discharge pathway may be appropriate."
    elif score <= 6:
        band, text = "moderate", "Moderate risk (~12–17% 6-week MACE); observation and further testing."
    else:
        band, text = "high", "High risk (~50–65% 6-week MACE); early invasive strategy should be considered."
    return CalcResult(calculator="heart_score", title="HEART score", value=score, unit="points", band=band,
                      interpretation=f"HEART {score}. {text}", details={"age_points": age_pts, "risk_factor_points": rf_pts},
                      reference="Six 2008; Backus 2013")


class PceIn(_In):
    age: int = Field(..., ge=40, le=79)
    sex: Sex
    race: Literal["white", "african_american", "other"] = Field(..., description="'other' uses the white equations (per guideline)")
    total_cholesterol_mg_dl: float = Field(..., ge=130, le=320)
    hdl_mg_dl: float = Field(..., ge=20, le=100)
    systolic_bp: float = Field(..., ge=90, le=200)
    on_bp_treatment: bool
    current_smoker: bool
    diabetes: bool


# Goff DC Jr et al. 2013 ACC/AHA guideline, Table A. Terms are on natural logs.
_PCE = {
    ("female", "white"): dict(age=-29.799, age2=4.884, tc=13.540, age_tc=-3.114, hdl=-13.578, age_hdl=3.149,
                              sbp_t=2.019, age_sbp_t=0.0, sbp_u=1.957, age_sbp_u=0.0, smoker=7.574, age_smoker=-1.665,
                              dm=0.661, mean=-29.18, s10=0.9665),
    ("female", "african_american"): dict(age=17.114, age2=0.0, tc=0.940, age_tc=0.0, hdl=-18.920, age_hdl=4.475,
                                         sbp_t=29.291, age_sbp_t=-6.432, sbp_u=27.820, age_sbp_u=-6.087, smoker=0.691,
                                         age_smoker=0.0, dm=0.874, mean=86.61, s10=0.9533),
    ("male", "white"): dict(age=12.344, age2=0.0, tc=11.853, age_tc=-2.664, hdl=-7.990, age_hdl=1.769, sbp_t=1.797,
                            age_sbp_t=0.0, sbp_u=1.764, age_sbp_u=0.0, smoker=7.837, age_smoker=-1.795, dm=0.658,
                            mean=61.18, s10=0.9144),
    ("male", "african_american"): dict(age=2.469, age2=0.0, tc=0.302, age_tc=0.0, hdl=-0.307, age_hdl=0.0, sbp_t=1.916,
                                       age_sbp_t=0.0, sbp_u=1.809, age_sbp_u=0.0, smoker=0.549, age_smoker=0.0, dm=0.645,
                                       mean=19.54, s10=0.8954),
}


@calculator("ascvd_pce", "10-year ASCVD risk (Pooled Cohort Equations)", "Cardiology",
            "2013 ACC/AHA 10-year risk of first hard ASCVD event for adults 40–79 without ASCVD.", PceIn,
            "Goff DC Jr et al. Circulation 2014;129(suppl 2):S49-73.",
            ["Only for primary prevention in adults 40–79 without clinical ASCVD and LDL <190 mg/dL.",
             "Tends to overestimate risk in contemporary and some Asian/Hispanic populations; the AHA PREVENT equations (2023) are an alternative.",
             "Race-specific coefficients reflect the derivation cohorts, not biology."])
def ascvd_pce(p: PceIn) -> CalcResult:
    c = _PCE[(p.sex, "african_american" if p.race == "african_american" else "white")]
    la, ltc, lhdl, lsbp = math.log(p.age), math.log(p.total_cholesterol_mg_dl), math.log(p.hdl_mg_dl), math.log(p.systolic_bp)
    total = (c["age"] * la + c["age2"] * la * la + c["tc"] * ltc + c["age_tc"] * la * ltc + c["hdl"] * lhdl
             + c["age_hdl"] * la * lhdl + c["dm"] * p.diabetes
             + (c["smoker"] + c["age_smoker"] * la) * p.current_smoker)
    total += (c["sbp_t"] + c["age_sbp_t"] * la) * lsbp if p.on_bp_treatment else (c["sbp_u"] + c["age_sbp_u"] * la) * lsbp
    risk = 1 - c["s10"] ** math.exp(total - c["mean"])
    pct = risk * 100
    if pct < 5:
        band, text = "low", "Low (<5%). Emphasise lifestyle; statin generally not indicated on risk alone."
    elif pct < 7.5:
        band, text = "borderline", "Borderline (5–7.4%). Risk-enhancers may favour a moderate-intensity statin."
    elif pct < 20:
        band, text = "intermediate", "Intermediate (7.5–19.9%). Moderate-intensity statin favoured; consider CAC score if uncertain."
    else:
        band, text = "high", "High (≥20%). High-intensity statin recommended (2018 ACC/AHA cholesterol guideline)."
    return CalcResult(calculator="ascvd_pce", title="10-year ASCVD risk (PCE)", value=_r(pct), unit="%", band=band,
                      interpretation=f"10-year ASCVD risk {pct:.1f}%. {text}", reference="Goff 2013; Grundy 2018")


class QtcIn(_In):
    qt_ms: float = Field(..., gt=200, lt=800)
    heart_rate_bpm: float = Field(..., gt=20, lt=250)
    sex: Sex | None = None


@calculator("qtc", "Corrected QT interval", "Cardiology", "QTc by Bazett and Fridericia (Fridericia preferred at high/low rates).", QtcIn,
            "Bazett 1920; Fridericia 1920; AHA/ACCF/HRS 2009 ECG standardisation.")
def qtc(p: QtcIn) -> CalcResult:
    rr = 60.0 / p.heart_rate_bpm
    baz, fri = p.qt_ms / math.sqrt(rr), p.qt_ms / rr ** (1 / 3)
    limit = 460 if p.sex == "female" else 450
    band = "markedly prolonged" if fri > 500 else "prolonged" if fri > limit else "normal"
    text = {"markedly prolonged": ">500 ms: high torsades risk; review QT-prolonging drugs and electrolytes.",
            "prolonged": f">{limit} ms: prolonged.", "normal": "Within normal limits."}[band]
    return CalcResult(calculator="qtc", title="QTc", value=_r(fri, 0), unit="ms (Fridericia)", band=band,
                      interpretation=f"QTc Fridericia {fri:.0f} ms, Bazett {baz:.0f} ms. {text}",
                      details={"bazett_ms": _r(baz, 0), "fridericia_ms": _r(fri, 0)}, reference="Bazett; Fridericia")


# ======================================================== pulmonary
class WellsPeIn(_In):
    clinical_signs_dvt: bool = False
    pe_most_likely_diagnosis: bool = False
    heart_rate_over_100: bool = False
    immobilisation_or_surgery_4_weeks: bool = False
    previous_pe_or_dvt: bool = False
    haemoptysis: bool = False
    active_malignancy: bool = False


@calculator("wells_pe", "Wells score for PE", "Pulmonary", "Pre-test probability of pulmonary embolism.", WellsPeIn,
            "Wells PS et al. Thromb Haemost 2000;83:416-20; Ann Intern Med 2001;135:98-107.",
            ["Apply to outpatients / ED patients with suspected PE; less validated in inpatients and pregnancy."])
def wells_pe(p: WellsPeIn) -> CalcResult:
    score = (3 * p.clinical_signs_dvt + 3 * p.pe_most_likely_diagnosis + 1.5 * p.heart_rate_over_100
             + 1.5 * p.immobilisation_or_surgery_4_weeks + 1.5 * p.previous_pe_or_dvt + p.haemoptysis + p.active_malignancy)
    three = "high" if score > 6 else "moderate" if score >= 2 else "low"
    two = "PE likely" if score > 4 else "PE unlikely"
    nxt = ("CT pulmonary angiography (D-dimer should not be used to exclude PE)." if score > 4
           else "D-dimer (age-adjusted if >50 y); if negative, PE is excluded. Consider PERC if gestalt probability is low.")
    return CalcResult(calculator="wells_pe", title="Wells PE", value=score, unit="points", band=two,
                      interpretation=f"Wells {score:g}: {two} (three-tier: {three}). Next: {nxt}",
                      details={"three_tier": three}, reference="Wells 2000/2001")


class PercIn(_In):
    age: int = Field(..., ge=0, le=120)
    heart_rate_bpm: float
    oxygen_saturation_pct: float = Field(..., ge=50, le=100)
    unilateral_leg_swelling: bool = False
    haemoptysis: bool = False
    recent_surgery_or_trauma_4_weeks: bool = False
    prior_pe_or_dvt: bool = False
    hormone_use: bool = Field(False, description="Oral contraceptives, HRT or oestrogen")


@calculator("perc", "PERC rule", "Pulmonary", "Rule out PE without testing when pre-test probability is low (<15%).", PercIn,
            "Kline JA et al. J Thromb Haemost 2004;2:1247-55; 2008;6:772-80.",
            ["Only valid when clinical gestalt probability is already low (<15%)."])
def perc(p: PercIn) -> CalcResult:
    failed = [name for name, hit in {
        "age ≥50": p.age >= 50, "HR ≥100": p.heart_rate_bpm >= 100, "SaO₂ <95%": p.oxygen_saturation_pct < 95,
        "unilateral leg swelling": p.unilateral_leg_swelling, "haemoptysis": p.haemoptysis,
        "recent surgery/trauma": p.recent_surgery_or_trauma_4_weeks, "prior VTE": p.prior_pe_or_dvt, "hormone use": p.hormone_use,
    }.items() if hit]
    negative = not failed
    return CalcResult(calculator="perc", title="PERC", value=len(failed), unit="criteria present",
                      band="PERC negative" if negative else "PERC positive",
                      interpretation=("PERC negative: with low gestalt probability, PE is ruled out without D-dimer."
                                      if negative else f"PERC positive ({', '.join(failed)}): cannot rule out with PERC; use Wells/D-dimer."),
                      details={"criteria_present": failed}, reference="Kline 2004/2008")


class Curb65In(_In):
    confusion: bool = False
    urea_over_7_mmol_l: bool = Field(False, description="Urea >7 mmol/L (BUN >19 mg/dL)")
    respiratory_rate_30_or_more: bool = False
    low_blood_pressure: bool = Field(False, description="SBP <90 or DBP ≤60 mmHg")
    age_65_or_more: bool = False


@calculator("curb65", "CURB-65", "Pulmonary", "Severity of community-acquired pneumonia.", Curb65In,
            "Lim WS et al. Thorax 2003;58:377-82.",
            ["Complements, not replaces, clinical judgement; the ATS/IDSA 2019 guideline prefers PSI for site-of-care decisions."])
def curb65(p: Curb65In) -> CalcResult:
    score = sum(p.model_dump().values())
    band = "low" if score <= 1 else "moderate" if score == 2 else "severe"
    text = {"low": "Low severity: usually suitable for outpatient treatment.",
            "moderate": "Moderate: consider short admission or closely supervised outpatient care.",
            "severe": "Severe: hospitalise; assess for ICU especially at 4–5."}[band]
    return CalcResult(calculator="curb65", title="CURB-65", value=score, unit="points", band=band,
                      interpretation=f"CURB-65 {score}. {text}", reference="Lim 2003")


# ============================================================ sepsis
class QsofaIn(_In):
    respiratory_rate_22_or_more: bool = False
    altered_mentation: bool = False
    systolic_bp_100_or_less: bool = False


@calculator("qsofa", "qSOFA", "Critical care", "Bedside prompt for poor outcome in suspected infection.", QsofaIn,
            "Seymour CW et al. JAMA 2016;315:762-74 (Sepsis-3).",
            ["Surviving Sepsis Campaign 2021 recommends against qSOFA alone as a screening tool for sepsis."])
def qsofa(p: QsofaIn) -> CalcResult:
    score = sum(p.model_dump().values())
    return CalcResult(calculator="qsofa", title="qSOFA", value=score, unit="points", band="high risk" if score >= 2 else "not high risk",
                      interpretation=f"qSOFA {score}. " + ("≥2: higher risk of death or prolonged ICU stay; assess for organ dysfunction (SOFA)."
                                                            if score >= 2 else "<2 does not exclude sepsis."),
                      reference="Seymour 2016")


# ============================================================= liver
class MeldNaIn(_In):
    bilirubin_mg_dl: float = Field(..., gt=0, lt=80)
    inr: float = Field(..., gt=0.5, lt=20)
    creatinine_mg_dl: float = Field(..., gt=0.1, lt=25)
    sodium_mmol_l: float = Field(..., gt=100, lt=180)
    dialysis_twice_in_last_week: bool = Field(False, description="≥2 dialysis sessions or ≥24 h CVVHD in the past week")


@calculator("meld_na", "MELD-Na (UNOS/OPTN 2016)", "Hepatology", "Liver disease severity / transplant priority.", MeldNaIn,
            "OPTN Policy 9.1 (Jan 2016); Kim WR et al. N Engl J Med 2008;359:1018-26.",
            ["OPTN adopted MELD 3.0 for allocation in 2023; MELD-Na remains widely used clinically."])
def meld_na(p: MeldNaIn) -> CalcResult:
    cr = 4.0 if p.dialysis_twice_in_last_week else min(max(p.creatinine_mg_dl, 1.0), 4.0)
    bili, inr = max(p.bilirubin_mg_dl, 1.0), max(p.inr, 1.0)
    na = min(max(p.sodium_mmol_l, 125), 137)
    meld_i = round(0.957 * math.log(cr) + 0.378 * math.log(bili) + 1.120 * math.log(inr) + 0.643, 1) * 10
    meld = meld_i + 1.32 * (137 - na) - 0.033 * meld_i * (137 - na) if meld_i > 11 else meld_i
    meld = min(round(meld), 40)
    band = "≥30" if meld >= 30 else "20–29" if meld >= 20 else "10–19" if meld >= 10 else "<10"
    return CalcResult(calculator="meld_na", title="MELD-Na", value=meld, unit="points", band=band,
                      interpretation=f"MELD-Na {meld} (MELD {meld_i:g}). Higher scores predict higher 90-day mortality; "
                      "consider transplant referral at MELD ≥15.", details={"meld_initial": meld_i}, reference="OPTN 2016")


class ChildPughIn(_In):
    bilirubin_mg_dl: float = Field(..., gt=0)
    albumin_g_dl: float = Field(..., gt=0.5, lt=7)
    inr: float = Field(..., gt=0.5)
    ascites: Literal["none", "mild", "moderate_severe"]
    encephalopathy: Literal["none", "grade_1_2", "grade_3_4"]


@calculator("child_pugh", "Child-Pugh", "Hepatology", "Cirrhosis severity class (used in many hepatic dosing labels).", ChildPughIn,
            "Pugh RN et al. Br J Surg 1973;60:646-9.")
def child_pugh(p: ChildPughIn) -> CalcResult:
    bili = 1 if p.bilirubin_mg_dl < 2 else 2 if p.bilirubin_mg_dl <= 3 else 3
    alb = 1 if p.albumin_g_dl > 3.5 else 2 if p.albumin_g_dl >= 2.8 else 3
    inr = 1 if p.inr < 1.7 else 2 if p.inr <= 2.3 else 3
    asc = {"none": 1, "mild": 2, "moderate_severe": 3}[p.ascites]
    enc = {"none": 1, "grade_1_2": 2, "grade_3_4": 3}[p.encephalopathy]
    score = bili + alb + inr + asc + enc
    cls = "A" if score <= 6 else "B" if score <= 9 else "C"
    return CalcResult(calculator="child_pugh", title="Child-Pugh", value=score, unit="points", band=f"Class {cls}",
                      interpretation=f"Child-Pugh {score}, class {cls} ({ {'A': 'well-compensated', 'B': 'significant functional compromise', 'C': 'decompensated'}[cls] }).",
                      details={"bilirubin": bili, "albumin": alb, "inr": inr, "ascites": asc, "encephalopathy": enc},
                      reference="Pugh 1973")


class Fib4In(_In):
    age: int = Field(..., ge=18, le=120)
    ast_u_l: float = Field(..., gt=0)
    alt_u_l: float = Field(..., gt=0)
    platelets_10e9_l: float = Field(..., gt=0, description="×10⁹/L")


@calculator("fib4", "FIB-4", "Hepatology", "Non-invasive advanced fibrosis risk (MASLD, viral hepatitis).", Fib4In,
            "Sterling RK et al. Hepatology 2006;43:1317-25; AASLD 2023 MASLD guidance.",
            ["Less accurate under 35 years; use cut-off 2.0 (instead of 1.3) at age ≥65."])
def fib4(p: Fib4In) -> CalcResult:
    value = p.age * p.ast_u_l / (p.platelets_10e9_l * math.sqrt(p.alt_u_l))
    low_cut = 2.0 if p.age >= 65 else 1.3
    band = "low" if value < low_cut else "high" if value > 2.67 else "indeterminate"
    text = {"low": "Low risk of advanced fibrosis.", "indeterminate": "Indeterminate: second-line test (VCTE/ELF) recommended.",
            "high": "High risk of advanced fibrosis: refer to hepatology."}[band]
    return CalcResult(calculator="fib4", title="FIB-4", value=_r(value, 2), band=band, interpretation=f"FIB-4 {value:.2f}. {text}",
                      reference="Sterling 2006; AASLD 2023")


# ===================================================== general / labs
class BodyIn(_In):
    weight_kg: float = Field(..., gt=1, lt=400)
    height_cm: float = Field(..., gt=40, lt=250)


@calculator("bmi_bsa", "BMI and body surface area", "General", "BMI (WHO class) and BSA (Mosteller).", BodyIn,
            "WHO BMI classification; Mosteller RD. N Engl J Med 1987;317:1098.")
def bmi_bsa(p: BodyIn) -> CalcResult:
    bmi = p.weight_kg / (p.height_cm / 100) ** 2
    bsa = math.sqrt(p.height_cm * p.weight_kg / 3600)
    band = ("underweight" if bmi < 18.5 else "normal" if bmi < 25 else "overweight" if bmi < 30
            else "obesity class I" if bmi < 35 else "obesity class II" if bmi < 40 else "obesity class III")
    return CalcResult(calculator="bmi_bsa", title="BMI / BSA", value=_r(bmi), unit="kg/m²", band=band,
                      interpretation=f"BMI {bmi:.1f} kg/m² ({band}); BSA {bsa:.2f} m².", details={"bsa_m2": _r(bsa, 2)},
                      reference="WHO; Mosteller 1987")


class CalciumIn(_In):
    calcium_mg_dl: float = Field(..., gt=2, lt=20)
    albumin_g_dl: float = Field(..., gt=0.5, lt=7)


@calculator("corrected_calcium", "Albumin-corrected calcium", "Labs", "Total calcium corrected for low albumin.", CalciumIn,
            "Payne RB et al. BMJ 1973;4:643-6.", ["Ionised calcium is preferred when available; correction is unreliable in CKD and critical illness."])
def corrected_calcium(p: CalciumIn) -> CalcResult:
    value = p.calcium_mg_dl + 0.8 * (4.0 - p.albumin_g_dl)
    band = "low" if value < 8.5 else "high" if value > 10.5 else "normal"
    return CalcResult(calculator="corrected_calcium", title="Corrected calcium", value=_r(value), unit="mg/dL", band=band,
                      interpretation=f"Corrected calcium {value:.1f} mg/dL ({band}; ref ~8.5–10.5).", reference="Payne 1973")


class AnionGapIn(_In):
    sodium: float = Field(..., gt=100, lt=180, description="mmol/L")
    chloride: float = Field(..., gt=50, lt=150)
    bicarbonate: float = Field(..., gt=1, lt=60)
    albumin_g_dl: float | None = Field(None, gt=0.5, lt=7)


@calculator("anion_gap", "Anion gap", "Labs", "Serum anion gap, albumin-corrected, with delta ratio.", AnionGapIn,
            "Figge J et al. Crit Care Med 1998;26:1807-10 (albumin correction).")
def anion_gap(p: AnionGapIn) -> CalcResult:
    ag = p.sodium - (p.chloride + p.bicarbonate)
    corrected = ag + 2.5 * (4.0 - p.albumin_g_dl) if p.albumin_g_dl is not None else ag
    details: dict[str, Any] = {"uncorrected": _r(ag)}
    if corrected > 12 and p.bicarbonate < 24:
        details["delta_ratio"] = _r((corrected - 12) / (24 - p.bicarbonate), 2)
    band = "elevated" if corrected > 12 else "normal"
    return CalcResult(calculator="anion_gap", title="Anion gap", value=_r(corrected), unit="mmol/L", band=band,
                      interpretation=f"Anion gap {corrected:.1f} ({band}; normal ≈ 8–12 without K⁺)."
                      + (f" Delta ratio {details['delta_ratio']}." if "delta_ratio" in details else ""),
                      details=details, reference="Figge 1998")


class SodiumGlucoseIn(_In):
    sodium: float = Field(..., gt=100, lt=180)
    glucose_mg_dl: float = Field(..., gt=20, lt=3000)


@calculator("corrected_sodium", "Sodium corrected for hyperglycaemia", "Labs", "Katz (1.6) and Hillier (2.4) corrections.",
            SodiumGlucoseIn, "Katz MA. N Engl J Med 1973;289:843-4; Hillier TA et al. Am J Med 1999;106:399-403.")
def corrected_sodium(p: SodiumGlucoseIn) -> CalcResult:
    excess = max(0.0, p.glucose_mg_dl - 100) / 100
    katz, hillier = p.sodium + 1.6 * excess, p.sodium + 2.4 * excess
    return CalcResult(calculator="corrected_sodium", title="Corrected sodium", value=_r(hillier), unit="mmol/L",
                      interpretation=f"Corrected Na {hillier:.1f} (Hillier 2.4) / {katz:.1f} (Katz 1.6) mmol/L.",
                      details={"katz": _r(katz), "hillier": _r(hillier)}, reference="Katz 1973; Hillier 1999")


def catalogue() -> list[dict[str, Any]]:
    return [{"name": c.name, "title": c.title, "category": c.category, "description": c.description,
             "reference": c.reference, "caveats": c.caveats, "schema": c.schema()} for c in REGISTRY.values()]
