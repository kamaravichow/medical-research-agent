"""ClinicalTrials.gov API v2 (free, no key)."""

from __future__ import annotations

from typing import Any

import httpx

from ..models import Trial, TrialLocation
from .base import get_json

BASE = "https://clinicaltrials.gov/api/v2/studies"
RECRUITING = ["RECRUITING", "NOT_YET_RECRUITING", "ENROLLING_BY_INVITATION"]


def to_trial(study: dict[str, Any]) -> Trial:
    p = study.get("protocolSection", {})
    ident = p.get("identificationModule", {})
    status = p.get("statusModule", {})
    design = p.get("designModule", {})
    arms = p.get("armsInterventionsModule", {})
    elig = p.get("eligibilityModule", {})
    locs = p.get("contactsLocationsModule", {}).get("locations", [])
    nct = ident.get("nctId", "")
    return Trial(
        id=f"nct:{nct}",
        nct_id=nct,
        title=ident.get("briefTitle") or ident.get("officialTitle") or nct,
        official_title=ident.get("officialTitle"),
        status=status.get("overallStatus"),
        phases=[ph.replace("PHASE", "Phase ").replace("EARLY_", "Early ").strip() for ph in design.get("phases", []) if ph != "NA"],
        study_type=design.get("studyType"),
        conditions=p.get("conditionsModule", {}).get("conditions", []),
        interventions=[f"{i.get('type', '').title()}: {i.get('name')}" if i.get("type") else i.get("name", "")
                       for i in arms.get("interventions", [])],
        sponsor=p.get("sponsorCollaboratorsModule", {}).get("leadSponsor", {}).get("name"),
        enrollment=(design.get("enrollmentInfo") or {}).get("count"),
        start_date=(status.get("startDateStruct") or {}).get("date"),
        primary_completion_date=(status.get("primaryCompletionDateStruct") or {}).get("date"),
        last_update=(status.get("lastUpdatePostDateStruct") or {}).get("date"),
        has_results=bool(study.get("hasResults")),
        summary=p.get("descriptionModule", {}).get("briefSummary"),
        primary_outcomes=[
            f"{o.get('measure')}" + (f" ({o['timeFrame']})" if o.get("timeFrame") else "")
            for o in p.get("outcomesModule", {}).get("primaryOutcomes", [])
        ],
        eligibility=elig.get("eligibilityCriteria"),
        min_age=elig.get("minimumAge"),
        max_age=elig.get("maximumAge"),
        sex=elig.get("sex"),
        locations=[TrialLocation(facility=l.get("facility"), city=l.get("city"), country=l.get("country"), status=l.get("status"))
                   for l in locs],
        url=f"https://clinicaltrials.gov/study/{nct}",
    )


class ClinicalTrialsClient:
    name = "clinicaltrials"

    def __init__(self, client: httpx.AsyncClient):
        self._client = client

    async def search(
        self,
        *,
        condition: str | None = None,
        term: str | None = None,
        intervention: str | None = None,
        location: str | None = None,
        recruiting_only: bool = False,
        phases: list[str] | None = None,
        limit: int = 20,
        sort_recent: bool = True,
    ) -> list[Trial]:
        if not any((condition, term, intervention, location)):
            raise ValueError("Give at least one of condition, term, intervention or location")
        params: dict[str, Any] = {"pageSize": min(limit, 100), "format": "json", "countTotal": "false"}
        if condition:
            params["query.cond"] = condition
        if term:
            params["query.term"] = term
        if intervention:
            params["query.intr"] = intervention
        if location:
            params["query.locn"] = location
        if recruiting_only:
            params["filter.overallStatus"] = ",".join(RECRUITING)
        if phases:
            params["filter.advanced"] = " OR ".join(f"AREA[Phase]{ph.upper().replace(' ', '')}" for ph in phases)
        if sort_recent:
            params["sort"] = "LastUpdatePostDate:desc"
        data = await get_json(self._client, BASE, params=params, provider=self.name)
        return [to_trial(s) for s in data.get("studies", [])]

    async def get(self, nct_id: str) -> Trial:
        data = await get_json(self._client, f"{BASE}/{nct_id.upper()}", params={"format": "json"}, provider=self.name)
        return to_trial(data)
