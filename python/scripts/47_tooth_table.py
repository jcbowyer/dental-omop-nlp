"""The tooth table on a small seeded synthetic Open Dental extract (spec 029 US2, #370).

    python scripts/47_tooth_table.py [--patients 200] [--seed 42]

Builds the extract (open_dental.build), cleans it as silver (open_dental.clean) and derives one row per patient and
tooth (tooth_loss.tooth_table) and one per planned extraction (tooth_loss.planned_extraction). Writes
data/datasets/tooth_loss/: the Open Dental columns the status rules read (procedurelog, procedurecode, definition,
toothinitial, proctp, patient), patient_tooth.csv and planned_extraction.csv. r/tests/test_parity.R recomputes the
statuses and plan-copy counts from the same inputs in base R. Synthetic data only; the answer key is not written here.
"""

import argparse

from health_transformation_lab_nlp import open_dental, telemetry, tooth_loss
from health_transformation_lab_nlp.paths import DATASETS_DIR

ap = argparse.ArgumentParser()
ap.add_argument("--patients", type=int, default=200)
ap.add_argument("--seed", type=int, default=42)
args = ap.parse_args()

telemetry.setup()
telemetry.start_script("47_tooth_table", data_label="synthetic")
tables, _, readings = open_dental.build_with_readings(open_dental.Params(n_patients=args.patients), seed=args.seed)
x = {**open_dental.clean(tables), "radiograph_bone_level": readings}   # the reading is SIMULATED (#385)
out = DATASETS_DIR / "tooth_loss"
out.mkdir(parents=True, exist_ok=True)

INPUTS = {"procedurelog": ["procnum", "patnum", "procstatus", "codenum", "toothnum", "dx", "datetp", "datecomplete"],
          "procedurecode": ["codenum", "proccode"], "definition": ["defnum", "category", "itemname"],
          "toothinitial": ["patnum", "toothnum", "initialtype"], "proctp": ["proctpnum", "procnumorig", "datetp"],
          "patient": ["patnum"]}
for name, cols in INPUTS.items():
    x[name][cols].to_csv(out / f"{name}.csv", index=False)
teeth = tooth_loss.tooth_table(x)
teeth.to_csv(out / "patient_tooth.csv", index=False)
tooth_loss.planned_extraction(x).to_csv(out / "planned_extraction.csv", index=False)

print(f"SYNTHETIC extract: {args.patients} patients, seed {args.seed}")
print(open_dental.realism_profile(tables, readings).round(3).to_string(index=False))
print(teeth["tooth_status_code"].value_counts().to_string())
