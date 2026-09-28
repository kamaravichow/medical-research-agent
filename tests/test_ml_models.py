from medagent.ml.nlp import ClinicalFindings, extract_demographics, extract_measurements, prefill_calculator
from medagent.ml.pico import PICOExtractor, rule_pico
from medagent.ml.rerank import Reranker, bm25_scores
from medagent.models import Article

from .conftest import requires_ner
from .fixtures import PUBMED_XML

CASE = ("78-year-old woman with atrial fibrillation (AF), hypertension and type 2 diabetes. Denies chest pain, "
        "no history of stroke, on metformin. Not taking warfarin. Weight 58 kg, height 160 cm, creatinine 1.3 mg/dL, "
        "HR 92, BP 148/86, SpO2 97%.")


def test_demographics_and_measurements():
    assert extract_demographics(CASE) == (78, "female")
    assert extract_demographics("A 64 yo man") == (64, "male")
    m = {x.name: x.value for x in extract_measurements(CASE)}
    assert m["weight_kg"] == 58 and m["height_cm"] == 160 and m["creatinine_mg_dl"] == 1.3
    assert m["heart_rate_bpm"] == 92 and m["systolic_bp"] == 148 and m["diastolic_bp"] == 86 and m["oxygen_saturation_pct"] == 97
    umol = {x.name: x.value for x in extract_measurements("creatinine 115 µmol/L")}
    assert umol["creatinine_mg_dl"] == 1.3


@requires_ner
def test_ner_negation_and_abbreviations(ner):
    f = ner.analyze(CASE)
    assert f.backend == "scispacy:en_ner_bc5cdr_md"
    conds = [c.lower() for c in f.conditions]
    assert "atrial fibrillation" in conds and "hypertension" in conds
    assert any("chest pain" in c.lower() for c in f.negated_conditions)
    assert any("stroke" in c.lower() for c in f.negated_conditions)
    assert "metformin" in [m.lower() for m in f.medications]          # "no stroke, on metformin" is affirmed
    assert "warfarin" in [m.lower() for m in f.negated_medications]
    assert f.abbreviations.get("AF") == "atrial fibrillation"


@requires_ner
def test_prefill_from_ner(ner):
    f = ner.analyze(CASE)
    params, missing = prefill_calculator("cha2ds2_vasc", f)
    assert params["age"] == 78 and params["sex"] == "female" and params["hypertension"] and params["diabetes"]
    assert params["stroke_tia_thromboembolism"] is False and missing == []
    cg, missing = prefill_calculator("cockcroft_gault", f)
    assert cg == {"age": 78, "sex": "female", "weight_kg": 58, "creatinine_mg_dl": 1.3, "height_cm": 160} and not missing


def test_prefill_reports_missing_inputs():
    params, missing = prefill_calculator("ckd_epi_2021", ClinicalFindings(backend="rules", age=60))
    assert params == {"age": 60} and set(missing) == {"sex", "creatinine_mg_dl"}


def test_rule_pico_on_trial_abstract():
    text = ("We randomly assigned 5988 patients with class II-IV heart failure and an ejection fraction of more than 40% "
            "to receive empagliflozin (10 mg once daily) or placebo. The primary outcome was a composite of cardiovascular "
            "death or hospitalization for heart failure.")
    p = rule_pico(text)
    assert p.backend == "rules" and p.sample_size == 5988 and p.design_hint == "randomised"
    assert any("empagliflozin" in i for i in p.intervention) and any("placebo" in c for c in p.comparator)
    assert any("class II-IV heart failure" in x for x in p.population)
    assert any("cardiovascular death" in o for o in p.outcomes)


def test_transformer_pico_backend_is_used_and_merged():
    def fake_pipeline(model_name):
        def run(text):
            return [{"entity_group": "PAR", "word": "adults with HFpEF", "score": 0.93},
                    {"entity_group": "INT", "word": "empagliflozin", "score": 0.97},
                    {"entity_group": "OUT", "word": "cardiovascular death", "score": 0.88},
                    {"entity_group": "OUT", "word": "noise", "score": 0.2}]
        return run

    ex = PICOExtractor("fake/pico", pipeline_factory=fake_pipeline)
    p = ex.extract("We randomly assigned 400 adults to empagliflozin or placebo.")
    assert p.backend == "transformers:fake/pico" and ex.status["loaded"]
    assert p.population == ["adults with HFpEF"] and p.intervention == ["empagliflozin"]
    assert p.outcomes == ["cardiovascular death"] and p.comparator == ["placebo"]  # comparator from rules


def test_transformer_failure_falls_back_to_rules():
    def broken(_):
        raise OSError("no network")

    ex = PICOExtractor("fake/pico", pipeline_factory=broken)
    assert ex.extract("patients with sepsis received drug A versus drug B").backend == "rules"
    assert "no network" in ex.status["error"]


def _art(i, title, abstract=""):
    return Article(id=str(i), source="t", title=title, abstract=abstract)


def test_bm25_prefers_on_topic_article():
    docs = ["Empagliflozin in heart failure with preserved ejection fraction", "Statins for primary prevention in older adults",
            "Heart failure hospitalisation after SGLT2 inhibition: empagliflozin trial"]
    s = bm25_scores("empagliflozin HFpEF heart failure preserved", docs)
    assert s[0] > s[1] and s[2] > s[1]


def test_reranker_backends():
    arts = [_art(1, "Statins in elderly"), _art(2, "Colchicine after myocardial infarction")]
    rules = Reranker(enabled=False)
    scores, backend = rules.scores("colchicine after MI", arts)
    assert backend == "bm25" and scores[1] > scores[0]
    cross = Reranker("fake/medcpt", scorer=lambda pairs: [5.0 if "Colchicine" in d else -5.0 for _, d in pairs])
    scores, backend = cross.scores("colchicine after MI", arts)
    assert backend == "cross-encoder:fake/medcpt" and scores[1] > 0.99 and scores[0] < 0.01


async def test_search_reranks_by_question(harness):
    harness.ml.reranker = Reranker("fake/medcpt", scorer=lambda pairs: [9.0 if "meta-analysis" in d else -9.0 for _, d in pairs])
    bundle = await harness.search("sglt2", rerank_question="pooled evidence for SGLT2 inhibitors")
    assert bundle.relevance_backend == "cross-encoder:fake/medcpt"
    assert bundle.articles[0].id == "pmid:38000002" and bundle.articles[0].relevance > 0.99
