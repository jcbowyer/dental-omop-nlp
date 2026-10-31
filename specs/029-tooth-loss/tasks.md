# Tasks: tooth lost to periodontitis (spec 029)

Implementation starts after this spec, plan and tasks are reviewed.

## US1 #369: synthetic extract in Open Dental's table format, own bronze schema

- [x] T001 [US1] Check each table and column in plan.md against Open Dental's source schema ([research.md](research.md));
  `TABLES` is written from it in T003
- [x] T001a #377 Spec, plan and research follow how Open Dental records diagnoses (the practice's own lists,
  changing over time) and treatment plans (one planned procedure, many editable copies)
- [x] T002 [US1] Failing tests: `test_open_dental.py` (seed, unchanged datasets, sources, no truth in the
  extract, rates recovered)
- [x] T003 [US1] `open_dental.py` generator, own random stream; writes the extract and `tooth_loss_truth.csv`;
  two diagnosis lists with an adoption date and lag; planned extractions with their plan copies
- [x] T004 [US1] `<layer>_opendental_perio` schemas and the landing volume in `schemas.py` and
  `unity_catalog.yml`; failing schema and bundle tests first (`fact_tooth_loss_prediction` goes in `gold_model.py`
  with the model, T010)

## US2 #370: one silver row per patient and tooth

- [x] T005 [US2] Failing tests: statuses on hand-built extracts, nothing dated after the loss
- [x] T006 [US2] `tooth_loss.tooth_table` and `planned_extraction` (plan copies counted once); base-R twin and
  parity inputs
- [ ] T006a [US2] Failing tests, then the bronze-to-silver data-quality checks after Kookal et al. 2024
  (completeness, accuracy, consistency; FR-009), with planted faults the generator records
- [x] T007 [US2] Load job `open_dental_load` (`12_load_open_dental.py`): generates the extract into the landing
  volume, bronze as generated, silver cleaned (`open_dental.clean`) plus the answer key; overwrite per run, batch
  keys; deploy starts it when bronze is empty. The silver tooth table joins it with T006

## US3 #371: the model, checked against the hidden truth

- [ ] T008 [US3] Failing tests: feature sets, grouped stratified split, metrics, expected-count stage rule
- [ ] T009 [US3] Logistic regression and XGBoost on both label sets (completed; completed and planned); scores,
  calibration and stage recount; R twins for metrics and the stage rule
- [ ] T010 [US3] `docs/tooth_loss.md`, results labelled synthetic; gold `fact_tooth_loss_prediction`
- [ ] T011 Full test suite, `ruff`, R parity; review file for each implementation PR

## US4 #379: ERDs of the Open Dental silver tables and an OMOP alternative

- [x] T012 [US4] Failing tests (`test_silver_erd.py`), then `opendental_silver_model.py`, `omop_silver_model.py` and
  `silver_erd.py`, using `gold_erd.py`'s writer (gold output unchanged); entity and full `.drawio`, `.mmd`, PNGs and
  `diagrams/silver/data_model.md`
- [x] T013 [US4] A third format, the data dictionary (`dictionary_erd.py`, `table_profile.py`): subject areas, fact
  and dimension tables, row counts, each column's nulls, distinct and top values, PHI and open questions marked;
  it fills in once T003 writes the extract

## US5 #381: the rest of a typical research extract

- [x] T014 [US5] The 16 further Open Dental tables in research.md (checked in the source), the silver model and the
  three ERDs, in the reference's subject areas; free text marked PHI
- [x] T015 [US5] The generator (T003) and the load job (T007) write them too

## US6 #385: the synthetic extract is as messy as real practice records

- [x] T016 [US6] Failing tests (`test_open_dental.py`), then the generator's mess rates (charts not done, partial,
  copied, uniform, out of range, charted after loss), radiograph procedures and `document` rows, and the simulated
  `radiograph_bone_level` reading; `realism_profile`; research.md, the silver model and the ERDs
- [x] T017 [US6] Failing tests (`test_tooth_loss.py`), then `last_rbl_pct` and the last chart's quality in the tooth
  table; the load job writes `radiograph_bone_level`
