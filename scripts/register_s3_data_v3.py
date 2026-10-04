"""Register `s3-data-v3`, the S3 v3 evaluation patients (ADR-0015 phase 1), and publish it as a release asset.

The simulator outputs are read from `rare-disease-simulator/outputs/s3v3/`. The rich-cases file was
deleted after validation and export; its sha256 is in `cases.jsonl.sha256`.

Usage: PYTHONPATH=src .venv/bin/python scripts/register_s3_data_v2.py
"""

import json
import shutil
from pathlib import Path

from diagnostic_ar_training import DATA_DIR, INTERIM_DIR
from diagnostic_ar_training.lineage.gitinfo import code_state
from diagnostic_ar_training.lineage.hashing import sha256_file
from diagnostic_ar_training.lineage.manifest import (
    build_manifest,
    ensure_new,
    load_manifest,
    publish,
    write_manifest,
)
from diagnostic_ar_training.lineage.registry import LineageError

ARTIFACT = "s3-data-v3"
SIM_OUT = Path("/home/mate/FIUBA/trabajo-profesional/rare-disease-simulator/outputs/s3v3")
STEM = "s3-sim0.5.4-full-n84-s4004"
SIM_ARCHIVE_SHA = "4664812d146ade15f7004cf069e963cb8778f4313f0007608b3becda46794433"
SIM_ARCHIVE = Path("/home/mate/FIUBA/trabajo-profesional/sim-pins/sim-cfc20da.tar.gz")
ELIGIBLE_GENES = DATA_DIR / "s3" / "s3-v3-eligible-genes.txt"


def artifact_input(artifact: str, name: str) -> dict:
    out = next(o for o in load_manifest(artifact).outputs if Path(o.path).name == name)
    return {"id": f"artifact:{artifact}", "sha256": out.sha256}


def main() -> None:
    ensure_new(ARTIFACT)
    state = code_state()
    if state.dirty:
        raise LineageError("commit before producing artifacts")
    if sha256_file(SIM_ARCHIVE) != SIM_ARCHIVE_SHA:
        raise LineageError("the pinned simulator archive changed")
    card = json.loads((SIM_OUT / f"{STEM}.card.json").read_text())
    export = SIM_OUT / f"{STEM}.jsonl.gz"
    if card["file"]["sha256"] != sha256_file(export):
        raise LineageError("the export does not match its dataset card")
    run_summary = SIM_OUT / "run.summary.json"
    if card["inputs"]["run_summary"]["sha256"] != sha256_file(run_summary):
        raise LineageError("the run summary does not match the dataset card")
    profiles_summary = json.loads((SIM_OUT / "profiles-full.summary.json").read_text())
    if profiles_summary["output"]["sha256"] != sha256_file(SIM_OUT / "profiles-full.jsonl"):
        raise LineageError("the profiles do not match their build summary")
    stats = json.loads((SIM_OUT / "rich-stats.json").read_text())
    if stats["counts"].get("literature") != stats["cases"]:
        raise LineageError("not every case used a literature onset age")
    rich_sha = (SIM_OUT / "cases.jsonl.sha256").read_text().split()[0]

    out_dir = INTERIM_DIR / "datasets" / ARTIFACT
    out_dir.mkdir(parents=True, exist_ok=True)
    outputs = []
    for src, name in (
        (export, f"{STEM}.jsonl.gz"),
        (SIM_OUT / f"{STEM}.card.json", f"{STEM}.card.json"),
        (SIM_OUT / "rich-stats.json", "rich-stats.json"),
    ):
        shutil.copyfile(src, out_dir / name)
        outputs.append(out_dir / name)

    inputs = [
        artifact_input("simcal-s3-v2", "simcal-s3-v2.json"),
        artifact_input("genes-v2", "genes.json.gz"),
        artifact_input("hpoa-enriched-v2", "phenotype.hpoa"),
        artifact_input("annot-split-v2", "heldout.tsv"),
        artifact_input("onset-ages-v2", "onset-ages.tsv"),
        artifact_input("presentation-ages-v2", "presentation-ages.tsv"),
        {"id": "file:data/s3/s3-v3-eligible-genes.txt", "sha256": sha256_file(ELIGIBLE_GENES)},
        {"id": "simulator-archive:rare-disease-simulator@cfc20da", "sha256": SIM_ARCHIVE_SHA},
        {
            "id": "simulator-profiles:full (build summary)",
            "sha256": sha256_file(SIM_OUT / "profiles-full.summary.json"),
        },
        {"id": "simulator-profiles:full", "sha256": sha256_file(SIM_OUT / "profiles-full.jsonl")},
        {"id": "simulator-run-summary", "sha256": sha256_file(run_summary)},
        {"id": "simulator-rich-cases (deleted after export)", "sha256": rich_sha},
    ]
    params = {
        "generator": "rare-disease-simulator@cfc20da (git archive)",
        "simulator_version": "0.5.4",
        "profiles": "full (A+B) from hpoa-enriched-v2, r1-v1 heldout mask",
        "mode": "gene-first, restricted to the genes whose every drawable entity has an onset-ages-v2 row",
        "cases_per_gene": 84,
        "difficulty": "medium",
        "seed": 4004,
        "simulator_split_ignored": True,
        "role": "S3 v3 evaluation only; never trained on",
        "cases": stats["cases"],
        "genes": stats["genes"],
        "onset_age_source": {k: v for k, v in stats["counts"].items() if k in ("literature", "category")},
        "sex": {k: v for k, v in stats["counts"].items() if k.startswith("sex_")},
        "invariant_violations": 0,
    }
    manifest = build_manifest(ARTIFACT, "simulated-eval-dataset", inputs, params, outputs, state=state)
    manifest = publish(manifest, ARTIFACT)
    write_manifest(manifest)
    print(json.dumps(params, indent=1))


if __name__ == "__main__":
    main()
