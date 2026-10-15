"""EXP-V-002's declared post-read readings, from the committed vault ranks only (the vault is not reopened).

- a bootstrap over gene clusters (publications that share a gene are not independent);
- Δ split by whether the gene has real patients in folds 0-3 (unswapped);
- Δ by vault source: `p2-v1` test (EXP-P-005's patients), `p2-v1` vault and `p2-fresh-v1` (EXP-P-006's);
- E0 parity: our E0 ranks against Phase 2's E0 rank files for the same patients;
- the drop from CONFIRM to the vault.
Writes results/P3/EXP-V-002/post_read.json.
"""

import json
from collections import Counter
from pathlib import Path

import numpy as np

from diagnostic_ar_training import RESULTS_DIR
from diagnostic_ar_training.v4 import patients, report

EXP_DIR = RESULTS_DIR / "P3" / "EXP-V-002"
SYSTEMS = {"F1": "p3-addon-v1-all", "F2": "network"}
STRATA = ("uncited", "cited")
PHASE2_E0 = {
    "EXP-P-005": RESULTS_DIR / "EXP-P-005" / "p2-v1-test-ft-v1.1-c1-lin-all-ens" / "E0.ranks.jsonl",
    "EXP-P-006": RESULTS_DIR / "EXP-P-006" / "final-check" / "p2-v1+p2-fresh-v1-vault__E0__all.ranks.jsonl",
}


def ranks(name: str) -> list[dict]:
    return report.read_ranks(EXP_DIR / "ranks" / f"{name}.ranks.jsonl")


def summary(new: list[dict], base: list[dict]) -> dict:
    by_id = {r["case_id"]: r for r in base}
    x = report.stratum_summary(new, [by_id[r["case_id"]] for r in new])
    keys = ("n", "n_groups", "mrr_cap", "helped", "harmed", "delta_mrr_cap_ci95")
    return {k: x[k] for k in keys} | {
        "e0_mrr_cap": x["e0"]["mrr_cap"],
        "delta_mrr_cap": x["delta"]["mrr_cap"],
    }


def gene_cluster_ci(new: list[dict], base: list[dict]) -> dict:
    """Δ capped MRR and its 95% CI, resampling genes (with all their publications), not publications."""
    by_id = {r["case_id"]: r["rank"] for r in base}
    w = report.cap_weights([r["group"] for r in new])
    d = np.array([1 / r["rank"] - 1 / by_id[r["case_id"]] for r in new])
    _, inv = np.unique([r["gene"].upper() for r in new], return_inverse=True)
    num, den = np.bincount(inv, weights=w * d), np.bincount(inv, weights=w)
    rng = np.random.default_rng(report.BOOTSTRAP["seed"])
    picks = rng.integers(0, num.size, size=(report.BOOTSTRAP["n_resamples"], num.size))
    deltas = num[picks].sum(axis=1) / den[picks].sum(axis=1)
    return {
        "n_genes": int(num.size),
        "delta_mrr_cap": float(num.sum() / den.sum()),
        "ci95": [float(x) for x in np.percentile(deltas, [2.5, 97.5])],
    }


def sources() -> dict[str, str]:
    """case id -> vault source, from the Phase 2 rank files' patients."""
    out = {}
    for line in PHASE2_E0["EXP-P-005"].read_text().splitlines():
        out[json.loads(line)["case_id"]] = "p2-v1 test"
    for line in PHASE2_E0["EXP-P-006"].read_text().splitlines():
        r = json.loads(line)
        out[r["case_id"]] = "p2-fresh-v1" if r["group"].startswith("p2-fresh-v1:") else "p2-v1 vault"
    return out


def e0_parity(e0: list[dict]) -> dict:
    theirs = {}
    for path in PHASE2_E0.values():
        for line in path.read_text().splitlines():
            r = json.loads(line)
            theirs[r["case_id"]] = float(r["rank"])
    pairs = [(r["rank"], theirs[r["case_id"]]) for r in e0 if r["case_id"] in theirs]
    finite = [(a, b) for a, b in pairs if np.isfinite(a) and np.isfinite(b)]
    return {
        "n_ours": len(e0),
        "n_matched": len(pairs),
        "equal": sum(a == b for a, b in pairs),
        "both_finite": len(finite),
        "finite_equal": sum(a == b for a, b in finite),
        "inf_mismatch": sum(np.isfinite(a) != np.isfinite(b) for a, b in pairs),
        "max_abs_diff_finite": float(max((abs(a - b) for a, b in finite), default=0.0)),
    }


def main() -> None:
    e0 = ranks("E0")
    recs = {k: ranks(v) for k, v in SYSTEMS.items()}
    training = {p.case.gene.upper() for p in patients.load_folds((0, 1, 2, 3))}
    source = sources()
    out = {"gene_cluster": {}, "by_training_gene": {}, "by_source": {}}
    for k, new in recs.items():
        for s in STRATA:
            sub = [r for r in new if s in r["strata"]]
            out["gene_cluster"][f"{k} {s}"] = gene_cluster_ci(sub, e0)
            for label, keep in (("with training patients", True), ("without", False)):
                part = [r for r in sub if (r["gene"].upper() in training) == keep]
                out["by_training_gene"][f"{k} {s} gene {label}"] = summary(part, e0)
            for src in sorted(set(source.values())):
                part = [r for r in sub if source.get(r["case_id"]) == src]
                if part:
                    out["by_source"][f"{k} {s} {src}"] = summary(part, e0)
    out["sources"] = dict(Counter(source.get(r["case_id"], "unknown") for r in e0))
    out["e0_parity_with_phase2"] = e0_parity(e0)
    confirm = json.loads((RESULTS_DIR / "P3" / "addon" / "confirm.json").read_text())
    vault = json.loads((EXP_DIR / "vault.json").read_text())
    c = confirm["p3-addon-v1-all"]["vs_e0"]["uncited"]["delta"]["mrr_cap"]
    v = vault["gate"]["F1"]["delta"]
    out["confirm_to_vault"] = {"confirm_F1_uncited": c, "vault_F1_uncited": v, "drop": c - v}
    path = EXP_DIR / "post_read.json"
    Path(path).write_text(json.dumps(out, indent=1, default=float) + "\n")
    for section in ("gene_cluster", "by_training_gene", "by_source"):
        for name, x in out[section].items():
            ci = x.get("delta_mrr_cap_ci95") or x["ci95"]
            n = x.get("n", x.get("n_genes"))
            print(f"{section:16} {name:44} n {n:5} Δ {x['delta_mrr_cap']:+.4f} [{ci[0]:+.4f}, {ci[1]:+.4f}]")
    print("sources", out["sources"])
    print("e0 parity", out["e0_parity_with_phase2"])
    print("confirm -> vault", out["confirm_to_vault"])


if __name__ == "__main__":
    main()
