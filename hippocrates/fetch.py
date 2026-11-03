"""Download current studies from the ClinicalTrials.gov v2 API.

The CSV export has no eligibility criteria or exact age limits. This client
writes the export's column names plus those fields, so `clean` can read either.
"""

import json
import time
import urllib.parse
import urllib.request

import pandas as pd

from . import config

_CLOSED_SITE_STATUSES = {"COMPLETED", "TERMINATED", "WITHDRAWN", "SUSPENDED"}


def study_to_row(study):
    """Flatten one API study into the CSV export's columns."""
    protocol = study.get("protocolSection", {})
    ident = protocol.get("identificationModule", {})
    status = protocol.get("statusModule", {})
    desc = protocol.get("descriptionModule", {})
    conds = protocol.get("conditionsModule", {})
    arms = protocol.get("armsInterventionsModule", {})
    design = protocol.get("designModule", {})
    elig = protocol.get("eligibilityModule", {})
    sponsor = protocol.get("sponsorCollaboratorsModule", {}).get("leadSponsor", {})
    sites = protocol.get("contactsLocationsModule", {}).get("locations", [])
    nct_id = ident.get("nctId", "")

    return {
        "NCT Number": nct_id,
        "Study Title": ident.get("officialTitle") or ident.get("briefTitle", ""),
        "Study URL": f"https://clinicaltrials.gov/study/{nct_id}",
        "Study Status": status.get("overallStatus", ""),
        "Brief Summary": desc.get("briefSummary", ""),
        "Conditions": "|".join(conds.get("conditions", [])),
        "Interventions": "|".join(
            f"{i.get('type', '')}: {i.get('name', '')}" for i in arms.get("interventions", [])
        ),
        "Sponsor": sponsor.get("name", ""),
        "Sex": elig.get("sex", ""),
        "Age": ", ".join(elig.get("stdAges", [])),
        "Phases": "|".join(design.get("phases", [])),
        "Enrollment": design.get("enrollmentInfo", {}).get("count", ""),
        "Study Type": design.get("studyType", ""),
        "Last Update Posted": status.get("lastUpdatePostDateStruct", {}).get("date", ""),
        "Locations": _format_sites(sites),
        "Eligibility Criteria": elig.get("eligibilityCriteria", ""),
        "Minimum Age": elig.get("minimumAge", ""),
        "Maximum Age": elig.get("maximumAge", ""),
    }


def _format_sites(sites):
    """Prefer sites still taking patients; keep all if the API marks none open."""
    open_sites = [s for s in sites if s.get("status") not in _CLOSED_SITE_STATUSES]
    return "|".join(
        ", ".join(str(s[k]) for k in ("facility", "city", "state", "zip", "country") if s.get(k))
        for s in open_sites or sites
    )


def fetch_studies(condition, page_size=200, opener=urllib.request.urlopen, pause=0.3):
    """Yield raw studies for a condition, following the API's page tokens."""
    token = None
    while True:
        params = {"query.cond": condition, "pageSize": page_size, "format": "json"}
        if token:
            params["pageToken"] = token
        request = urllib.request.Request(
            f"{config.CTGOV_API}?{urllib.parse.urlencode(params)}",
            headers={"User-Agent": "hippocrates-analytics/2.0"},
        )
        with opener(request, timeout=60) as response:
            payload = json.load(response)
        yield from payload.get("studies", [])
        token = payload.get("nextPageToken")
        if not token:
            return
        time.sleep(pause)


def run(condition="glioblastoma OR astrocytoma OR meningioma", out_path=None):
    out_path = out_path or config.API_CSV
    rows = [study_to_row(study) for study in fetch_studies(condition)]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out_path, index=False, lineterminator="\n")
    print(f"Fetched {len(rows)} studies -> {out_path.name}")
