"""openFDA (free; key optional): FDA drug labels and FAERS adverse-event counts."""

from __future__ import annotations

from typing import Any

import httpx

from ..models import AdverseEventCount, AdverseEventSummary, DrugLabel
from .base import ProviderError, get_json, request

BASE = "https://api.fda.gov/drug"


def _join(label: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = label.get(key)
        if value:
            return "\n\n".join(value) if isinstance(value, list) else str(value)
    return None


def _quote(name: str) -> str:
    return '"' + name.replace('"', "").strip() + '"'


def to_label(label: dict[str, Any]) -> DrugLabel:
    ofda = label.get("openfda", {})
    set_id = label.get("set_id") or (ofda.get("spl_set_id") or [None])[0]
    effective = label.get("effective_time")
    if effective and len(effective) == 8:
        effective = f"{effective[:4]}-{effective[4:6]}-{effective[6:]}"
    return DrugLabel(
        id=f"fda:{set_id or label.get('id')}",
        brand_names=ofda.get("brand_name", []),
        generic_names=ofda.get("generic_name", []),
        manufacturer=(ofda.get("manufacturer_name") or [None])[0],
        route=ofda.get("route", []),
        pharm_class=ofda.get("pharm_class_epc", []) or ofda.get("pharm_class_moa", []),
        boxed_warning=_join(label, "boxed_warning"),
        indications=_join(label, "indications_and_usage"),
        dosage=_join(label, "dosage_and_administration"),
        contraindications=_join(label, "contraindications"),
        warnings=_join(label, "warnings_and_cautions", "warnings"),
        adverse_reactions=_join(label, "adverse_reactions"),
        interactions=_join(label, "drug_interactions"),
        pregnancy=_join(label, "pregnancy", "use_in_specific_populations"),
        renal_hepatic=_join(label, "use_in_specific_populations"),
        effective_date=effective,
        url=f"https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid={set_id}" if set_id else None,
    )


class OpenFDAClient:
    name = "openfda"

    def __init__(self, client: httpx.AsyncClient, api_key: str | None = None):
        self._client = client
        self._key = api_key

    def _params(self, params: dict[str, Any]) -> dict[str, Any]:
        if self._key:
            params["api_key"] = self._key
        return params

    async def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        # openFDA answers "no matches" with a 404 body, which is an empty result, not an outage.
        response = await request(self._client, "GET", f"{BASE}/{path}", params=self._params(params),
                                 provider=self.name, ok_statuses=(404,))
        if response.status_code == 404:
            return {"results": [], "meta": {"results": {"total": 0}}}
        return response.json()

    async def label(self, drug: str, limit: int = 1) -> list[DrugLabel]:
        q = _quote(drug)
        search = f"openfda.generic_name:{q} OR openfda.brand_name:{q} OR openfda.substance_name:{q}"
        data = await self._get("label.json", {"search": search, "limit": limit})
        return [to_label(item) for item in data.get("results", [])]

    async def adverse_events(self, drug: str, top: int = 15) -> AdverseEventSummary:
        q = _quote(drug)
        field = f"(patient.drug.openfda.generic_name:{q} OR patient.drug.openfda.brand_name:{q})"
        counts = await self._get("event.json", {"search": field, "count": "patient.reaction.reactionmeddrapt.exact", "limit": top})
        total = await self._get("event.json", {"search": field, "limit": 1})
        serious = await self._get("event.json", {"search": f"{field} AND serious:1", "limit": 1})
        return AdverseEventSummary(
            drug=drug,
            total_reports=(total.get("meta", {}).get("results") or {}).get("total"),
            serious_reports=(serious.get("meta", {}).get("results") or {}).get("total"),
            top_reactions=[AdverseEventCount(term=r["term"].title(), count=r["count"]) for r in counts.get("results", [])],
        )


__all__ = ["OpenFDAClient", "ProviderError"]
