"""EXP-P-003 addendum (descriptive, train only): the r1-v1 train patients an ft bundle harms vs E0, compared
with those `ft-v1-c1-lin-all-ens` harmed, and, for each one the new bundle still harms, the features that
lower the patient's own gene (w_k · c_k on the true gene; harm can only come from that gene being lowered
more than the genes it falls behind).

Reads the ranks files of the two ensemble evaluations and E0's train ranks (EXP-P-001), the r1-v1 train
patients, both knowledge artifacts' X-linked flags, and the new bundle. No dev, test or vault patient.

Usage: python scripts/analysis/ft_v11_train_harmed.py ft-v1.1-<config>-ens
"""

import json
import math
import sys

import numpy as np

from diagnostic_ar_training import RESULTS_DIR, SPLITS_DIR
from diagnostic_ar_training.ft.bundle import FEATURES, FtResidual, Knowledge, load
from diagnostic_ar_training.ft.system import case_inputs
from diagnostic_ar_training.lineage import manifest
from diagnostic_ar_training.lineage.gitinfo import code_state
from diagnostic_ar_training.lineage.hashing import sha256_file
from diagnostic_ar_training.lineage.registry import Purpose
from diagnostic_ar_training.rerank import kb as kb_io
from diagnostic_ar_training.splits import load_part
from diagnostic_ar_training.systems.genphenia_v3 import GenPheniaV3

EXP = "EXP-P-003"
OLD = "ft-v1-c1-lin-all-ens"
E0_RANKS = RESULTS_DIR / "EXP-P-001" / "r1-v1-train__E0__all.ranks.jsonl"


def ranks(path) -> dict[str, float]:
    with open(path) as f:
        rows = [json.loads(line) for line in f]
    return {r["case_id"]: math.inf if r["rank"] in (None, "inf") else float(r["rank"]) for r in rows}


def output(artifact_id: str, name: str):
    m = manifest.load_manifest(artifact_id)
    if problems := manifest.verify_outputs(m):
        raise SystemExit("; ".join(problems))
    return next(manifest.output_path(o) for o in m.outputs if o.path.endswith(name))


def main(new_id: str) -> None:
    artifact_id = f"results-{EXP}-{new_id}-train-harmed"
    manifest.ensure_new(artifact_id)
    state = code_state()
    if state.dirty:
        raise SystemExit("commit your code first")
    e0 = ranks(E0_RANKS)
    old_path = RESULTS_DIR / EXP / OLD / "r1-v1-train.ranks.jsonl"
    new_path = RESULTS_DIR / EXP / new_id / "r1-v1-train.ranks.jsonl"
    old, new = ranks(old_path), ranks(new_path)
    old_harmed = {c for c in e0 if old[c] > e0[c]}
    new_harmed = {c for c in e0 if new[c] > e0[c]}

    bundle_path = output(new_id, "ft-v1-bundle.json")
    bundle = load(bundle_path)
    kb_path = output(bundle["kb_id"], "ft-kb.json.gz")
    kb = kb_io.read(kb_path)
    xlr_v1 = {g for g, r in kb_io.read(output("ft-kb-all-v1", "ft-kb.json.gz"))["genes"].items() if r.get("xlr_only")}
    base = GenPheniaV3()
    knowledge = Knowledge(kb, base.genes, (base.inputs.emb_index, base.inputs.vectors), bundle["kb_id"])
    residual = FtResidual(bundle, knowledge)
    index = {g: i for i, g in enumerate(base.genes)}
    cases = {c.case_id: c for c in load_part("r1-v1", "train", Purpose.TRAIN)}

    def describe(cid: str) -> dict:
        case = cases[cid]
        gene = case.gene.upper()
        row = {
            "case_id": cid,
            "gene": gene,
            "sex": case.sex.value,
            "age_years": case.age_years,
            "onset_years": case.onset_years,
            "n_excluded": len(case.excluded),
            "rank_e0": e0[cid],
            "rank_ft_v1": old[cid],
            "rank_new": new[cid],
            "gene_xlr_only_ft_kb_v1": gene in xlr_v1,
            "gene_xlr_only_ft_kb_v2": bool(kb["genes"].get(gene, {}).get("xlr_only")),
        }
        if cid in new_harmed and gene in index:
            inputs = case_inputs(case)
            w = residual.weights(inputs).mean(axis=0)
            c = knowledge.features(inputs)[:, index[gene]].astype(np.float64)
            row["true_gene_contributions"] = {
                f: round(float(w[k] * c[k]), 4) for k, f in enumerate(FEATURES) if w[k] * c[k] != 0
            }
        return row

    old_rows = [describe(c) for c in sorted(old_harmed)]
    females_v1 = [r for r in old_rows if r["sex"] == "female" and r["gene_xlr_only_ft_kb_v1"]]
    out = {
        "new": new_id,
        "old": OLD,
        "train_cases": len(e0),
        "old_harmed": len(old_harmed),
        "new_harmed": len(new_harmed),
        "old_harmed_no_longer_harmed": len(old_harmed - new_harmed),
        "still_harmed": len(old_harmed & new_harmed),
        "newly_harmed": len(new_harmed - old_harmed),
        "old_harmed_female_gene_xlr_only_v1": len(females_v1),
        "of_which_gene_xlr_only_v2": sum(r["gene_xlr_only_ft_kb_v2"] for r in females_v1),
        "patients_new_harmed": [describe(c) for c in sorted(new_harmed)],
        "patients_old_harmed_only": [describe(c) for c in sorted(old_harmed - new_harmed)],
    }
    path = RESULTS_DIR / EXP / f"{new_id}-train-harmed.json"
    path.write_text(json.dumps(out, indent=1) + "\n")
    inputs = [
        {"id": f"ranks:{OLD}/train", "sha256": sha256_file(old_path)},
        {"id": f"ranks:{new_id}/train", "sha256": sha256_file(new_path)},
        {"id": "ranks:EXP-P-001/E0/train", "sha256": sha256_file(E0_RANKS)},
        {"id": f"artifact:{new_id}", "sha256": sha256_file(bundle_path)},
        {"id": f"artifact:{bundle['kb_id']}", "sha256": sha256_file(kb_path)},
        {"id": "split:r1-v1", "sha256": sha256_file(SPLITS_DIR / "r1-v1.json")},
        *base.lineage_inputs(),
    ]
    params = {"exp": EXP, "new": new_id, "old": OLD, "script": "scripts/analysis/ft_v11_train_harmed.py"}
    manifest.write_manifest(
        manifest.build_manifest(artifact_id, "ft-train-harmed", inputs, params, [path], state=state)
    )
    summary = {k: v for k, v in out.items() if not k.startswith("patients")}
    print(json.dumps(summary, indent=1))
    for r in out["patients_new_harmed"]:
        print(
            r["case_id"], r["gene"], r["sex"], r["rank_e0"], "->", r["rank_new"],
            r.get("true_gene_contributions"),
        )


if __name__ == "__main__":
    main(sys.argv[1])
