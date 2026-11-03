"""The first version's matching rules, kept only to compare against.

This reproduces the original trial_matcher.py logic exactly, faults included:
it never checks trial status, it requires an EGFR mention for EGFR-positive
patients, and it reads any "N years" in a summary as a minimum age.
"""

import re

import pandas as pd

from . import config


def legacy_matches(patients, trials):
    """Return one row per (patient, trial) pair the first version would have listed."""
    trials = trials.fillna({"conditions": "", "eligibility_text": ""})
    rows = []
    for patient in patients.to_dict("records"):
        condition = str(patient["AI_Predicted_Condition"]).lower()
        candidates = trials[trials["conditions"].str.contains(condition, regex=False)]
        for trial in candidates.to_dict("records"):
            text = trial["eligibility_text"]
            if patient.get("Biomarker_EGFR") == "Positive" and "egfr" not in text:
                continue
            ages = [int(age) for age in re.findall(r"(\d+)\s+years", text)]
            if ages and ("older" in text or "over" in text) and patient["Patient_Age"] < min(ages):
                continue
            rows.append({"Patient_ID": patient["Patient_ID"], "nct_id": trial["nct_id"], "status": trial["status"]})
    return pd.DataFrame(rows, columns=["Patient_ID", "nct_id", "status"])


def summarize(matches):
    """Match count and the share of matches a patient could still join."""
    share = matches["status"].isin(config.OPEN_STATUS_POINTS).mean() * 100 if len(matches) else 0.0
    return {"matches": len(matches), "open_share": round(float(share), 1)}


def summary(patients, trials):
    return summarize(legacy_matches(patients, trials))
