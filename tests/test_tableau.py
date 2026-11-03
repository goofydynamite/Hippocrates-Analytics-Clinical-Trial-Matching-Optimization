import xml.etree.ElementTree as ET

import pandas as pd
import pytest

from hippocrates import tableau

PATIENTS = pd.DataFrame([{
    "Patient_ID": "PID-001", "AI_Predicted_Condition": "Glioblastoma", "Patient_Age": 55, "Patient_Sex": "Male",
    "Patient_Location": "Houston, TX", "Disease_Setting": "Recurrent", "Biomarker_EGFR": "Negative",
    "Biomarker_IDH": "Wildtype", "Biomarker_MGMT": "Methylated",
}])
MATCHES = pd.DataFrame([
    {
        "Patient_ID": "PID-001", "AI_Predicted_Condition": "Glioblastoma", "Patient_Age": 55, "nct_id": "NCT1",
        "trial_title": "A <Trial> & more", "match_score": 88, "match_tier": "Strong", "patient_rank": 1,
        "status": "NOT_YET_RECRUITING", "phases": "PHASE1|PHASE2", "best_site": None, "geography": "unknown",
        "match_reasons": "Glioblastoma listed", "review_flags": None,
    },
    {
        "Patient_ID": "PID-001", "AI_Predicted_Condition": "Glioblastoma", "Patient_Age": 55, "nct_id": "NCT2",
        "trial_title": "Second", "match_score": 60, "match_tier": "Good", "patient_rank": 2,
        "status": "RECRUITING", "phases": "PHASE2", "best_site": "Winston-Salem, North Carolina", "geography": "country",
        "match_reasons": "Glioblastoma listed", "review_flags": None,
    },
])
TRIALS = pd.DataFrame({
    "nct_id": ["NCT1", "NCT2", "NCT3"],
    "status": ["RECRUITING", "COMPLETED", "NOT_YET_RECRUITING"],
    "phases": ["PHASE2", "PHASE3", None],
    "conditions": ["glioblastoma", "glioblastoma", "meningioma"],
    "eligibility_text": ["adults", "adults", "adults"],
})
FIRST_VERSION = {"matches": 10, "open_share": 25.0}
FUNNEL = pd.DataFrame([{
    "Patient_ID": "PID-001", "remaining_after_condition": 10, "remaining_after_status": 8, "remaining_after_age": 8,
    "remaining_after_sex": 8, "remaining_after_biomarker": 6, "remaining_after_setting": 4, "remaining_after_geography": 2,
}])


def scout():
    return tableau.build_scout_table(PATIENTS, MATCHES)


def test_scout_table_is_readable():
    row = scout().iloc[0]
    assert row["status"] == "Not yet recruiting"
    assert row["phases"] == "Phase 1/Phase 2"
    assert row["best_site"] == "No site listed"
    assert row["review_flags"] == "None"
    assert row["Biomarker_IDH"] == "Wildtype"


def test_scout_table_keeps_every_match():
    assert len(scout()) == len(MATCHES)


def test_site_splits_into_map_fields():
    unlisted, listed = scout().to_dict("records")
    assert (listed["site_city"], listed["site_state"], listed["site_country"]) == (
        "Winston-Salem", "North Carolina", "United States",
    )
    assert (unlisted["site_city"], unlisted["site_country"]) == ("", "")
    assert (unlisted["distance"], listed["distance"]) == ("No site listed", "Elsewhere in the US")


def test_funnel_runs_in_screening_order():
    table = tableau.build_funnel_table(FUNNEL, 100)
    assert table["stage"].tolist()[:2] == ["0. All trials", "1. Condition"]
    assert table["avg_trials_left"].iloc[0] == 100
    assert table["avg_trials_left"].iloc[-1] == 2


def test_kpis():
    kpis = tableau.build_kpi_table(PATIENTS, TRIALS, MATCHES)
    assert kpis["kpi"].tolist() == tableau.KPI_ORDER
    assert kpis["value"].tolist() == [1, 2, 2, 1]


def test_comparison_uses_first_version_figures_as_shares():
    table = tableau.build_comparison_table(MATCHES, FIRST_VERSION).set_index("version")
    assert table.loc["Current version", "matches"] == 2
    assert table.loc["Current version", "joinable_pct"] == 1.0
    assert table.loc["First version", "matches"] == 10
    assert table.loc["First version", "joinable_pct"] == 0.25


def test_phase_table_counts_open_trials_in_phase_order():
    table = tableau.build_phase_table(TRIALS)
    assert table.to_dict("records") == [
        {"phase": "Phase 2", "open_trials": 1}, {"phase": "Not applicable", "open_trials": 1},
    ]


def test_legacy_status_table_marks_closed_trials():
    first = pd.DataFrame({"status": ["COMPLETED", "COMPLETED", "RECRUITING"]})
    table = tableau.build_legacy_status_table(first)
    assert table.iloc[0].to_dict() == {
        "status_label": "Completed", "can_join": "Closed to new patients", "matches": 2,
    }
    assert table.iloc[1]["can_join"] == "Can still join"


def test_checks_have_a_value_per_version():
    checks = tableau.build_checks_table()
    assert len(checks) == 2 * len(tableau.COMPARISON_CHECKS)
    assert set(checks["version"]) == set(tableau.VERSIONS)


def workbook_root():
    funnel = tableau.build_funnel_table(FUNNEL, 100)
    extra = {
        "kpis": tableau.build_kpi_table(PATIENTS, TRIALS, MATCHES),
        "comparison": tableau.build_comparison_table(MATCHES, FIRST_VERSION),
        "checks": tableau.build_checks_table(),
        "phases": tableau.build_phase_table(TRIALS),
        "legacy_status": tableau.build_legacy_status_table(pd.DataFrame({"status": ["COMPLETED"]})),
        "patient_stats": tableau.build_patient_stats_table(scout()),
    }
    return ET.fromstring(tableau.build_workbook(scout(), funnel, "C:/data", extra))


def test_workbook_has_every_view():
    root = workbook_root()
    sheets = {s for group in tableau.DASHBOARD_SHEETS.values() for s in group} | {"Candidates by Tier"}
    assert {w.get("name") for w in root.iter("worksheet")} == sheets
    assert {d.get("name") for d in root.find("dashboards")} == set(tableau.DASHBOARD_SHEETS)


def test_every_data_source_reads_a_hyper_extract():
    # Tableau Public refuses to open a workbook whose data is not an extract.
    sources = [d for d in workbook_root().find("datasources") if d.get("name") != "Parameters"]
    assert len(sources) == 8
    for source in sources:
        connection = source.find("extract/connection")
        assert connection.get("class") == "hyper" and connection.get("dbname").endswith(".hyper")


def test_dashboard_windows_list_their_sheets():
    # Without these viewpoints Tableau fails with an internal error drawing the dashboard.
    windows = {w.get("name"): w for w in workbook_root().find("windows")}
    for dashboard, sheets in tableau.DASHBOARD_SHEETS.items():
        assert [v.get("name") for v in windows[dashboard].find("viewpoints")] == sheets


def test_navigation_buttons_point_at_real_dashboards():
    root = workbook_root()
    ids = {w.find("simple-id").get("uuid") for w in root.find("windows") if w.get("class") == "dashboard"}
    buttons = [b.get("action") for b in root.iter("button")]
    assert len(buttons) == 6
    assert all(any(i in action for i in ids) for action in buttons)


def test_trial_link_opens_clinicaltrials_gov():
    link = workbook_root().find("actions/action/link")
    assert link.get("expression") == "https://clinicaltrials.gov/study/<[nct_id]>"


def test_map_fields_have_geographic_roles():
    scout_source = next(d for d in workbook_root().find("datasources") if d.get("name") == tableau.SCOUT)
    roles = {c.get("name"): c.get("semantic-role") for c in scout_source.findall("column")}
    assert roles["[site_city]"] == "[City].[Name]" and roles["[site_state]"] == "[State].[Name]"


def test_manual_sort_keeps_given_order():
    xml = tableau._manual_sort("[x].[none:a:nk]", ["One", "Two"])
    assert xml.index("One") < xml.index("Two")


def test_tier_colours_are_keyed_to_a_data_source_instance():
    scout_source = next(d for d in workbook_root().find("datasources") if d.get("name") == tableau.SCOUT)
    instances = {c.get("name") for c in scout_source.findall("column-instance")}
    assert scout_source.find("style/style-rule/encoding").get("field") in instances


def test_write_extract_round_trips(tmp_path):
    hyperapi = pytest.importorskip("tableauhyperapi")
    path = tmp_path / "funnel.hyper"
    tableau.write_extract(tableau.build_funnel_table(FUNNEL, 100), path)
    with hyperapi.HyperProcess(telemetry=hyperapi.Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU) as hyper:
        with hyperapi.Connection(hyper.endpoint, str(path)) as connection:
            count = connection.execute_scalar_query('SELECT COUNT(*) FROM "Extract"."Extract"')
    assert count == 8


def test_patient_stats():
    stats = tableau.build_patient_stats_table(scout()).set_index("stat")["value"].to_dict()
    assert stats == {"Candidate trials": 2, "Strong matches": 1, "With a site in their city": 0, "Best score": 88}
