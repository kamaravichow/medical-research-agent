import pytest

from medagent.ml.effects import extract_effects
from medagent.ml.stats import DiagnosticIn, EffectIn, diagnostic_probability, treatment_effect


def test_bayes_with_sens_spec():
    out = diagnostic_probability(DiagnosticIn(pretest_probability=0.2, sensitivity=0.9, specificity=0.8))
    assert out["lr_positive"] == pytest.approx(4.5) and out["lr_negative"] == pytest.approx(0.125)
    assert out["posttest_if_positive"] == pytest.approx(0.5294, abs=1e-4)
    assert out["posttest_if_negative"] == pytest.approx(0.0303, abs=1e-4)
    assert out["ppv"] == pytest.approx(0.5294, abs=1e-4) and out["npv"] == pytest.approx(0.9697, abs=1e-4)


def test_bayes_needs_accuracy():
    with pytest.raises(ValueError):
        DiagnosticIn(pretest_probability=0.3)


def test_effect_from_counts_with_ci():
    out = treatment_effect(EffectIn(control_events=171, control_total=1000, treatment_events=138, treatment_total=1000, timeframe="2 years"))
    assert out["absolute_risk_reduction"] == pytest.approx(0.033) and out["nnt"] == 31
    lo, hi = out["arr_95ci"]
    assert 0 < lo < 0.033 < hi
    assert "NNT 31 over 2 years" in out["interpretation"]


def test_effect_from_hr_and_baseline():
    out = treatment_effect(EffectIn(control_risk=0.10, hazard_ratio=0.75, rr_ci=(0.6, 0.9)))
    assert out["treatment_risk"] == pytest.approx(1 - 0.9 ** 0.75, abs=1e-4)
    assert out["nnt"] == 42 and out["nnt_95ci"][0] < 42 < out["nnt_95ci"][1]


def test_effect_harm_and_nonsignificant():
    out = treatment_effect(EffectIn(control_events=10, control_total=100, treatment_events=12, treatment_total=100))
    assert out["nnh"] == 50 and "crosses zero" in out["interpretation"]


def test_extract_effects_variants():
    text = ("The primary outcome occurred in 13.8% vs 17.1% (hazard ratio, 0.79; 95% confidence interval [CI], 0.69 to 0.90; P<0.001). "
            "Death: OR 0.62, 95% CI 0.45-0.86. Bleeding RR = 1.10 [0.85, 1.42]; p=0.47. Mean difference −2.3 mm Hg (95% CI −3.1 to −1.5). NNT 17. "
            "Patients received 3 or 4 doses.")
    r = extract_effects(text)
    got = [(e.measure, e.value, e.ci_low, e.ci_high, e.significant) for e in r.effects]
    assert got == [("HR", 0.79, 0.69, 0.90, True), ("OR", 0.62, 0.45, 0.86, True), ("RR", 1.10, 0.85, 1.42, False),
                   ("MD", -2.3, -3.1, -1.5, True)]
    assert r.effects[0].p_value == "P<0.001" and r.effects[2].p_value == "P=0.47"
    assert r.nnt == ["NNT 17"] and r.arm_percentages == ["13.8% vs 17.1%"]
