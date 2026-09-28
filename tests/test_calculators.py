import pytest

from medagent.ml import calculators as c
from medagent.ml.calculators import CalculatorError


@pytest.mark.parametrize("sex,race,expected", [
    ("female", "white", 2.1), ("female", "african_american", 3.0), ("male", "white", 5.3), ("male", "african_american", 6.1),
])
def test_pce_matches_2013_guideline_worked_example(sex, race, expected):
    # Goff 2013: 55 y, TC 213, HDL 50, SBP 120 untreated, non-smoker, no diabetes.
    r = c.run("ascvd_pce", dict(age=55, sex=sex, race=race, total_cholesterol_mg_dl=213, hdl_mg_dl=50, systolic_bp=120,
                                on_bp_treatment=False, current_smoker=False, diabetes=False))
    assert r.value == pytest.approx(expected, abs=0.11)  # guideline rounds intermediate terms


def test_pce_smoker_diabetic_is_high():
    r = c.run("ascvd_pce", dict(age=65, sex="male", race="white", total_cholesterol_mg_dl=240, hdl_mg_dl=35, systolic_bp=160,
                                on_bp_treatment=True, current_smoker=True, diabetes=True))
    assert r.band == "high" and r.value > 20


def test_ckd_epi_2021():
    assert c.run("ckd_epi_2021", dict(age=50, sex="female", creatinine_mg_dl=1.0)).value == 69
    male = c.run("ckd_epi_2021", dict(age=60, sex="male", creatinine_mg_dl=2.2))
    assert male.value == round(142 * (2.2 / 0.9) ** -1.2 * 0.9938 ** 60) == 33 and male.band == "G3b"
    assert c.run("ckd_epi_2021", dict(age=30, sex="male", creatinine_mg_dl=0.7)).band == "G1"


def test_cockcroft_gault_weights():
    r = c.run("cockcroft_gault", dict(age=80, sex="female", weight_kg=55, creatinine_mg_dl=1.2))
    assert r.value == pytest.approx((140 - 80) * 55 / (72 * 1.2) * 0.85, abs=0.1)
    obese = c.run("cockcroft_gault", dict(age=50, sex="male", weight_kg=130, creatinine_mg_dl=1.0, height_cm=175))
    assert "adjusted" in obese.interpretation and obese.value < obese.details["crcl_actual_weight"]


def test_cha2ds2_vasc_and_va():
    r = c.run("cha2ds2_vasc", dict(age=78, sex="female", hypertension=True, diabetes=True))
    assert r.value == 5 and r.details["cha2ds2_va"] == 4 and r.band == "high"
    lone_female = c.run("cha2ds2_vasc", dict(age=50, sex="female"))
    assert lone_female.value == 1 and lone_female.band == "low"  # female sex alone is not an indication
    assert c.run("cha2ds2_vasc", dict(age=66, sex="male")).band == "intermediate"


def test_scores():
    assert c.run("has_bled", dict(age_over_65=True, antiplatelet_or_nsaid=True, labile_inr=True)).band == "high"
    heart = c.run("heart_score", dict(history=2, ecg=1, age=67, risk_factor_count=3, troponin=0))
    assert heart.value == 7 and heart.band == "high"
    wells = c.run("wells_pe", dict(clinical_signs_dvt=True, heart_rate_over_100=True))
    assert wells.value == 4.5 and wells.band == "PE likely"
    assert c.run("perc", dict(age=30, heart_rate_bpm=80, oxygen_saturation_pct=98)).band == "PERC negative"
    assert "age ≥50" in c.run("perc", dict(age=55, heart_rate_bpm=80, oxygen_saturation_pct=98)).details["criteria_present"]
    assert c.run("curb65", dict(confusion=True, age_65_or_more=True, low_blood_pressure=True)).band == "severe"
    assert c.run("qsofa", dict(respiratory_rate_22_or_more=True, altered_mentation=True)).band == "high risk"


def test_liver():
    assert c.run("meld_na", dict(bilirubin_mg_dl=2, inr=1.5, creatinine_mg_dl=1.2, sodium_mmol_l=130)).value == 21
    low = c.run("meld_na", dict(bilirubin_mg_dl=0.5, inr=0.9, creatinine_mg_dl=0.6, sodium_mmol_l=120))
    assert low.value == 6  # all values floored at 1.0 -> MELD(i) 6.4 -> no sodium adjustment below 12
    dial = c.run("meld_na", dict(bilirubin_mg_dl=1, inr=1, creatinine_mg_dl=1.0, sodium_mmol_l=137, dialysis_twice_in_last_week=True))
    assert dial.details["meld_initial"] == 20  # creatinine set to 4.0; UNOS rounds MELD(i) to one decimal before ×10
    cp = c.run("child_pugh", dict(bilirubin_mg_dl=2.5, albumin_g_dl=3.0, inr=1.8, ascites="mild", encephalopathy="none"))
    assert cp.value == 9 and cp.band == "Class B"
    assert c.run("fib4", dict(age=55, ast_u_l=40, alt_u_l=36, platelets_10e9_l=180)).value == pytest.approx(55 * 40 / (180 * 6), abs=0.01)


def test_labs_and_general():
    assert c.run("bmi_bsa", dict(weight_kg=90, height_cm=180)).value == 27.8
    assert c.run("corrected_calcium", dict(calcium_mg_dl=8.0, albumin_g_dl=2.0)).value == 9.6
    ag = c.run("anion_gap", dict(sodium=140, chloride=100, bicarbonate=14, albumin_g_dl=2.0))
    assert ag.value == 31 and ag.details["uncorrected"] == 26 and ag.details["delta_ratio"] == 1.9
    assert c.run("corrected_sodium", dict(sodium=130, glucose_mg_dl=600)).value == 142
    q = c.run("qtc", dict(qt_ms=400, heart_rate_bpm=60))
    assert q.value == 400 and q.band == "normal"


def test_input_validation_is_explicit():
    with pytest.raises(CalculatorError, match="Required: age, sex, creatinine_mg_dl"):
        c.run("ckd_epi_2021", {"age": 50})
    with pytest.raises(CalculatorError, match="Unknown calculator"):
        c.run("nope", {})
    with pytest.raises(CalculatorError, match="age"):
        c.run("ascvd_pce", dict(age=30, sex="male", race="white", total_cholesterol_mg_dl=200, hdl_mg_dl=50,
                                systolic_bp=120, on_bp_treatment=False, current_smoker=False, diabetes=False))


def test_catalogue_has_schemas_and_references():
    cat = c.catalogue()
    assert len(cat) >= 18
    for item in cat:
        assert item["reference"] and item["schema"]["properties"]
