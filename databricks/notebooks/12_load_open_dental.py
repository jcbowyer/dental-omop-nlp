# Databricks notebook source
# MAGIC %md
# MAGIC # Load the synthetic Open Dental extract (spec 029 T007; #369, #370, #381)
# MAGIC
# MAGIC Generates the seeded synthetic extract (`open_dental.write`) into the landing volume, then loads it:
# MAGIC - **bronze** (`bronze_opendental_perio`): every Open Dental table as generated, one table each;
# MAGIC - **silver** (`silver_opendental_perio`): the same tables read the way Open Dental means them
# MAGIC   (`open_dental.clean`: -1 is null, gingival margins of 100+ are negative), the tooth tables derived from
# MAGIC   them (`tooth_loss.tooth_table` → `patient_tooth`, `tooth_loss.planned_extraction` → `planned_extraction`), the
# MAGIC   SIMULATED radiograph reading `radiograph_bone_level` (Open Dental stores none),
# MAGIC   and the answer key `tooth_loss_truth`, which only the evaluation reads.
# MAGIC
# MAGIC Every table is overwritten per run (idempotent) and keeps Open Dental's columns only. Each run appends one
# MAGIC row per table written to `silver_opendental_perio.load_log`, with `run_id`, `run_ts` and `git_commit_sha`.
# MAGIC The same seed gives the same rows. Synthetic data only. Serverless CPU is enough.

# COMMAND ----------

# MAGIC %pip install -q -e ../../python

# COMMAND ----------

dbutils.library.restartPython()  # noqa: F821

# COMMAND ----------

import time
from pathlib import Path

import pandas as pd

from health_transformation_lab_nlp import open_dental, tooth_loss
from health_transformation_lab_nlp import tracking as _tracking

dbutils.widgets.text("git_commit", "")  # noqa: F821  set by the job: the commit it was deployed from
_tracking.use_git_commit(dbutils)  # noqa: F821
dbutils.widgets.text("run_id", "")  # noqa: F821  the job run ({{job.run_id}}): every retry shares it
dbutils.widgets.text("od_catalog", "health_transformation_lab")  # noqa: F821
dbutils.widgets.text("bronze_schema", "bronze_opendental_perio")  # noqa: F821
dbutils.widgets.text("silver_schema", "silver_opendental_perio")  # noqa: F821
dbutils.widgets.text("landing_dir", "/Volumes/health_transformation_lab/landing_opendental_perio/data")  # noqa: F821
dbutils.widgets.text("seed", "42")  # noqa: F821
dbutils.widgets.text("n_patients", "2000")  # noqa: F821

w = dbutils.widgets.get  # noqa: F821
git_commit = w("git_commit") or "unknown"
run_id = w("run_id") or f"manual-{time.strftime('%Y%m%dT%H%M%S')}"
catalog, bronze, silver, landing = w("od_catalog"), w("bronze_schema"), w("silver_schema"), w("landing_dir")
seed, params = int(w("seed")), open_dental.Params(n_patients=int(w("n_patients")))
# a bad setting fails before any work (AGENTS.md "Configuration and secrets")
for name, value in (("od_catalog", catalog), ("bronze_schema", bronze), ("silver_schema", silver)):
    if not value or not value.replace("_", "").isalnum():
        raise ValueError(f"{name} is not a plain name: {value!r}")
if not landing.startswith("/Volumes/"):
    raise ValueError(f"landing_dir must be a Unity Catalog volume path, not {landing!r}")
print(f"run {run_id} · commit {git_commit} · seed {seed} · {params.n_patients} patients")

# COMMAND ----------

# Generate into the landing volume: the extract in one folder, the answer key in another
counts = open_dental.write(Path(landing) / "extract", Path(landing) / "answer_key", params, seed)
print(counts)

# COMMAND ----------

run_ts = pd.Timestamp.now(tz="UTC").tz_localize(None)


def save(df: pd.DataFrame, schema: str, name: str, mode: str = "overwrite") -> None:
    """Write the table as it is: Open Dental's columns only. Its run is recorded in load_log."""
    sdf = spark.createDataFrame(df.astype({c: "string" for c in df.columns if df[c].dtype == object}))  # noqa: F821
    sdf.write.mode(mode).option("overwriteSchema", "true").saveAsTable(f"{catalog}.{schema}.{name}")
    print(f"{catalog}.{schema}.{name}: {len(df):,} rows")


tables, truth, readings = open_dental.build_with_readings(params, seed)
clean = open_dental.clean(tables)
# the SIMULATED radiograph reading (#385; Open Dental stores none), then the derived tooth tables (spec 029 US2): one
# row per patient and tooth, and one per planned extraction
clean_read = {**clean, "radiograph_bone_level": readings}
silver_tables = {**clean, "radiograph_bone_level": readings, "patient_tooth": tooth_loss.tooth_table(clean_read),
                 "planned_extraction": tooth_loss.planned_extraction(clean), "tooth_loss_truth": truth}
print(open_dental.realism_profile(tables, readings).to_string(index=False))
for name, df in tables.items():
    save(df, bronze, name)
for name, df in silver_tables.items():
    save(df, silver, name)

# COMMAND ----------

# The batch key (AGENTS.md "Failures, retries and reruns"): one row per table written, appended per run. Every table
# above is overwritten whole, so all its rows belong to the run logged last for it.
log = open_dental.load_log({bronze: tables, silver: silver_tables}, run_id=run_id, run_ts=run_ts,
                           git_commit_sha=git_commit, seed=seed, n_patients=params.n_patients)
save(log, silver, "load_log", mode="append")
