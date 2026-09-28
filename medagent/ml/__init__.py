"""Specialised medical ML models exposed to the agent through function calling.

- ClinicalNLP: scispaCy BC5CDR NER + NegEx + abbreviations + vitals/labs regex
- PICOExtractor: BioELECTRA-PICO (EBM-NLP) with a rule-based fallback
- Reranker: NCBI MedCPT cross-encoder with a BM25 fallback
- calculators / stats / effects: deterministic validated equations and extractors

Heavy models load lazily on first use, and inference runs in a worker thread.
"""

from __future__ import annotations

import asyncio
from typing import Any

from . import calculators, effects, stats
from .nlp import ClinicalFindings, ClinicalNLP, prefill_calculator
from .pico import PICO, PICOExtractor
from .rerank import Reranker


class ModelHub:
    def __init__(self, settings=None, *, nlp: ClinicalNLP | None = None, pico: PICOExtractor | None = None,
                 reranker: Reranker | None = None):
        mode = getattr(settings, "ml_mode", "auto")
        enabled = mode != "rules"
        self.nlp = nlp or ClinicalNLP(getattr(settings, "ner_model", "en_ner_bc5cdr_md"), enabled=enabled)
        self.pico = pico or PICOExtractor(getattr(settings, "pico_model", "kamalkraj/BioELECTRA-PICO"), enabled=enabled)
        self.reranker = reranker or Reranker(getattr(settings, "reranker_model", "ncbi/MedCPT-Cross-Encoder"), enabled=enabled)

    def status(self) -> list[dict[str, Any]]:
        return [self.nlp.status, self.pico.status, self.reranker.status,
                {"component": "calculators", "backend": "deterministic", "loaded": True, "count": len(calculators.REGISTRY)}]

    async def analyze(self, text: str) -> ClinicalFindings:
        return await asyncio.to_thread(self.nlp.analyze, text)

    async def extract_pico(self, text: str) -> PICO:
        findings = await self.analyze(text)
        return await asyncio.to_thread(self.pico.extract, text, findings.entities)

    async def rerank(self, question: str, articles: list[Any]) -> tuple[list[float], str]:
        return await asyncio.to_thread(self.reranker.scores, question, articles)

    async def warm(self) -> None:
        """Load models up front (e.g. at server start) so the first question is not slow."""
        await asyncio.to_thread(self.nlp.analyze, "warm up: aspirin for stroke")


__all__ = ["ClinicalFindings", "ModelHub", "PICO", "calculators", "effects", "prefill_calculator", "stats"]
