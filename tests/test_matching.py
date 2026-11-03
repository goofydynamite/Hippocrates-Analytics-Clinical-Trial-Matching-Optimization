import pandas as pd
import pytest

from hippocrates import matching, parsing

HOUSTON = "Hospital, Houston, Texas, 77030, United States"


def make_patient(**overrides):
    return {
        "Patient_ID": "PID-001", "AI_Predicted_Condition": "Glioblastoma", "Patient_Age": 55,
        "Patient_Location": "Houston, TX", "Patient_Sex": "Female", "Biomarker_EGFR": "Negative",
        "Biomarker_IDH": "Wildtype", "Biomarker_MGMT": "Methylated", "Disease_Setting": "Recurrent",
        **overrides,
    }


def make_trial(**overrides):
    return {
        "nct_id": "NCT00000001", "title": "Study of Drug X", "status": "RECRUITING",
        "conditions": "glioblastoma", "age_min": 18, "age_max": 120, "text_age_min": None,
        "text_age_max": None, "sex": "ALL", "egfr_rule": "none", "idh_rule": "any", "mgmt_rule": "any",
        "disease_setting": "any", "study_type": "INTERVENTIONAL", "locations": HOUSTON,
        "last_update": "2025-09-01", "eligibility_criteria": "",
        **overrides,
    }


def screen(patient=None, trial=None):
    patient = patient or make_patient()
    trial = trial or make_trial()
    return matching.evaluate(
        patient, trial, parsing.parse_sites(trial["locations"]),
        parsing.parse_patient_location(patient["Patient_Location"]),
        pd.Timestamp("2025-09-15"),
    )


class TestCondition:
    @pytest.mark.parametrize("patient, conditions, expected", [
        ("Glioblastoma", "glioblastoma multiforme", "exact"),
        ("Glioblastoma", "gbm", "exact"),
        ("Glioblastoma", "gliosarcoma", "exact"),
        ("Glioblastoma", "high grade glioma", "broad"),
        ("Glioblastoma", "brain tumor", "broad"),
        ("Glioblastoma", "brain metastases", ""),
        ("Astrocytoma", "anaplastic astrocytoma", "exact"),
        ("Astrocytoma", "glioma", "broad"),
        ("Meningioma", "malignant meningioma", "exact"),
        ("Meningioma", "primary brain tumor", "broad"),
    ])
    def test_taxonomy(self, patient, conditions, expected):
        assert matching.condition_match(patient, conditions) == expected

    def test_family_term_beside_glioma_does_not_claim_meningioma(self):
        assert matching.condition_match("Meningioma", "glioblastoma|brain tumor|glioma") == ""

    def test_family_term_with_glioma_title_does_not_claim_meningioma(self):
        assert matching.condition_match("Meningioma", "brain tumor", "Recurrent Glioma Study") == ""

    def test_terms_do_not_match_inside_other_words(self):
        assert matching.condition_match("Glioblastoma", "subgbmx disease") == ""

    def test_unknown_condition_matches_literally(self):
        assert matching.condition_match("Ependymoma", "recurrent ependymoma") == "exact"


class TestGates:
    @pytest.mark.parametrize("status", ["COMPLETED", "TERMINATED", "WITHDRAWN", "UNKNOWN", "SUSPENDED", "ACTIVE_NOT_RECRUITING"])
    def test_closed_statuses_excluded(self, status):
        assert screen(trial=make_trial(status=status)).excluded_by == "status"

    @pytest.mark.parametrize("status", ["RECRUITING", "NOT_YET_RECRUITING", "ENROLLING_BY_INVITATION", "AVAILABLE"])
    def test_open_statuses_pass(self, status):
        assert screen(trial=make_trial(status=status)).excluded_by is None

    def test_age_above_category_limit(self):
        assert screen(trial=make_trial(age_min=0, age_max=17)).excluded_by == "age"

    def test_age_above_stated_limit(self):
        assert screen(trial=make_trial(age_min=0, age_max=64, text_age_max=21)).excluded_by == "age"

    def test_age_below_stated_limit(self):
        assert screen(trial=make_trial(text_age_min=70)).excluded_by == "age"

    def test_sex_restriction(self):
        assert screen(trial=make_trial(sex="MALE")).excluded_by == "sex"

    def test_sex_unknown_patient_passes(self):
        assert screen(make_patient(Patient_Sex=""), make_trial(sex="MALE")).excluded_by is None

    def test_setting_mismatch(self):
        assert screen(trial=make_trial(disease_setting="newly_diagnosed")).excluded_by == "setting"

    def test_international_only_excluded(self):
        trial = make_trial(locations="Hospital, Madrid, Madrid, 28001, Spain")
        assert screen(trial=trial).excluded_by == "geography"

    def test_no_sites_stays_in_with_flag(self):
        result = screen(trial=make_trial(locations=""))
        assert result.excluded_by is None and "No site listed" in result.flags


class TestBiomarkers:
    def test_egfr_negative_excluded_from_egfr_selected_trial(self):
        assert screen(trial=make_trial(egfr_rule="required")).excluded_by == "biomarker"

    def test_egfr_positive_not_limited_to_egfr_trials(self):
        # The first version required an EGFR mention for positive patients, which
        # hid every other trial from them.
        result = screen(make_patient(Biomarker_EGFR="Positive"))
        assert result.excluded_by is None

    def test_egfr_positive_gains_for_egfr_trial(self):
        positive = make_patient(Biomarker_EGFR="Positive")
        assert screen(positive, make_trial(egfr_rule="required")).score > screen(positive).score

    def test_untested_marker_never_excludes(self):
        patient = make_patient(Biomarker_EGFR="Not Tested", Biomarker_IDH="Not Tested", Biomarker_MGMT="Not Tested")
        trial = make_trial(egfr_rule="required", idh_rule="wildtype", mgmt_rule="methylated")
        assert screen(patient, trial).excluded_by is None

    def test_idh_conflict(self):
        assert screen(trial=make_trial(idh_rule="mutant")).excluded_by == "biomarker"

    def test_mgmt_conflict_gives_reason(self):
        result = screen(trial=make_trial(mgmt_rule="unmethylated"))
        assert result.excluded_by == "biomarker" and "MGMT" in result.reasons[0]


class TestScoring:
    def test_perfect_match_scores_100(self):
        trial = make_trial(idh_rule="wildtype", disease_setting="recurrent")
        result = screen(trial=trial)
        assert result.score == 100 and result.tier == "Strong"

    def test_closer_site_ranks_higher(self):
        city = screen(trial=make_trial(locations=HOUSTON))
        state = screen(trial=make_trial(locations="Hospital, Dallas, Texas, 75201, United States"))
        country = screen(trial=make_trial(locations="Hospital, Boston, Massachusetts, 02115, United States"))
        assert city.score > state.score > country.score

    def test_city_needs_matching_state(self):
        result = screen(trial=make_trial(locations="Hospital, Houston, Mississippi, 38851, United States"))
        assert result.geography == "country"

    def test_nationwide_trial_without_specific_fit_is_not_strong(self):
        trial = make_trial(locations="Hospital, Boston, Massachusetts, 02115, United States")
        assert screen(trial=trial).tier == "Good"

    def test_stale_record_penalised_and_flagged(self):
        fresh, stale = screen(), screen(trial=make_trial(last_update="2020-01-01"))
        assert stale.score == fresh.score - 5
        assert "Record not updated in over 2 years" in stale.flags

    def test_blank_criteria_flagged(self):
        assert "Full eligibility criteria not reviewed" in screen().flags
        assert "Full eligibility criteria not reviewed" not in screen(
            trial=make_trial(eligibility_criteria="Inclusion Criteria: adults")
        ).flags


class TestMatchAll:
    def test_rejects_missing_columns(self):
        with pytest.raises(ValueError, match="Patient_Age"):
            matching.match_all(pd.DataFrame({"Patient_ID": ["A"], "AI_Predicted_Condition": ["x"]}), pd.DataFrame([make_trial()]))

    def test_ranks_and_counts_each_gate(self):
        trials = pd.DataFrame([
            make_trial(nct_id="NCT1"),
            make_trial(nct_id="NCT2", locations="Hospital, Boston, Massachusetts, 02115, United States"),
            make_trial(nct_id="NCT3", status="COMPLETED"),
            make_trial(nct_id="NCT4", conditions="breast cancer"),
        ])
        matches, funnel = matching.match_all(pd.DataFrame([make_patient()]), trials)
        assert matches["nct_id"].tolist() == ["NCT1", "NCT2"]
        assert matches["patient_rank"].tolist() == [1, 2]
        row = funnel.iloc[0]
        assert (row["excluded_condition"], row["excluded_status"], row["remaining_after_geography"]) == (1, 1, 2)

    def test_all_empty_text_column_is_treated_as_blank(self):
        trials = pd.DataFrame([make_trial()]).assign(eligibility_criteria=float("nan"))
        matches, _ = matching.match_all(pd.DataFrame([make_patient()]), trials)
        assert "Full eligibility criteria not reviewed" in matches.loc[0, "review_flags"]

    def test_no_matches_gives_empty_frame(self):
        trials = pd.DataFrame([make_trial(status="COMPLETED")])
        matches, funnel = matching.match_all(pd.DataFrame([make_patient()]), trials)
        assert matches.empty and len(funnel) == 1
