"""Eligible genes of `s3-data-v3` (ADR-0015 phase 1, step 1) and the cases per gene.

A gene is eligible when every entity the simulator can draw for it in gene-first mode (the
simulable entities with a positive `sim_weight` and a built profile, as `plan_genes` keeps them)
has a row in `onset-ages-v2` under the entity id or any of its profile ids, which is the
lookup the simulator uses (`OnsetAges.range_for((entity, *profile_ids))`). Requiring every
entity, not just one, is what guarantees that no case of the gene falls back to an Orphanet
category. The genes with only some entities listed are counted and left out.

Needs the pinned simulator on PYTHONPATH (read-only), only to reuse `plan_genes` and the onset
reader. Usage:
  PYTHONPATH=src:<sim>/src .venv/bin/python scripts/s3_v3_eligible_genes.py <profiles-full.jsonl>
"""

import json
import math
import sys
from pathlib import Path

from rare_disease_simulator.data_sources.gene_profiles import (
    plan_genes,
    read_gene_profiles,
    read_gnn_genes,
)
from rare_disease_simulator.simulation.reporting import load_onset_ages

from diagnostic_ar_training import DATA_DIR
from diagnostic_ar_training.lineage.hashing import sha256_file
from diagnostic_ar_training.lineage.manifest import fetch_outputs, load_manifest

TARGET_CASES = 10_000
OUT_DIR = DATA_DIR / "s3"
GNN_GENES = DATA_DIR / "interim/genphenia-v3.0/checkpoints/graphens_best_model/genes.json"


def artifact_file(artifact: str, name: str) -> Path:
    return next(p for p in fetch_outputs(load_manifest(artifact)) if p.name == name)


def main(profiles_path: Path) -> None:
    genes_path = artifact_file("genes-v2", "genes.json.gz")
    onset_path = artifact_file("onset-ages-v2", "onset-ages.tsv")
    onsets = load_onset_ages(onset_path)
    profile_ids = {json.loads(line)["disease_id"] for line in profiles_path.open(encoding="utf-8")}
    plan = plan_genes(read_gene_profiles(genes_path), read_gnn_genes(GNN_GENES), profile_ids)

    eligible, partial, none_listed = [], [], []
    eligible_entities = set()
    for target in plan.targets:
        covered = [onsets.range_for((o.entity, *o.profile_ids)) is not None for o in target.entities]
        if all(covered):
            eligible.append(target.symbol)
            eligible_entities.update(o.entity for o in target.entities)
        elif any(covered):
            partial.append(target.symbol)
        else:
            none_listed.append(target.symbol)
    per_gene = math.ceil(TARGET_CASES / len(eligible))

    OUT_DIR.mkdir(exist_ok=True)
    genes_file = OUT_DIR / "s3-v3-eligible-genes.txt"
    genes_file.write_text("".join(f"{g}\n" for g in sorted(eligible)))
    summary = {
        "rule": "every drawable entity of the gene has an onset-ages-v2 row (entity id or any profile id)",
        "simulated_genes_in_plan": len(plan.targets),
        "eligible_genes": len(eligible),
        "eligible_entities": len(eligible_entities),
        "genes_with_only_some_entities_listed (excluded)": len(partial),
        "genes_with_no_entity_listed": len(none_listed),
        "target_cases": TARGET_CASES,
        "cases_per_gene": per_gene,
        "expected_cases": per_gene * len(eligible),
        "inputs": {
            "profiles_sha256": sha256_file(profiles_path),
            "genes_v2_sha256": sha256_file(genes_path),
            "onset_ages_v2_sha256": sha256_file(onset_path),
        },
        "gene_list_sha256": sha256_file(genes_file),
    }
    (OUT_DIR / "s3-v3-eligible-genes.summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
