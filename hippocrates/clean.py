"""Convert a raw ClinicalTrials.gov export into the trial table the matcher uses."""

import pandas as pd

from . import config, parsing

# The first version's column names are kept, so its matching rules (legacy.py) still run.
RENAMES = {
    "NCT Number": "nct_id",
    "Study Title": "title",
    "Study Status": "status",
    "Conditions": "conditions",
    "Interventions": "interventions",
    "Age": "age_criteria",
    "Locations": "locations",
    "Brief Summary": "eligibility_text",
    "Study URL": "study_url",
    "Sex": "sex",
    "Phases": "phases",
    "Study Type": "study_type",
    "Enrollment": "enrollment",
    "Sponsor": "sponsor",
    "Last Update Posted": "last_update",
    "Eligibility Criteria": "eligibility_criteria",
    "Minimum Age": "minimum_age",
    "Maximum Age": "maximum_age",
}
REQUIRED = ["NCT Number", "Study Title", "Study Status", "Conditions", "Brief Summary", "Age"]


def clean_trials(raw):
    missing = [c for c in REQUIRED if c not in raw.columns]
    if missing:
        raise ValueError(f"Raw export is missing required columns: {missing}")

    df = raw.reindex(columns=list(RENAMES)).rename(columns=RENAMES)
    df = df.dropna(subset=["nct_id", "eligibility_text", "conditions"])
    df = df.drop_duplicates("nct_id").fillna("").copy()
    df["eligibility_text"] = df["eligibility_text"].str.lower()
    df["conditions"] = df["conditions"].str.lower()
    return pd.concat([df, df.apply(_derive, axis=1, result_type="expand")], axis=1)


def _derive(row):
    inclusion, _ = parsing.split_eligibility(row["eligibility_criteria"])
    age_min, age_max = parsing.bounds_from_categories(row["age_criteria"])
    exact_min = parsing.parse_structured_age(row["minimum_age"])
    exact_max = parsing.parse_structured_age(row["maximum_age"])
    text_min, text_max = parsing.age_bounds_from_text(row["eligibility_text"])
    return {
        "age_min": exact_min if exact_min is not None else age_min,
        "age_max": exact_max if exact_max is not None else age_max,
        "text_age_min": text_min,
        "text_age_max": text_max,
        "disease_setting": parsing.disease_setting(row["title"], row["conditions"], inclusion),
        **parsing.biomarker_profile(
            row["title"], row["conditions"], row["interventions"], row["eligibility_text"], inclusion
        ),
    }


def run(raw_path=None, out_path=None):
    raw_path = raw_path or (config.API_CSV if config.API_CSV.exists() else config.RAW_CSV)
    out_path = out_path or config.TRIALS_CSV
    raw = pd.read_csv(raw_path, dtype=str)
    trials = clean_trials(raw)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    trials.to_csv(out_path, index=False, lineterminator="\n")
    print(f"Cleaned {len(trials)} of {len(raw)} trials from {raw_path.name} -> {out_path.name}")
    return trials
