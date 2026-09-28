"""Question-aware relevance ranking of retrieved articles.

Backend 1: NCBI MedCPT Cross-Encoder (Jin et al., Bioinformatics 2023), a
PubMedBERT cross-encoder trained on 255M PubMed search-log query/article pairs.
It scores (question, title + abstract) pairs.
Backend 2: Okapi BM25 over title + abstract + MeSH, which is deterministic and
dependency-free.
"""

from __future__ import annotations

import math
import re
import threading
from collections import Counter
from typing import Any

_TOKEN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_STOP = set("a an and are as at be by for from has have in into is it its of on or that the their this to was were with "
            "what which who whom does do did can should would how why when than vs versus patients patient".split())


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOP and len(t) > 1]


def bm25_scores(query: str, docs: list[str], k1: float = 1.5, b: float = 0.75) -> list[float]:
    q = tokenize(query)
    toks = [tokenize(d) for d in docs]
    if not q or not docs:
        return [0.0] * len(docs)
    avgdl = sum(len(t) for t in toks) / len(toks) or 1.0
    df = Counter(term for t in toks for term in set(t))
    n = len(docs)
    scores = []
    for t in toks:
        tf = Counter(t)
        s = 0.0
        for term in q:
            if term not in tf:
                continue
            idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
            s += idf * tf[term] * (k1 + 1) / (tf[term] + k1 * (1 - b + b * len(t) / avgdl))
        scores.append(s)
    return scores


def normalise(scores: list[float]) -> list[float]:
    if not scores:
        return []
    lo, hi = min(scores), max(scores)
    if hi - lo < 1e-9:
        return [0.5] * len(scores)
    return [(s - lo) / (hi - lo) for s in scores]


def doc_text(article: Any) -> str:
    return " ".join(x for x in (article.title, article.abstract or "", " ".join(article.mesh_terms or [])) if x)


class Reranker:
    def __init__(self, model: str | None = "ncbi/MedCPT-Cross-Encoder", enabled: bool = True, scorer=None):
        self.model_name = model
        self.enabled = enabled and bool(model)
        self._scorer = scorer  # callable(pairs) -> list[float]; injectable for tests
        self._model = None
        self._error: str | None = None
        self._lock = threading.Lock()

    @property
    def status(self) -> dict[str, Any]:
        loaded = self._scorer is not None or self._model is not None
        return {"component": "reranker", "model": self.model_name, "loaded": loaded, "error": self._error,
                "backend": f"cross-encoder:{self.model_name}" if loaded else "bm25"}

    def _load(self):
        if self._scorer is not None or self._error or not self.enabled:
            return self._scorer
        with self._lock:
            if self._scorer is None and not self._error:
                try:
                    import torch
                    from transformers import AutoModelForSequenceClassification, AutoTokenizer

                    tok = AutoTokenizer.from_pretrained(self.model_name)
                    model = AutoModelForSequenceClassification.from_pretrained(self.model_name).eval()

                    def score(pairs: list[list[str]]) -> list[float]:
                        with torch.no_grad():
                            enc = tok(pairs, truncation=True, padding=True, return_tensors="pt", max_length=512)
                            return model(**enc).logits.squeeze(dim=1).tolist()

                    self._model = model
                    self._scorer = score
                except Exception as exc:
                    self._error = f"{exc.__class__.__name__}: {exc}"[:300]
        return self._scorer

    def scores(self, question: str, articles: list[Any]) -> tuple[list[float], str]:
        """Relevance in 0..1 per article, plus the backend that produced it."""
        if not articles:
            return [], "none"
        docs = [doc_text(a) for a in articles]
        scorer = self._load()
        if scorer is not None:
            try:
                raw: list[float] = []
                for i in range(0, len(docs), 16):
                    raw += list(scorer([[question, d[:2000]] for d in docs[i:i + 16]]))
                return [1 / (1 + math.exp(-x)) for x in raw], self.status["backend"]
            except Exception as exc:
                self._error = f"inference: {exc}"[:300]
        return normalise(bm25_scores(question, docs)), "bm25"
