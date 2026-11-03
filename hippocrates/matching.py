"""Screen patients against trials using hard gates, then rank what survives.

A trial that clears every gate is a candidate for clinician review. It is not
a statement that the patient is eligible.
"""

import re
from dataclasses import dataclass, field

import pandas as pd

from . import config, parsing

GATES = ["condition", "status", "age", "sex", "biomarker", "setting", "geography"]
REQUIRED_PATIENT_COLUMNS = ["Patient_ID", "AI_Predicted_Condition", "Patient_Age"]
REQUIRED_TRIAL_COLUMNS = ["nct_id", "title", "status", "conditions", "age_min", "age_max"]
_NUMERIC_TRIAL_COLUMNS = ["age_min", "age_max", "text_age_min", "text_age_max"]
_SEX_VALUES = {"female": "FEMALE", "male": "MALE"}


@dataclass
class Evaluation:
    excluded_by: str | None = None
    score: int = 0
    reasons: list = field(default_factory=list)
    flags: list = field(default_factory=list)
    best_site: str = ""
    condition_match: str = ""
    geography: str = ""
    sites_in_country: int = 0

    @property
    def tier(self):
        return next(label for floor, label in config.TIERS if self.score >= floor)


def _compile_terms(terms):
    return re.compile(r"(?<![a-z])(?:" + "|".join(terms) + r")(?![a-z])")


_CONDITION_PATTERNS = {
    name: {group: _compile_terms(terms) for group, terms in groups.items()}
    for name, groups in config.CONDITION_TAXONOMY.items()
}


def condition_match(patient_condition, trial_conditions, trial_title=""):
    """Return 'exact', 'broad' or ''. Unknown conditions match on the literal word."""
    key = patient_condition.strip().lower()
    trial_text = trial_conditions.lower()
    patterns = _CONDITION_PATTERNS.get(key)
    if patterns is None:
        return "exact" if re.search(rf"\b{re.escape(key)}\b", trial_text) else ""
    if patterns["exact"].search(trial_text):
        return "exact"
    if patterns["broad"].search(trial_text) and not patterns["rivals"].search(f"{trial_text} {trial_title.lower()}"):
        return "broad"
    return ""


def _number(value):
    return None if value is None or pd.isna(value) or value == "" else float(value)


def _geography(patient_site, sites):
    """Return the closest tier, the best site's label and the in-country site count."""
    if not sites:
        return "unknown", "", 0
    domestic = [s for s in sites if s["country"] == patient_site["country"]]
    same_city = [
        s for s in domestic
        if s["city"].lower() == patient_site["city"].lower() and s["state"] == patient_site["state"]
    ]
    same_state = [s for s in domestic if patient_site["state"] and s["state"] == patient_site["state"]]
    if same_city:
        return "city", _site_label(same_city[0]), len(domestic)
    if same_state:
        return "state", _site_label(same_state[0]), len(domestic)
    if domestic:
        return "country", _site_label(domestic[0]), len(domestic)
    return "international", _site_label(sites[0]), 0


def _site_label(site):
    return ", ".join(p for p in (site["city"], site["state"] or site["country"]) if p)


def _check_biomarkers(patient, trial):
    """Return (excluded_reason, aligned_labels). Untested markers never exclude."""
    aligned = []
    egfr = str(patient.get("Biomarker_EGFR", ""))
    rule = trial.get("egfr_rule", "none")
    if egfr == "Negative" and rule == "required":
        return "EGFR alteration required", aligned
    if egfr == "Positive" and rule in ("required", "targeted"):
        aligned.append("EGFR-directed")

    idh = str(patient.get("Biomarker_IDH", "")).lower()
    rule = trial.get("idh_rule", "any")
    if idh in ("mutant", "wildtype") and rule != "any":
        if idh != rule:
            return f"IDH-{rule} required", aligned
        aligned.append(f"IDH-{rule}")

    mgmt = str(patient.get("Biomarker_MGMT", "")).lower()
    rule = trial.get("mgmt_rule", "any")
    if mgmt in ("methylated", "unmethylated") and rule != "any":
        if mgmt != rule:
            return f"MGMT {rule} required", aligned
        aligned.append(f"MGMT {rule}")
    return None, aligned


def evaluate(patient, trial, sites, patient_site, snapshot_date=None):
    """Run one patient against one trial. Gates stop at the first failure."""
    result = Evaluation()

    match = condition_match(patient["AI_Predicted_Condition"], trial["conditions"], trial["title"])
    if not match:
        result.excluded_by = "condition"
        return result
    result.condition_match = match

    if trial["status"] not in config.OPEN_STATUS_POINTS:
        result.excluded_by = "status"
        return result

    age = patient["Patient_Age"]
    low, high = _number(trial.get("age_min")), _number(trial.get("age_max"))
    text_low, text_high = _number(trial.get("text_age_min")), _number(trial.get("text_age_max"))
    if (
        (low is not None and age < low) or (high is not None and age > high)
        or (text_low is not None and age < text_low) or (text_high is not None and age > text_high)
    ):
        result.excluded_by = "age"
        return result

    sex = _SEX_VALUES.get(str(patient.get("Patient_Sex", "")).lower())
    trial_sex = trial.get("sex") or "ALL"
    if sex and trial_sex in _SEX_VALUES.values() and trial_sex != sex:
        result.excluded_by = "sex"
        return result

    conflict, aligned = _check_biomarkers(patient, trial)
    if conflict:
        result.excluded_by = "biomarker"
        result.reasons.append(conflict)
        return result

    setting = str(patient.get("Disease_Setting", "")).lower().replace(" ", "_")
    trial_setting = trial.get("disease_setting", "any")
    if setting in ("recurrent", "newly_diagnosed") and trial_setting != "any" and setting != trial_setting:
        result.excluded_by = "setting"
        return result

    geography, result.best_site, result.sites_in_country = _geography(patient_site, sites)
    if geography == "international":
        result.excluded_by = "geography"
        return result
    result.geography = geography

    _score(result, patient, trial, aligned, setting == trial_setting, snapshot_date)
    return result


def _score(result, patient, trial, aligned, setting_aligned, snapshot_date):
    points = config.SCORE
    score = points["condition"][result.condition_match]
    score += points["geography"][result.geography]
    score += config.OPEN_STATUS_POINTS[trial["status"]]
    score += points["biomarker"]["aligned" if aligned else "neutral"]
    score += points["setting"]["aligned" if setting_aligned else "neutral"]
    interventional = trial.get("study_type") == "INTERVENTIONAL"
    score += points["design"]["interventional" if interventional else "other"]

    condition_label = patient["AI_Predicted_Condition"]
    result.reasons.append(
        f"{condition_label} listed" if result.condition_match == "exact"
        else f"Broader tumour family that may include {condition_label}"
    )
    if result.best_site:
        result.reasons.append(f"Site in {result.best_site}")
    if aligned:
        result.reasons.append(f"Biomarker fit: {', '.join(aligned)}")
    if setting_aligned:
        result.reasons.append(str(patient["Disease_Setting"]) + " disease specified")

    if result.geography == "unknown":
        result.flags.append("No site listed")
    if trial["status"] == "ENROLLING_BY_INVITATION":
        result.flags.append("Enrollment is by invitation only")
    if not interventional:
        result.flags.append(f"{str(trial.get('study_type', '')).replace('_', ' ').title()} study, not a treatment trial")
    if not trial.get("eligibility_criteria"):
        result.flags.append("Full eligibility criteria not reviewed")
    last_update = pd.to_datetime(trial.get("last_update"), errors="coerce")
    if snapshot_date is not None and pd.notna(last_update):
        if (snapshot_date - last_update).days > config.STALE_AFTER_DAYS:
            score -= points["stale_penalty"]
            result.flags.append("Record not updated in over 2 years")
    result.score = max(0, min(100, score))


def _validate(df, required, name):
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"{name} is missing required columns: {missing}")


def match_all(patients, trials):
    """Return (matches, funnel) DataFrames for every patient against every trial."""
    _validate(patients, REQUIRED_PATIENT_COLUMNS, "Patient data")
    _validate(trials, REQUIRED_TRIAL_COLUMNS, "Trial data")
    # An all-empty column loads as float NaN, which is truthy, so restore blanks here.
    text_columns = trials.columns.difference(_NUMERIC_TRIAL_COLUMNS)
    trials = trials.astype({c: object for c in text_columns}).fillna({c: "" for c in text_columns})
    records = trials.to_dict("records")
    sites_by_trial = {t["nct_id"]: parsing.parse_sites(t.get("locations", "")) for t in records}
    snapshot = pd.to_datetime(trials.get("last_update"), errors="coerce").max() if "last_update" in trials else None

    matches, funnel = [], []
    for patient in patients.to_dict("records"):
        patient_site = parsing.parse_patient_location(patient.get("Patient_Location", ""))
        counts = dict.fromkeys(GATES, 0)
        for trial in records:
            result = evaluate(patient, trial, sites_by_trial[trial["nct_id"]], patient_site, snapshot)
            if result.excluded_by:
                counts[result.excluded_by] += 1
                continue
            matches.append(_match_row(patient, trial, result))
        funnel.append(_funnel_row(patient, counts, len(records)))

    columns = [
        "Patient_ID", "AI_Predicted_Condition", "Patient_Age", "nct_id", "trial_title", "match_score",
        "match_tier", "condition_match", "geography", "best_site", "sites_in_country", "status",
        "phases", "study_type", "sponsor", "study_url", "match_reasons", "review_flags",
    ]
    matches_df = pd.DataFrame(matches, columns=columns)
    if not matches_df.empty:
        matches_df = matches_df.sort_values(
            ["Patient_ID", "match_score", "nct_id"], ascending=[True, False, True]
        ).reset_index(drop=True)
        matches_df["patient_rank"] = matches_df.groupby("Patient_ID").cumcount() + 1
    return matches_df, pd.DataFrame(funnel)


def _match_row(patient, trial, result):
    return {
        "Patient_ID": patient["Patient_ID"],
        "AI_Predicted_Condition": patient["AI_Predicted_Condition"],
        "Patient_Age": patient["Patient_Age"],
        "nct_id": trial["nct_id"],
        "trial_title": trial["title"],
        "match_score": result.score,
        "match_tier": result.tier,
        "condition_match": result.condition_match,
        "geography": result.geography,
        "best_site": result.best_site,
        "sites_in_country": result.sites_in_country,
        "status": trial["status"],
        "phases": trial.get("phases", ""),
        "study_type": trial.get("study_type", ""),
        "sponsor": trial.get("sponsor", ""),
        "study_url": trial.get("study_url", ""),
        "match_reasons": "; ".join(result.reasons),
        "review_flags": "; ".join(result.flags),
    }


def _funnel_row(patient, counts, total):
    row = {"Patient_ID": patient["Patient_ID"], "trials_screened": total}
    remaining = total
    for gate in GATES:
        remaining -= counts[gate]
        row[f"excluded_{gate}"] = counts[gate]
        row[f"remaining_after_{gate}"] = remaining
    return row


def run(patients_path=None, trials_path=None, matches_path=None, funnel_path=None):
    patients = pd.read_csv(patients_path or config.PATIENTS_CSV)
    trials = pd.read_csv(trials_path or config.TRIALS_CSV, dtype={"enrollment": str})
    matches, funnel = match_all(patients, trials)
    matches.to_csv(matches_path or config.MATCHES_CSV, index=False, lineterminator="\n")
    funnel.to_csv(funnel_path or config.FUNNEL_CSV, index=False, lineterminator="\n")
    print(f"Screened {len(patients)} patients against {len(trials)} trials: {len(matches)} candidate matches")
    return matches, funnel
