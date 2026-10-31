"""One row per patient and tooth from a cleaned Open Dental extract (spec 029 US2, #370).

`tooth_table` says how each tooth left the record (or didn't), the label that gives (`is_perio_loss`: the recorded
diagnosis maps to periodontal), and what was charted before. `planned_extraction` counts each planned extraction once,
however many treatment-plan copies carry it. Reads the silver tables `open_dental.clean` returns; synthetic only.

Status, first rule that applies:
1. a completed extraction (ProcStatus 2): extracted_perio, extracted_other or extracted_no_dx, by its diagnosis item
   mapped through `open_dental.DIAGNOSIS_LOOKUP` (a planned extraction later completed is the same row, so it counts
   once, as completed);
2. missing at entry: a `toothinitial` row of InitialType 0, or an extraction done elsewhere (ProcStatus 4);
3. a planned extraction (ProcStatus 1) with a diagnosis: planned_perio or planned_other;
4. otherwise present (a planned extraction with no diagnosis leaves the tooth present and unlabelled).

Own measures come from the last perio exam on or before the event date that charted the tooth (extraction date, or
the plan date for a planned one; an exam on the extraction day is charted first; a present tooth uses the last), with
that chart's quality (complete, partial, copied, uniform: open_dental.chart_quality), since real charts are often
missing or partial (#385). Neighbours come from the patient's last exam on or before the event. Own radiographic bone
loss is the last radiograph reading on or before the event (`radiograph_bone_level`, a SIMULATED reading; optional).
A tooth missing at entry has no own measures; its neighbours come from the first exam. CAL = probing depth + gingival margin per site
(Open Dental never stores it). Mouth-level measures come from the first exam.
"""

from __future__ import annotations

import pandas as pd

from . import open_dental as od
from .telemetry import traced

SMOKER_SNOMED = ("449868002", "428041000124106")   # daily and occasional tobacco smoker
DIABETES_ICD10 = ("E10", "E11")
TEETH = range(1, 33)
_INCISORS, _CANINES = {7, 8, 9, 10, 23, 24, 25, 26}, {6, 11, 22, 27}
_PREMOLARS = {4, 5, 12, 13, 20, 21, 28, 29}
_FAR_FUTURE = pd.Timestamp("2200-01-01")

# what the model may read: shared features exist for every tooth, own features only where the tooth was charted
SHARED_FEATURES = ["tooth_type_code", "neighbour_max_cal_mm", "mouth_cal5_site_pct", "mouth_max_pd_mm",
                   "mouth_bop_pct", "mouth_max_rbl_pct", "teeth_missing_at_entry_count", "age_at_first_exam_num", "is_smoker",
                   "is_diabetic"]
OWN_FEATURES = [*SHARED_FEATURES, "last_max_pd_mm", "last_max_cal_mm", "last_bop_pct", "last_mobility_code",
                "last_chart_quality_code", "last_rbl_pct"]
COLUMNS = ["patient_id", "tooth_num", "tooth_status_code", "loss_date", "label_source_code", "dx_def_id",
           "is_perio_loss", "last_exam_date", "last_max_pd_mm", "last_max_cal_mm", "last_bop_pct",
           "last_mobility_code", "last_chart_quality_code", "last_rbl_pct", "last_radiograph_date",
           "neighbour_max_cal_mm", "mouth_cal5_site_pct", "mouth_max_pd_mm", "mouth_bop_pct", "mouth_max_rbl_pct",
           "teeth_missing_at_entry_count", "tooth_type_code", "age_at_first_exam_num", "is_smoker", "is_diabetic"]


def _tooth_type(t: int) -> str:
    kind = ("incisor" if t in _INCISORS else "canine" if t in _CANINES else "premolar" if t in _PREMOLARS
            else "molar")
    return f"{'upper' if t <= 16 else 'lower'}_{kind}"


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def _date(s: pd.Series) -> pd.Series:
    """Dates at one resolution, so they compare and join whatever unit the source used."""
    return pd.to_datetime(s).astype("datetime64[ns]")


def _extractions(x: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Extraction procedures on teeth 1-32, with numeric keys, dates and the diagnosis class."""
    pl = x["procedurelog"]
    ext = pl[pl["codenum"].isin(od.extraction_codenums(x))].copy()
    ext["patient_id"], ext["tooth_num"] = _num(ext["patnum"]), _num(ext["toothnum"])
    ext["procstatus"], ext["dx"] = _num(ext["procstatus"]), _num(ext["dx"]).fillna(0)
    ext = ext[ext["tooth_num"].between(1, 32)]
    for c in ("datetp", "datecomplete"):
        ext[c] = _date(ext[c])
    d = x["definition"][_num(x["definition"]["category"]) == od.DEFCAT_DIAGNOSIS]
    names = dict(zip(_num(d["defnum"]), d["itemname"]))
    ext["dx_class"] = ext["dx"].map(lambda v: od.DIAGNOSIS_LOOKUP.get(names.get(v, ""), "none")).astype(str)
    return ext


def _exam_teeth(x: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """One row per perio exam and charted tooth: deepest probing, worst CAL, bleeding share, mobility."""
    pm = x["periomeasure"].copy()
    pm["perioexamnum"], pm["tooth_num"], pm["sequencetype"] = (_num(pm["perioexamnum"]), _num(pm["inttooth"]),
                                                               _num(pm["sequencetype"]))
    sites = pm[od.SITE_VALUES].apply(_num).astype(float)
    key = ["perioexamnum", "tooth_num"]

    def seq(kind):
        m = pm["sequencetype"] == kind
        return pm.loc[m, key].join(sites[m]).drop_duplicates(key).set_index(key)

    probe, margin, bleed = seq(od.SEQ_PROBING), seq(od.SEQ_MARGIN), seq(od.SEQ_BLEEDING)
    out = pd.DataFrame({"max_pd": probe.max(axis=1)})
    cal = probe.add(margin.reindex(probe.index))
    out["max_cal"] = cal.max(axis=1)
    bled = (bleed.fillna(0).astype(int) & 1).astype(float).where(bleed.notna())
    out = out.join(pd.DataFrame({"bop_pct": 100 * bled.sum(axis=1) / bled.notna().sum(axis=1).replace(0, float("nan"))}),
                   how="outer")
    mob = pm[pm["sequencetype"] == od.SEQ_MOBILITY].drop_duplicates(key).set_index(key)["toothvalue"]
    out = out.join(_num(mob).dropna().astype(int).astype(str).rename("mobility"), how="outer")
    out = out.join(pd.DataFrame({"cal5_sites": (cal >= 5).sum(axis=1), "cal_sites": cal.notna().sum(axis=1),
                                 "bled_sites": bled.sum(axis=1), "bop_sites": bled.notna().sum(axis=1)}), how="left")
    return out.reset_index()


def _exams(x: dict[str, pd.DataFrame]) -> pd.DataFrame:
    e = x["perioexam"][["perioexamnum", "patnum", "examdate"]].copy()
    e["perioexamnum"], e["patient_id"] = _num(e["perioexamnum"]), _num(e["patnum"])
    e["examdate"] = _date(e["examdate"])
    return e.drop(columns="patnum").sort_values(["examdate", "perioexamnum"]).reset_index(drop=True)


def _neighbours(teeth: pd.DataFrame) -> pd.DataFrame:
    """Worst CAL on the teeth either side, in the same arch, at the same exam."""
    parts = []
    for step in (-1, 1):
        n = teeth[["perioexamnum", "tooth_num", "max_cal"]].copy()
        n["tooth_num"] = n["tooth_num"] + step
        same_arch = (n["tooth_num"] - 1) // 16 == (n["tooth_num"] - step - 1) // 16
        parts.append(n[same_arch & n["tooth_num"].between(1, 32)])
    both = pd.concat(parts).dropna(subset=["max_cal"])
    return both.groupby(["perioexamnum", "tooth_num"], as_index=False)["max_cal"].max().rename(
        columns={"max_cal": "neighbour_max_cal_mm"})


def _statuses(x: dict[str, pd.DataFrame], patients: pd.Series) -> pd.DataFrame:
    ext = _extractions(x)
    grid = pd.MultiIndex.from_product([sorted(patients), list(TEETH)], names=["patient_id", "tooth_num"])
    t = pd.DataFrame(index=grid).reset_index()
    t["tooth_status_code"], t["label_source_code"] = "present", "none"
    t["loss_date"] = t["event_date"] = pd.Series(pd.NaT, index=t.index, dtype="datetime64[ns]")
    t["dx_def_id"] = pd.Series(pd.NA, index=t.index, dtype="Int64")
    t = t.set_index(["patient_id", "tooth_num"])

    planned = ext[(ext["procstatus"] == od.PLANNED) & (ext["dx_class"] != "none")]
    planned = planned.sort_values(["datetp", "procnum"]).drop_duplicates(["patient_id", "tooth_num"])
    idx = pd.MultiIndex.from_frame(planned[["patient_id", "tooth_num"]])
    t.loc[idx, "tooth_status_code"] = ("planned_" + planned["dx_class"]).to_numpy()
    t.loc[idx, "label_source_code"] = "planned"
    t.loc[idx, "event_date"] = planned["datetp"].to_numpy()
    t.loc[idx, "dx_def_id"] = planned["dx"].astype("int64").to_numpy()

    ti = x["toothinitial"]
    entry = ti[_num(ti["initialtype"]) == 0]
    missing = set(zip(_num(entry["patnum"]), _num(entry["toothnum"])))
    elsewhere = ext[ext["procstatus"] == od.EXISTING_OTHER]
    missing |= set(zip(elsewhere["patient_id"], elsewhere["tooth_num"]))
    missing = [k for k in missing if k in t.index]
    t.loc[missing, ["tooth_status_code", "label_source_code"]] = ["missing_at_entry", "none"]
    t.loc[missing, "event_date"] = pd.NaT
    t.loc[missing, "dx_def_id"] = pd.NA

    done = ext[ext["procstatus"] == od.COMPLETE].sort_values(["datecomplete", "procnum"])
    done = done.drop_duplicates(["patient_id", "tooth_num"])
    idx = pd.MultiIndex.from_frame(done[["patient_id", "tooth_num"]])
    t.loc[idx, "tooth_status_code"] = ("extracted_" + done["dx_class"].replace("none", "no_dx")).to_numpy()
    t.loc[idx, "label_source_code"] = done["dx_class"].map(lambda c: "none" if c == "none" else "completed").to_numpy()
    t.loc[idx, "loss_date"] = t.loc[idx, "event_date"] = done["datecomplete"].to_numpy()
    t.loc[idx, "dx_def_id"] = done["dx"].astype("int64").where(done["dx"] != 0).astype("Int64").to_numpy()

    t = t.reset_index()
    label = t["tooth_status_code"].map({"extracted_perio": True, "planned_perio": True, "extracted_other": False,
                                        "planned_other": False})
    t["is_perio_loss"] = label.astype("boolean")
    return t


def _chart_quality_codes(x: dict[str, pd.DataFrame]) -> pd.Series:
    """Each perio exam's quality, worst first: copied, uniform, partial, else complete (open_dental.chart_quality)."""
    if x["perioexam"].empty:
        return pd.Series(dtype=object)
    q = od.chart_quality(x)
    code = pd.Series("complete", index=q.index)
    code[q["is_partial"]] = "partial"
    code[q["is_uniform"]] = "uniform"
    code[q["is_copied"]] = "copied"
    return pd.Series(code.to_numpy(), index=_num(q["perioexamnum"]).to_numpy())


def _readings(x: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Radiograph readings with a value (the simulated `radiograph_bone_level`), sorted for an as-of join."""
    r = x.get("radiograph_bone_level")
    if r is None or r.empty:
        r = pd.DataFrame({c: pd.Series(dtype=d) for c, d in (("document_id", "int64"), ("patient_id", "int64"),
                                                              ("tooth_num", "int64"), ("image_date", "datetime64[ns]"),
                                                              ("bone_loss_pct", "float64"))})
    r = r.dropna(subset=["bone_loss_pct"]).astype({"document_id": "int64", "patient_id": "int64",
                                                  "tooth_num": "int64", "bone_loss_pct": "float64"})
    r["image_date"] = _date(r["image_date"])
    return r[["document_id", "patient_id", "tooth_num", "image_date", "bone_loss_pct"]].sort_values("image_date")


def _patient_features(x: dict[str, pd.DataFrame], exams: pd.DataFrame, teeth: pd.DataFrame) -> pd.DataFrame:
    pat = x["patient"].copy()
    pat["patient_id"] = _num(pat["patnum"])
    first = exams.drop_duplicates("patient_id")[["patient_id", "perioexamnum", "examdate"]].rename(
        columns={"perioexamnum": "first_exam", "examdate": "first_exam_date"})
    pat = pat.merge(first, on="patient_id", how="left")
    born = _date(pat["birthdate"])
    on = pat["first_exam_date"].fillna(_date(pat["datefirstvisit"]))
    before_birthday = (on.dt.month < born.dt.month) | ((on.dt.month == born.dt.month) & (on.dt.day < born.dt.day))
    pat["age_at_first_exam_num"] = (on.dt.year - born.dt.year - before_birthday.astype(int)).astype("Int64")
    pat["is_smoker"] = pat["smokingsnomed"].astype(str).isin(SMOKER_SNOMED)
    dz = x["disease"].assign(diseasedefnum=_num(x["disease"]["diseasedefnum"])).merge(
        x["diseasedef"].assign(diseasedefnum=_num(x["diseasedef"]["diseasedefnum"])), on="diseasedefnum")
    diabetic = set(_num(dz.loc[dz["icd10code"].astype(str).str.startswith(DIABETES_ICD10), "patnum"]))
    pat["is_diabetic"] = pat["patient_id"].isin(diabetic)
    mouth = teeth.groupby("perioexamnum")[["cal5_sites", "cal_sites", "bled_sites", "bop_sites", "max_pd"]].agg(
        {"cal5_sites": "sum", "cal_sites": "sum", "bled_sites": "sum", "bop_sites": "sum", "max_pd": "max"})
    mouth["mouth_cal5_site_pct"] = 100 * mouth["cal5_sites"] / mouth["cal_sites"].replace(0, float("nan"))
    mouth["mouth_bop_pct"] = 100 * mouth["bled_sites"] / mouth["bop_sites"].replace(0, float("nan"))
    mouth = mouth.rename(columns={"max_pd": "mouth_max_pd_mm"})[["mouth_cal5_site_pct", "mouth_max_pd_mm",
                                                                 "mouth_bop_pct"]]
    pat = pat.merge(mouth, left_on="first_exam", right_index=True, how="left")
    return pat[["patient_id", "first_exam", "age_at_first_exam_num", "is_smoker", "is_diabetic",
                "mouth_cal5_site_pct", "mouth_max_pd_mm", "mouth_bop_pct"]]


@traced
def tooth_table(x: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """One row per patient and tooth 1-32: status, label, and features charted before the loss (module docstring)."""
    pats = _patient_features(x, exams := _exams(x), teeth := _exam_teeth(x))
    t = _statuses(x, pats["patient_id"])
    t = t.merge(pats, on="patient_id", how="left")

    # the reference exam: the last one on or before the event (present teeth: the last one at all)
    t["_ref"] = t["event_date"].fillna(_FAR_FUTURE)
    t["_order"] = range(len(t))
    t["patient_id"], t["tooth_num"] = t["patient_id"].astype("int64"), t["tooth_num"].astype("int64")
    t = pd.merge_asof(t.sort_values("_ref"), exams[["patient_id", "perioexamnum", "examdate"]],
                      left_on="_ref", right_on="examdate", by="patient_id", direction="backward").drop(columns="examdate")
    entry = t["tooth_status_code"] == "missing_at_entry"
    t.loc[entry, "perioexamnum"] = float("nan")

    # own measures: the last exam on or before the event that charted this tooth (charts are often partial, #385)
    own = teeth.merge(exams, on="perioexamnum").rename(columns={
        "examdate": "last_exam_date", "max_pd": "last_max_pd_mm", "max_cal": "last_max_cal_mm",
        "bop_pct": "last_bop_pct", "mobility": "last_mobility_code"})
    own["last_chart_quality_code"] = own["perioexamnum"].map(_chart_quality_codes(x))
    own = own.astype({"patient_id": "int64", "tooth_num": "int64"}).sort_values("last_exam_date")
    own_cols = ["last_exam_date", "last_max_pd_mm", "last_max_cal_mm", "last_bop_pct", "last_mobility_code",
                "last_chart_quality_code"]
    t = pd.merge_asof(t.sort_values("_ref"), own[["patient_id", "tooth_num", *own_cols]], left_on="_ref",
                      right_on="last_exam_date", by=["patient_id", "tooth_num"], direction="backward")
    t.loc[entry, own_cols] = None
    t["last_exam_date"] = t["last_exam_date"].astype("datetime64[ns]")

    # own radiographic bone loss: the last radiograph read on or before the event (a SIMULATED reading here)
    reads = _readings(x)
    t = pd.merge_asof(t.sort_values("_ref"), reads.rename(columns={"image_date": "last_radiograph_date",
                                                                    "bone_loss_pct": "last_rbl_pct"}),
                      left_on="_ref", right_on="last_radiograph_date", by=["patient_id", "tooth_num"],
                      direction="backward")
    t.loc[entry, ["last_rbl_pct", "last_radiograph_date"]] = [float("nan"), pd.NaT]
    first_doc = reads.sort_values(["image_date", "document_id"]).drop_duplicates("patient_id")[["document_id"]]
    mouth_rbl = reads.merge(first_doc, on="document_id").groupby("patient_id")["bone_loss_pct"].max()
    t["mouth_max_rbl_pct"] = t["patient_id"].map(mouth_rbl).astype("float64")
    # neighbours at the reference exam, or at the first exam for a tooth missing at entry
    t["_nexam"] = t["perioexamnum"].where(~entry, t["first_exam"])
    t = t.merge(_neighbours(teeth).rename(columns={"perioexamnum": "_nexam"}), on=["_nexam", "tooth_num"], how="left")

    t["teeth_missing_at_entry_count"] = t.groupby("patient_id")["tooth_status_code"].transform(
        lambda s: (s == "missing_at_entry").sum()).astype("int64")
    t["tooth_type_code"] = t["tooth_num"].map(_tooth_type)
    t = t.sort_values("_order").reset_index(drop=True)
    return t[COLUMNS]


@traced
def planned_extraction(x: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """One row per extraction that was ever on a treatment plan, with its plan copies counted once each."""
    ext = _extractions(x)
    ext = ext[ext["procstatus"].isin([od.PLANNED, od.COMPLETE])]
    tp = x["proctp"].assign(procnumorig=_num(x["proctp"]["procnumorig"]), datetp=_date(x["proctp"]["datetp"]))
    copies = tp.groupby("procnumorig").agg(plan_copy_count=("proctpnum", "size"), first_plan_date=("datetp", "min"),
                                           last_plan_date=("datetp", "max"))
    ext["procnum"] = _num(ext["procnum"])
    out = ext.merge(copies, left_on="procnum", right_index=True, how="inner")
    out = out.assign(procedure_id=out["procnum"].astype("int64"), is_completed=out["procstatus"] == od.COMPLETE,
                     dx_def_id=out["dx"].astype("int64").where(out["dx"] != 0).astype("Int64"),
                     complete_date=out["datecomplete"], plan_copy_count=out["plan_copy_count"].astype("int64"))
    out["patient_id"], out["tooth_num"] = out["patient_id"].astype("int64"), out["tooth_num"].astype("int64")
    return out[["procedure_id", "patient_id", "tooth_num", "dx_def_id", "plan_copy_count", "first_plan_date",
                "last_plan_date", "is_completed", "complete_date"]].sort_values("procedure_id").reset_index(drop=True)
