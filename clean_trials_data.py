# Import the pandas library, the essential tool for data manipulation in Python
import pandas as pd

# --- 1. Load the Raw Data ---
# Use the actual filename you downloaded from the search results page.
# For this example, we'll assume it's named 'glioblastoma_search_results.csv'
file_name = 'glioblastoma_search_results.csv'

try:
    # We specify 'dtype=str' to ensure all columns are read as text initially.
    # This prevents pandas from making incorrect assumptions about data types.
    raw_trials_df = pd.read_csv(file_name, dtype=str)
    print(f"✅ Successfully loaded '{file_name}'")
    print(f"Raw data has {raw_trials_df.shape[0]} rows and {raw_trials_df.shape[1]} columns.")
except FileNotFoundError:
    print(f"❌ Error: '{file_name}' not found. Please make sure the file is in the same directory as the script.")
    exit()

# --- 2. Select the Most Important Columns for Our Project ---
# From the 30 columns, we only need a few key ones for matching.
# Note: The raw file does not contain a dedicated 'Eligibility Criteria' column.
# The 'Brief Summary' and 'Conditions' columns are our best proxies.
columns_to_keep = [
    'NCT Number',
    'Study Title',
    'Study Status',
    'Conditions',
    'Interventions',
    'Age',
    'Locations',
    'Brief Summary' # We will search this text for eligibility details
]

# Create a new DataFrame with only the columns we need.
# We use .copy() to avoid warnings and ensure we are working on a new object.
cleaned_df = raw_trials_df[columns_to_keep].copy()
print(f"\nFiltered down to {cleaned_df.shape[1]} relevant columns.")

# --- 3. Rename Columns for Easy Access ---
# Snake_case (e.g., 'nct_number') is the standard in Python and is much easier to work with.
cleaned_df.rename(columns={
    'NCT Number': 'nct_id',
    'Study Title': 'title',
    'Study Status': 'status',
    'Conditions': 'conditions',
    'Interventions': 'interventions',
    'Age': 'age_criteria',
    'Locations': 'locations',
    'Brief Summary': 'eligibility_text' # Renaming to reflect its new purpose
}, inplace=True)
print("Renamed columns to a cleaner, more usable format.")

# --- 4. Clean and Standardize Data ---
# Drop rows where we don't have the essential text to search for matches.
cleaned_df.dropna(subset=['eligibility_text', 'conditions'], inplace=True)

# Convert text to lowercase to make our keyword search case-insensitive.
cleaned_df['eligibility_text'] = cleaned_df['eligibility_text'].str.lower()
cleaned_df['conditions'] = cleaned_df['conditions'].str.lower()
print("Cleaned data: Dropped empty rows and converted text to lowercase.")

# --- 5. Save the Final, Cleaned Dataset ---
# This file is now ready to be used by your matching script (Step 3).
output_filename = 'cleaned_clinical_trials.csv'
cleaned_df.to_csv(output_filename, index=False)

print(f"\n✨ Success! Cleaned data with {cleaned_df.shape[0]} trials saved to '{output_filename}'.")