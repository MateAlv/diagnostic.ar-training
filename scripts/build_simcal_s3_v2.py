"""Build `simcal-s3-v2`: candidate 6's calibration (`simcal-v053-v1`) with a sex prior measured on R1-train.

Only R1-train patients are read (ADR-0014). The male share of each simulator sex-prior class is the
Jeffreys-smoothed share among R1-train patients with known sex; a class with fewer than 20 such
patients keeps the simulator default, and the two classes whose sex the genetics fix (male- and
female-limited) keep theirs too, because a share below 1 or above 0 would draw patients the
simulator's own validator rejects. Every decision is recorded in `_provenance`.

Usage: PYTHONPATH=src .venv/bin/python scripts/build_simcal_s3_v2.py
"""

import csv
import gzip
import json
from pathlib import Path

from diagnostic_ar_training import DATA_DIR, SPLITS_DIR, splits
from diagnostic_ar_training.knowledge import sex_prior
from diagnostic_ar_training.lineage.gitinfo import code_state
from diagnostic_ar_training.lineage.hashing import sha256_file
from diagnostic_ar_training.lineage.manifest import (
    build_manifest,
    ensure_new,
    fetch_outputs,
    load_manifest,
    write_manifest,
)
from diagnostic_ar_training.lineage.registry import LineageError, Purpose, load_sources, open_source
from diagnostic_ar_training.ontology import Ontology

ARTIFACT = "simcal-s3-v2"
BASE = DATA_DIR / "calib" / "simcal-v053-v1.json"


def profile_inheritance(hpoa: Path, ontology: Ontology) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    with hpoa.open(encoding="utf-8", newline="") as handle:
        rows = csv.DictReader((line for line in handle if not line.startswith("#")), delimiter="\t")
        for row in rows:
            if row["aspect"] == "I" and row["qualifier"] != "NOT":
                term = ontology.resolve(row["hpo_id"])
                if term and ontology.is_a(term, "HP:0000005"):
                    out.setdefault(row["database_id"], set()).add(term)
    return out


def main() -> None:
    ensure_new(ARTIFACT)
    state = code_state()
    if state.dirty:
        raise LineageError("commit before producing artifacts")
    ontology = Ontology.from_json(open_source("hpo_ontology", Purpose.KB))
    genes_manifest = load_manifest("genes-v2")
    genes_path = next(p for p in fetch_outputs(genes_manifest) if p.name == "genes.json.gz")
    with gzip.open(genes_path, "rt", encoding="utf-8") as handle:
        genes = json.load(handle)["genes"]
    hpoa_manifest = load_manifest("hpoa-enriched-v2")
    hpoa = next(p for p in fetch_outputs(hpoa_manifest) if p.name == "phenotype.hpoa")
    train = splits.load_part("r1-v1", splits.Part.TRAIN, Purpose.TRAIN)
    result = sex_prior.measure(train, genes, profile_inheritance(hpoa, ontology), ontology)

    base = json.loads(BASE.read_text())
    table = {}
    for key in sex_prior.CLASSES:
        male, female = result["mass"][key]["male"], result["mass"][key]["female"]
        n = male + female
        row = {
            "patients": round(n, 3),
            "male": round(male, 3),
            "raw_male_share": round(male / n, 4) if n else None,
            "jeffreys_male_share": round(sex_prior.jeffreys_male_share(male, n), 4),
            "simulator_default": sex_prior.SIMULATOR_DEFAULTS[key],
        }
        if key in sex_prior.FIXED_BY_DEFINITION:
            row["used"], row["decision"] = row["simulator_default"], "kept default: sex fixed by the class"
        elif n < sex_prior.MIN_PATIENTS:
            row["used"], row["decision"] = (
                row["simulator_default"],
                f"kept default: fewer than {sex_prior.MIN_PATIENTS} patients",
            )
        else:
            row["used"], row["decision"] = row["jeffreys_male_share"], "measured (Jeffreys)"
        table[key] = row

    calibration = {k: v for k, v in base.items() if k != "_provenance"}
    for key, row in table.items():
        calibration[f"sex.p_male.{key}"] = row["used"]
    calibration["_provenance"] = {
        "artifact": ARTIFACT,
        "base": {"id": "file:data/calib/simcal-v053-v1.json", "sha256": sha256_file(BASE)},
        "base_provenance": base.get("_provenance"),
        "sex_prior": {
            "source": "R1-train patients with known sex (r1-v1 train only)",
            "unit": "male share per simulator sex_key class; patient's entity from genes-v2",
            "entity_rule": "entity of the patient diagnosis, else sim_weight-weighted",
            "class_rule": "simulator 0.5.4 entity_sex_prior_key; hpoa-enriched-v2",
            "estimator": "Jeffreys, (male + 0.5) / (n + 1)",
            "min_patients": sex_prior.MIN_PATIENTS,
            "patients": result["patients"],
            "table": table,
        },
    }
    out = DATA_DIR / "calib" / f"{ARTIFACT}.json"
    out.write_text(json.dumps(calibration, indent=1, sort_keys=True) + "\n")

    inputs = [
        {"id": "file:data/calib/simcal-v053-v1.json", "sha256": sha256_file(BASE)},
        {"id": "split:r1-v1", "sha256": sha256_file(SPLITS_DIR / "r1-v1.json")},
        {"id": "artifact:genes-v2", "sha256": sha256_file(genes_path)},
        {"id": "artifact:hpoa-enriched-v2", "sha256": sha256_file(hpoa)},
        load_sources()["hpo_ontology"].as_input(),
    ]
    params = {
        "base": "simcal-v053-v1",
        "part": "train",
        "min_patients": sex_prior.MIN_PATIENTS,
        "estimator": "jeffreys",
        "fixed_by_definition": list(sex_prior.FIXED_BY_DEFINITION),
        "table": table,
    }
    write_manifest(build_manifest(ARTIFACT, "simulator-calibration-file", inputs, params, [out], state=state))
    print(json.dumps({"patients": result["patients"], "table": table}, indent=1))


if __name__ == "__main__":
    main()
