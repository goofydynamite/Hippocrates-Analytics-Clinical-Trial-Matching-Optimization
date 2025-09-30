import pandas as pd
import random

# --- Generate Realistic Mock Patient Data ---
data = {
    'Patient_ID': [f'PID-{i:03d}' for i in range(1, 21)],
    'AI_Predicted_Condition': random.choices(
        ['Glioblastoma', 'Astrocytoma', 'Meningioma'],
        weights=[10, 5, 5], k=20
    ),
    'Biomarker_EGFR': random.choices(['Positive', 'Negative'], k=20),
    'Tumor_Volume_mm3': [random.randint(1500, 5000) for _ in range(20)],
    'Patient_Age': [random.randint(35, 75) for _ in range(20)],
    'Patient_Location': random.choices(
        ['New York, NY', 'Houston, TX', 'Chicago, IL', 'Philadelphia, PA', 'Los Angeles, CA'],
        k=20
    )
}

patient_df = pd.DataFrame(data)

# --- Save to a CSV file ---
patient_df.to_csv('patient_diagnostics_mock.csv', index=False)

print("✅ Successfully created 'patient_diagnostics_mock.csv' with 20 sample patients.")