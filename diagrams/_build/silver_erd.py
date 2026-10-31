"""opendental_silver_model.py and omop_silver_model.py -> their ERDs, drawn by gold_erd.py's writer (spec 029, #379).
Writes   ../silver/source/{opendental,omop}_silver_{entity,full}.{mmd,drawio}
         ../silver/source/{opendental,omop}_silver_dictionary.drawio   the data-dictionary format (dictionary_erd.py),
             profiled from the seeded synthetic extract the load job writes (open_dental.py, spec 029)
         ../silver/data_model.md   both models as Mermaid (GitHub renders them) and every column
Run: python3 silver_erd.py   (then render: render.md)
"""
from pathlib import Path

import dictionary_erd
import gold_erd
import omop_silver_model
import opendental_silver_model

OUT = Path(__file__).resolve().parent.parent / "silver"
SRC = OUT / "source"
MODELS = [("opendental_silver", opendental_silver_model), ("omop_silver", omop_silver_model)]
TITLES = {
    "opendental_silver": ("Open Dental silver: `health_transformation_lab.silver_opendental_perio`",
                          ("The cleaned Open Dental tables spec 029 reads, with Open Dental's own names lowercased "
                          "([research](../../specs/029-tooth-loss/research.md)), the tables derived from them, and the "
                          "evaluation-only answer key. Dashed lines are matches, not keys: `proctp.dx` is text matched "
                          "to a diagnosis by name, and a planned procedure's copies point back with `procnumorig`.")),
    "omop_silver": ("OMOP silver: an alternative, not built",
                    ("The same data mapped to OMOP CDM 5.4 and the repo's dental extension "
                    "([`omop/ddl/dental_extension.sql`](../../omop/ddl/dental_extension.sql)). Each column says which "
                    "Open Dental column fills it (←). `not_mapped` lists what the CDM can't hold, which is why spec 029 "
                    "keeps silver in Open Dental's shape.")),
}


def extract_stats():
    """Profile the silver tables the load job writes: the seeded synthetic extract (open_dental.build with the job's
    seed and size), cleaned as silver (open_dental.clean), the tooth tables derived from it (tooth_loss) and its answer
    key. The data-quality table doesn't exist yet, so the dictionary says it isn't measured."""
    from health_transformation_lab_nlp import open_dental, tooth_loss

    import table_profile
    tables, truth, readings = open_dental.build_with_readings(open_dental.Params(), seed=42)
    frames = open_dental.clean(tables)
    frames["radiograph_bone_level"] = readings
    frames["patient_tooth"] = tooth_loss.tooth_table(frames)
    frames["planned_extraction"] = tooth_loss.planned_extraction(frames)
    frames["tooth_loss_truth"] = truth
    return table_profile.profile(frames)


def markdown() -> str:
    lines = ["# Silver data models (spec 029)", "",
             ("Generated from [`_build/opendental_silver_model.py`](../_build/opendental_silver_model.py) and "
              "[`_build/omop_silver_model.py`](../_build/omop_silver_model.py) by `_build/silver_erd.py`, with the "
              "gold ERDs' writer; `python/tests/test_silver_erd.py` checks them. Keys are logical. The draw.io and "
              "Mermaid sources are in `source/`. Synthetic data only."), ""]
    for prefix, m in MODELS:
        title, intro = TITLES[prefix]
        lines += [f"## {title}", "", intro, "",
                  (f"Draw.io: [entity](source/{prefix}_entity.drawio) · [full](source/{prefix}_full.drawio) · "
                   f"[data dictionary](source/{prefix}_dictionary.drawio) (subject areas, row counts, nulls, distinct "
                   "and top values)"), "",
                  "```mermaid", gold_erd.mermaid(False, m).rstrip(), "```", ""]
        for name, t in m.TABLES.items():
            lines += [f"### `{name}`", "", f"{t.description}. {t.writer}.", "",
                      "| Key | Column | Type | Description |", "|---|---|---|---|"]
            lines += [f"| {c.key} | `{c.name}` | {c.type} | {c.description} |" for c in t.columns]
            lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    SRC.mkdir(parents=True, exist_ok=True)
    for prefix, m in MODELS:
        names = list(m.TABLES)
        edges = [(r.parent, r.child) for r in m.RELATIONSHIPS if r.parent != r.child]
        grid = gold_erd.arrange(names, edges, {n: gold_erd.full_size(n, m) for n in names})
        for stem, full in ((f"{prefix}_entity", False), (f"{prefix}_full", True)):
            (SRC / f"{stem}.mmd").write_text(gold_erd.mermaid(full, m))
            (SRC / f"{stem}.drawio").write_text(gold_erd.build(grid, full, m).xml(stem))
            print("wrote", f"diagrams/silver/source/{stem}.drawio, .mmd")
    for prefix, m in MODELS:
        print("wrote", dictionary_erd.write(prefix, m, extract_stats() if prefix == "opendental_silver" else None))
    (OUT / "data_model.md").write_text(markdown())
    print("wrote diagrams/silver/data_model.md")
