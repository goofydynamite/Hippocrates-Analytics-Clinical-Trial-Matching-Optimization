# Tableau workbook

`python -m hippocrates run` writes these files to `tableau/`:

| File | Contents |
|---|---|
| `hippocrates.twb` | Workbook with three dashboards: Trial Scout, Overview, and Before and After |
| `trial_scout.hyper` | One row per patient and candidate trial, with the patient's facts and the trial's nearest site |
| `screening_funnel.hyper` | Average trials left per patient after each screening gate |
| `kpis.hyper` | Headline numbers for the Overview |
| `comparison.hyper`, `checks.hyper`, `legacy_status.hyper` | The first version's matcher against this one, recomputed from the current data by `hippocrates/legacy.py` |
| `phases.hyper` | Open trials by phase |
| `patient_stats.hyper` | Headline numbers per patient for the Trial Scout strip |
| `*.csv` | The same data as CSV, for checking or other tools |

Tableau Public only opens workbooks whose data is stored as `.hyper` extracts, which is why the pipeline depends on Tableau's `tableauhyperapi` package.

The workbook has been opened and checked in Tableau Public 2025.2, and is published:

- [Trial Scout](https://public.tableau.com/app/profile/deepti.singh.kushwaha/viz/HippocratesTrialScout/TrialScout)
- [Overview](https://public.tableau.com/app/profile/deepti.singh.kushwaha/viz/HippocratesTrialScout/Overview)
- [Before and After](https://public.tableau.com/app/profile/deepti.singh.kushwaha/viz/HippocratesTrialScout/BeforeandAfter)

## Dashboards

Each dashboard has buttons at the top to move between them.

- **Trial Scout:** pick a patient from the Patient control to see their facts, four headline numbers (candidate trials, Strong matches, trials with a site in their city, best score), and every candidate trial, ranked by score, with the reasons it matched. Tier and Distance filters narrow the list, and clicking a trial opens it on ClinicalTrials.gov. A map below shows where each trial's nearest site is.
- **Overview:** headline numbers, the average number of trials left after each screening gate, open trials by phase, and each patient's candidates split by tier.
- **Before and After:** the first version's matcher against this one, on the same patients and trials, what each version checks, and the trial status of every match the first version made.

## Open

Open `tableau/hippocrates.twb` in Tableau Public. The workbook stores the absolute path of its extracts, so after moving the project, run `python -m hippocrates tableau` to regenerate it.

## Save and publish

- **Save locally:** use **File > Save As**.
- **Publish:** **File > Save to Tableau Public As** uploads it to your public profile, where anyone can see it. Keep the title "Hippocrates Trial Scout" to replace the published version and keep its links. In Tableau Public, **Ctrl+S** also publishes.

After each data refresh, run the pipeline and publish again. The public copy does not update itself.

## Regenerating

Close the workbook in Tableau before running the pipeline. Tableau locks the `.hyper` files while the workbook is open, and the rebuild will fail.

## How the workbook is generated

`hippocrates/tableau.py` writes the workbook XML directly. Parts Tableau does not document were copied from workbooks Tableau saved itself, such as navigation buttons, URL actions and map field roles. The tests in `tests/test_tableau.py` cover the details Tableau needs to open the file.
