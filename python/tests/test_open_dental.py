"""Spec 029 US1 and US5 (#369, #381): the seeded synthetic dental-practice extract in Open Dental's table format
(health_transformation_lab_nlp.open_dental). Synthetic only: every row is generated here."""
import importlib.util
import random
import sys
from pathlib import Path

import pandas as pd
import pytest

from health_transformation_lab_nlp import open_dental as od

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "diagrams" / "_build"))
_spec = importlib.util.spec_from_file_location("opendental_silver_model",
                                               ROOT / "diagrams" / "_build" / "opendental_silver_model.py")
MODEL = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(MODEL)

SMALL = od.Params(n_patients=120)


@pytest.fixture(scope="module")
def built():
    return od.build(SMALL, seed=7)


def test_same_seed_same_extract_and_no_global_random_used(built):
    state = random.getstate()
    again, truth = od.build(SMALL, seed=7)
    assert random.getstate() == state                     # its own stream: the study datasets can't change
    tables, truth0 = built
    for name in tables:
        pd.testing.assert_frame_equal(tables[name], again[name], obj=name)
    pd.testing.assert_frame_equal(truth0, truth)
    other, _ = od.build(SMALL, seed=8)
    assert not tables["procedurelog"].equals(other["procedurelog"])


def test_every_table_and_column_is_the_silver_models(built):
    tables, _ = built
    source = {n: [c.name for c in t.columns] for n, t in MODEL.TABLES.items() if t.area == "source"}
    assert set(tables) == set(source)
    for name, cols in source.items():
        assert list(tables[name].columns) == cols, name
    assert od.TABLES == source


def test_keys_are_unique_and_foreign_keys_resolve(built):
    t, _ = built
    for name in od.TABLES:
        pk = [c.name for c in MODEL.TABLES[name].columns if "PK" in c.key]
        if pk:
            assert not t[name].duplicated(pk).any(), name
    pats = set(t["patient"]["patnum"])
    for name in ("procedurelog", "treatplan", "proctp", "perioexam", "toothinitial", "disease", "appointment",
                 "medicationpat", "allergy", "sheet", "vitalsign", "patientrace", "procnote", "ehrmeasureevent",
                 "patfield"):
        assert set(t[name]["patnum"]) <= pats, name
    assert set(t["procedurelog"]["codenum"]) <= set(t["procedurecode"]["codenum"])
    assert set(t["proctp"]["treatplannum"]) <= set(t["treatplan"]["treatplannum"])
    assert set(t["proctp"]["procnumorig"]) <= set(t["procedurelog"]["procnum"])
    assert set(t["periomeasure"]["perioexamnum"]) <= set(t["perioexam"]["perioexamnum"])
    assert set(t["sheetfield"]["sheetnum"]) <= set(t["sheet"]["sheetnum"])
    assert set(t["procnote"]["procnum"]) <= set(t["procedurelog"]["procnum"])
    dx = t["procedurelog"]["dx"]
    diagnoses = set(t["definition"].query("category == @od.DEFCAT_DIAGNOSIS")["defnum"])
    assert set(dx[dx != 0]) <= diagnoses                   # 0 is Open Dental's "none"


def test_the_truth_stays_out_of_the_extract(built):
    tables, truth = built
    assert list(truth.columns) == ["patient_id", "tooth_num", "true_reason_code"]
    assert set(truth["true_reason_code"]) <= {"perio", "other"}
    for name, df in tables.items():
        assert not any("truth" in c or "reason" in c for c in df.columns if c != "reaction"), name
    # every tooth missing at entry or extracted or planned in the record has a true reason
    t = tables
    ext = t["procedurelog"][t["procedurelog"]["codenum"].isin(od.extraction_codenums(t))]
    events = set(zip(ext["patnum"], ext["toothnum"].astype(int)))
    entry = t["toothinitial"][t["toothinitial"]["initialtype"] == 0]
    events |= set(zip(entry["patnum"], entry["toothnum"].astype(int)))
    assert events <= set(zip(truth["patient_id"], truth["tooth_num"]))


def test_extraction_diagnoses_follow_the_declared_rates():
    p = od.Params(n_patients=800, planned_not_done_per_visit=0.6, other_extraction_per_visit=0.3)  # many extractions
    tables, truth = od.build(p, seed=3)
    ext = od.extractions(tables, truth)                   # one row per extraction with its truth and mapped diagnosis
    assert len(ext) > 1000
    for kind in ("perio", "other"):
        sub = ext[ext["true_reason_code"] == kind]
        assert abs((sub["dx_class"] == kind).mean() - p.dx_correct) < 0.05, kind
        assert abs((sub["dx_class"] == "none").mean() - p.dx_none) < 0.05, kind
    icd = tables["procedurelog"]["diagnosticcode"].astype(str).str.len() > 0
    assert icd.mean() < 0.05                              # ICD codes only for medical claims: rare


def test_the_older_diagnosis_list_gives_way_to_the_2017_list():
    tables, truth = od.build(od.Params(n_patients=400), seed=3)
    p = od.Params()
    ext = od.extractions(tables, truth).dropna(subset=["dx_list"])
    before = ext[ext["datetp"] < pd.Timestamp(p.list_switch_date)]
    after = ext[ext["datetp"] > pd.Timestamp(p.list_switch_date) + pd.DateOffset(years=p.list_adoption_years)]
    assert (before["dx_list"] == "older").all() and (after["dx_list"] == "2017").all()
    assert {"older", "2017"} <= set(ext["dx_list"])


def test_a_planned_extraction_is_one_procedure_with_many_plan_copies(built):
    t, _ = built
    plog = t["procedurelog"].set_index("procnum")
    copies = t["proctp"].groupby("procnumorig").size()
    assert (copies >= 1).all() and (copies > 1).any()     # copied into several plans, and again at later exams
    assert set(plog.loc[copies.index, "procstatus"]) <= {1, 2}
    never = plog[(plog["procstatus"] == 1) & plog.index.isin(copies.index)]
    assert len(never) > 0                                  # some planned extractions are never completed
    edited = t["proctp"].merge(t["procedurelog"][["procnum", "toothnum"]], left_on="procnumorig", right_on="procnum")
    assert (edited["toothnumtp"] != edited["toothnum"]).sum() >= 0


def test_open_dental_value_conventions(built):
    t, _ = built
    pm = t["periomeasure"]
    assert 7 not in set(pm["sequencetype"])                # CAL is never stored
    sites = pm[["mbvalue", "bvalue", "dbvalue", "mlvalue", "lvalue", "dlvalue"]]
    ok = sites.isin([-1]) | sites.apply(lambda s: s.between(0, 19)) | (sites >= 100)
    assert ok.all().all()
    assert pm["inttooth"].between(1, 32).all()
    assert set(t["procedurelog"]["procstatus"]) <= {1, 2, 4}
    assert set(t["patient"]["patstatus"]) <= {0, 1, 2, 3, 4, 5, 6}
    assert set(t["toothinitial"]["initialtype"]) <= set(range(11))
    assert (t["sheet"]["sheettype"] == od.SHEET_EXAM).all()


def test_write_puts_the_truth_apart(tmp_path):
    out, key = tmp_path / "open_dental", tmp_path / "answer_key"
    od.write(out, key, od.Params(n_patients=10), seed=1)
    assert {p.stem for p in out.glob("*.csv")} == set(od.TABLES)
    assert [p.name for p in key.iterdir()] == ["tooth_loss_truth.csv"]


# ---------- T007: silver cleaning and the load job (#370, #381) ----------
def test_silver_cleans_to_open_dentals_conventions():
    pm = pd.DataFrame({"periomeasurenum": [1, 2, 3, 4], "perioexamnum": [1, 1, 1, 1],
                       "sequencetype": [od.SEQ_MARGIN, od.SEQ_MARGIN, od.SEQ_PROBING, od.SEQ_MOBILITY],
                       "inttooth": [3, 3, 3, 3], "toothvalue": [-1, -1, -1, 2],
                       "mbvalue": [105, 2, 4, -1], "bvalue": [-1, 100, 3, -1], "dbvalue": [1, 1, 1, -1],
                       "mlvalue": [1, 1, 1, -1], "lvalue": [1, 1, 1, -1], "dlvalue": [1, 1, 1, -1]})
    silver = od.clean({"periomeasure": pm, "patient": pd.DataFrame({"patnum": [1]})})
    s = silver["periomeasure"]
    assert s.loc[0, "mbvalue"] == -5 and s.loc[1, "bvalue"] == 0      # gingival margins of 100+ are negative
    assert s.loc[2, "mbvalue"] == 4                                     # probing depths are left alone
    assert pd.isna(s.loc[0, "bvalue"]) and pd.isna(s.loc[3, "mbvalue"])  # -1: not measured
    assert pd.isna(s.loc[0, "toothvalue"]) and s.loc[3, "toothvalue"] == 2
    assert list(s.columns) == list(pm.columns)                          # same names and layout as bronze
    assert silver["patient"].equals(pd.DataFrame({"patnum": [1]}))


def _bundle():
    import yaml
    return yaml.safe_load((ROOT / "databricks" / "resources" / "jobs.yml").read_text())["resources"]["jobs"]


def test_the_load_job_generates_and_loads_bronze_and_silver():
    job = _bundle()["open_dental_load"]
    assert job["name"] == "Load Open Dental" and job["tags"]["data"] == "synthetic"
    p = job["tasks"][0]["notebook_task"]["base_parameters"]
    assert p["bronze_schema"] == "${resources.schemas.opendental_perio_bronze.name}"
    assert p["silver_schema"] == "${resources.schemas.opendental_perio_silver.name}"
    assert p["od_catalog"] == "${resources.schemas.opendental_perio_bronze.catalog_name}"
    assert "opendental_perio_data" in p["landing_dir"]
    nb = (ROOT / "databricks" / "notebooks" / "12_load_open_dental.py").read_text()
    for call in ("open_dental.write(", "open_dental.clean(", 'mode: str = "overwrite"', 'mode="append"',
                 "open_dental.load_log(", "tooth_loss.tooth_table(clean_read)", "tooth_loss.planned_extraction(clean)",
                 '"radiograph_bone_level": readings'):
        assert call in nb, call
    # the Open Dental tables hold Open Dental's columns only; the batch key goes in load_log (AGENTS.md: every row
    # still traces to its run, through the one load_log row per run and table)
    assert ".assign(run_id" not in nb and "saveAsTable" in nb
    assert "answer_key" in nb                  # the truth lands in its own folder, read only by the evaluation


def test_the_deploy_loads_the_extract_once_it_is_missing():
    deploy = (ROOT / ".github" / "workflows" / "deploy.yml").read_text()
    assert "bundle run -t \"$TARGET\" --no-wait open_dental_load" in deploy
    assert "bronze_opendental_perio.patient" in deploy


def test_the_load_log_records_each_table_written_with_its_batch_key():
    tables, truth = od.build(od.Params(n_patients=5), seed=1)
    log = od.load_log({"bronze_opendental_perio": tables, "silver_opendental_perio": {"tooth_loss_truth": truth}},
                      run_id="123", run_ts=pd.Timestamp("2026-10-31"), git_commit_sha="abc", seed=1, n_patients=5)
    assert list(log.columns) == ["schema_name", "table_name", "row_count", "seed_num", "patient_count",
                                 "run_id", "run_ts", "git_commit_sha"]
    assert len(log) == len(tables) + 1
    row = log[log["table_name"] == "procedurelog"].iloc[0]
    assert row["row_count"] == len(tables["procedurelog"]) and row["run_id"] == "123"


# ---------- US6 (#385): as messy as real practice records ----------
NO_MESS = od.Params(n_patients=150, **od.NO_MESS)


@pytest.fixture(scope="module")
def messy():
    return od.build_with_readings(od.Params(n_patients=600), seed=11)


def test_build_is_build_with_readings_without_the_readings():
    tables, truth = od.build(SMALL, seed=7)
    again, truth2, readings = od.build_with_readings(SMALL, seed=7)
    for name in tables:
        pd.testing.assert_frame_equal(tables[name], again[name], obj=name)
    pd.testing.assert_frame_equal(truth, truth2)
    assert list(readings.columns) == [c.name for c in MODEL.TABLES["radiograph_bone_level"].columns]
    assert readings["is_simulated"].all()


def test_the_realism_profile_measures_the_declared_rates(messy):
    tables, _, readings = messy
    p = od.Params()
    prof = od.realism_profile(tables, readings)
    assert set(prof["metric_name"]) >= {"charted_visit_office_share", "charted_visit_site_share", "partial_chart_share",
                                        "buccal_only_chart_share", "no_margin_chart_share", "no_bleeding_chart_share",
                                        "copied_chart_share", "uniform_chart_share", "out_of_range_site_share",
                                        "charted_after_loss_chart_share", "radiograph_visit_share",
                                        "unread_tooth_share"}
    got = dict(zip(prof["metric_name"], prof["value_ratio"]))
    assert list(prof.columns) == ["metric_name", "value_ratio", "numerator_count", "denominator_count"]
    assert abs(got["charted_visit_office_share"] - p.chart_office) < 0.04
    assert abs(got["charted_visit_site_share"] - p.chart_site) < 0.12          # few patients live at sites
    for metric, rate in (("partial_chart_share", p.partial_chart), ("buccal_only_chart_share", p.buccal_only),
                         ("no_margin_chart_share", p.no_margin), ("no_bleeding_chart_share", p.no_bleeding),
                         ("copied_chart_share", p.copied_chart), ("uniform_chart_share", p.uniform_chart),
                         ("unread_tooth_share", p.reading_missing)):
        assert abs(got[metric] - rate) < 0.05, metric
    assert 0 < got["out_of_range_site_share"] < 0.01
    assert got["charted_after_loss_chart_share"] > 0
    assert 0.2 < got["radiograph_visit_share"] < 0.6


def test_with_no_mess_every_visit_has_a_complete_chart():
    tables, _, readings = od.build_with_readings(NO_MESS, seed=2)
    prof = od.realism_profile(tables, readings)
    got = dict(zip(prof["metric_name"], prof["value_ratio"]))
    assert got["charted_visit_office_share"] == 1
    assert pd.isna(got["charted_visit_site_share"]) or got["charted_visit_site_share"] == 1
    for metric in ("partial_chart_share", "buccal_only_chart_share", "no_margin_chart_share", "no_bleeding_chart_share",
                   "copied_chart_share", "uniform_chart_share", "out_of_range_site_share",
                   "charted_after_loss_chart_share", "unread_tooth_share"):
        assert got[metric] == 0, metric


def test_every_radiograph_has_its_procedure_and_readings_only_for_its_teeth(messy):
    t, _, readings = messy
    docs = t["document"]
    assert (docs["imgtype"] == od.IMG_RADIOGRAPH).all()
    cats = t["definition"].query("category == @od.DEFCAT_IMAGECATS")
    assert set(docs["doccategory"]) <= set(cats["defnum"])
    pc = t["procedurecode"]
    xray = set(pc.loc[pc["proccode"].isin(od.RADIOGRAPHS), "codenum"])
    assert pc.loc[pc["proccode"].isin(od.RADIOGRAPHS), "isradiology"].all()
    procs = t["procedurelog"][t["procedurelog"]["codenum"].isin(xray)]
    done = set(zip(procs["patnum"], pd.to_datetime(procs["procdate"]).dt.normalize()))
    assert set(zip(docs["patnum"], pd.to_datetime(docs["datecreated"]).dt.normalize())) <= done
    assert len(docs) == len(procs)
    on_image = {(d, int(n)) for d, nums in zip(docs["docnum"], docs["toothnumbers"]) for n in nums.split(",")}
    assert set(zip(readings["document_id"], readings["tooth_num"])) == on_image
    read = readings["bone_loss_pct"].dropna()
    assert read.between(0, 95).all() and len(read) > 0
