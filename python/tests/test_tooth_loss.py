"""Spec 029 US2 (#370): one silver row per patient and tooth (tooth_loss.tooth_table), and planned extractions
counted once (tooth_loss.planned_extraction). Hand-built Open Dental-shaped extracts; synthetic only."""
import pandas as pd
import pytest

from health_transformation_lab_nlp import open_dental as od
from health_transformation_lab_nlp import tooth_loss as tl

D = pd.Timestamp


def _extract(procs=(), initial=(), exams=(), measures=(), plans=(), smoke="266919005", diseases=(), readings=()):
    """A tiny extract for patient 1. procs: (procnum, tooth, status, dx_name, datetp, datecomplete).
    exams: (examnum, date). measures: (examnum, tooth, seq, six site values or toothvalue)."""
    defs = [(i + 1, od.DEFCAT_DIAGNOSIS, n, a, i, False) for i, (n, a, _) in enumerate(od.OLDER_LIST + od.LIST_2017)]
    defnum = {n: k for k, _, n, _, _, _ in defs}
    t = {name: pd.DataFrame(columns=cols) for name, cols in od.TABLES.items()}
    t["definition"] = pd.DataFrame(defs, columns=od.TABLES["definition"])
    t["procedurecode"] = pd.DataFrame([(1, "D7140", "Extraction", "Ext", 2, 0, False, False, "", False),
                                       (2, "D1110", "Prophylaxis", "Pro", 3, 0, False, True, "", False)],
                                      columns=od.TABLES["procedurecode"])
    t["patient"] = pd.DataFrame([{"patnum": 1, "birthdate": D("1960-01-01"), "gender": 0, "patstatus": 0, "clinicnum": 1, "priprov": 1,
                                      "datefirstvisit": D("2020-01-01"), "smokingsnomed": smoke}], columns=od.TABLES["patient"])
    t["procedurelog"] = pd.DataFrame(
        [{"procnum": p, "patnum": 1, "procstatus": s, "codenum": 1, "toothnum": str(tooth), "dx": defnum.get(dx, 0),
              "datetp": D(dtp) if dtp else pd.NaT, "datecomplete": D(dc) if dc else pd.NaT, "procdate": D(dc or dtp or "2020-01-01")}
         for p, tooth, s, dx, dtp, dc in procs], columns=od.TABLES["procedurelog"])
    t["toothinitial"] = pd.DataFrame([{"toothinitialnum": i + 1, "patnum": 1, "toothnum": str(tooth), "initialtype": 0, "movement": 0.0}
                                      for i, tooth in enumerate(initial)], columns=od.TABLES["toothinitial"])
    t["perioexam"] = pd.DataFrame([{"perioexamnum": e, "patnum": 1, "examdate": D(d), "provnum": 1} for e, d in exams],
                                  columns=od.TABLES["perioexam"])
    rows = []
    for i, (e, tooth, seq, vals) in enumerate(measures):
        sites = dict(zip(od.SITE_VALUES, vals)) if isinstance(vals, (list, tuple)) else dict.fromkeys(od.SITE_VALUES, -1)
        rows.append(dict(periomeasurenum=i + 1, perioexamnum=e, sequencetype=seq, inttooth=tooth,
                         toothvalue=vals if not isinstance(vals, (list, tuple)) else -1, **sites))
    t["periomeasure"] = pd.DataFrame(rows, columns=od.TABLES["periomeasure"])
    t["proctp"] = pd.DataFrame([{"proctpnum": i + 1, "treatplannum": i + 1, "patnum": 1, "procnumorig": p, "datetp": D(d)}
                                for i, (p, d) in enumerate(plans)], columns=od.TABLES["proctp"])
    t["diseasedef"] = pd.DataFrame([{"diseasedefnum": 1, "diseasename": "Type 2 diabetes mellitus", "icd10code": "E11.9"}],
                                   columns=od.TABLES["diseasedef"])
    t["disease"] = pd.DataFrame([{"diseasenum": i + 1, "patnum": 1, "diseasedefnum": 1} for i in range(len(diseases))],
                                columns=od.TABLES["disease"])
    x = od.clean(t)
    x["radiograph_bone_level"] = pd.DataFrame([(doc, tooth, 1, D(d), pct, True) for doc, tooth, d, pct in readings],
                                              columns=od.READING_COLUMNS).astype({"bone_loss_pct": "float64"})
    return x


def _row(table, tooth):
    return table[(table["patient_id"] == 1) & (table["tooth_num"] == tooth)].iloc[0]


def test_one_row_per_patient_and_tooth_with_each_status():
    x = _extract(procs=[(10, 3, od.COMPLETE, "Periodontal disease, advanced", "2020-03-01", "2020-04-01"),
                        (11, 14, od.COMPLETE, "Caries, non-restorable", "2020-03-01", "2020-04-01"),
                        (12, 19, od.COMPLETE, "", "2020-03-01", "2020-04-01"),
                        (13, 30, od.PLANNED, "Periodontitis, stage IV", "2021-01-01", None),
                        (14, 31, od.PLANNED, "Fracture (2017 list)", "2021-01-01", None),
                        (15, 18, od.EXISTING_OTHER, "", None, None)],
                 initial=[2])
    t = tl.tooth_table(x)
    assert len(t) == 32 and not t.duplicated(["patient_id", "tooth_num"]).any()
    expect = {3: ("extracted_perio", True, "completed"), 14: ("extracted_other", False, "completed"),
              19: ("extracted_no_dx", None, "none"), 30: ("planned_perio", True, "planned"),
              31: ("planned_other", False, "planned"), 2: ("missing_at_entry", None, "none"),
              18: ("missing_at_entry", None, "none"), 5: ("present", None, "none")}
    for tooth, (status, label, source) in expect.items():
        r = _row(t, tooth)
        assert r["tooth_status_code"] == status, tooth
        assert (pd.isna(r["is_perio_loss"]) if label is None else r["is_perio_loss"] == label), tooth
        assert r["label_source_code"] == source, tooth


def test_a_planned_extraction_later_completed_counts_once_as_completed():
    x = _extract(procs=[(10, 3, od.COMPLETE, "Periodontitis, stage III", "2020-03-01", "2020-09-01")],
                 plans=[(10, "2020-03-01"), (10, "2020-03-01"), (10, "2020-06-01")])
    t = tl.tooth_table(x)
    assert _row(t, 3)["tooth_status_code"] == "extracted_perio"
    pe = tl.planned_extraction(x)
    assert len(pe) == 1
    r = pe.iloc[0]
    assert r["plan_copy_count"] == 3 and bool(r["is_completed"])
    assert r["first_plan_date"] == D("2020-03-01") and r["last_plan_date"] == D("2020-06-01")


def test_features_come_only_from_exams_before_the_loss():
    # tooth 3 extracted on day 400 (2021-02-04); exams on day 0 and 200 before it, and one after
    x = _extract(procs=[(10, 3, od.COMPLETE, "Periodontitis, stage IV", "2020-07-01", "2021-02-04")],
                 exams=[(1, "2020-01-01"), (2, "2020-07-19"), (3, "2021-06-01")],
                 measures=[(1, 3, od.SEQ_PROBING, [3, 3, 3, 3, 3, 3]), (1, 3, od.SEQ_MARGIN, [0] * 6),
                           (2, 3, od.SEQ_PROBING, [5, 6, 5, 4, 4, 4]), (2, 3, od.SEQ_MARGIN, [2, 1, 105, 0, 0, 0]),
                           (2, 3, od.SEQ_BLEEDING, [1, 0, 1, 4, 0, 0]), (2, 3, od.SEQ_MOBILITY, 2),
                           (2, 4, od.SEQ_PROBING, [4, 4, 4, 4, 4, 4]), (2, 4, od.SEQ_MARGIN, [3, 3, 3, 3, 3, 3]),
                           (3, 3, od.SEQ_PROBING, [9, 9, 9, 9, 9, 9])])            # after the loss: never used
    r = _row(tl.tooth_table(x), 3)
    assert r["last_exam_date"] == D("2020-07-19")
    assert r["last_max_pd_mm"] == 6 and r["last_max_cal_mm"] == 7          # 5 + 2 and 6 + 1; 5 + (-5) = 0
    assert r["last_bop_pct"] == pytest.approx(100 * 2 / 6)                 # bit 1 only: the plaque flag (4) isn't bleeding
    assert r["last_mobility_code"] == "2"
    assert r["neighbour_max_cal_mm"] == 7                                   # tooth 4: 4 + 3 (tooth 2 not charted)


def test_missing_at_entry_teeth_have_no_own_measures_but_mouth_and_patient_features():
    x = _extract(initial=[2], exams=[(1, "2020-01-01")],
                 measures=[(1, 3, od.SEQ_PROBING, [6, 4, 4, 4, 4, 4]), (1, 3, od.SEQ_MARGIN, [0, 0, 0, 0, 0, 0]),
                           (1, 4, od.SEQ_PROBING, [3] * 6), (1, 4, od.SEQ_MARGIN, [0] * 6)],
                 smoke="449868002", diseases=[1])
    r = _row(tl.tooth_table(x), 2)
    assert pd.isna(r["last_max_pd_mm"]) and pd.isna(r["last_exam_date"])
    assert r["mouth_cal5_site_pct"] == pytest.approx(100 * 1 / 12)
    assert r["teeth_missing_at_entry_count"] == 1
    assert r["tooth_type_code"] == "upper_molar" and bool(r["is_smoker"]) and bool(r["is_diabetic"])
    assert r["age_at_first_exam_num"] == 60


def test_shared_features_exclude_the_teeths_own_measures():
    assert not any(c.startswith("last_") for c in tl.SHARED_FEATURES)
    assert set(tl.SHARED_FEATURES) < set(tl.OWN_FEATURES)
    assert "is_perio_loss" not in tl.OWN_FEATURES and "true_reason_code" not in tl.OWN_FEATURES


def test_on_the_synthetic_extract_the_labels_agree_with_the_truth_at_the_declared_rate():
    tables, truth = od.build(od.Params(n_patients=300), seed=5)
    t = tl.tooth_table(od.clean(tables)).merge(truth, on=["patient_id", "tooth_num"], how="left")
    labelled = t.dropna(subset=["is_perio_loss"])
    agree = (labelled["is_perio_loss"] == (labelled["true_reason_code"] == "perio")).mean()
    assert agree > 0.85                                   # dx_correct 0.80 of all, ~0.94 of those with a diagnosis
    missing = t[t["tooth_status_code"] == "missing_at_entry"]
    assert missing["true_reason_code"].notna().all()     # every tooth the model is applied to has a known answer


def test_a_planned_extraction_never_completed_is_one_row_with_its_copies_counted():
    # spec 029 US2 scenario 4: copied into three plans at one exam and two more six months later
    x = _extract(procs=[(10, 30, od.PLANNED, "Periodontitis, stage III", "2020-03-01", None)],
                 plans=[(10, "2020-03-01")] * 3 + [(10, "2020-09-01")] * 2)
    t = tl.tooth_table(x)
    assert (t["tooth_num"] == 30).sum() == 1 and _row(t, 30)["tooth_status_code"] == "planned_perio"
    pe = tl.planned_extraction(x)
    assert len(pe) == 1 and pe.iloc[0]["plan_copy_count"] == 5 and not bool(pe.iloc[0]["is_completed"])


def test_the_tables_hold_the_columns_the_silver_model_declares():
    import importlib.util
    import sys
    from pathlib import Path
    build = Path(__file__).resolve().parents[2] / "diagrams" / "_build"
    sys.path.insert(0, str(build))
    spec = importlib.util.spec_from_file_location("opendental_silver_model", build / "opendental_silver_model.py")
    model = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(model)
    x = _extract(procs=[(10, 3, od.PLANNED, "Periodontitis, stage III", "2020-03-01", None)], plans=[(10, "2020-03-01")])
    for name, df in (("patient_tooth", tl.tooth_table(x)), ("planned_extraction", tl.planned_extraction(x))):
        declared = [c.name for c in model.TABLES[name].columns]   # the batch key is in load_log
        assert list(df.columns) == declared, name


# ---------- US6 (#385): messy charts and radiographs ----------
def test_own_measures_come_from_the_last_exam_that_charted_the_tooth():
    # exam 2 is partial: it charts tooth 4 but not tooth 3, so tooth 3's own measures come from exam 1
    x = _extract(procs=[(10, 3, od.COMPLETE, "Periodontitis, stage IV", "2020-09-01", "2020-09-01")],
                 exams=[(1, "2020-01-01"), (2, "2020-07-01")],
                 measures=[(1, 3, od.SEQ_PROBING, [5, 4, 4, 4, 4, 4]), (1, 3, od.SEQ_MARGIN, [1] * 6),
                           (2, 4, od.SEQ_PROBING, [3] * 6), (2, 4, od.SEQ_MARGIN, [4] * 6)])
    r = _row(tl.tooth_table(x), 3)
    assert r["last_exam_date"] == D("2020-01-01") and r["last_max_pd_mm"] == 5 and r["last_max_cal_mm"] == 6
    assert r["neighbour_max_cal_mm"] == 7                     # neighbours from the patient's last exam, 3 + 4


def test_the_last_radiograph_reading_before_the_loss_is_the_teeths_bone_loss():
    x = _extract(procs=[(10, 3, od.COMPLETE, "Periodontitis, stage IV", "2021-01-01", "2021-01-01")],
                 exams=[(1, "2020-01-01")], measures=[(1, 3, od.SEQ_PROBING, [4] * 6)],
                 readings=[(1, 3, "2020-01-01", 40.0), (1, 4, "2020-01-01", 20.0), (2, 3, "2020-06-01", None),
                           (3, 3, "2021-03-01", 80.0)])            # unread, then after the loss: neither used
    t = tl.tooth_table(x)
    r = _row(t, 3)
    assert r["last_rbl_pct"] == 40 and r["last_radiograph_date"] == D("2020-01-01")
    assert r["mouth_max_rbl_pct"] == 40                        # the first radiograph read: worst of 40 and 20
    assert pd.isna(_row(t, 10)["last_rbl_pct"])                 # never on an image


def test_each_tooth_says_how_good_its_last_chart_was():
    x = _extract(exams=[(1, "2020-01-01"), (2, "2020-07-01")],
                 measures=[(1, 3, od.SEQ_PROBING, [3] * 6), (1, 4, od.SEQ_PROBING, [3] * 6),
                           (2, 5, od.SEQ_PROBING, [4, 5, 4, 3, 3, 3])])
    t = tl.tooth_table(x)
    assert _row(t, 3)["last_chart_quality_code"] == "uniform"
    assert _row(t, 5)["last_chart_quality_code"] == "partial"  # one tooth of 32 charted
    assert pd.isna(_row(t, 9)["last_chart_quality_code"])      # never charted
