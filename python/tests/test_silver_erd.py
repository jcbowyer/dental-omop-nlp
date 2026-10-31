"""Spec 029 US4 (#379): the Open Dental silver ERD and its OMOP alternative, drawn from declarations in
diagrams/_build/ the way the gold ERDs are."""
import importlib.util
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "diagrams" / "_build"
sys.path.insert(0, str(BUILD))       # the models import gold_model's dataclasses, as gold_erd does


def _load(name):
    spec = importlib.util.spec_from_file_location(name, BUILD / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


OD = _load("opendental_silver_model")
OM = _load("omop_silver_model")
RESEARCH = (ROOT / "specs" / "029-tooth-loss" / "research.md").read_text()


def _research_columns(table):
    """The columns research.md lists for an Open Dental table, lowercased."""
    section = RESEARCH.split(f"### `{table}`", 1)[1].split("\n### ", 1)[0].split("\n## ", 1)[0]
    cols = set()
    for line in section.splitlines():
        if line.startswith("| `"):
            cols |= {c.lower() for c in re.findall(r"`(\w+)`", line.split("|")[1])}
    return cols


def test_open_dental_tables_are_the_ones_spec_029_researched():
    source = [n for n, t in OD.TABLES.items() if t.area == "source"]
    assert set(source) == {"patient", "clinic", "procedurelog", "procedurecode", "treatplan", "proctp", "definition",
                           "perioexam", "periomeasure", "toothinitial", "disease", "diseasedef",
                           # #381: the rest of a typical research extract
                           "provider", "appointment", "medication", "medicationpat", "allergy", "allergydef", "sheet",
                           "sheetfield", "vitalsign", "patientrace", "cdcrec", "site", "procnote", "ehrmeasureevent",
                           "patfield", "snomed",
                           # #385: radiographs
                           "document"}
    assert "language" not in OD.TABLES          # Open Dental's language table is screen translations
    for name in source:
        allowed = _research_columns(name)
        for c in OD.TABLES[name].columns:
            assert c.name in allowed, f"{name}.{c.name} isn't in research.md's {name} table"
            assert c.name == c.name.lower()


def test_the_derived_tables_follow_spec_029():
    assert {"patient_tooth", "planned_extraction", "tooth_loss_dq_check", "tooth_loss_truth",
            "radiograph_bone_level"} <= set(OD.TABLES)
    assert OD.TABLES["radiograph_bone_level"].area == "derived"          # simulated: never an Open Dental table
    assert OD.TABLES["tooth_loss_truth"].area == "eval"


@pytest.mark.parametrize("model", [OD, OM], ids=["opendental", "omop"])
def test_every_relationship_joins_declared_columns(model):
    for r in model.RELATIONSHIPS:
        assert r.parent in model.TABLES and r.child in model.TABLES, r
        for t, cols in ((r.parent, r.parent_cols), (r.child, r.child_cols)):
            names = {c.name for c in model.TABLES[t].columns}
            assert set(cols) <= names, (t, cols)


@pytest.mark.parametrize("model", [OD, OM], ids=["opendental", "omop"])
def test_every_table_and_column_says_what_it_is(model):
    for name, t in model.TABLES.items():
        assert t.description and t.area in model.AREAS, name
        assert t.columns, name
        for c in t.columns:
            assert c.description, (name, c.name)


def test_the_plan_copies_quirk_is_drawn():
    rel = {(r.parent, r.child): r for r in OD.RELATIONSHIPS}
    assert ("procedurelog", "proctp") in rel and rel[("procedurelog", "proctp")].child_cols == ("procnumorig",)
    assert rel[("definition", "procedurelog")].child_cols == ("dx",) and not rel[("definition", "procedurelog")].derived
    assert rel[("definition", "proctp")].derived            # proctp.dx is text, matched by name, not a key


def test_every_omop_column_names_its_open_dental_source():
    for name, t in OM.TABLES.items():
        if t.area not in ("vocab", "gap"):            # the CDM and dental-extension tables
            for c in t.columns:
                assert "←" in c.description or "not from Open Dental" in c.description, (name, c.name)
    assert "not_mapped" in OM.TABLES                            # what the CDM can't hold


def test_the_generated_files_are_current():
    erd = _load("silver_erd")
    for prefix, model in erd.MODELS:
        for stem, full in ((f"{prefix}_entity", False), (f"{prefix}_full", True)):
            assert (erd.SRC / f"{stem}.mmd").read_text() == erd.gold_erd.mermaid(full, model), \
                f"run python3 diagrams/_build/silver_erd.py ({stem}.mmd is stale)"
            assert (erd.SRC / f"{stem}.drawio").exists()
    assert (erd.OUT / "data_model.md").read_text() == erd.markdown()


# ---------- the data-dictionary format (subject areas, row counts, nulls, distinct and top values) ----------
def test_a_column_profile_gives_nulls_distinct_and_value_counts():
    import pandas as pd
    prof = _load("table_profile")
    s = pd.Series([2, 2, 1, None, 2])            # few values: each one's count, one per line
    assert prof.column_profile(s) == "null=1 (20%);\nn_distinct=2;\n1=1 (20%);\n2=3 (60%)"
    many = pd.Series(range(100))                 # all distinct: no top results worth showing
    assert prof.column_profile(many) == "null=0 (0%);\nn_distinct=100"
    skewed = pd.Series([7] * 5 + [8] * 3 + list(range(20)))
    assert prof.column_profile(skewed).endswith("top results:\n  7=6 (21%);\n  8=4 (14%);\n  0=1 (4%)")
    dates = pd.Series(pd.to_datetime(["2016-03-01", "2019-07-02", None, "2024-01-05"]))
    assert prof.column_profile(dates) == "null=1 (25%);\nn_distinct=3;\nfirst=2016;\nlast=2024"
    blanks = pd.Series(["", " ", "x", None])          # Open Dental stores blank text, not NULL: count it as null
    assert prof.column_profile(blanks) == "null=3 (75%);\nn_distinct=1;\nx=1 (25%)"
    tables = prof.profile({"t": pd.DataFrame({"a": [1, None], "b": ["x", "y"]})})
    assert tables["t"]["rows"] == 2 and tables["t"]["columns"]["a"].startswith("null=1 (50%)")


@pytest.mark.parametrize("model", [OD, OM], ids=["opendental", "omop"])
def test_every_table_is_in_one_subject_area_with_a_kind(model):
    grouped = [t for _, _, tables in model.GROUPS for t in tables]
    assert sorted(grouped) == sorted(model.TABLES), "each table in exactly one subject area"
    assert set(model.KINDS) == set(model.TABLES) and set(model.KINDS.values()) <= {"fact", "dimension"}
    for table, col in [*model.PHI, *model.QUESTIONS]:
        assert col in {c.name for c in model.TABLES[table].columns}, (table, col)


def test_the_dictionary_shows_counts_or_says_they_are_not_measured():
    dic = _load("dictionary_erd")
    xml = dic.build(OD, {"patient": {"rows": 7, "columns": {"patnum": "null=0 (0%); n_distinct=7"}}}).xml("t")
    assert "&lt;br&gt;7&lt;br&gt;" in xml and "n_distinct=7" in xml      # the count under the name, as a number
    assert "rows not measured yet" in xml                       # every table without data says so
    for title, _, _ in OD.GROUPS:
        assert title in xml
    assert "Legend" in xml and "FACT" in xml and "DIMENSION" in xml
    # each table is as wide as its own content, and lines leave and enter at the side of the key row
    widths = dic.table_widths(OD, {})
    assert widths["procedurelog"] != widths["clinic"]
    assert all(sum(w) <= 640 for w in widths.values())
    assert "exitX=" in xml and "entryX=" in xml
    assert (dic.SRC / "opendental_silver_dictionary.drawio").exists()
    assert (dic.SRC / "omop_silver_dictionary.drawio").exists()


def test_the_open_dental_areas_sit_in_the_reference_layout():
    # the owner's reference data dictionary for an Open Dental extract (its layout only; nothing else is used):
    # left Medication + Allergy over Socio-Demographic over Patient Health; centre-left Provider over Research
    # Authorization over Patient over Initial Odontogram; centre-right Appointment over Misc Definitions over Location;
    # right Perio Charting over Treatment Planning over Procedures; spec 029's own areas in a fifth column
    cols = {}
    for title, c, tables in OD.GROUPS:
        cols.setdefault(c, []).append(title)
    assert cols[0] == ["Medication + Allergy", "Socio-Demographic", "Patient Health"]
    assert cols[1] == ["Provider", "Research Authorization", "Patient", "Initial Odontogram"]
    assert cols[2] == ["Appointment", "Misc Definitions", "Location"]
    assert cols[3] == ["Perio Charting", "Treatment Planning", "Procedures"]
    assert cols[4] == ["Tooth loss (spec 029)", "Data quality", "Answer key (evaluation only)"]
    tables = {title: t for title, _, t in OD.GROUPS}
    assert tables["Treatment Planning"] == ["proctp", "treatplan"]
    assert tables["Patient Health"][:2] == ["diseasedef", "disease"]
    assert tables["Procedures"][:2] == ["procedurelog", "procedurecode"] and "procnote" in tables["Procedures"]
    assert tables["Location"] == ["clinic", "site"]
    assert tables["Perio Charting"] == ["perioexam", "periomeasure"]
    # every column now fills from the top, as in the reference
    assert not getattr(OD, "COLUMN_ALIGN", {})
