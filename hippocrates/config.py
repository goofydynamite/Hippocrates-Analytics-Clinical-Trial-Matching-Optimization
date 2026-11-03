"""Paths and matching policy. Every tunable decision lives here."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW_CSV = ROOT / "data" / "raw" / "glioblastoma_search_results.csv"
API_CSV = ROOT / "data" / "raw" / "ctgov_api_studies.csv"
PROCESSED = ROOT / "data" / "processed"
TRIALS_CSV = PROCESSED / "cleaned_clinical_trials.csv"
PATIENTS_CSV = PROCESSED / "patient_diagnostics_mock.csv"
MATCHES_CSV = PROCESSED / "successful_matches.csv"
FUNNEL_CSV = PROCESSED / "match_funnel.csv"
DASHBOARD_HTML = ROOT / "dashboard" / "index.html"
TABLEAU_DIR = ROOT / "tableau"

# Statuses a patient can still act on, with the points each earns.
OPEN_STATUS_POINTS = {
    "RECRUITING": 10,
    "NOT_YET_RECRUITING": 7,
    "ENROLLING_BY_INVITATION": 5,
    "AVAILABLE": 5,  # expanded access
}

# "exact" terms name the patient's tumour; "broad" terms describe a family of
# tumours that includes it, so the trial may or may not cover this patient.
# "rivals" are other tumours: a broad term beside one usually means "brain tumour
# of that kind" (e.g. glioblastoma|brain tumor), so it does not count as a match.
CONDITION_TAXONOMY = {
    "glioblastoma": {
        "exact": [r"glioblastomas?", r"gbm", r"gliosarcomas?", r"grade (?:iv|4) (?:astrocytoma|glioma)"],
        "broad": [
            r"high[- ]grade gliomas?", r"malignant gliomas?", r"gliomas?, malignant", r"gliomas?",
            r"(?:primary |malignant )?brain (?:tumou?rs?|cancers?|neoplasms?)",
            r"brain neoplasms?, malignant", r"(?:cns|central nervous system) (?:tumou?rs?|neoplasms?)",
        ],
        "rivals": [r"meningiomas?"],
    },
    "astrocytoma": {
        "exact": [r"astrocytomas?"],
        "broad": [
            r"high[- ]grade gliomas?", r"low[- ]grade gliomas?", r"malignant gliomas?",
            r"gliomas?, malignant", r"gliomas?",
            r"(?:primary |malignant )?brain (?:tumou?rs?|cancers?|neoplasms?)",
            r"(?:cns|central nervous system) (?:tumou?rs?|neoplasms?)",
        ],
        "rivals": [r"meningiomas?"],
    },
    "meningioma": {
        "exact": [r"meningiomas?"],
        "broad": [
            r"(?:primary )?brain (?:tumou?rs?|neoplasms?)",
            r"(?:cns|central nervous system) (?:tumou?rs?|neoplasms?)",
        ],
        "rivals": [
            r"gliomas?", r"glioblastomas?", r"gbm", r"astrocytomas?", r"gliosarcomas?", r"dipg",
            r"ependymomas?", r"medulloblastomas?", r"oligodendrogliomas?",
        ],
    },
}

# Points by dimension. They add up to 100 before penalties.
SCORE = {
    "condition": {"exact": 35, "broad": 18},
    "geography": {"city": 25, "state": 18, "country": 10, "unknown": 5},
    "biomarker": {"aligned": 20, "neutral": 8},
    "setting": {"aligned": 5, "neutral": 2},
    "design": {"interventional": 5, "other": 2},
    "stale_penalty": 5,
}
TIERS = [(75, "Strong"), (55, "Good"), (0, "Possible")]

# A record not updated for this long before the snapshot may have a wrong status.
STALE_AFTER_DAYS = 730

CTGOV_API = "https://clinicaltrials.gov/api/v2/studies"
