"""Per-conversation citation registry.

Every record a tool hands the model is given a short number ([1], [2], ...).
The model may only cite those numbers, and the UI resolves them back to the
full record for hover previews, so citations cannot drift from real sources.
"""

from __future__ import annotations

import threading
from typing import Any

from .evidence import design_label
from .models import Article, DrugLabel, Trial, WebResult

Record = Article | Trial | WebResult | DrugLabel


class SourceRegistry:
    def __init__(self) -> None:
        self._items: list[Record] = []
        self._by_key: dict[str, int] = {}
        self._lock = threading.Lock()

    def add(self, record: Record) -> int:
        key = _key(record)
        with self._lock:
            if key in self._by_key:
                return self._by_key[key]
            self._items.append(record)
            self._by_key[key] = len(self._items)
            return len(self._items)

    def get(self, number: int) -> Record | None:
        return self._items[number - 1] if 0 < number <= len(self._items) else None

    def __len__(self) -> int:
        return len(self._items)

    def to_payload(self, since: int = 0) -> list[dict[str, Any]]:
        return [{"n": i, "kind": _kind(r), "record": r.model_dump(mode="json")}
                for i, r in enumerate(self._items, start=1) if i > since]


def _key(record: Record) -> str:
    if isinstance(record, Article):
        if record.pmid:
            return f"pmid:{record.pmid}"
        return f"doi:{record.doi.lower()}" if record.doi else record.id
    if isinstance(record, WebResult):
        return f"url:{record.url}"
    return record.id


def _kind(record: Record) -> str:
    return {Article: "article", Trial: "trial", WebResult: "web", DrugLabel: "drug"}[type(record)]


# ----------------------------------------------------------- compact renderings
# What the model sees: dense, citation-numbered, no wasted tokens.

def brief_article(n: int, a: Article, abstract_chars: int = 500) -> str:
    meta = [design_label(a.design), f"LoE {a.evidence_level}"]
    if a.sample_size:
        meta.append(f"n≈{a.sample_size:,}")
    if a.cited_by:
        meta.append(f"cited {a.cited_by}")
    if a.is_preprint:
        meta.append("PREPRINT (not peer reviewed)")
    if a.is_retracted:
        meta.append("RETRACTED - do not rely on")
    if a.open_access:
        meta.append("open access")
    head = f"[{n}] {a.title} — {a.journal or a.source} {a.year or ''}".strip()
    ids = " ".join(x for x in (f"PMID {a.pmid}" if a.pmid else "", f"doi:{a.doi}" if a.doi else "") if x)
    body = a.bottom_line or (a.abstract or "")[:abstract_chars]
    return f"{head}\n    ({'; '.join(meta)}) {ids}\n    Conclusion: {body}"


def brief_trial(n: int, t: Trial) -> str:
    phase = "/".join(t.phases) or t.study_type or ""
    loc_countries = sorted({l.country for l in t.locations if l.country})[:6]
    parts = [
        f"[{n}] {t.nct_id}: {t.title}",
        f"    {t.status or '?'}; {phase}; n={t.enrollment or '?'}; sponsor {t.sponsor or '?'}; "
        f"primary completion {t.primary_completion_date or '?'}; results posted: {'yes' if t.has_results else 'no'}",
        f"    Interventions: {', '.join(t.interventions[:4]) or '?'}",
    ]
    if t.primary_outcomes:
        parts.append(f"    Primary outcome: {t.primary_outcomes[0]}")
    if loc_countries:
        parts.append(f"    Sites in: {', '.join(loc_countries)} ({len(t.locations)} sites)")
    return "\n".join(parts)


def brief_web(n: int, w: WebResult) -> str:
    tier = f" [{w.authority}]" if w.authority else ""
    return f"[{n}] {w.title} — {w.site}{tier} {w.date or ''}\n    {w.snippet}\n    {w.url}"
