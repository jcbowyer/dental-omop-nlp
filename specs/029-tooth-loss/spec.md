# Feature Specification: was a missing tooth lost to periodontitis? A tooth-level model on an Open Dental-shaped extract

**Feature Branch**: `spec/369-029-tooth-loss`

**Created**: 2026-10-30

**Status**: draft

**Input**: "Focus on predicting tooth loss. We need a separate bronze and silver database using the Open Dental
database format." A tooth-level binary model (logistic regression or XGBoost): did this tooth get lost because of
periodontitis? It is trained on extractions with a periodontal diagnosis attached, then applied to teeth already
missing with no diagnosis. No OMOP, no NLP.

**Clarified** (2026-10-31, the owner): the unit is the tooth. For each tooth: lost to periodontitis, yes or no.
That per-tooth answer feeds the count that separates stage III from IV, and so the person-level classification.
How Open Dental records it changes the design (#377):
- a dental procedure's diagnosis comes from the practice's own diagnosis list (`procedurelog.Dx` → `definition`),
  not from ICD-10, which appears only on medical claims;
- that list changes when a practice adopts the 2017 classification, and adoption can take a while;
- planned extractions (treatment plans) are a second source of labelled teeth, since a planned extraction may
  never be completed in the record;
- a planned procedure is copied into every saved plan, so its copies must be counted once and checked against
  the original;
- silver stays close to Open Dental; a common model (OMOP) comes later, and loses tooth detail.

> Personal learning project; synthetic data; public sources only (`DISCLAIMER.md`). The extract only follows the
> *shape* of Open Dental's published database schema (opendental.com documentation). No practice's data, extract,
> code lists or plans come into this repo; every row is generated here and labelled synthetic.

## Why

Stage III and stage IV periodontitis (2017 AAP/EFP; Tonetti, Greenwell & Kornman 2018) are told apart by teeth
lost to periodontitis: 1–4 teeth lost points to III, 5 or more to IV (`docs/staging_grading.md`). A dental
record rarely says why a tooth is gone:
- an extraction done in the practice may carry a diagnosis;
- a tooth that was already missing at the first exam carries none.

So the count stage IV needs is unknown for most patients. The repo's stage rules currently either count only
recorded losses (`teeth_lost_perio`) or count every missing tooth (`all_missing_perio`). Neither is right.

A model trained on extractions with a recorded diagnosis can estimate, for each tooth missing without one, the
chance it was lost to periodontitis. On real records nobody can check that estimate. On synthetic records,
where `sites.draw_mouth` (spec 006) already knows why each tooth is missing, it can be checked. That is what
this benchmark adds.

## User Scenarios & Testing

### User Story 1 - A synthetic extract in Open Dental's table format, in its own bronze schema (Priority: P1) #369

A seeded generator writes the tables a practice-management extract would hold, using Open Dental's table and
column names, lowercased:
- patients;
- procedures (code, tooth, status, date, attached diagnosis), completed and planned;
- the procedure-code list;
- treatment plans, and the planned procedures copied into each saved plan;
- perio exams and their measures;
- teeth recorded missing at the first exam;
- the diagnosis definitions;
- medical problems;
- and the rest of a typical research extract (#381): providers, appointments, medications, allergies, exam
  forms and their answers, vitals, race and ethnicity, places of care, procedure notes, tobacco assessments,
  practice-defined patient fields and the SNOMED codes they use.

The CSV files land in the `data` volume of `landing_opendental_perio`, and are loaded as is, one table per
Open Dental table, into `bronze_opendental_perio`.

It is built from the existing synthetic people and mouths, so every missing tooth has a known reason, `perio`
or `other`. That truth is written only to a separate answer-key table, never into the extract.

**Why this priority**: everything else reads it.

**Independent Test**: build with a fixed seed twice and get identical files. Every table and column has a named
source in Open Dental's published schema. The answer key covers every missing tooth. No column in the extract
reveals the reason a tooth is missing, except a recorded diagnosis.

**Acceptance Scenarios**:

1. **Given** the default seed, **When** the extract is built, **Then** each person has:
   - a first perio exam whose missing teeth are listed as missing, with no reason;
   - later visits, some with completed extractions.
2. **Given** an extraction of a tooth truly lost to periodontitis, **When** its diagnosis is drawn, **Then** it
   is a periodontal item from the practice's diagnosis list in use on that date (the older list before the
   practice adopts the 2017 classification, the newer after, with a lag) at the declared rate. Otherwise it is
   another item (a recording mismatch) or none. Each rate and date is a named parameter.
3. **Given** the existing study datasets, **When** this extract is built, **Then** they are byte-identical. The
   extract uses its own random stream and its own files.
4. **Given** an extraction a dentist plans at an exam, **When** the extract is built, **Then** it is one
   `procedurelog` row with `ProcStatus` 1 (planned), copied into each plan saved that day (one or more) and into
   the plans saved at later exams until it is completed or the record ends. Some planned extractions are never
   completed in the record; the share is a named parameter.

---

### User Story 2 - One silver row per patient and tooth (Priority: P1) #370

`silver_opendental_perio` holds one row per patient and tooth (universal numbering 1–32), next to the cleaned
Open Dental tables it is built from.

Each row has a status:
- present at the last exam;
- extracted with a periodontal diagnosis;
- extracted with another diagnosis;
- extracted with no diagnosis;
- missing at the first exam;
- planned for extraction with a periodontal diagnosis, not completed in the record;
- planned for extraction with another diagnosis, not completed in the record.

A planned extraction that is later completed counts once, as completed.

It also has the features charted **before** the tooth was lost:
- the tooth's own last probing depth, attachment loss, bleeding, mobility and furcation, where an exam came
  before the loss;
- the same for its neighbours on both sides;
- mouth-level measures from the first exam: the share of sites with CAL ≥ 5 mm, maximum PD, bleeding, and how
  many teeth are already missing;
- tooth type (incisor, canine, premolar, molar; upper or lower);
- age at the first exam;
- smoking and diabetes from the medical problems.

**Why this priority**: the model, the label rules and the stage recount all read this table.

**Independent Test**:
- Hand-built extracts give the expected status for each case.
- The R twin gives the same statuses.
- No feature uses anything dated after the tooth's loss.

**Acceptance Scenarios**:

1. **Given** a tooth listed missing at the first exam with no later procedure, **Then** its status is "missing
   at the first exam", and it has no own measures.
2. **Given** an extraction with a periodontal diagnosis on day 400, after exams on days 0 and 200, **Then**
   only the day-200 exam's measures are its own last measures.
3. **Given** the parity inputs, **When** `r/tests/test_parity.R` runs, **Then** the statuses match exactly.
4. **Given** one planned extraction copied into three plans at one exam and two more six months later, and never
   completed, **Then** the tooth has one row, status "planned, not completed", and the plan copies are counted
   (five) but not repeated.

---

### User Story 3 - The tooth-level model, checked against the hidden truth (Priority: P1) #371

A binary model, P(lost to periodontitis), is trained on teeth extracted with a recorded diagnosis:
- periodontal diagnosis = 1;
- other diagnosis = 0.

It is trained on two label sets (FR-010): completed extractions only, and completed plus planned extractions.
The second has more teeth but weaker labels, since a plan states an intention, not what happened.

It is fitted twice, as logistic regression and as XGBoost, split 70/30 by patient with a fixed seed.

It is applied to teeth missing at the first exam and to teeth extracted without a diagnosis. Those teeth have no
own measures, so the applied model uses only features both groups have: neighbours, the mouth, the tooth's type
and the patient. A second model fitted with the tooth's own measures is reported beside it, to show what those
measures add where they exist.

Each patient's stage is then recounted with the expected number of teeth lost to periodontitis, as an
alternative `stage4_rule`.

**Why this priority**: it is the model the request asks for, and the synthetic truth is what makes it checkable.

**Independent Test**: one script run with a fixed seed writes these scores, all labelled synthetic:
- the held-out scores on extracted teeth;
- the scores on the missing-at-entry teeth against the answer key;
- a table of stage III vs IV under each counting rule.

**Acceptance Scenarios**:

1. **Given** the held-out extracted teeth, **Then** AUC, Brier score, sensitivity and specificity at the
   chosen threshold, and a calibration table (10 bins) are reported.
2. **Given** the missing-at-entry teeth, **Then** the same metrics are reported against the answer key, and the
   gap between the two shows how well training on extractions carries over to teeth that were never extracted
   in the record.
3. **Given** each counting rule for stage IV, the counts compared are:
   - recorded only;
   - every missing tooth;
   - expected from the model;
   - the truth.

   **Then** the number of patients called III and IV under each is compared with the truth.
4. **Given** the two label sets, **Then** both models are scored on the same held-out teeth and the same
   missing-at-entry teeth, so what the planned extractions add (or cost) is measured.

### User Story 4 - ERDs of the Open Dental silver tables and an OMOP alternative (Priority: P2) #379

Draw.io ERDs, generated from declarations like the gold ERDs (`diagrams/silver/`):
- **Open Dental silver:** the cleaned Open Dental tables with their own names, the derived tables and the answer
  key, with the source's quirks drawn as lines (`procedurelog.dx` a key into `definition`; `proctp` copies back to
  `procedurelog` by `procnumorig`; `proctp.dx` matched by name, not a key);
- **Data dictionary:** the same tables grouped in subject areas, fact and dimension headers, each table's row
  count and grain, and each column's nulls, distinct and top values from the data, with PHI columns and open
  questions marked;
- **OMOP silver (not built):** the same data in OMOP CDM 5.4 and the dental extension, each column naming its Open
  Dental source, and a list of what the CDM can't hold.

**Why this priority**: it is how the source shape is learned, and how keeping silver in Open Dental's shape is
weighed against a common model.

**Independent Test**: every Open Dental column in the declaration is in [research.md](research.md); every
relationship joins declared columns; every OMOP column names its source; the generated files are current.

### User Story 6 - The synthetic extract is as messy as real practice records (Priority: P1) #385

Real records are incomplete. Many visits have no full perio chart, some charts are partial or of poor quality, and
radiographs are often what's left to judge bone loss. A model that does well on a clean synthetic extract would do
worse on a real one, so the generator makes the same mess, at named rates:
- **charts not done:** a visit gets a full perio chart at a named rate, lower at mobile and nursing-home sites;
- **partial charts:** some teeth only; buccal sites only; no gingival margin (so no CAL); no bleeding;
- **poor readings:** a chart copied forward from the last one; every site the same depth; an out-of-range
  value; a tooth charted after its extraction;
- **radiographs:** full-mouth, bitewing and panoramic procedures, each with an Open Dental `document` row
  (`ImgType` 1, Radiograph; `ToothNumbers`). Open Dental doesn't store bone loss as a number, so a separate,
  **simulated** reading (`radiograph_bone_level`: bone loss % per tooth on the image, sometimes not read) stands
  in for a radiograph-reading tool. It's a derived silver table, never an Open Dental one.

`realism_profile(tables)` measures the same rates from any extract in this format, as counts and shares only. The
parameters can be set from a real extract's profile without moving any of its rows. The tooth table gains the
tooth's last radiograph bone loss before the loss and the quality of its last chart (complete, partial, copied,
uniform), so the model can learn when to trust which.

**Why this priority**: the model's results only mean something if the data is as hard as the real thing.

**Independent Test**:
- The profile of a generated extract matches the declared rates.
- Setting every mess rate to zero gives back complete charts.
- Every `document` row has its radiograph procedure.
- Readings exist only for documents.

**Acceptance Scenarios**:

1. **Given** the default parameters, **When** `realism_profile` runs on a generated extract, **Then** each
   measured rate is within sampling error of its parameter.
2. **Given** a visit without a perio chart, **Then** the tooth table takes that tooth's own measures from the last
   charted exam before it, and records which exam that was.
3. **Given** a radiograph before the loss with a reading for the tooth, **Then** `last_rbl_pct` is that reading;
   with none, it is null and the tooth still has a row.

### Edge Cases

- **Third molars:** they are often missing for other reasons (the synthetic mouths already treat them so), so
  they are excluded from the label and the stage count by default. This is a parameter, and the repo's choice,
  not a rule cited to the classification.
- **A tooth extracted twice in the record (a data error) or extracted after being listed missing:** it is
  counted once, at its first loss, and flagged.
- **A patient with no exam before an extraction:** the tooth has no own measures; its neighbours' and the
  mouth's come from the first exam after.
- **Classes are imbalanced** (most extractions in the synthetic set may be periodontal): rates are parameters,
  and the metrics include ones that don't depend on prevalence (AUC) and ones that do (Brier).
- **A planned extraction's tooth later listed missing** with no completed extraction (done elsewhere, or lost
  otherwise): the plan's diagnosis is its label, flagged "planned, outcome elsewhere".
- **A diagnosis from the older list after the practice switched**, or the newer list before: both lists are
  mapped, and the use is counted by a data-quality check, not rejected.
- **The answer key** is never a model feature. A test fails if any feature column can be traced to it.

## Requirements

### Functional Requirements

- **FR-001** `python/health_transformation_lab_nlp/open_dental.py` declares the extract's tables and columns once
  (`TABLES`), each with its Open Dental source:
  `patient`, `procedurelog`, `procedurecode`, `treatplan`, `proctp`, `perioexam`, `periomeasure`, `toothinitial`,
  `definition`, `disease`, `diseasedef`, `clinic`; and (#381) `provider`, `appointment`, `medication`,
  `medicationpat`, `allergy`, `allergydef`, `sheet`, `sheetfield`, `vitalsign`, `patientrace`, `cdcrec`, `site`,
  `procnote`, `ehrmeasureevent`, `patfield`, `snomed`. Only Open Dental's own columns: an extract's research ID,
  day counts, copied insurance types and age stay out, and so does Open Dental's `language` table (screen
  translations).
  - Only the columns this spec needs are included.
  - Names are checked against Open Dental's published schema documentation before implementation (T001).
  - Extractions use public CDT procedure codes (D7140, D7210).
  - Diagnoses are items in the practice's own list (`definition`, category Diagnosis), joined from
    `procedurelog.Dx`. The generator invents two synthetic lists: one before the 2017 classification and one
    after it, each with short codes and names for periodontal and other reasons (caries, fracture, orthodontic,
    other). They are invented here and are not any practice's list.
  - `DiagnosticCode` (ICD-10-CM, for medical claims) is filled on a small, named share of procedures only, so the
    model never depends on it.
- **FR-002** The generator draws a timeline per synthetic person: a first exam, then later visits, with
  extractions dated between exams. It uses its own seeded stream (`random.Random(f"{seed}:open_dental")`), so
  existing outputs don't change. Shares and rates are named parameters with fixed defaults:
  - teeth missing at entry vs extracted during the record;
  - extractions with a periodontal diagnosis, another diagnosis or none;
  - recording mismatches;
  - the date the practice adopts the 2017 list, and how long both lists stay in use;
  - planned extractions: how many plans are saved per exam, how often a planned extraction is re-planned at the
    next exam, and the share never completed in the record.
- **FR-003** The answer key (`tooth_loss_truth`: patient, tooth, true reason) is written apart from the extract,
  and only the evaluation reads it.
- **FR-004** New schema family `opendental_perio` in `schemas.py`, named like the old
  `<layer>_dental_omop_perio` schemas with the format changed: `landing_opendental_perio`,
  `bronze_opendental_perio`, `silver_opendental_perio`, `gold_opendental_perio`.
  - landing holds the CSV files, in the managed volume `data`;
  - bronze holds Open Dental's tables as is, one table each, with Open Dental's names (`patient`,
    `procedurelog`, `periomeasure`, ...);
  - silver holds the same tables cleaned, with the same names and layout: types enforced, -1 read as not
    measured, gingival margins of 100 and up decoded as negative, CAL computed, bleeding decoded from its bit,
    diagnoses mapped from either practice list to periodontal / other / none by a declared lookup (a parameter,
    since every practice's list differs), and each row flagged by the data-quality checks (FR-009). Next to them, the tooth
    table, following AGENTS.md naming (`tooth_status_code`, `is_perio_loss`, `last_max_pd_mm`, ...), and
    `planned_extraction`, one row per planned `procedurelog` extraction with
    how many plan copies carry it, the first and last plan dates and whether it was completed; and
    `tooth_loss_dq_check`, one row per check and run;
  - gold holds only the model's answers (`fact_tooth_loss_prediction`).

  Declared in `databricks/resources/unity_catalog.yml` and `diagrams/_build/gold_model.py`. Same names in
  every target.
- **FR-005** The tooth-status rules and the stage recount (expected teeth lost) are label rules: they get base-R
  twins, checked by `r/tests/test_parity.R`. Model fitting stays Python only.
- **FR-006** Metrics (AUC, Brier, sensitivity, specificity, calibration bins) get base-R twins too. If spec
  023's `class_metrics` has landed, the binary case reuses it.
- **FR-007** Writes are idempotent (overwrite by run, or delete-then-append by `run_id`). The Open Dental tables
  keep Open Dental's columns only; each run appends one row per table written to `silver_opendental_perio.load_log`
  with `run_id`, `run_ts` and `git_commit_sha`. The derived tables are logged the same way (#370), except
  `tooth_loss_dq_check`, which carries `run_id` on every row.
- **FR-008** No OMOP mapping, no note text, no language models anywhere in this bench.
- **FR-010** Two training label sets, each with its own fitted models:
  - **completed:** extractions with `ProcStatus` 2 and a mapped diagnosis;
  - **completed and planned:** plus planned extractions (`ProcStatus` 1) with a mapped diagnosis, one per
    `procedurelog` row however many plan copies carry it. A tooth with both counts once, as completed.
- **FR-009** Data-quality checks run between the bronze extract and the silver tooth table. They follow
  Kookal et al. 2024 (references item 57; NIH Collaboratory framework), so a real extract in the same format would
  get the same checks. Each check reports a number, and failures are flagged, never silently fixed:
  - **completeness:** every declared column present and none extra; types and value sets as declared; one value
    per field; the null/unknown/missing share per column and overall; duplicate rows; duplicate keys (patient,
    tooth, procedure); rows missing any value the tooth table needs;
  - **accuracy:** values outside known ranges (probing depth, CAL, mobility 0–3, tooth numbers 1–32, dates in
    order); procedure codes not in the CDT list; diagnosis items not in either declared practice list; ICD codes,
    where present, not valid ICD-10-CM;
  - **plan copies against the original:** `proctp` rows whose `ProcNumOrig` has no `procedurelog` row, and copies
    whose `ProcCode`, `ToothNumTP` or `Dx` text differs from the original procedure's code, tooth or diagnosis
    item (the copies are text saved with the plan and can be edited);
  - **list in use:** diagnosis items from the older list after the switch date, and from the newer list before
    it;
  - **consistency:** the null/unknown/missing share per office (clinic), against the mean of all offices, with
    offices beyond 2 SD flagged.

  The synthetic generator plants a known number of each kind of fault, at named rates, so each check is tested
  against what it should find. Results go to a silver `tooth_loss_dq_check` table (one row per check and run).

### Key Entities

- **Extract tables** (bronze): Open Dental's table and column names, lowercased.
- **Data-quality check** (silver): check × run: domain, check number (after Kookal et al. 2024), count found,
  share, flagged.
- **Tooth** (silver): patient × tooth number: status, loss date, features before the loss.
- **Planned extraction** (silver): one planned `procedurelog` row: tooth, diagnosis item, plan-copy count, first
  and last plan dates, completed or not.
- **Truth** (silver, evaluation only): patient × tooth: true reason.
- **Prediction** (gold): patient × tooth × model × run: probability, label at threshold.

## Success Criteria

- **SC-001** A rebuild with the default seed is identical, and the existing datasets are unchanged.
- **SC-002** Every extract column names its Open Dental source table and column.
- **SC-003** The model's scores on the held-out extractions and on the missing-at-entry teeth are both reported,
  labelled synthetic.
- **SC-004** The stage III/IV comparison shows each counting rule against the truth.
- **SC-005** R parity covers the tooth statuses, the expected-count stage rule and the metrics.
- **SC-006** Every planted fault is found by its check, and the clean rows pass every check.
- **SC-008** The realism profile of a generated extract matches its declared rates, and the model's scores are
  reported at the default (messy) rates and with every mess rate at zero, so the cost of messy records is shown.
- **SC-007** Both label sets are scored on the same held-out and missing-at-entry teeth, and every planned
  extraction counts once however many plan copies carry it.

## Assumptions

- "Open Dental format" means the shape of its published schema: table and column names, keys, how procedures
  carry a tooth number and a diagnosis. It does not mean a runnable Open Dental database.
- Gold is added only for the model's answers, following the repo's layer rules. Bronze and silver hold
  everything else.
- The diagnosis lists, the adoption date and lag, and the planning rates are invented parameters with fixed
  defaults, not observations of any practice.
- The synthetic mouths of spec 006 are the source of truth. Their loss process (`draw_mouth`) is reused, not
  changed.

## Out of scope

- Any real extract, or any specific practice's codes, workflows or plans.
- OMOP in the pipeline, notes, NLP, LLMs, agents. Diagrams of the silver tables and of how they would map to
  OMOP CDM 5.4 (what a common model keeps and loses) are a separate, follow-up issue.
- Predicting future tooth loss. This is about why a tooth already lost was lost.
