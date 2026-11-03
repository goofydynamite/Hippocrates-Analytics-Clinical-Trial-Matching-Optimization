"""Build the self-contained Trial Scout dashboard from the processed CSVs."""

import json
from pathlib import Path

import pandas as pd

from . import config, legacy, matching

TEMPLATE = Path(__file__).with_name("dashboard_template.html")
TRIAL_FIELDS = [
    "nct_id", "trial_title", "match_score", "match_tier", "condition_match", "geography", "best_site",
    "sites_in_country", "status", "phases", "study_type", "study_url", "match_reasons", "review_flags",
]


def build_payload(patients, trials, matches, funnel):
    matches = matches.fillna("")
    by_patient = {pid: group[TRIAL_FIELDS].to_dict("records") for pid, group in matches.groupby("Patient_ID")}
    open_trials = int(trials["status"].isin(config.OPEN_STATUS_POINTS).sum())
    gate_averages = {
        gate: round(float(funnel[f"remaining_after_{gate}"].mean()), 1) for gate in matching.GATES
    }
    tier_counts = (
        matches.groupby(["Patient_ID", "match_tier"]).size().unstack(fill_value=0).to_dict("index")
        if not matches.empty else {}
    )
    patient_rows = patients.where(patients.notna(), "").to_dict("records")
    for row in patient_rows:
        row["tiers"] = {t: int(tier_counts.get(row["Patient_ID"], {}).get(t, 0)) for t in ("Strong", "Good", "Possible")}
    return {
        "summary": {
            "patients": len(patients),
            "trials": len(trials),
            "open_trials": open_trials,
            "matches": len(matches),
            "strong_patients": sum(1 for p in patient_rows if p["tiers"]["Strong"]),
            "snapshot": str(pd.to_datetime(trials["last_update"], errors="coerce").max().date()),
            "has_criteria": bool(trials["eligibility_criteria"].fillna("").astype(bool).any()),
        },
        "legacy": legacy.summary(patients, trials),
        "funnel": {"start": len(trials), "gates": gate_averages},
        "patients": patient_rows,
        "matches": by_patient,
    }


def render(payload):
    # "</" is escaped so trial text cannot close the embedding <script> tag.
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return TEMPLATE.read_text(encoding="utf-8").replace("/*__DATA__*/null", data)


def run(out_path=None):
    out_path = out_path or config.DASHBOARD_HTML
    payload = build_payload(
        pd.read_csv(config.PATIENTS_CSV),
        pd.read_csv(config.TRIALS_CSV, dtype=str),
        pd.read_csv(config.MATCHES_CSV),
        pd.read_csv(config.FUNNEL_CSV),
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render(payload), encoding="utf-8", newline="\n")
    print(f"Dashboard written to {out_path}")
