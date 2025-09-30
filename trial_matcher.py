import pandas as pd
import re
import os # Import the 'os' library to work with file paths

# --- 1. Define File Paths Robustly ---
# Get the absolute path of the directory where this script is located
script_directory = os.path.dirname(os.path.abspath(__file__))

# Create the full, absolute paths for all the files
patient_filepath = os.path.join(script_directory, 'patient_diagnostics_mock.csv')
trials_filepath = os.path.join(script_directory, 'cleaned_clinical_trials.csv')
output_filepath = os.path.join(script_directory, 'successful_matches.csv')

# --- 2. Load the Datasets ---
try:
    patients_df = pd.read_csv(patient_filepath)
    trials_df = pd.read_csv(trials_filepath)
    print("✅ Successfully loaded patient and clinical trial data.")
except FileNotFoundError as e:
    # This error message is now more helpful
    print(f"❌ Error: Could not find an input file. Make sure '{os.path.basename(str(e))}' is in the same folder as the script.")
    exit()

# --- 3. The Matching Logic (This part is the same) ---
all_matches = []
print("\n🔎 Starting the matching process...")

for index, patient in patients_df.iterrows():
    patient_condition = patient['AI_Predicted_Condition'].lower()
    condition_matches = trials_df[trials_df['conditions'].str.contains(patient_condition, na=False)].copy()

    if condition_matches.empty:
        continue

    for i, trial in condition_matches.iterrows():
        eligibility_text = trial['eligibility_text']
        
        if patient['Biomarker_EGFR'] == 'Positive' and 'egfr' not in eligibility_text:
            continue

        age_numbers = re.findall(r'(\d+)\s+years', eligibility_text)
        age_numbers = [int(age) for age in age_numbers]

        if age_numbers and ('older' in eligibility_text or 'over' in eligibility_text):
            min_age = min(age_numbers)
            if patient['Patient_Age'] < min_age:
                continue

        all_matches.append({
            'Patient_ID': patient['Patient_ID'],
            'AI_Predicted_Condition': patient['AI_Predicted_Condition'],
            'Patient_Age': patient['Patient_Age'],
            'nct_id': trial['nct_id'],
            'trial_title': trial['title']
        })

print(f"✨ Matching complete. Found {len(all_matches)} potential matches.")

# --- 4. Save the Results to the Correct Location ---
matches_df = pd.DataFrame(all_matches)
matches_df.to_csv(output_filepath, index=False)

# This new message will show you the exact location of the saved file
print(f"\n✅ Success! Results were saved to: {output_filepath}")