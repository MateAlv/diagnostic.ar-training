"""Eligible genes of `s3-data-v3` (ADR-0015 phase 1, step 1) and the cases per gene.

A gene is eligible when every entity the simulator can draw for it in gene-first mode (the
simulable entities with a positive `sim_weight` and a built profile, as `plan_genes` keeps them)
has a row in `onset-ages-v2` under the entity id or any of its profile ids, which is the
lookup the simulator uses (`OnsetAges.range_for((entity, *profile_ids))`). Requiring every
entity, not just one, is what guarantees that no case of the gene falls back to an Orphanet
category. The genes with only some entities listed are counted and left out.

Needs the pinned simulator on PYTHONPATH (read-only), only to reuse `plan_genes` and the onset
reader. Usage:
  PYTHONPATH=src:<sim>/src .venv/bin/python scripts/s3_v3_eligible_genes.py <profiles-full.jsonl> \
      [all|any] [target cases] [name]
`all` (default) is the s3-v3 rule; `any` (a gene is eligible when at least one entity is listed) is
the s3-v3b rule: such genes can also draw entities without a row, so the primary analysis keeps only
the cases whose `metadata.onset_age_source` is "literature".
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

OUT_DIR = DATA_DIR / "s3"
GNN_GENES = DATA_DIR / "interim/genphenia-v3.0/checkpoints/graphens_best_model/genes.json"


def artifact_file(artifact: str, name: str) -> Path:
    return next(p for p in fetch_outputs(load_manifest(artifact)) if p.name == name)


def main(profiles_path: Path, rule: str = "all", target_cases: int = 10_000, name: str = "s3-v3") -> None:
    genes_path = artifact_file("genes-v2", "genes.json.gz")
    onset_path = artifact_file("onset-ages-v2", "onset-ages.tsv")
    onsets = load_onset_ages(onset_path)
    profile_ids = {json.loads(line)["disease_id"] for line in profiles_path.open(encoding="utf-8")}
    plan = plan_genes(read_gene_profiles(genes_path), read_gnn_genes(GNN_GENES), profile_ids)

    eligible, partial, none_listed = [], [], []
    eligible_entities, listed_entities = set(), set()
    for target in plan.targets:
        covered = [onsets.range_for((o.entity, *o.profile_ids)) is not None for o in target.entities]
        if all(covered) or (rule == "any" and any(covered)):
            eligible.append(target.symbol)
            eligible_entities.update(o.entity for o in target.entities)
            listed_entities.update(o.entity for o, c in zip(target.entities, covered, strict=True) if c)
            if not all(covered):
                partial.append(target.symbol)
        elif any(covered):
            partial.append(target.symbol)
        else:
            none_listed.append(target.symbol)
    per_gene = math.ceil(target_cases / len(eligible))

    OUT_DIR.mkdir(exist_ok=True)
    genes_file = OUT_DIR / f"{name}-eligible-genes.txt"
    genes_file.write_text("".join(f"{g}\n" for g in sorted(eligible)))
    summary = {
        "rule": (
            "every drawable entity of the gene has an onset-ages-v2 row (entity id or any profile id)"
            if rule == "all"
            else "at least one drawable entity of the gene has an onset-ages-v2 row (entity or profile id)"
        ),
        "simulated_genes_in_plan": len(plan.targets),
        "eligible_genes": len(eligible),
        "eligible_entities": len(eligible_entities),
        "eligible_entities_with_an_onset_row": len(listed_entities),
        "genes_with_only_some_entities_listed": len(partial),
        "partial_genes_eligible": rule == "any",
        "genes_with_no_entity_listed": len(none_listed),
        "target_cases": target_cases,
        "cases_per_gene": per_gene,
        "expected_cases": per_gene * len(eligible),
        "inputs": {
            "profiles_sha256": sha256_file(profiles_path),
            "genes_v2_sha256": sha256_file(genes_path),
            "onset_ages_v2_sha256": sha256_file(onset_path),
        },
        "gene_list_sha256": sha256_file(genes_file),
    }
    (OUT_DIR / f"{name}-eligible-genes.summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    args = sys.argv[1:]
    main(Path(args[0]), *(args[1:2] or ["all"]), *(int(a) for a in args[2:3]), *args[3:4])
