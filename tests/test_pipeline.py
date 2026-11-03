import io
import json

import pandas as pd
import pytest

from hippocrates import clean, config, dashboard, fetch, matching, patients


def raw_row(**overrides):
    return {
        "NCT Number": "NCT00000001", "Study Title": "A Study", "Study Status": "RECRUITING",
        "Conditions": "Glioblastoma", "Brief Summary": "Patients over 18 years old.",
        "Age": "ADULT, OLDER_ADULT", "Interventions": "DRUG: X", "Locations": "H, Houston, Texas, 77030, United States",
        **overrides,
    }


class TestClean:
    def test_keeps_power_bi_columns(self):
        out = clean.clean_trials(pd.DataFrame([raw_row()]))
        for column in ["nct_id", "title", "status", "conditions", "interventions", "age_criteria", "locations", "eligibility_text"]:
            assert column in out.columns

    def test_lowercases_and_derives(self):
        row = clean.clean_trials(pd.DataFrame([raw_row()])).iloc[0]
        assert row["conditions"] == "glioblastoma"
        assert (row["age_min"], row["age_max"], row["text_age_min"]) == (18, 120, 18)

    def test_structured_age_overrides_categories(self):
        row = clean.clean_trials(pd.DataFrame([raw_row(**{"Minimum Age": "21 Years", "Maximum Age": "70 Years"})])).iloc[0]
        assert (row["age_min"], row["age_max"]) == (21, 70)

    def test_inclusion_counts_but_exclusion_does_not(self):
        criteria = "Inclusion Criteria:\n* Adults\nExclusion Criteria:\n* EGFR-mutated tumours"
        row = clean.clean_trials(pd.DataFrame([raw_row(**{"Eligibility Criteria": criteria})])).iloc[0]
        assert row["egfr_rule"] == "none"

    def test_drops_duplicates_and_blanks(self):
        frame = pd.DataFrame([raw_row(), raw_row(), raw_row(**{"NCT Number": "NCT2", "Conditions": None})])
        assert len(clean.clean_trials(frame)) == 1

    def test_missing_column_is_named(self):
        with pytest.raises(ValueError, match="Study Status"):
            clean.clean_trials(pd.DataFrame([raw_row()]).drop(columns="Study Status"))


class TestPatients:
    def test_same_seed_same_patients(self):
        pd.testing.assert_frame_equal(patients.generate_patients(seed=7), patients.generate_patients(seed=7))

    def test_ids_are_unique_and_formatted(self):
        ids = patients.generate_patients(count=20)["Patient_ID"]
        assert ids.is_unique and ids.iloc[0] == "PID-001" and ids.iloc[-1] == "PID-020"

    def test_markers_follow_who_definitions(self):
        frame = patients.generate_patients(count=200)
        assert set(frame.loc[frame.AI_Predicted_Condition == "Glioblastoma", "Biomarker_IDH"]) == {"Wildtype"}
        assert set(frame.loc[frame.AI_Predicted_Condition == "Astrocytoma", "Biomarker_IDH"]) == {"Mutant"}
        assert set(frame.loc[frame.AI_Predicted_Condition == "Meningioma", "Biomarker_EGFR"]) == {"Not Tested"}


STUDY = {
    "protocolSection": {
        "identificationModule": {"nctId": "NCT09999999", "briefTitle": "Short", "officialTitle": "Official Title"},
        "statusModule": {"overallStatus": "RECRUITING", "lastUpdatePostDateStruct": {"date": "2026-10-01"}},
        "descriptionModule": {"briefSummary": "Summary."},
        "conditionsModule": {"conditions": ["Glioblastoma", "Glioma"]},
        "armsInterventionsModule": {"interventions": [{"type": "DRUG", "name": "X"}]},
        "designModule": {"studyType": "INTERVENTIONAL", "phases": ["PHASE1", "PHASE2"], "enrollmentInfo": {"count": 40}},
        "eligibilityModule": {
            "eligibilityCriteria": "Inclusion Criteria:\n* Adults", "minimumAge": "18 Years",
            "maximumAge": "75 Years", "sex": "ALL", "stdAges": ["ADULT", "OLDER_ADULT"],
        },
        "sponsorCollaboratorsModule": {"leadSponsor": {"name": "Sponsor"}},
        "contactsLocationsModule": {"locations": [
            {"facility": "Open", "city": "Houston", "state": "Texas", "zip": "77030", "country": "United States", "status": "RECRUITING"},
            {"facility": "Shut", "city": "Boston", "state": "Massachusetts", "country": "United States", "status": "COMPLETED"},
        ]},
    }
}


class TestFetch:
    def test_study_to_row_flows_through_clean(self):
        row = fetch.study_to_row(STUDY)
        assert row["Phases"] == "PHASE1|PHASE2"
        assert row["Locations"] == "Open, Houston, Texas, 77030, United States"
        cleaned = clean.clean_trials(pd.DataFrame([row])).iloc[0]
        assert (cleaned["age_min"], cleaned["age_max"]) == (18, 75)

    def test_keeps_all_sites_when_none_open(self):
        sites = [{"facility": "A", "city": "B", "country": "C", "status": "COMPLETED"}]
        assert fetch._format_sites(sites) == "A, B, C"

    def test_follows_page_tokens(self):
        pages = [{"studies": [STUDY], "nextPageToken": "t2"}, {"studies": [STUDY]}]
        seen = []

        def opener(request, timeout):
            seen.append(request.full_url)
            return io.BytesIO(json.dumps(pages[len(seen) - 1]).encode())

        assert len(list(fetch.fetch_studies("glioma", opener=opener, pause=0))) == 2
        assert "pageToken=t2" in seen[1]


class TestDashboard:
    def payload(self):
        people = pd.DataFrame([{"Patient_ID": "PID-001", "AI_Predicted_Condition": "Glioblastoma", "Patient_Age": 55, "Patient_Location": "Houston, TX"}])
        trials = clean.clean_trials(pd.DataFrame([
            raw_row(**{"Study Title": "Bad </script><b>title", "Study URL": "https://clinicaltrials.gov/study/NCT00000001", "Last Update Posted": "2025-09-01"})
        ]))
        matches, funnel = matching.match_all(people, trials)
        return dashboard.build_payload(people, trials, matches, funnel)

    def test_payload_counts(self):
        payload = self.payload()
        assert payload["summary"]["matches"] == 1 and payload["summary"]["open_trials"] == 1
        assert payload["summary"]["snapshot"] == "2025-09-01"

    def test_trial_text_cannot_close_script_tag(self):
        assert "</script><b>" not in dashboard.render(self.payload())


@pytest.fixture(scope="module")
def matches():
    return pd.read_csv(config.MATCHES_CSV)


@pytest.fixture(scope="module")
def trials():
    return pd.read_csv(config.TRIALS_CSV, dtype=str)


class TestShippedData:
    """Guards on the committed outputs, so a bad rule change fails CI."""

    def test_every_match_is_open_and_unique(self, matches):
        assert matches["status"].isin(config.OPEN_STATUS_POINTS).all()
        assert not matches.duplicated(["Patient_ID", "nct_id"]).any()

    def test_every_match_is_a_known_trial(self, matches, trials):
        assert matches["nct_id"].isin(trials["nct_id"]).all()

    def test_ages_respect_trial_limits(self, matches, trials):
        joined = matches.merge(trials[["nct_id", "age_min", "age_max"]], on="nct_id")
        assert joined["Patient_Age"].ge(joined["age_min"].astype(float)).all()
        assert joined["Patient_Age"].le(joined["age_max"].astype(float)).all()

    def test_funnel_reconciles_with_matches(self, matches):
        funnel = pd.read_csv(config.FUNNEL_CSV)
        assert funnel["remaining_after_geography"].sum() == len(matches)
