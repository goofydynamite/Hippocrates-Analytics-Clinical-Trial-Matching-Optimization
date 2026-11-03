# Updating the Power BI report

`powerbi/Hippocrates - Autonomous Diagnostic Imaging & Clinical Trial Scout.pbix` still holds the first version's data. These changes need Power BI Desktop. None of them have been tested in it.

## Reconnect the data

1. Open the report, then go to **Transform data > Data source settings**.
2. Point each source at `data/processed/` in this repository. The file names are unchanged.
3. Original column names are unchanged, so existing fields should still load. New columns appear only after you add them to each query.
4. Select **Refresh**, then add `match_funnel.csv` as a new table.
5. Relate `patient_diagnostics_mock[Patient_ID]` one-to-many to `successful_matches[Patient_ID]` and `match_funnel[Patient_ID]`, and `cleaned_clinical_trials[nct_id]` one-to-many to `successful_matches[nct_id]`.

## Fix existing visuals

- **Scatter on page 2:** the X axis is a count of `Tumor_Volume_mm3`, so every point shows 1. Change it to **Don't summarize** or **Average**.
- **Scatter play axis:** `Patient_ID` animates through patients one at a time. Remove it.
- **Match Rate card:** check its measure against the new data, because the DAX could not be read outside Power BI. `Patients with a match / Total Patients` is now 100%, so a Strong-tier rate says more:

```dax
Strong Match Rate =
DIVIDE(
    CALCULATE(DISTINCTCOUNT(successful_matches[Patient_ID]), successful_matches[match_tier] = "Strong"),
    DISTINCTCOUNT(patient_diagnostics_mock[Patient_ID])
)
```

## Add the missing Trial Scout page

The report has two pages. The original README described a third, the Trial Scout, but it is not in the file.

1. Add a slicer on `patient_diagnostics_mock[Patient_ID]`.
2. Add a table from `successful_matches` with `patient_rank`, `match_score`, `match_tier`, `trial_title`, `best_site`, `status`, `match_reasons` and `review_flags`, sorted by `patient_rank`.
3. Set `study_url` to the **Web URL** data category so it shows as a link.
4. Add a text box: "Synthetic patients. Candidates for clinician review only."

## Before publishing

Rename the report if you keep it public. "Autonomous Diagnostic Imaging" describes a capability the project does not have.
