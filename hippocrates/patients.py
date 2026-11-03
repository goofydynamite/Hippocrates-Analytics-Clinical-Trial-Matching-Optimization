"""Reproducible synthetic patients. No real patient data is used anywhere."""

import random

import pandas as pd

from . import config

CITIES = ["New York, NY", "Houston, TX", "Chicago, IL", "Philadelphia, PA", "Los Angeles, CA"]
DEFAULT_SEED = 42


def _idh_status(rng, condition):
    # WHO 2021: glioblastoma is IDH-wildtype by definition; adult diffuse
    # astrocytoma is IDH-mutant by definition; IDH is not tested in meningioma.
    return {"Glioblastoma": "Wildtype", "Astrocytoma": "Mutant", "Meningioma": "Not Tested"}[condition]


def generate_patients(count=20, seed=DEFAULT_SEED):
    rng = random.Random(seed)
    rows = []
    for number in range(1, count + 1):
        condition = rng.choices(["Glioblastoma", "Astrocytoma", "Meningioma"], weights=[10, 5, 5])[0]
        glial = condition != "Meningioma"
        rows.append({
            "Patient_ID": f"PID-{number:03d}",
            "AI_Predicted_Condition": condition,
            "Biomarker_EGFR": rng.choice(["Positive", "Negative"]) if glial else "Not Tested",
            "Tumor_Volume_mm3": rng.randint(1500, 5000),
            "Patient_Age": rng.randint(35, 75),
            "Patient_Location": rng.choice(CITIES),
            "Patient_Sex": rng.choice(["Female", "Male"]),
            "Biomarker_IDH": _idh_status(rng, condition),
            "Biomarker_MGMT": rng.choice(["Methylated", "Unmethylated"]) if glial else "Not Tested",
            "Disease_Setting": rng.choice(["Newly Diagnosed", "Recurrent"]),
        })
    return pd.DataFrame(rows)


def run(count=20, seed=DEFAULT_SEED, out_path=None):
    out_path = out_path or config.PATIENTS_CSV
    patients = generate_patients(count, seed)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    patients.to_csv(out_path, index=False, lineterminator="\n")
    print(f"Generated {len(patients)} synthetic patients (seed={seed}) -> {out_path.name}")
    return patients
