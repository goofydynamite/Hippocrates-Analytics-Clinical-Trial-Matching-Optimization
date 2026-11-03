import pandas as pd

from hippocrates import legacy

PATIENTS = pd.DataFrame([
    {"Patient_ID": "P1", "AI_Predicted_Condition": "Glioblastoma", "Biomarker_EGFR": "Positive", "Patient_Age": 40},
    {"Patient_ID": "P2", "AI_Predicted_Condition": "Glioblastoma", "Biomarker_EGFR": "Negative", "Patient_Age": 40},
])
TRIALS = pd.DataFrame([
    {"nct_id": "A", "status": "COMPLETED", "conditions": "glioblastoma", "eligibility_text": "egfr study"},
    {"nct_id": "B", "status": "RECRUITING", "conditions": "glioblastoma", "eligibility_text": "survival over 50 years"},
    {"nct_id": "C", "status": "RECRUITING", "conditions": "meningioma", "eligibility_text": "egfr"},
])


def test_reproduces_first_version_faults():
    matches = legacy.legacy_matches(PATIENTS, TRIALS)
    pairs = set(zip(matches["Patient_ID"], matches["nct_id"]))
    # P1 is EGFR-positive, so only trials mentioning EGFR survive; B is also dropped
    # because "over 50 years" reads as a minimum age of 50. Closed trial A is kept.
    assert pairs == {("P1", "A"), ("P2", "A")}


def test_summary_share_of_open_matches():
    # With no EGFR mention anywhere, the EGFR-positive patient matches nothing.
    trials = TRIALS.assign(eligibility_text="")
    assert legacy.summary(PATIENTS, trials) == {"matches": 2, "open_share": 50.0}
