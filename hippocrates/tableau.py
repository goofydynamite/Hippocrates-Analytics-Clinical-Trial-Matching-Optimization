"""Export flat CSVs for Tableau and generate a workbook that reads them."""

import uuid
from xml.sax.saxutils import escape, quoteattr

import pandas as pd

from . import config, legacy, matching

STATUS_LABELS = {
    "RECRUITING": "Recruiting",
    "NOT_YET_RECRUITING": "Not yet recruiting",
    "ENROLLING_BY_INVITATION": "By invitation",
    "AVAILABLE": "Expanded access",
}
GATE_LABELS = {
    "condition": "Condition", "status": "Open status", "age": "Age", "sex": "Sex",
    "biomarker": "Biomarker", "setting": "Disease setting", "geography": "Geography",
}
PATIENT_COLUMNS = [
    "Patient_ID", "AI_Predicted_Condition", "Patient_Age", "Patient_Sex", "Patient_Location",
    "Disease_Setting", "Biomarker_EGFR", "Biomarker_IDH", "Biomarker_MGMT",
]
TIER_COLORS = {"Strong": "#184f95", "Good": "#3987e5", "Possible": "#86b6ef"}
DISTANCE_LABELS = {
    "city": "Same city", "state": "Same state", "country": "Elsewhere in the US", "unknown": "No site listed",
}
SCOUT = "federated.scout"
FUNNEL = "federated.funnel"
PHASES = "federated.phases"
LEGACY_STATUS = "federated.legacy_status"
PATIENT_STATS = "federated.patient_stats"
KPIS = "federated.kpis"
COMPARISON = "federated.comparison"
CHECKS = "federated.checks"
VERSIONS = ["First version", "Current version"]
KPI_ORDER = ["Synthetic patients", "Open trials", "Candidate matches", "Patients with a Strong match"]


def build_scout_table(patients, matches):
    """One row per patient and candidate trial, with patient facts on each row."""
    table = matches.drop(columns=["AI_Predicted_Condition", "Patient_Age"]).merge(
        patients[PATIENT_COLUMNS], on="Patient_ID", how="left", validate="many_to_one"
    )
    table = table.fillna({"phases": "", "best_site": "", "match_reasons": "", "review_flags": ""})
    table["status"] = table["status"].map(STATUS_LABELS).fillna(table["status"])
    table["phases"] = (
        table["phases"].astype(str).str.replace("EARLY_PHASE1", "Early phase 1")
        .str.replace("PHASE", "Phase ").str.replace("|", "/")
    )
    # Every candidate's site is in the patient's country (the US), so "City, State"
    # splits cleanly; Tableau places these on its built-in map.
    located = table["geography"].isin(["city", "state", "country"])
    site = table["best_site"].where(located, "").str.rsplit(", ", n=1, expand=True).reindex(columns=[0, 1])
    table["site_city"] = site[0].fillna("")
    table["site_state"] = site[1].fillna("")
    table["site_country"] = located.map({True: "United States", False: ""})
    table["distance"] = table["geography"].map(DISTANCE_LABELS).fillna("No site listed")
    table["best_site"] = table["best_site"].replace("", "No site listed")
    # Internal blank-free text keeps Tableau from showing Null in the table.
    table["review_flags"] = table["review_flags"].replace("", "None")
    return table


def build_kpi_table(patients, trials, matches):
    """Headline numbers for the Overview tiles, in display order."""
    strong = matches.loc[matches["match_tier"] == "Strong", "Patient_ID"].nunique()
    return pd.DataFrame([
        {"kpi_order": 1, "kpi": "Synthetic patients", "value": len(patients)},
        {"kpi_order": 2, "kpi": "Open trials", "value": int(trials["status"].isin(config.OPEN_STATUS_POINTS).sum())},
        {"kpi_order": 3, "kpi": "Candidate matches", "value": len(matches)},
        {"kpi_order": 4, "kpi": "Patients with a Strong match", "value": int(strong)},
    ])


def build_comparison_table(matches, first_version):
    """The first version's matcher against this one, on the same patients and trials."""
    return pd.DataFrame([
        {"version": "First version", "matches": first_version["matches"], "joinable_pct": first_version["open_share"] / 100},
        {"version": "Current version", "matches": len(matches), "joinable_pct": 1.0},
    ])


COMPARISON_CHECKS = [
    ("Only trials a patient can still join", "No", "Yes"),
    ("Registered age limits checked", "No", "Yes"),
    ("EGFR, IDH and MGMT conflicts excluded", "No", "Yes"),
    ("Site in the patient's country required", "No", "Yes"),
    ("Ranked, with the reasons shown", "No", "Yes"),
    ("Automated tests", "None", "Yes"),
]


def build_checks_table():
    """One row per check and version, so Tableau can lay versions out as columns."""
    return pd.DataFrame(
        [{"check": check, "version": version, "value": value}
         for check, first, current in COMPARISON_CHECKS
         for version, value in (("First version", first), ("Current version", current))]
    )


PHASE_LABELS = {
    "EARLY_PHASE1": "Early phase 1", "PHASE1": "Phase 1", "PHASE1|PHASE2": "Phase 1/2", "PHASE2": "Phase 2",
    "PHASE2|PHASE3": "Phase 2/3", "PHASE3": "Phase 3", "PHASE4": "Phase 4", "": "Not applicable",
}
CLOSED_STATUS_LABELS = {
    "COMPLETED": "Completed", "TERMINATED": "Terminated", "UNKNOWN": "Status unknown",
    "ACTIVE_NOT_RECRUITING": "Active, not recruiting", "WITHDRAWN": "Withdrawn", "SUSPENDED": "Suspended",
    "NO_LONGER_AVAILABLE": "No longer available",
}
JOINABLE_COLORS = {"Can still join": "#3987e5", "Closed to new patients": "#b8c2cf"}


def build_phase_table(trials):
    """Open trials by phase, in phase order."""
    open_trials = trials[trials["status"].isin(config.OPEN_STATUS_POINTS)]
    phases = open_trials["phases"].fillna("").map(lambda p: PHASE_LABELS.get(p, "Other"))
    counts = phases.value_counts()
    order = list(PHASE_LABELS.values()) + ["Other"]
    return pd.DataFrame(
        [{"phase": label, "open_trials": int(counts[label])} for label in order if label in counts]
    )


def build_legacy_status_table(first_version_matches):
    """What the first version's matches were, by trial status, largest first."""
    labels = {**STATUS_LABELS, **CLOSED_STATUS_LABELS}
    status = first_version_matches["status"]
    table = (
        pd.DataFrame({
            "status_label": status.map(lambda s: labels.get(s, s.replace("_", " ").title())),
            "can_join": status.isin(config.OPEN_STATUS_POINTS).map(
                {True: "Can still join", False: "Closed to new patients"}
            ),
        })
        .value_counts().rename("matches").reset_index()
        .sort_values("matches", ascending=False, ignore_index=True)
    )
    return table[["status_label", "can_join", "matches"]]


def build_patient_stats_table(scout):
    """Headline numbers per patient, one row each, for the Trial Scout strip."""
    rows = []
    for patient_id, group in scout.groupby("Patient_ID"):
        values = [
            len(group), int((group["match_tier"] == "Strong").sum()),
            int((group["geography"] == "city").sum()), int(group["match_score"].max()),
        ]
        rows += [{"Patient_ID": patient_id, "stat": stat, "value": value}
                 for stat, value in zip(PATIENT_STAT_ORDER, values)]
    return pd.DataFrame(rows)


def build_funnel_table(funnel, trial_count):
    """Average trials left per patient, one row per stage in screening order."""
    # Numbered labels keep the gates in screening order when Tableau sorts them.
    rows = [{"stage_order": 0, "stage": "0. All trials", "avg_trials_left": float(trial_count)}]
    for order, gate in enumerate(matching.GATES, start=1):
        rows.append({
            "stage_order": order,
            "stage": f"{order}. {GATE_LABELS[gate]}",
            "avg_trials_left": round(float(funnel[f"remaining_after_{gate}"].mean()), 1),
        })
    return pd.DataFrame(rows)


def _column_xml(frame):
    types = {"int64": "integer", "float64": "real"}
    return "\n".join(
        f"            <column datatype='{types.get(str(frame[name].dtype), 'string')}' "
        f"name={quoteattr(name)} ordinal='{index}' />"
        for index, name in enumerate(frame.columns)
    )


def _datasource(name, caption, filename, frame, directory, columns="", style=""):
    key = name.split(".")[1]
    return f"""    <datasource caption={quoteattr(caption)} inline='true' name='{name}' version='18.1'>
      <connection class='federated'>
        <named-connections>
          <named-connection caption={quoteattr(filename)} name='textscan.{key}'>
            <connection class='textscan' directory={quoteattr(directory)} filename={quoteattr(filename)} password='' server='' />
          </named-connection>
        </named-connections>
        <relation connection='textscan.{key}' name={quoteattr(filename)} table='[{filename.replace('.', '#')}]' type='table'>
          <columns character-set='UTF-8' header='yes' locale='en_US' separator=','>
{_column_xml(frame)}
          </columns>
        </relation>
      </connection>
      <aliases enabled='yes' />
{columns}
{_extract(filename, directory)}
      <layout dim-ordering='alphabetic' dim-percentage='0.5' measure-ordering='alphabetic' measure-percentage='0.4' show-structure='true' />
{style}
    </datasource>
"""


def _extract(filename, directory):
    """Tableau Public only opens data stored as a .hyper extract beside the workbook."""
    hyper = f"{directory}/{filename.replace('.csv', '.hyper')}"
    return f"""      <extract count='-1' enabled='true' units='records'>
        <connection access_mode='readonly' author-locale='en_US' class='hyper' dbname={quoteattr(hyper)} default-settings='hyper' schema='Extract' sslmode='' tablename='Extract' username='tableau_internal_user'>
          <relation name='Extract' table='[Extract].[Extract]' type='table' />
        </connection>
      </extract>"""


def write_extract(frame, path):
    """Write a frame as a Hyper extract table, Extract.Extract, the name Tableau expects."""
    from tableauhyperapi import (
        Connection, CreateMode, HyperProcess, Inserter, NOT_NULLABLE, NULLABLE, SqlType,
        TableDefinition, TableName, Telemetry,
    )

    def sql_type(dtype):
        if pd.api.types.is_integer_dtype(dtype):
            return SqlType.big_int()
        if pd.api.types.is_float_dtype(dtype):
            return SqlType.double()
        return SqlType.text()

    table = TableDefinition(TableName("Extract", "Extract"), [
        TableDefinition.Column(name, sql_type(frame[name].dtype), NULLABLE) for name in frame.columns
    ])
    rows = frame.astype(object).where(frame.notna(), None).values.tolist()
    with HyperProcess(telemetry=Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU) as hyper:
        with Connection(hyper.endpoint, str(path), CreateMode.CREATE_AND_REPLACE) as connection:
            connection.catalog.create_schema("Extract")
            connection.catalog.create_table(table)
            with Inserter(connection, table) as inserter:
                inserter.add_rows(rows)
                inserter.execute()


def _parameter(patient_ids):
    members = "\n".join(f"          <member value='&quot;{p}&quot;' />" for p in patient_ids)
    first = patient_ids[0]
    return f"""    <datasource hasconnection='false' inline='true' name='Parameters' version='18.1'>
      <aliases enabled='yes' />
      <column caption='Patient' datatype='string' name='[Parameter 1]' param-domain-type='list' role='measure' type='nominal' value='&quot;{first}&quot;'>
        <calculation class='tableau' formula='&quot;{first}&quot;' />
        <members>
{members}
        </members>
      </column>
    </datasource>
"""


SELECTED = "[none:Selected Patient:nk]"
PATIENT_STAT_ORDER = ["Candidate trials", "Strong matches", "With a site in their city", "Best score"]


SCOUT_CALCS = """      <column caption='Selected Patient' datatype='boolean' name='[Selected Patient]' role='dimension' type='nominal'>
        <calculation class='tableau' formula='[Patient_ID] = [Parameters].[Parameter 1]' />
      </column>
      <column caption='Patient Summary' datatype='string' name='[Patient Summary]' role='dimension' type='nominal'>
        <calculation class='tableau' formula='[AI_Predicted_Condition] + &quot;  |  Age &quot; + STR([Patient_Age]) + &quot;  |  &quot; + [Patient_Sex] + &quot;  |  &quot; + [Patient_Location] + &quot;  |  &quot; + [Disease_Setting] + &quot;  |  EGFR &quot; + [Biomarker_EGFR] + &quot;  |  IDH &quot; + [Biomarker_IDH] + &quot;  |  MGMT &quot; + [Biomarker_MGMT]' />
      </column>
      <column caption='Candidates' datatype='integer' name='[Candidates]' role='measure' type='quantitative'>
        <calculation class='tableau' formula='COUNTD([nct_id] + [Patient_ID])' />
      </column>
"""


def _instance(column, derivation="None", kind="nominal"):
    short = {"None": "none", "Sum": "sum", "User": "usr"}[derivation]
    suffix = {"nominal": "nk", "ordinal": "ok", "quantitative": "qk"}[kind]
    name = f"[{short}:{column}:{suffix}]"
    pivot = " pivot='key'"
    return name, f"<column-instance column='[{column}]' derivation='{derivation}' name='{name}'{pivot} type='{kind}' />"


def _sheet(name, source, columns, instances, rows, cols, mark, encodings="", filtered=False, title="",
           sort="", style="<style />", quick_filters=(), pane_extra="", mapsources=False):
    caption = SOURCE_CAPTIONS[source]
    dependencies = "\n".join(f"            {c}" for c in columns + instances)
    filter_xml = ""
    sliced = []
    if filtered:
        filter_xml += (
            f"          <filter class='categorical' column='[{source}].{SELECTED}'>\n"
            f"            <groupfilter function='member' level='{SELECTED}' member='true' "
            "user:ui-domain='relevant' user:ui-enumeration='inclusive' user:ui-marker='enumerate' />\n"
            "          </filter>\n"
        )
        sliced.append(SELECTED)
    # Quick filters start with every value selected; the dashboard shows their controls.
    for field in quick_filters:
        filter_xml += (
            f"          <filter class='categorical' column='[{source}].{field}'>\n"
            f"            <groupfilter function='level-members' level='{field}' "
            "user:ui-enumeration='all' user:ui-marker='enumerate' />\n"
            "          </filter>\n"
        )
        sliced.append(field)
    slices = (
        "          <slices>\n" + "".join(f"            <column>[{source}].{f}</column>\n" for f in sliced)
        + "          </slices>\n" if sliced else ""
    )
    title_xml = (
        f"      <layout-options>\n        <title>\n          <formatted-text>\n            <run bold='true' fontcolor='#184f95' fontsize='13'>{escape(title)}</run>\n"
        "          </formatted-text>\n        </title>\n      </layout-options>\n" if title else ""
    )
    # The sheet's own data must be listed first: Tableau treats it as the primary source.
    extra_ds = "\n            <datasource name='Parameters' />" if filtered else ""
    maps = "          <mapsources>\n            <mapsource name='Tableau' />\n          </mapsources>\n" if mapsources else ""
    dependency_parameters = (
        "          <datasource-dependencies datasource='Parameters'>\n"
        "            <column caption='Patient' datatype='string' name='[Parameter 1]' param-domain-type='list' role='measure' type='nominal' value='&quot;PID-001&quot;'>\n"
        "              <calculation class='tableau' formula='&quot;PID-001&quot;' />\n"
        "            </column>\n          </datasource-dependencies>\n" if filtered else ""
    )
    return f"""    <worksheet name={quoteattr(name)}>
{title_xml}      <table>
        <view>
          <datasources>
            <datasource caption='{caption}' name='{source}' />{extra_ds}
          </datasources>
{maps}{dependency_parameters}          <datasource-dependencies datasource='{source}'>
{dependencies}
          </datasource-dependencies>
{filter_xml}{sort}{slices}          <aggregation value='true' />
        </view>
        {style}
        <panes>
          <pane selection-relaxation-option='selection-relaxation-allow'>
            <view>
              <breakdown value='auto' />
            </view>
            <mark class='{mark}' />
{encodings}
{pane_extra}
          </pane>
        </panes>
        <rows>{rows}</rows>
        <cols>{cols}</cols>
      </table>
    </worksheet>
"""


CAPTIONS = {
    "patient_rank": "Rank", "match_score": "Score", "match_tier": "Tier", "trial_title": "Trial",
    "nct_id": "NCT ID", "status": "Status", "best_site": "Nearest site", "match_reasons": "Why it matches",
    "Patient_ID": "Patient", "Number of Records": "Candidates", "stage": "Stage",
    "avg_trials_left": "Average trials left per patient", "distance": "Distance",
    "site_city": "City", "site_state": "State", "site_country": "Country",
    "kpi": "Metric", "value": "Value", "version": "Version", "matches": "Matches",
    "joinable_pct": "% of matches a patient can still join", "check": "Check",
    "phase": "Phase", "open_trials": "Open trials", "status_label": "Trial status",
    "can_join": "Can a patient join?", "stat": "Number",
}
COLUMN_TYPES = {
    "patient_rank": ("integer", "ordinal"), "match_score": ("integer", "ordinal"),
    "avg_trials_left": ("real", "quantitative"), "matches": ("integer", "quantitative"),
    "joinable_pct": ("real", "quantitative"), "open_trials": ("integer", "quantitative"),
}
GEO_ROLES = {"site_city": "[City].[Name]", "site_state": "[State].[Name]", "site_country": "[Country].[Name]"}
TRIAL_WIDTHS = {"trial_title": 330, "nct_id": 95, "best_site": 170, "match_reasons": 330, "status": 120}
SOURCE_CAPTIONS = {
    "federated.scout": "Trial Scout", "federated.funnel": "Funnel", "federated.kpis": "KPIs",
    "federated.comparison": "Comparison", "federated.checks": "Checks",
    "federated.phases": "Phases", "federated.legacy_status": "First Version Statuses",
    "federated.patient_stats": "Patient Numbers",
}
NUMBER_OF_RECORDS = (
    "<column caption='Candidates' datatype='integer' name='[Number of Records]' role='measure' "
    "type='quantitative' user:auto-column='numrec'><calculation class='tableau' formula='1' /></column>"
)
RECORD_COUNT = "[sum:Number of Records:qk]"


def _string_column(name, role="dimension", kind="nominal", datatype="string"):
    caption = f" caption={quoteattr(CAPTIONS[name])}" if name in CAPTIONS else ""
    geo = f" semantic-role='{GEO_ROLES[name]}'" if name in GEO_ROLES else ""
    fmt = " default-format='p0.0%'" if name == "joinable_pct" else ""
    return f"<column{caption} datatype='{datatype}'{fmt} name='[{name}]' role='{role}'{geo} type='{kind}' />"


def _field(name):
    """A column definition with its caption, type and role, for datasource or sheet use."""
    datatype, kind = COLUMN_TYPES.get(name, ("string", "nominal"))
    role = "measure" if kind == "quantitative" else "dimension"
    return _string_column(name, role, kind, datatype)


def _caption_columns(names):
    """Datasource-level captions, so headers and axes read as words, not field names."""
    return "\n".join("      " + _field(name) for name in names) + "\n"


def _header_widths(prefix, widths, hide_labels=False, column_widths=None):
    rules = "\n".join(
        f"            <format attr='width' field='{prefix}[none:{field}:nk]' value='{width}' />"
        for field, width in widths.items()
    )
    # Headers on the Columns shelf take their width from the cells beneath them.
    cells = "".join(
        f"\n          <style-rule element='cell'>\n            <format attr='width' field='{prefix}[none:{field}:nk]' value='{width}' />\n          </style-rule>"
        for field, width in (column_widths or {}).items()
    )
    labels = (
        "\n          <style-rule element='worksheet'>\n"
        "            <format attr='display-field-labels' scope='rows' value='false' />\n"
        "          </style-rule>" if hide_labels else ""
    )
    return f"<style>\n          <style-rule element='header'>\n{rules}\n          </style-rule>{cells}{labels}\n        </style>"


def _manual_sort(column, values):
    buckets = "".join(f"              <bucket>&quot;{escape(v)}&quot;</bucket>\n" for v in values)
    return (
        f"          <sort class='manual' column='{column}' direction='ASC'>\n            <dictionary>\n"
        f"{buckets}            </dictionary>\n          </sort>\n"
    )


def _encodings(**channels):
    lines = [
        f"              <{channel} column='{column}' />"
        for channel, columns in channels.items()
        for column in (columns if isinstance(columns, list) else [columns])
    ]
    return "            <encodings>\n" + "\n".join(lines) + "\n            </encodings>"


SHOW_LABELS = (
    "            <style>\n              <style-rule element='mark'>\n"
    "                <format attr='mark-labels-show' value='true' />\n"
    "                <format attr='mark-color' value='#3987e5' />\n"
    "              </style-rule>\n            </style>"
)
MARK_COLOR = (
    "            <style>\n              <style-rule element='mark'>\n"
    "                <format attr='mark-color' value='#184f95' />\n"
    "              </style-rule>\n            </style>"
)


def _rich_text(element, runs):
    """A customized tooltip or mark label; runs are (text, attributes) pairs."""
    body = "".join(f"<run{attrs}>{text}</run>" for text, attrs in runs)
    return f"            <{element}>\n              <formatted-text>{body}</formatted-text>\n            </{element}>"


def _ref(prefix, instance):
    return f"&lt;{prefix}{instance}&gt;"


def _big_number_style():
    return (
        "<style>\n          <style-rule element='cell'>\n"
        "            <format attr='font-size' value='22' />\n            <format attr='font-weight' value='bold' />\n"
        "            <format attr='color' value='#184f95' />\n          </style-rule>\n        </style>"
    )


def _worksheets(extra):
    q = f"[{SCOUT}]."
    selected_calc = (
        "<column caption='Selected Patient' datatype='boolean' name='[Selected Patient]' role='dimension' type='nominal'>"
        "<calculation class='tableau' formula='[Patient_ID] = [Parameters].[Parameter 1]' /></column>"
    )
    selected_instance = _instance("Selected Patient")[1]
    patient_id = _field("Patient_ID")

    # Patient facts line
    summary_calc = (
        "<column caption='Patient Summary' datatype='string' name='[Patient Summary]' role='dimension' type='nominal'>"
        "<calculation class='tableau' formula='[AI_Predicted_Condition] + &quot;  |  Age &quot; + STR([Patient_Age]) + "
        "&quot;  |  &quot; + [Patient_Sex] + &quot;  |  &quot; + [Patient_Location] + &quot;  |  &quot; + [Disease_Setting] + "
        "&quot;  |  EGFR &quot; + [Biomarker_EGFR] + &quot;  |  IDH &quot; + [Biomarker_IDH] + &quot;  |  MGMT &quot; + [Biomarker_MGMT]' /></column>"
    )
    summary_name, summary_instance = _instance("Patient Summary")
    facts = _sheet(
        "Patient Facts", SCOUT,
        [patient_id, selected_calc, summary_calc], [selected_instance, summary_instance],
        f"{q}{summary_name}", "", "Text", filtered=True, title="Selected patient",
        style=_header_widths(q, {"Patient Summary": 1150}, hide_labels=True),
    )

    # Ranked candidate list, with Tier and Distance filters and a link to each study
    rank_name, rank = _instance("patient_rank", kind="ordinal")
    score_name, score = _instance("match_score", kind="ordinal")
    tier_name, tier = _instance("match_tier")
    title_name, title_col = _instance("trial_title")
    id_name, id_col = _instance("nct_id")
    status_name, status = _instance("status")
    site_name, site = _instance("best_site")
    reason_name, reason = _instance("match_reasons")
    distance_name, distance = _instance("distance")
    trials = _sheet(
        "Candidate Trials", SCOUT,
        [patient_id, selected_calc] + [_field(n) for n in (
            "patient_rank", "match_score", "match_tier", "trial_title", "nct_id", "status", "best_site",
            "match_reasons", "distance",
        )],
        [selected_instance, rank, score, tier, title_col, id_col, status, site, reason, distance],
        " / ".join(
            f"{q}{n}" for n in [rank_name, score_name, tier_name, title_name, id_name, status_name, site_name, reason_name]
        ).join("()"),
        "", "Text", filtered=True, title="Candidate trials, best first. Click a trial to open it on ClinicalTrials.gov.",
        style=_header_widths(q, TRIAL_WIDTHS), quick_filters=(tier_name, distance_name),
    )

    # Map of the selected patient's candidate trial sites
    city_name, city = _instance("site_city")
    state_name, state = _instance("site_state")
    country_name, country = _instance("site_country")
    sites = _sheet(
        "Trial Sites", SCOUT,
        [patient_id, selected_calc, NUMBER_OF_RECORDS] + [_field(n) for n in ("site_city", "site_state", "site_country")],
        [selected_instance, city, state, country,
         "<column-instance column='[Number of Records]' derivation='Sum' name='[sum:Number of Records:qk]' pivot='key' type='quantitative' />"],
        f"{q}[Latitude (generated)]", f"{q}[Longitude (generated)]", "Circle",
        encodings=_encodings(lod=[f"{q}{city_name}", f"{q}{state_name}", f"{q}{country_name}"], size=f"{q}{RECORD_COUNT}"),
        pane_extra=_rich_text("customized-tooltip", [
            (f"{_ref(q, city_name)}, {_ref(q, state_name)}", " bold='true'"),
            (f"&#10;Candidate trials with a site here: {_ref(q, RECORD_COUNT)}", ""),
        ]) + "\n" + MARK_COLOR,
        filtered=True, mapsources=True, title="Nearest site of each candidate trial",
        style="<style>\n          <style-rule element='map'>\n            <format attr='washout' value='0.0' />\n          </style-rule>\n        </style>",
    )

    # Candidates per patient by tier
    patient_name, patient_instance = _instance("Patient_ID")
    tier_chart = _sheet(
        "Candidates by Tier", SCOUT,
        [patient_id, _field("match_tier"), NUMBER_OF_RECORDS],
        [patient_instance, tier, "<column-instance column='[Number of Records]' derivation='Sum' name='[sum:Number of Records:qk]' pivot='key' type='quantitative' />"],
        f"{q}{patient_name}", f"{q}{RECORD_COUNT}", "Bar",
        encodings=_encodings(color=f"{q}{tier_name}"),
        title="Candidates per patient by tier",
        # Stacks and legends list a manual sort in reverse, so reverse it to show Strong first.
        sort=_manual_sort(f"{q}{tier_name}", reversed(TIER_COLORS)),
    )

    # Screening funnel
    f = f"[{FUNNEL}]."
    stage_name, stage = _instance("stage")
    left_name, left = _instance("avg_trials_left", "Sum", "quantitative")
    funnel = _sheet(
        "Screening Funnel", FUNNEL,
        [_field("stage"), _field("avg_trials_left")], [stage, left],
        f"{f}{stage_name}", f"{f}{left_name}", "Bar",
        encodings=_encodings(text=f"{f}{left_name}"), pane_extra=SHOW_LABELS,
        title="Average trials left after each screening gate",
    )

    # Headline numbers
    k = f"[{KPIS}]."
    kpi_name, kpi = _instance("kpi")
    value_name, value = _instance("value", "Sum", "quantitative")
    kpi_tiles = _sheet(
        "KPI Tiles", KPIS,
        [_field("kpi"), "<column caption='Value' datatype='integer' name='[value]' role='measure' type='quantitative' />"],
        [kpi, value], "", f"{k}{kpi_name}", "Text",
        encodings=_encodings(text=f"{k}{value_name}"),
        sort=_manual_sort(f"{k}{kpi_name}", KPI_ORDER),
        style=(
            "<style>\n          <style-rule element='cell'>\n"
            "            <format attr='font-size' value='26' />\n            <format attr='font-weight' value='bold' />\n"
            "            <format attr='color' value='#184f95' />\n"
            f"            <format attr='width' field='{k}{kpi_name}' value='290' />\n          </style-rule>\n"
            "          <style-rule element='header'>\n"
            + "".join(f"            <format attr='width' field='{k}{kpi_name}' value='300' />\n" for _ in [0])
            + "          </style-rule>\n          <style-rule element='worksheet'>\n"
            "            <format attr='display-field-labels' scope='cols' value='false' />\n"
            "          </style-rule>\n        </style>"
        ),
    )

    # Before and after
    c = f"[{COMPARISON}]."
    version_name, version = _instance("version")
    matches_name, matches_instance = _instance("matches", "Sum", "quantitative")
    joinable_name, joinable = _instance("joinable_pct", "Sum", "quantitative")
    compared = []
    for sheet, measure, instance, title in (
        ("Matches Compared", matches_name, matches_instance, "Candidate matches"),
        ("Joinable Compared", joinable_name, joinable, "% of matches a patient can still join"),
    ):
        compared.append(_sheet(
            sheet, COMPARISON,
            [_field("version"), _field("matches"), _field("joinable_pct")], [version, instance],
            f"{c}{version_name}", f"{c}{measure}", "Bar",
            encodings=_encodings(text=f"{c}{measure}"), title=title, pane_extra=SHOW_LABELS,
            sort=_manual_sort(f"{c}{version_name}", VERSIONS),
        ))
    h = f"[{CHECKS}]."
    check_name, check = _instance("check")
    check_version_name, check_version = _instance("version")
    check_value_name, check_value = _instance("value")
    checks = _sheet(
        "Checks Table", CHECKS,
        [_field("check"), _field("version"), _string_column("value")], [check, check_version, check_value],
        f"{h}{check_name}", f"{h}{check_version_name}", "Text",
        encodings=_encodings(text=f"{h}{check_value_name}"), title="What each version checks",
        sort=_manual_sort(f"{h}{check_name}", [row[0] for row in COMPARISON_CHECKS])
        + _manual_sort(f"{h}{check_version_name}", VERSIONS),
        style=_header_widths(h, {"check": 290}, column_widths={"version": 122}),
    )
    # Headline numbers for the selected patient
    st = f"[{PATIENT_STATS}]."
    stat_name, stat = _instance("stat")
    stat_value_name, stat_value = _instance("value", "Sum", "quantitative")
    stats = _sheet(
        "Patient Numbers", PATIENT_STATS,
        [_field("Patient_ID"), selected_calc, _field("stat"),
         "<column caption='Value' datatype='integer' name='[value]' role='measure' type='quantitative' />"],
        [selected_instance, stat, stat_value], "", f"{st}{stat_name}", "Text",
        encodings=_encodings(text=f"{st}{stat_value_name}"), filtered=True,
        sort=_manual_sort(f"{st}{stat_name}", PATIENT_STAT_ORDER),
        style=(
            "<style>\n          <style-rule element='cell'>\n"
            "            <format attr='font-size' value='22' />\n            <format attr='font-weight' value='bold' />\n"
            "            <format attr='color' value='#184f95' />\n"
            f"            <format attr='width' field='{st}{stat_name}' value='290' />\n          </style-rule>\n"
            "          <style-rule element='worksheet'>\n"
            "            <format attr='display-field-labels' scope='cols' value='false' />\n"
            "          </style-rule>\n        </style>"
        ),
    )

    # Open trials by phase
    ph = f"[{PHASES}]."
    phase_name, phase = _instance("phase")
    open_name, open_count = _instance("open_trials", "Sum", "quantitative")
    phases = _sheet(
        "Trials by Phase", PHASES, [_field("phase"), _field("open_trials")], [phase, open_count],
        f"{ph}{phase_name}", f"{ph}{open_name}", "Bar",
        encodings=_encodings(text=f"{ph}{open_name}"), pane_extra=SHOW_LABELS,
        title="Open trials by phase",
        sort=_manual_sort(f"{ph}{phase_name}", extra["phases"]["phase"] if "phases" in extra else []),
    )

    # What the first version's matches were
    ls = f"[{LEGACY_STATUS}]."
    status_name, status_label = _instance("status_label")
    join_name, join = _instance("can_join")
    count_name, count = _instance("matches", "Sum", "quantitative")
    legacy_statuses = _sheet(
        "First Version Statuses", LEGACY_STATUS,
        [_field("status_label"), _field("can_join"), _field("matches")], [status_label, join, count],
        f"{ls}{status_name}", f"{ls}{count_name}", "Bar",
        encodings=_encodings(color=f"{ls}{join_name}", text=f"{ls}{count_name}"),
        pane_extra=SHOW_LABELS.replace("\n                <format attr='mark-color' value='#3987e5' />", ""),
        title="What the first version's matches were (blue: a patient can still join)",
        sort=_manual_sort(
            f"{ls}{status_name}",
            extra["legacy_status"]["status_label"] if "legacy_status" in extra else [],
        ),
    )
    return (
        facts + trials + sites + tier_chart + funnel + kpi_tiles + "".join(compared) + checks
        + stats + phases + legacy_statuses
    )


def _window_id(dashboard):
    return "{" + str(uuid.uuid5(uuid.NAMESPACE_URL, f"hippocrates/{dashboard}")).upper() + "}"


PALETTE = {
    "banner": "#0f2b4c", "brand": "#184f95", "accent": "#3987e5", "page": "#eef2f7",
    "card": "#ffffff", "border": "#d5deea", "muted": "#5b6b80", "button": "#2f6fc0",
}
SUBTITLES = {
    "Trial Scout": "Pick a patient to see their candidate trials, ranked, with the reason for each match",
    "Overview": "How screening narrows thousands of trials to a ranked shortlist per patient",
    "Before and After": "The first matcher against this one, on the same patients and trials",
}


def _zone_style(background=None, border=False, margin=6, padding=0):
    formats = [f"<format attr='margin' value='{margin}' />"]
    if padding:
        formats.append(f"<format attr='padding' value='{padding}' />")
    if background:
        formats.append(f"<format attr='background-color' value='{background}' />")
    if border:
        formats += [
            f"<format attr='border-color' value='{PALETTE['border']}' />",
            "<format attr='border-style' value='solid' />",
            "<format attr='border-width' value='1' />",
        ]
    lines = "".join(f"              {f}\n" for f in formats)
    return f"            <zone-style>\n{lines}            </zone-style>\n"


def _text_zone(zone_id, x, y, w, h, runs, background=None, padding=0, margin=6):
    body = "".join(f"<run{attrs}>{escape(text)}</run>" for text, attrs in runs)
    return (
        f"          <zone forceUpdate='true' h='{h}' id='{zone_id}' type-v2='text' w='{w}' x='{x}' y='{y}'>\n"
        f"            <formatted-text>{body}</formatted-text>\n"
        f"{_zone_style(background, margin=margin, padding=padding)}          </zone>\n"
    )


def _button_zone(zone_id, x, y, w, h, target, label):
    return f"""          <zone h='{h}' id='{zone_id}' type-v2='dashboard-object' w='{w}' x='{x}' y='{y}'>
            <button action='tabdoc:goto-sheet window-id=&quot;{_window_id(target)}&quot;' button-type='text'>
              <button-visual-state>
                <caption>{escape(label)}</caption>
                <button-caption-font-style fontcolor='#ffffff' fontname='Tableau Bold' fontsize='10' />
                <format attr='background-color' value='{PALETTE["button"]}' />
              </button-visual-state>
            </button>
{_zone_style(PALETTE["banner"], margin=0, padding=4)}          </zone>
"""


def _sheet_zone(zone_id, x, y, w, h, sheet, show_title=True):
    """A worksheet shown as a white card with a thin border."""
    hidden = "" if show_title else " show-title='false'"
    return (
        f"          <zone h='{h}' id='{zone_id}' name={quoteattr(sheet)}{hidden} w='{w}' x='{x}' y='{y}'>\n"
        f"{_zone_style(PALETTE['card'], border=True, margin=6, padding=8)}          </zone>\n"
    )


def _control_zone(zone_id, x, y, w, h, kind, param, name=""):
    named = f" name={quoteattr(name)}" if name else ""
    mode = "compact" if kind == "paramctrl" else "checkdropdown"
    values = "" if kind == "paramctrl" else " values='relevant'"
    return (
        f"          <zone h='{h}' id='{zone_id}' mode='{mode}'{named} param='{param}' type-v2='{kind}'{values} "
        f"w='{w}' x='{x}' y='{y}'>\n{_zone_style(PALETTE['card'], margin=6, padding=4)}          </zone>\n"
    )


def _dashboard(name, height, zones):
    return f"""    <dashboard name={quoteattr(name)}>
      <style>
        <style-rule element='table'>
          <format attr='background-color' value='{PALETTE["page"]}' />
        </style-rule>
      </style>
      <size maxheight='{height}' maxwidth='1280' minheight='{height}' minwidth='1280' />
      <zones>
        <zone h='100000' id='1' type-v2='layout-basic' w='100000' x='0' y='0'>
{"".join(zones)}        </zone>
      </zones>
    </dashboard>
"""


class _Rows:
    """Stacks zones top to bottom in pixels, converting to Tableau's 0-100000 units."""

    def __init__(self, height):
        self.height, self.y = height, 0

    def take(self, px=None):
        """Return (y, h) units for the next px pixels, or for all that is left."""
        px = px if px is not None else self.height - self.y - 6
        # Both edges are rounded from pixel positions, so neighbouring zones meet exactly:
        # a one-unit overlap makes Tableau rearrange a tiled layout.
        y, end = self.units(self.y), self.units(self.y + px)
        self.y += px
        return y, end - y

    def units(self, px):
        return round(px * 100000 / self.height)


def _banner(name, targets, rows):
    """Navy title bar with the dashboard's name, a one-line subtitle and navigation buttons."""
    # Two stacked text zones: Tableau keeps a dashboard text zone on a single line.
    _, title_h = rows.take(52)
    _, subtitle_h = rows.take(32)
    h = title_h + subtitle_h
    zones = [
        _text_zone(2, 0, 0, 76000, title_h, [
            ("Hippocrates Trial Scout", " bold='true' fontcolor='#ffffff' fontsize='20'"),
            (f"   |   {name}", " fontcolor='#9ec5f4' fontsize='14'"),
        ], background=PALETTE["banner"], padding=10, margin=0),
        _text_zone(8, 0, title_h, 76000, subtitle_h, [
            (SUBTITLES[name], " fontcolor='#cde2fb' fontsize='10'"),
            (f"   ·   {SHORT_NOTICE}", " fontcolor='#86b6ef' fontsize='9' italic='true'"),
        ], background=PALETTE["banner"], padding=6, margin=0),
    ]
    for index, (target, label) in enumerate(targets):
        zones.append(_button_zone(10 + index, 76000 + index * 12000, 0, 12000, h, target, label))
    return zones


SHORT_NOTICE = "Synthetic patients · not medical advice"


SCOUT_HEIGHT = 1360


def _dashboards():
    s = f"[{SCOUT}]."

    rows = _Rows(SCOUT_HEIGHT)
    zones = _banner("Trial Scout", [("Overview", "Overview →"), ("Before and After", "Before / after →")], rows)
    y, h = rows.take(62)
    controls = [
        _control_zone(3, 800, y, 22000, h, "paramctrl", "[Parameters].[Parameter 1]"),
        _control_zone(20, 23200, y, 22000, h, "filter", f"{s}[none:match_tier:nk]", "Candidate Trials"),
        _control_zone(21, 45600, y, 22000, h, "filter", f"{s}[none:distance:nk]", "Candidate Trials"),
    ]
    facts = _sheet_zone(4, 800, *_span(rows, 96), "Patient Facts")
    strip = [_sheet_zone(30, 800, *_span(rows, 104), "Patient Numbers", show_title=False)]
    trials = _sheet_zone(5, 800, *_span(rows, 560), "Candidate Trials")
    sites = _sheet_zone(6, 800, *_span(rows), "Trial Sites")
    scout = _dashboard("Trial Scout", SCOUT_HEIGHT, zones + controls + [facts] + strip + [trials, sites])

    rows = _Rows(860)
    zones = _banner("Overview", [("Trial Scout", "Trial Scout →"), ("Before and After", "Before / after →")], rows)
    kpis = _sheet_zone(3, 800, *_span(rows, 112), "KPI Tiles", show_title=False)
    y, h = rows.take()
    legend_h = rows.units(46)
    funnel_h = rows.units(322)
    overview = _dashboard("Overview", 860, zones + [
        kpis,
        _sheet_zone(4, 800, y, 48600, funnel_h, "Screening Funnel"),
        _sheet_zone(7, 800, y + funnel_h, 48600, h - funnel_h, "Trials by Phase"),
        f"          <zone h='{legend_h}' id='5' name='Candidates by Tier' pane-specification-id='0' param='{s}[none:match_tier:nk]' type-v2='color' w='49800' x='49600' y='{y}'>\n"
        f"{_zone_style(PALETTE['card'], border=True, margin=6, padding=4)}          </zone>\n",
        _sheet_zone(6, 49600, y + legend_h, 49800, h - legend_h, "Candidates by Tier"),
    ])

    rows = _Rows(860)
    zones = _banner("Before and After", [("Trial Scout", "Trial Scout →"), ("Overview", "Overview →")], rows)
    y, h = rows.take(250)
    comparison = _dashboard("Before and After", 860, zones + [
        _sheet_zone(4, 800, y, 48600, h, "Matches Compared"),
        _sheet_zone(5, 49600, y, 49800, h, "Joinable Compared"),
        _sheet_zone(6, 800, *_span(rows), "Checks Table").replace("w='98400'", "w='48600'", 1),
    ]).replace("        </zone>\n      </zones>", _legacy_zone(rows) + "        </zone>\n      </zones>", 1)
    return scout + overview + comparison


def _legacy_zone(rows):
    """The first version's status breakdown, beside the checklist on Before and After."""
    y = rows.units(84 + 250)
    return _sheet_zone(7, 49600, y, 49800, 99400 - y, "First Version Statuses")


def _span(rows, px=None):
    """Full-width (y, w, h) for the next block: unpacks after x in _sheet_zone's arguments."""
    y, h = rows.take(px)
    return y, 98400, h


WORKSHEET_CARDS = """      <cards>
        <edge name='left'>
          <strip size='160'>
            <card type='pages' />
            <card type='filters' />
            <card type='marks' />
          </strip>
        </edge>
        <edge name='top'>
          <strip size='2147483647'>
            <card type='columns' />
          </strip>
          <strip size='2147483647'>
            <card type='rows' />
          </strip>
        </edge>
      </cards>
"""


DASHBOARD_SHEETS = {
    "Trial Scout": ["Patient Facts", "Patient Numbers", "Candidate Trials", "Trial Sites"],
    "Overview": ["KPI Tiles", "Screening Funnel", "Trials by Phase", "Candidates by Tier"],
    "Before and After": ["Matches Compared", "Joinable Compared", "Checks Table", "First Version Statuses"],
}


def _windows():
    """Tableau needs an active sheet on open: the Trial Scout dashboard."""
    lines = ["  <windows source-height='30'>"]
    # Each dashboard window must list the sheets it shows, or Tableau cannot draw it.
    for name, sheets in DASHBOARD_SHEETS.items():
        maximized = " maximized='true'" if name == "Trial Scout" else ""
        lines += [f"    <window class='dashboard'{maximized} name='{name}'>", "      <viewpoints>"]
        lines += [f"        <viewpoint name='{sheet}' />" for sheet in sheets]
        # Navigation buttons find a dashboard by this id.
        lines += ["      </viewpoints>", "      <active id='-1' />", f"      <simple-id uuid='{_window_id(name)}' />", "    </window>"]
    for name in [sheet for sheets in DASHBOARD_SHEETS.values() for sheet in sheets]:
        lines += [f"    <window class='worksheet' name='{name}'>", WORKSHEET_CARDS.rstrip(), "    </window>"]
    return "\n".join(lines + ["  </windows>", ""])


SCOUT_CAPTIONS = _caption_columns([
    "patient_rank", "match_score", "match_tier", "trial_title", "nct_id", "status", "best_site", "match_reasons",
    "Patient_ID", "distance", "site_city", "site_state", "site_country",
]) + (
    "      <column caption='Candidates' datatype='integer' name='[Number of Records]' role='measure' "
    "type='quantitative' user:auto-column='numrec'>\n        <calculation class='tableau' formula='1' />\n      </column>\n"
    # The tier colours are keyed to this instance, so it must exist at data-source level.
    "      <column-instance column='[match_tier]' derivation='None' name='[none:match_tier:nk]' pivot='key' type='nominal' />\n"
)


EXTRA_CAPTIONS = {
    "kpis": "KPIs", "comparison": "Comparison", "checks": "Checks", "phases": "Phases",
    "legacy_status": "First Version Statuses", "patient_stats": "Patient Numbers",
}
EXTRA_COLUMNS = {
    "kpis": ["kpi"], "comparison": ["version", "matches", "joinable_pct"], "checks": ["check", "version"],
    "phases": ["phase", "open_trials"], "legacy_status": ["status_label", "can_join", "matches"],
    "patient_stats": ["Patient_ID", "stat"],
}
def _palette_style(field, colors):
    maps = "\n".join(
        f"          <map to='{color}'>\n            <bucket>&quot;{value}&quot;</bucket>\n          </map>"
        for value, color in colors.items()
    )
    return (
        f"      <style>\n        <style-rule element='mark'>\n          <encoding attr='color' field='{field}' type='palette'>\n"
        f"{maps}\n          </encoding>\n        </style-rule>\n      </style>\n"
    )


# A colour rule only applies when its field instance exists at data-source level.
EXTRA_INSTANCES = {
    "legacy_status": "      <column-instance column='[can_join]' derivation='None' name='[none:can_join:nk]' pivot='key' type='nominal' />\n",
}
EXTRA_INSTANCES["patient_stats"] = (
    "      <column caption='Selected Patient' datatype='boolean' name='[Selected Patient]' role='dimension' type='nominal'>\n"
    "        <calculation class='tableau' formula='[Patient_ID] = [Parameters].[Parameter 1]' />\n      </column>\n"
)
EXTRA_STYLES = {"legacy_status": _palette_style("[none:can_join:nk]", JOINABLE_COLORS)}
ACTIONS = f"""  <actions>
    <action caption='Open on ClinicalTrials.gov' name='[Action1_OpenStudy]'>
      <activation type='on-select' />
      <source dashboard='Trial Scout' type='sheet' worksheet='Candidate Trials' />
      <link caption='' expression='https://clinicaltrials.gov/study/&lt;[nct_id]&gt;' />
    </action>
    <datasources>
      <datasource caption='Trial Scout' name='{SCOUT}' />
    </datasources>
    <datasource-dependencies datasource='{SCOUT}'>
      <column caption='NCT ID' datatype='string' name='[nct_id]' role='dimension' type='nominal' />
    </datasource-dependencies>
  </actions>
"""


def build_workbook(scout, funnel, directory, extra=None):
    patient_ids = sorted(scout["Patient_ID"].unique())
    directory = str(directory).replace("\\", "/")
    colors = "\n".join(
        f"          <map to='{color}'>\n            <bucket>&quot;{tier}&quot;</bucket>\n          </map>"
        for tier, color in TIER_COLORS.items()
    )
    tier_style = f"""      <style>
        <style-rule element='mark'>
          <encoding attr='color' field='[none:match_tier:nk]' type='palette'>
{colors}
          </encoding>
        </style-rule>
      </style>
"""
    return f"""<?xml version='1.0' encoding='utf-8' ?>
<workbook source-build='2025.2.0 (20252.25.0912.2314)' source-platform='win' version='18.1' xmlns:user='http://www.tableausoftware.com/xml/user'>
  <document-format-change-manifest>
    <BasicButtonObject />
    <BasicButtonObjectTextSupport />
    <MapboxVectorStylesAndLayers />
    <WindowsPersistSimpleIdentifiers />
  </document-format-change-manifest>
  <preferences>
    <preference name='ui.encoding.shelf.height' value='24' />
    <preference name='ui.shelf.height' value='26' />
  </preferences>
  <datasources>
{_parameter(patient_ids)}{_datasource(SCOUT, "Trial Scout", "trial_scout.csv", scout, directory, SCOUT_CALCS + SCOUT_CAPTIONS, tier_style)}{_datasource(FUNNEL, "Funnel", "screening_funnel.csv", funnel, directory, _caption_columns(["stage", "avg_trials_left"]))}{"".join(
    _datasource(f"federated.{name}", EXTRA_CAPTIONS[name], f"{name}.csv", frame, directory,
                _caption_columns(EXTRA_COLUMNS[name]) + EXTRA_INSTANCES.get(name, ""), EXTRA_STYLES.get(name, ""))
    for name, frame in (extra or {}).items()
)}  </datasources>
  <mapsources>
    <mapsource name='Tableau' />
  </mapsources>
{ACTIONS if extra else ""}  <worksheets>
{_worksheets(extra or {})}  </worksheets>
  <dashboards>
{_dashboards()}  </dashboards>
{_windows()}</workbook>
"""


def run():
    patients = pd.read_csv(config.PATIENTS_CSV)
    matches = pd.read_csv(config.MATCHES_CSV)
    funnel = pd.read_csv(config.FUNNEL_CSV)
    trial_count = len(pd.read_csv(config.TRIALS_CSV, usecols=["nct_id"]))
    scout = build_scout_table(patients, matches)
    funnel_table = build_funnel_table(funnel, trial_count)

    config.TABLEAU_DIR.mkdir(parents=True, exist_ok=True)
    scout.to_csv(config.TABLEAU_DIR / "trial_scout.csv", index=False, lineterminator="\n")
    funnel_table.to_csv(config.TABLEAU_DIR / "screening_funnel.csv", index=False, lineterminator="\n")
    write_extract(scout, config.TABLEAU_DIR / "trial_scout.hyper")
    write_extract(funnel_table, config.TABLEAU_DIR / "screening_funnel.hyper")
    trials = pd.read_csv(config.TRIALS_CSV, dtype=str, usecols=["nct_id", "status", "phases", "conditions", "eligibility_text"])
    first_version = legacy.legacy_matches(patients, trials)
    extra = {
        "kpis": build_kpi_table(patients, trials, matches),
        "comparison": build_comparison_table(matches, legacy.summarize(first_version)),
        "checks": build_checks_table(),
        "phases": build_phase_table(trials),
        "legacy_status": build_legacy_status_table(first_version),
        "patient_stats": build_patient_stats_table(scout),
    }
    for name, frame in extra.items():
        frame.to_csv(config.TABLEAU_DIR / f"{name}.csv", index=False, lineterminator="\n")
        write_extract(frame, config.TABLEAU_DIR / f"{name}.hyper")
    workbook = config.TABLEAU_DIR / "hippocrates.twb"
    workbook.write_text(
        build_workbook(scout, funnel_table, config.TABLEAU_DIR, extra), encoding="utf-8", newline="\n"
    )
    print(f"Tableau workbook written to {workbook}")
