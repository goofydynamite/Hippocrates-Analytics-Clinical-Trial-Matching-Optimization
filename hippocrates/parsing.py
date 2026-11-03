"""Turn ClinicalTrials.gov free text into structured facts.

Each detector favours the fields that define who a trial enrolls (title,
conditions, interventions). A brief summary often mentions a biomarker as
background, so it counts only in "patients with ..." phrasing.

Inclusion criteria are long and full of side conditions, so they only add a
restriction those fields did not state, and only from a clause that states it
plainly. Unclear wording leaves the trial open for a clinician to review.
"""

import re

US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}
_STATE_NAMES = set(US_STATES.values())

_AGE_CATEGORY_BOUNDS = {"CHILD": (0, 17), "ADULT": (18, 64), "OLDER_ADULT": (65, 120)}

_AGE_UNIT = r"(?:years?|yrs?|y/?o)"
_AGE_TAIL = rf"{_AGE_UNIT}(?:[- ]?old|\s+of\s+age)"
_MIN_AGE_PATTERNS = [
    rf"(?:aged?|age of)\s*(\d{{1,3}})\s*{_AGE_UNIT}?(?:\s+old)?\s*(?:or|and)\s*(?:older|above|over)",
    rf"(?:aged?|age)\s*(?:of\s*)?(?:>=|≥|>|over|above|at least|older than|greater than(?: or equal to)?)\s*(\d{{1,3}})",
    rf"(?:>=|≥|>|over|above|older than|at least|greater than(?: or equal to)?)\s*(\d{{1,3}})\s*{_AGE_TAIL}",
]
_MAX_AGE_PATTERNS = [
    rf"(?:aged?|age)\s*(?:of\s*)?(?:<=|≤|<|under|below|younger than|less than)\s*(\d{{1,3}})",
    rf"(?:<=|≤|<|under|below|younger than|less than)\s*(\d{{1,3}})\s*{_AGE_TAIL}",
]
_AGE_RANGE = re.compile(
    rf"(?:aged?|ages?)\s*(?:between\s*|from\s*)?(\d{{1,3}})\s*(?:-|–|to|and)\s*(\d{{1,3}})(?:\s*{_AGE_UNIT})?"
)

_EGFR_DRUGS = (
    r"erlotinib|gefitinib|afatinib|osimertinib|lapatinib|dacomitinib|lazertinib|"
    r"cetuximab|nimotuzumab|panitumumab|depatux\w*|rindopepimut"
)
_EGFR_SELECTED = (
    r"\bh?egfrv(?:iii|3)\b|\bh?egfr\)?[- ](?:gene[- ])?"
    r"(?:amplif\w*|alter\w*|mutat\w*|mutant|modified|positive|overexpress\w*|fusions?)"
)
_IDH_MUTANT = r"\bidh[12]?(?:/[12])?\)?[- ]*(?:gene[- ]*)?(?:mutant|mutated|mutation|mut\b|r132)"
_IDH_WILDTYPE = (
    r"\bidh[12]?\)?(?:\s*\(isocitrate dehydrogenase\))?[- ]*(?:wild[- ]?type|wt\b)"
)
_MGMT_UNMETHYLATED = r"(?:un|non-?)methylated mgmt|mgmt(?: promot[eo]r)?[- ](?:un|non-?)methylated"
_MGMT_METHYLATED = r"(?<!un)(?<!non)(?<!non-)methylated mgmt|mgmt(?: promot[eo]r)?[- ]methylated"
_RECURRENT = r"recurren|relaps|progressive|refractory|\brgbm\b"
_NEWLY_DIAGNOSED = r"newly[- ]diagnosed|first[- ]line|treatment[- ]naive|untreated|\bndgbm\b|\bngbm\b"
_COHORT_PHRASE = r"(?:patients?|participants?|subjects?|adults?)\s+with\s[^.]{0,80}?"
# In inclusion criteria, "eGFR" usually means estimated glomerular filtration
# rate, so a bare mention never counts: only _EGFR_SELECTED phrasing does.
_NOT_A_REQUIREMENT = (
    r"\b(?:or|either|both|and mutant|and unmethylated|if|for|without|absence|no known|"
    r"non|regardless|independent|irrespective|practice|dispensable|allowed|likely)\b"
)
_RECURRENT_CLAUSE = (
    r"recurren(?:t|ce)\b[^.\n]{0,40}(?:gbm|glioblastoma|glioma|meningioma|tumou?r|disease)|"
    r"(?:recurrence|relapse) of (?:an? |the )?(?:\w+ ){0,3}(?:gbm|glioblastoma|glioma|tumou?r)|"
    r"first (?:recurrence|relapse)"
)
_NEWLY_DIAGNOSED_CLAUSE = r"newly[- ]diagnosed[^.\n]{0,50}(?:gbm|glioblastoma|glioma|who grade|brain|neoplasm)"
_SETTING_NOT_A_REQUIREMENT = r"\b(?:if|for|fear|suspected|primary)\b|pseudo"


def clean_escapes(text):
    """ClinicalTrials.gov escapes markdown, e.g. ``\\>=18``."""
    return text.replace("\\", "") if isinstance(text, str) else ""


def bounds_from_categories(age_criteria):
    """Convert 'ADULT, OLDER_ADULT' to (18, 120); unknown input to (None, None)."""
    cats = [c.strip() for c in str(age_criteria).split(",")]
    spans = [_AGE_CATEGORY_BOUNDS[c] for c in cats if c in _AGE_CATEGORY_BOUNDS]
    if not spans:
        return None, None
    return min(s[0] for s in spans), max(s[1] for s in spans)


def parse_structured_age(value):
    """Convert the API's '18 Years' to 18; months and weeks round down to 0 years."""
    match = re.match(r"\s*(\d+)\s*(year|month|week|day|hour|minute)", str(value), re.I)
    if not match:
        return None
    return int(match[1]) if match[2].lower() == "year" else 0


def age_bounds_from_text(text):
    """Find explicit age limits, ignoring durations like 'survival over 2 years'."""
    text = clean_escapes(text).lower()
    low, high = None, None
    for match in _AGE_RANGE.finditer(text):
        lo, hi = int(match[1]), int(match[2])
        if lo < hi <= 120:
            low = lo if low is None else min(low, lo)
            high = hi if high is None else max(high, hi)
    for pattern in _MIN_AGE_PATTERNS:
        for match in re.finditer(pattern, text):
            age = int(match[1])
            if age <= 120:
                low = age if low is None else min(low, age)
    for pattern in _MAX_AGE_PATTERNS:
        for match in re.finditer(pattern, text):
            age = int(match[1])
            if age <= 120:
                high = age if high is None else max(high, age)
    return low, high


def split_eligibility(criteria):
    """Return (inclusion, exclusion) text from a full eligibility criteria block."""
    criteria = clean_escapes(criteria)
    parts = re.split(r"exclusion\s+criteria\s*:?", criteria, maxsplit=1, flags=re.I)
    return parts[0], parts[1] if len(parts) > 1 else ""


def parse_sites(locations):
    """Parse 'Facility, City, State, ZIP, Country|...' into site dicts."""
    sites = []
    if not isinstance(locations, str) or not locations.strip():
        return sites
    for raw in locations.split("|"):
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        if len(parts) < 2:
            continue
        country = parts[-1]
        state = ""
        city = parts[-2]
        if country == "United States":
            state_index = next(
                (i for i in range(len(parts) - 2, -1, -1) if parts[i] in _STATE_NAMES), None
            )
            if state_index is not None:
                state = parts[state_index]
                city = parts[state_index - 1] if state_index > 0 else ""
        sites.append({"city": city, "state": state, "country": country})
    return sites


def parse_patient_location(location):
    """Convert 'Houston, TX' to a site-shaped dict."""
    city, _, code = str(location).partition(",")
    return {"city": city.strip(), "state": US_STATES.get(code.strip().upper(), ""), "country": "United States"}


def _selection(head, summary, selected_pattern):
    if re.search(selected_pattern, head):
        return True
    return re.search(_COHORT_PHRASE + f"(?:{selected_pattern})", summary) is not None


def _clauses(text):
    """Split criteria into bullets and sentences."""
    return [c for c in re.split(r"\n+|(?:^|\s)(?:\*|\d+[.)])\s|\.\s", text) if c.strip()]


def _stated(clauses, pattern, guard):
    """True if a clause states the pattern with no qualifier that weakens it."""
    return any(re.search(pattern, c) and not re.search(guard, c) for c in clauses)


def _stated_side(clauses, left, left_pattern, right, right_pattern, guard=_NOT_A_REQUIREMENT):
    """Pick the value the criteria require. Criteria naming both accept both."""
    if any(re.search(left_pattern, c) for c in clauses) and any(re.search(right_pattern, c) for c in clauses):
        return "any"
    return _one_sided(
        left, _stated(clauses, left_pattern, guard), right, _stated(clauses, right_pattern, guard),
    )


def biomarker_profile(title, conditions, interventions, summary, inclusion=""):
    """Classify what a trial asks of EGFR, IDH and MGMT status."""
    head = clean_escapes(" | ".join([title, conditions, interventions])).lower()
    summary = clean_escapes(summary).lower()
    clauses = _clauses(clean_escapes(inclusion).lower())

    egfr_required = _selection(head, summary, _EGFR_SELECTED) or _stated(
        clauses, _EGFR_SELECTED, _NOT_A_REQUIREMENT
    )
    egfr_targeted = egfr_required or bool(
        re.search(rf"\bh?egfr\b|{_EGFR_DRUGS}", head)
    )

    # IDH status is stated as an entry requirement often enough in summaries
    # that the whole text counts; it is rarely mere background.
    idh_text = f"{head} {summary}"
    idh_rule = _idh_scope(
        _one_sided(
            "mutant", bool(re.search(_IDH_MUTANT, idh_text)),
            "wildtype", bool(re.search(_IDH_WILDTYPE, idh_text)),
        ),
        clean_escapes(title).lower(), clean_escapes(conditions).lower(),
    )
    if idh_rule == "any" and not re.search(_IDH_MUTANT + "|" + _IDH_WILDTYPE, idh_text):
        idh_rule = _idh_scope(
            _stated_side(clauses, "mutant", _IDH_MUTANT, "wildtype", _IDH_WILDTYPE),
            clean_escapes(title).lower(), clean_escapes(conditions).lower(),
        )
    mgmt_rule = _one_sided(
        "methylated", _selection(head, summary, _MGMT_METHYLATED),
        "unmethylated", _selection(head, summary, _MGMT_UNMETHYLATED),
    )
    if mgmt_rule == "any":
        mgmt_rule = _stated_side(clauses, "methylated", _MGMT_METHYLATED, "unmethylated", _MGMT_UNMETHYLATED)

    return {
        "egfr_rule": "required" if egfr_required else "targeted" if egfr_targeted else "none",
        "idh_rule": idh_rule,
        "mgmt_rule": mgmt_rule,
    }


def _idh_scope(rule, title, conditions):
    """Keep an IDH rule only if it covers the whole trial.

    In 'Glioblastoma|Astrocytoma, IDH-Mutant' the qualifier belongs to the
    astrocytoma arm, so the glioblastoma arm still accepts wildtype tumours.
    """
    entries = conditions.split("|")
    if rule == "mutant":
        trial_wide = re.search(_IDH_MUTANT + r"[^|]{0,15}gliomas?", title) or any(
            re.fullmatch(r"\s*" + _IDH_MUTANT + r".{0,12}", e) for e in entries
        )
        unqualified = any(
            re.search(r"glioblastoma|\bgbm\b", e) and not re.search(_IDH_MUTANT, e) for e in entries
        )
        return "mutant" if trial_wide or not unqualified else "any"
    if rule == "wildtype":
        if re.search(_IDH_WILDTYPE, title):
            return "wildtype"
        unqualified = any(
            re.search(r"astrocytoma|glioma", e) and not re.search(_IDH_WILDTYPE, e) for e in entries
        )
        return "any" if unqualified else "wildtype"
    return rule


def _one_sided(left, has_left, right, has_right):
    """A trial naming both values accepts both, so it only restricts if one-sided."""
    if has_left == has_right:
        return "any"
    return left if has_left else right


def disease_setting(title, conditions, inclusion=""):
    text = clean_escapes(" | ".join([title, conditions])).lower()
    setting = _one_sided(
        "recurrent", bool(re.search(_RECURRENT, text)),
        "newly_diagnosed", bool(re.search(_NEWLY_DIAGNOSED, text)),
    )
    if setting != "any" or re.search(_RECURRENT + "|" + _NEWLY_DIAGNOSED, text):
        return setting
    clauses = _clauses(clean_escapes(inclusion).lower())
    return _stated_side(
        clauses, "recurrent", _RECURRENT_CLAUSE, "newly_diagnosed", _NEWLY_DIAGNOSED_CLAUSE,
        _SETTING_NOT_A_REQUIREMENT,
    )
