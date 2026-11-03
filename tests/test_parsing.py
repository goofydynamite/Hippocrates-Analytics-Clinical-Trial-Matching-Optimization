import pytest

from hippocrates import parsing


@pytest.mark.parametrize("categories, expected", [
    ("ADULT, OLDER_ADULT", (18, 120)),
    ("CHILD, ADULT", (0, 64)),
    ("OLDER_ADULT", (65, 120)),
    ("", (None, None)),
])
def test_bounds_from_categories(categories, expected):
    assert parsing.bounds_from_categories(categories) == expected


@pytest.mark.parametrize("value, expected", [
    ("18 Years", 18), ("6 Months", 0), ("", None), (None, None),
])
def test_parse_structured_age(value, expected):
    assert parsing.parse_structured_age(value) == expected


@pytest.mark.parametrize("text, expected", [
    ("adults aged 70 years or older", (70, None)),
    ("patients over 18 years old", (18, None)),
    ("male or female > 18 years of age", (18, None)),
    (r"patients age \>= 18 with disease", (18, None)),
    ("participants, ages 6 to 25 years, with relapse", (6, 25)),
    ("patients ≤ 21 years of age", (None, 21)),
    ("patients < 22 years of age", (None, 22)),
])
def test_age_bounds_from_text(text, expected):
    assert parsing.age_bounds_from_text(text) == expected


@pytest.mark.parametrize("text", [
    "survival of 30% in 2 years",
    "follow-up over 5 years",
    "in the last 20 years, only temozolomide",
    "performed over a period of 2 years",
])
def test_durations_are_not_age_limits(text):
    assert parsing.age_bounds_from_text(text) == (None, None)


def test_parse_us_site_with_comma_in_facility():
    sites = parsing.parse_sites("Center, Inc., Great Neck, New York, 11021, United States")
    assert sites == [{"city": "Great Neck", "state": "New York", "country": "United States"}]


def test_parse_international_and_multiple_sites():
    sites = parsing.parse_sites("Hospital A, Madrid, Madrid, 28001, Spain|Clinic B, Houston, Texas, 77030, United States")
    assert [s["country"] for s in sites] == ["Spain", "United States"]
    assert sites[1]["state"] == "Texas"


@pytest.mark.parametrize("blank", ["", None, float("nan")])
def test_parse_sites_blank(blank):
    assert parsing.parse_sites(blank) == []


def test_patient_location():
    assert parsing.parse_patient_location("Houston, TX") == {
        "city": "Houston", "state": "Texas", "country": "United States",
    }


def profile(title="", conditions="", interventions="", summary="", inclusion=""):
    return parsing.biomarker_profile(title, conditions, interventions, summary, inclusion)


class TestEgfr:
    def test_selected_in_title_is_required(self):
        assert profile("Therapy for EGFR-Mutated Glioblastoma")["egfr_rule"] == "required"

    def test_egfrviii_is_required(self):
        assert profile(interventions="DRUG: hEGFRvIII-CD3 (BRiTE)")["egfr_rule"] == "required"

    def test_cohort_phrase_in_summary_is_required(self):
        summary = "patients with newly diagnosed, egfr-amplified glioblastoma."
        assert profile(summary=summary)["egfr_rule"] == "required"

    def test_background_in_summary_is_not_required(self):
        summary = "molecular glioblastoma is defined by necrosis or egfr gene amplification."
        assert profile(summary=summary)["egfr_rule"] == "none"

    def test_drug_without_selection_is_targeted(self):
        assert profile(interventions="DRUG: Afatinib")["egfr_rule"] == "targeted"

    def test_vegfr_is_not_egfr(self):
        assert profile(summary="vegfr2 expression", interventions="DRUG: VEGFR inhibitor")["egfr_rule"] == "none"


class TestIdh:
    def test_wildtype_only(self):
        assert profile(conditions="glioblastoma, idh-wildtype")["idh_rule"] == "wildtype"

    def test_both_values_accepts_any(self):
        conditions = "glioblastoma, idh-wildtype|glioblastoma, idh-mutant"
        assert profile(conditions=conditions)["idh_rule"] == "any"

    def test_trial_wide_mutant_title(self):
        assert profile("Safusidenib in IDH1 Mutant Glioma", "glioma")["idh_rule"] == "mutant"

    def test_mutant_title_binds_despite_bare_glioblastoma(self):
        title = "Treating Isocitrate Dehydrogenase (IDH)1/2-Mutant Grade I-IV Gliomas"
        assert profile(title, "glioblastoma|idh1 gene mutation")["idh_rule"] == "mutant"

    def test_mutant_qualifier_on_one_arm_keeps_bare_glioblastoma_open(self):
        conditions = "glioblastoma (gbm)|astrocytoma, idh-mutant, grade 4"
        assert profile(conditions=conditions)["idh_rule"] == "any"

    def test_wildtype_title_binds_despite_bare_astrocytoma(self):
        title = "Treatment Intensification for IDH Wildtype Gliomas"
        assert profile(title, "astrocytoma|glioblastoma")["idh_rule"] == "wildtype"

    def test_wildtype_qualifier_on_one_arm_keeps_astrocytoma_open(self):
        conditions = "glioblastoma idh (isocitrate dehydrogenase) wildtype|astrocytoma, grade iii"
        assert profile(conditions=conditions)["idh_rule"] == "any"


class TestMgmt:
    def test_unmethylated_is_not_read_as_methylated(self):
        assert profile("Newly Diagnosed MGMT Unmethylated Glioblastoma")["mgmt_rule"] == "unmethylated"

    def test_methylated(self):
        assert profile("Patients With MGMT Methylated Glioblastoma")["mgmt_rule"] == "methylated"

    def test_promoter_variant(self):
        assert profile("Patients With MGMT Promotor Unmethylated GBM")["mgmt_rule"] == "unmethylated"

    def test_stratification_mention_does_not_restrict(self):
        assert profile(summary="stratified by mgmt methylation status.")["mgmt_rule"] == "any"

    def test_subgroup_mention_does_not_restrict(self):
        summary = "for mgmt promoter methylated gbm, lomustine may be added."
        assert profile(summary=summary)["mgmt_rule"] == "any"


class TestInclusionText:
    """Wording seen in real ClinicalTrials.gov criteria."""

    def test_kidney_egfr_is_not_the_biomarker(self):
        inclusion = "* estimated glomerular filtration rate (egfr) >= 60 ml/min/1.73 m2"
        assert profile(inclusion=inclusion)["egfr_rule"] == "none"

    def test_stated_egfr_requirement(self):
        inclusion = "* patients must have evidence of egfr gene amplification by clia-certified assay"
        assert profile(inclusion=inclusion)["egfr_rule"] == "required"

    def test_egfr_in_a_molecular_definition_is_not_required(self):
        inclusion = "* one or more of tert promoter mutations, egfr gene amplification, or chromosome 7 gain"
        assert profile(inclusion=inclusion)["egfr_rule"] == "none"

    def test_without_idh_mutation_is_not_mutant(self):
        assert profile(inclusion="* diffuse glioma without idh1 mutation")["idh_rule"] == "any"

    def test_both_idh_values_allowed(self):
        inclusion = "* idh wt and mutant patients are eligible"
        assert profile(inclusion=inclusion)["idh_rule"] == "any"

    def test_separate_bullets_for_each_idh_value_accept_both(self):
        inclusion = "* glioblastoma, idh-wildtype\n* grade 3 or 4 idh1/2 mutant astrocytoma"
        assert profile(inclusion=inclusion)["idh_rule"] == "any"

    def test_stated_idh_wildtype(self):
        assert profile(inclusion="* newly diagnosed gbm, idh wild-type")["idh_rule"] == "wildtype"

    @pytest.mark.parametrize("inclusion", [
        "* both mgmt methylated and unmethylated patients are allowed",
        "* recurrent glioblastoma independent of methylated mgmt promotor status",
        "* mgmt promoter methylated or unmethylated",
        "* prior temozolomide is not required for mgmt unmethylated tumours",
    ])
    def test_permissive_mgmt_wording_does_not_restrict(self, inclusion):
        assert profile(inclusion=inclusion)["mgmt_rule"] == "any"

    def test_mgmt_listing_each_status_accepts_all(self):
        inclusion = "* mgmt methylated tumours\n* mgmt unmethylated tumours"
        assert profile(inclusion=inclusion)["mgmt_rule"] == "any"

    def test_stated_mgmt(self):
        assert profile(inclusion="* participant must have unmethylated mgmt")["mgmt_rule"] == "unmethylated"

    def test_title_selection_survives_inclusion_wording(self):
        rule = profile("Trial in Unmethylated MGMT GBM", inclusion="* mgmt methylated tumours")["mgmt_rule"]
        assert rule == "unmethylated"

    @pytest.mark.parametrize("inclusion, expected", [
        ("* newly diagnosed glioblastoma confirmed by pathology", "newly_diagnosed"),
        ("1. recurrence of glioblastoma multiforme. 2. age > 18", "recurrent"),
        ("* elevated fear of recurrence distress rating", "any"),
        ("* primary or recurrent glioblastoma", "any"),
        ("* gbm patients including newly diagnosed and recurrent gbm", "any"),
        ("* for nets: progressive disease on approved therapies", "any"),
        ("* uncertainty between pseudoprogression or tumor recurrence", "any"),
        ("* treatment-naive samples should be preferred", "any"),
    ])
    def test_setting_from_inclusion(self, inclusion, expected):
        assert parsing.disease_setting("Glioma Study", "glioma", inclusion) == expected


@pytest.mark.parametrize("title, conditions, expected", [
    ("Trial in Recurrent Glioblastoma", "glioblastoma", "recurrent"),
    ("Trial in Newly Diagnosed GBM", "glioblastoma", "newly_diagnosed"),
    ("Newly Diagnosed and Recurrent Glioblastoma", "glioblastoma", "any"),
    ("Imaging in Glioblastoma", "glioblastoma", "any"),
])
def test_disease_setting(title, conditions, expected):
    assert parsing.disease_setting(title, conditions) == expected


def test_split_eligibility():
    inclusion, exclusion = parsing.split_eligibility(
        "Inclusion Criteria:\n* EGFR amplified\n\nExclusion Criteria:\n* Prior EGFR therapy"
    )
    assert "amplified" in inclusion and "Prior" not in inclusion
    assert "Prior EGFR therapy" in exclusion
