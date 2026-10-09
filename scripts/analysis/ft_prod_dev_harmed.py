"""ft-v1.1-prod on r1-v1 dev (descriptive, not a claim): the patients it or the evaluated bundle harms vs E0.

For each one: the features that lower the patient's own gene under each knowledge (ft-kb-prod-v1 and
ft-kb-all-v2), and for `neg_obligate` the obligate phenotypes the excluded terms contradict, with the
phenotype.hpoa rows (frequency, references) behind them, and whether a reference is the patient's own paper.

The production knowledge includes the dev papers, so a dev patient can be penalised by an annotation curated
from their own publication. Reads r1-v1 dev only. Writes data/ft/ft-v1.1-prod/dev-harmed.json with a
manifest.

Usage: python scripts/analysis/ft_prod_dev_harmed.py
"""

import csv
import json

from diagnostic_ar_training import DATA_DIR, SPLITS_DIR
from diagnostic_ar_training.eval.metrics import rank_of
from diagnostic_ar_training.ft.bundle import FEATURES, FtResidual, Knowledge, load, softmax64
from diagnostic_ar_training.ft.system import E0Logits, case_inputs
from diagnostic_ar_training.lineage import manifest
from diagnostic_ar_training.lineage.gitinfo import code_state
from diagnostic_ar_training.lineage.hashing import sha256_file
from diagnostic_ar_training.lineage.registry import Purpose, load_sources, open_source
from diagnostic_ar_training.rerank import kb as kb_io
from diagnostic_ar_training.safe.knowledge import is_obligate
from diagnostic_ar_training.splits import load_part
from diagnostic_ar_training.systems.genphenia_v3 import GenPheniaV3

ARTIFACT = "results-ft-v1.1-prod-dev-harmed"
PROD, EVALUATED = "ft-v1.1-prod", "ft-v1.1-c1-lin-all-ens"


def output(artifact_id: str, name: str):
    m = manifest.load_manifest(artifact_id)
    if problems := manifest.verify_outputs(m):
        raise SystemExit("; ".join(problems))
    return next(manifest.output_path(o) for o in m.outputs if o.path.endswith(name))


def hpoa_rows(path, keys: set[tuple[str, str]]) -> dict[tuple[str, str], list[dict]]:
    out: dict[tuple[str, str], list[dict]] = {}
    with open(path, encoding="utf-8", newline="") as f:
        for r in csv.DictReader((x for x in f if not x.startswith("#")), delimiter="\t"):
            key = (r["database_id"], r["hpo_id"])
            if key in keys and r["aspect"] == "P" and r["qualifier"] != "NOT":
                out.setdefault(key, []).append(
                    {
                        "frequency": r["frequency"],
                        "obligate": is_obligate(r["frequency"]),
                        "reference": r["reference"],
                    }
                )
    return out


def main() -> None:
    manifest.ensure_new(ARTIFACT)
    state = code_state()
    if state.dirty:
        raise SystemExit("commit your code first")
    base = GenPheniaV3()
    genes = base.genes
    e0 = E0Logits(base)
    systems = {}
    inputs = list(base.lineage_inputs())
    for bundle_id in (PROD, EVALUATED):
        bundle_path = output(bundle_id, "ft-v1-bundle.json")
        bundle = load(bundle_path)
        kb_path = output(bundle["kb_id"], "ft-kb.json.gz")
        kb = kb_io.read(kb_path)
        know = Knowledge(kb, genes, (base.inputs.emb_index, base.inputs.vectors), bundle["kb_id"])
        systems[bundle_id] = (FtResidual(bundle, know), kb)
        inputs += [
            {"id": f"artifact:{bundle_id}", "sha256": sha256_file(bundle_path)},
            {"id": f"artifact:{bundle['kb_id']}", "sha256": sha256_file(kb_path)},
        ]
    inputs.append({"id": "split:r1-v1", "sha256": sha256_file(SPLITS_DIR / "r1-v1.json")})
    index = {g.upper(): i for i, g in enumerate(genes)}
    rows = []
    for case in load_part("r1-v1", "dev", Purpose.EVAL):
        logits, _ = e0(case)
        i = index.get(case.gene.upper())
        if logits is None or i is None:
            continue
        ci = case_inputs(case)
        rank_e0 = rank_of(genes[i], genes, softmax64(logits))
        ranks = {b: rank_of(genes[i], genes, r.apply(logits, ci)) for b, (r, _) in systems.items()}
        if not any(v > rank_e0 for v in ranks.values()):
            continue
        row = {
            "case_id": case.case_id,
            "gene": genes[i],
            "pmids": list(case.pmids),
            "sex": case.sex.value,
            "age_years": case.age_years,
            "onset_years": case.onset_years,
            "n_excluded": len(case.excluded),
            "rank_e0": rank_e0,
            "ranks": ranks,
            "harmed_by": sorted(b for b, v in ranks.items() if v > rank_e0),
        }
        for bundle_id, (residual, kb) in systems.items():
            feats = residual.knowledge.features(ci)[:, i]
            w = residual.weights(ci).mean(axis=0)
            contradicted = []
            excluded = set(case.excluded)
            anc = kb["safe"]["ancestors_or_self"]
            for disease, terms in kb["safe"]["genes"][genes[i]].get("obligate", {}).items():
                for t in terms:
                    covering = sorted(excluded & set(anc[t]))
                    if covering:
                        contradicted.append({"disease": disease, "obligate": t, "excluded": covering})
            row[bundle_id] = {
                "kb": residual.knowledge.rules.bundle["kb_id"],
                "lowering": {
                    f: round(float(-w[k] * feats[k]), 4) for k, f in enumerate(FEATURES) if w[k] * feats[k]
                },
                "contradicted_obligate": contradicted if feats[FEATURES.index("neg_obligate")] else [],
            }
        rows.append(row)
    hpoa_path = open_source("hpo_annotations", Purpose.KB)
    keys = {
        (c["disease"], c["obligate"]) for r in rows for b in systems for c in r[b]["contradicted_obligate"]
    }
    found = hpoa_rows(hpoa_path, keys)
    for r in rows:
        own = {p.removeprefix("PMID:") for p in r["pmids"]}
        for b in systems:
            for c in r[b]["contradicted_obligate"]:
                c["hpoa"] = found.get((c["disease"], c["obligate"]), [])
                refs = {
                    x.strip().removeprefix("PMID:")
                    for h in c["hpoa"]
                    if h["obligate"]
                    for x in h["reference"].split(";")
                }
                c["own_paper"] = bool(refs & own)
    inputs.append(load_sources()["hpo_annotations"].as_input())
    summary = {
        b: {
            "harmed": sum(b in r["harmed_by"] for r in rows),
            "harmed_with_neg_obligate": sum(
                b in r["harmed_by"] and bool(r[b]["contradicted_obligate"]) for r in rows
            ),
            "harmed_by_own_paper_obligate": sum(
                b in r["harmed_by"] and any(c["own_paper"] for c in r[b]["contradicted_obligate"])
                for r in rows
            ),
        }
        for b in systems
    }
    out = {
        "note": "Descriptive, r1-v1 dev; ft-kb-prod-v1 includes the dev papers. Not a claim.",
        "summary": summary,
        "genes": {g: sum(r["gene"] == g for r in rows) for g in sorted({r["gene"] for r in rows})},
        "cases": rows,
    }
    path = DATA_DIR / "ft" / PROD / "dev-harmed.json"
    path.write_text(json.dumps(out, indent=1, default=float) + "\n")
    params = {"part": "r1-v1/dev", "systems": [PROD, EVALUATED], "harmed": "rank worse than E0's"}
    manifest.write_manifest(
        manifest.build_manifest(ARTIFACT, "ft-analysis", inputs, params, [path], state=state)
    )
    print(json.dumps({"summary": summary, "genes": out["genes"]}, indent=1))


if __name__ == "__main__":
    main()
