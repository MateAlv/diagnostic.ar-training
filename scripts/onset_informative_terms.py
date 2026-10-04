# ruff: noqa: E501
"""Onset-informative HPO terms v1: for which symptoms does knowing the onset age help (web app "Precisar" list).

Usage:
    python scripts/onset_informative_terms.py

1. Scores every HPO term under Phenotypic abnormality with >= 3 onset-annotated genes on the full production
   knowledge base (kb-v3): mutual information between gene and onset bin given the term (rerank/onset_terms.py).
2. Dev, exploratory: splits S3-v3b-dev cases by the max score of their reported present terms and reports the
   mean paired gain of F + onset 0.25 over F per tertile (results/EXP-B-005/dev/, never any test part).
3. Writes the list (score >= TAU_BITS and R1-train count >= MIN_R1_TRAIN) and its manifest.

TAU_BITS and MIN_R1_TRAIN were fixed from the score distribution and R1-train term counts, before the dev
validation was computed.
"""

import csv
import gzip
import json
from collections import Counter

import numpy as np

from diagnostic_ar_training import RESULTS_DIR, splits
from diagnostic_ar_training.eval import dev_search, onset_run
from diagnostic_ar_training.lineage.gitinfo import code_state
from diagnostic_ar_training.lineage.hashing import sha256_file
from diagnostic_ar_training.lineage.manifest import (
    build_manifest,
    ensure_new,
    fetch_outputs,
    load_manifest,
    write_manifest,
)
from diagnostic_ar_training.lineage.registry import LineageError, Purpose, open_source
from diagnostic_ar_training.ontology import Ontology
from diagnostic_ar_training.rerank import kb
from diagnostic_ar_training.rerank.features import GeneKnowledge
from diagnostic_ar_training.rerank.onset_terms import score_terms

ARTIFACT = "onset-informative-terms-v1"
KB_ID = "kb-v3"
TAU_BITS = 0.75
MIN_R1_TRAIN = 8
MIN_GENES = 3
DEV_DIR = RESULTS_DIR / "EXP-B-005" / "dev"
OUT_DIR = RESULTS_DIR / "onset-informative-terms"
COMMON = {
    "HP:0001250": "Seizure",
    "HP:0001263": "Global developmental delay",
    "HP:0001251": "Ataxia",
    "HP:0000365": "Hearing impairment",
    "HP:0000572": "Visual loss",
    "HP:0000505": "Visual impairment",
    "HP:0001324": "Muscle weakness",
    "HP:0001252": "Hypotonia",
    "HP:0001256": "Intellectual disability, mild",
    "HP:0001249": "Intellectual disability",
    "HP:0000750": "Delayed speech and language development",
    "HP:0002376": "Developmental regression",
    "HP:0002317": "Unsteady gait",
    "HP:0001297": "Stroke",
}
METHOD = (
    "For each HPO term t under Phenotypic abnormality annotated (directly or through a descendant) in kb-v3 for "
    ">= 3 genes with onset data: genes weighted by P(t | g) under a uniform gene prior, each gene's onset "
    "distribution over the 8 re-ranker onset bins (rerank/features.py GeneKnowledge.onset_distribution). "
    "score_bits = mutual information between gene and onset bin given t is present. "
    f"Listed: score_bits >= {TAU_BITS} and present in >= {MIN_R1_TRAIN} R1-train patients."
)


def tertile_table(ref, new, scores_per_case, mask) -> list[dict]:
    idx = [i for i, ok in enumerate(mask) if ok and scores_per_case[i] is not None]
    values = np.array([scores_per_case[i] for i in idx])
    lo, hi = np.quantile(values, [1 / 3, 2 / 3])
    groups = {
        "low": lambda v: v <= lo,
        "mid": lambda v: lo < v <= hi,
        "high": lambda v: v > hi,
    }  # fmt: skip
    rows = []
    for name, test in groups.items():
        sub = [
            mask[i] and scores_per_case[i] is not None and test(scores_per_case[i]) for i in range(len(mask))
        ]
        res = dev_search.compare(ref, new, sub)
        rows.append(
            {
                "tertile": name,
                "score_range": [
                    float(min(scores_per_case[i] for i in idx if sub[i])),
                    float(max(scores_per_case[i] for i in idx if sub[i])),
                ],
                "n": res["n"],
                "delta": res["delta"],
                "ci95": res["ci95"],
                "harmed": res["harmed"],
                "helped": res["helped"],
            }
        )
    return rows


def main() -> None:
    ensure_new(ARTIFACT)
    state = code_state()
    if state.dirty:
        raise LineageError("commit before producing artifacts")
    ontology = Ontology.from_json(open_source("hpo_ontology", Purpose.KB))
    kb_manifest = load_manifest(KB_ID)
    kb_path = fetch_outputs(kb_manifest)[0]
    knowledge = GeneKnowledge(kb.read(kb_path), ontology)
    scores = score_terms(knowledge, MIN_GENES)

    train = splits.load_part("r1-v1", splits.Part.TRAIN, Purpose.TRAIN)
    r1_train = Counter()
    for case in train:
        r1_train.update({ontology.resolve(t) or t for t in case.present})

    ranked = sorted(scores.items(), key=lambda kv: (-kv[1]["score_bits"], -r1_train[kv[0]], kv[0]))
    all_terms = [
        {
            "hpo_id": t,
            "label_en": ontology.labels[t],
            "score_bits": round(x["score_bits"], 4),
            "n_genes": x["n_genes"],
            "r1_train_count": r1_train[t],
        }
        for t, x in ranked
    ]
    terms = [t for t in all_terms if t["score_bits"] >= TAU_BITS and t["r1_train_count"] >= MIN_R1_TRAIN]
    listed = {t["hpo_id"] for t in terms}

    session = json.loads((DEV_DIR / "session.json").read_text())
    rows = onset_run.read_rows(DEV_DIR / "interviews.jsonl.gz")
    with gzip.open(DEV_DIR / "ranks.tsv.gz", "rt") as handle:
        rank_rows = list(csv.DictReader(handle, delimiter="\t"))
    if [r["case_id"] for r in rank_rows] != [r["case_id"] for r in rows]:
        raise LineageError("dev ranks and interviews cover different cases")
    ids = [r["case_id"] for r in rank_rows]
    genes = [r["gene"] for r in rank_rows]
    ref = dev_search.records(ids, genes, [float(r["F"]) for r in rank_rows])
    new = dev_search.records(ids, genes, [float(r["F+onset0.25"]) for r in rank_rows])
    case_scores = []
    in_list = []
    for r in rows:
        present = {ontology.resolve(t) or t for t in r["case"].present}
        s = [scores[t]["score_bits"] for t in present if t in scores]
        case_scores.append(max(s) if s else None)
        in_list.append(bool(present & listed))
    known = [r["case"].onset_years is not None for r in rows]
    n = len(rows)
    populations = {"all": [True] * n, "onset_known": known, "onset_unknown": [not k for k in known]}
    tertiles = {name: tertile_table(ref, new, case_scores, mask) for name, mask in populations.items()}
    listed_split = {}
    for name, mask in populations.items():
        for label, flag in (("has_listed_term", True), ("no_listed_term", False)):
            sub = [m and f == flag for m, f in zip(mask, in_list, strict=True)]
            listed_split[f"{name}/{label}"] = dev_search.compare(ref, new, sub)
    rho = {}
    for name, mask in populations.items():
        pairs = [
            (case_scores[i], 1 / float(rank_rows[i]["F+onset0.25"]) - 1 / float(rank_rows[i]["F"]))
            for i in range(n)
            if mask[i] and case_scores[i] is not None
        ]
        a = np.array(pairs)
        rho[name] = {"n": len(a), "pearson": float(np.corrcoef(a[:, 0], a[:, 1])[0, 1])}
    dev = {
        "label": "dev, exploratory",
        "source": "results/EXP-B-005/dev (S3-v3b-dev, F vs F + onset 0.25, Q2b interview)",
        "bootstrap": {"resamples": 2000, "seed": 0, "unit": "gene"},
        "cases": n,
        "cases_without_scored_term": sum(s is None for s in case_scores),
        "tertiles_by_max_reported_term_score": tertiles,
        "listed_vs_not": listed_split,
        "case_level_correlation_score_vs_reciprocal_rank_gain": rho,
        "dev_session_code_sha": session["code_sha"],
    }

    common = []
    for t, label in COMMON.items():
        common.append(
            {
                "hpo_id": t,
                "label_en": ontology.labels.get(t, label),
                "score_bits": None if t not in scores else round(scores[t]["score_bits"], 4),
                "n_genes": scores.get(t, {}).get("n_genes"),
                "r1_train_count": r1_train[t],
                "listed": t in listed,
            }
        )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{ARTIFACT}.json"
    out.write_text(
        json.dumps(
            {
                "version": "v1",
                "kb": KB_ID,
                "method": METHOD,
                "threshold_bits": TAU_BITS,
                "generated_from_commit": state.sha,
                "terms": terms,
            },
            indent=1,
            ensure_ascii=False,
        )
        + "\n"
    )
    scores_path = OUT_DIR / "term-scores-v1.json"
    scores_path.write_text(
        json.dumps({"min_r1_train": MIN_R1_TRAIN, "scored_terms": all_terms}, indent=0, ensure_ascii=False)
        + "\n"
    )
    dev_path = OUT_DIR / "dev-tertiles-v1.json"
    summary = {
        "scored_terms": len(all_terms),
        "listed_terms": len(terms),
        "score_quantiles_all_scored": {
            str(q): float(np.quantile([t["score_bits"] for t in all_terms], q))
            for q in (0, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 1)
        },
        "common_complaints": common,
        "dev": dev,
    }
    dev_path.write_text(json.dumps(summary, indent=1, ensure_ascii=False) + "\n")
    inputs = [
        {"id": f"artifact:{KB_ID}", "sha256": sha256_file(kb_path)},
        {"id": "source:hpo_ontology", "sha256": sha256_file(open_source("hpo_ontology", Purpose.KB))},
        {"id": "split:r1-v1/train", "sha256": sha256_file(splits.SPLITS_DIR / "r1-v1.json")},
        {"id": "results:EXP-B-005/dev/ranks", "sha256": sha256_file(DEV_DIR / "ranks.tsv.gz")},
        {"id": "results:EXP-B-005/dev/interviews", "sha256": sha256_file(DEV_DIR / "interviews.jsonl.gz")},
    ]
    params = {
        "kb": KB_ID,
        "min_genes": MIN_GENES,
        "threshold_bits": TAU_BITS,
        "min_r1_train_count": MIN_R1_TRAIN,
        "onset_smoothing": 0.1,
        "gene_prior": "uniform",
        "listed_terms": len(terms),
    }
    write_manifest(
        build_manifest(
            ARTIFACT, "onset-informative-terms", inputs, params, [out, scores_path, dev_path], state=state
        )
    )
    print(json.dumps({k: v for k, v in summary.items() if k != "common_complaints"}, indent=1))
    print(json.dumps(common, indent=1))


if __name__ == "__main__":
    main()
