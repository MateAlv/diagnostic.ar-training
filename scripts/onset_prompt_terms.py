# ruff: noqa: E501
"""Onset prompt terms v1 (most-reported): the symptoms where the app offers the onset-age selector.

Mateo's decision, 2026-10-04: the onset score is not the selection rule; the selector goes on the most reported
symptoms so that as many patients as possible give at least one onset. Terms under Phenotypic abnormality are ranked
by the number of R1-train patients reporting the exact term; the list is the smallest N covering >= 90% of R1-train
patients (cap 400). R1-train only, through splits.load_part.
"""

import json
from collections import Counter

from diagnostic_ar_training import RESULTS_DIR, splits
from diagnostic_ar_training.lineage.gitinfo import code_state
from diagnostic_ar_training.lineage.hashing import sha256_file
from diagnostic_ar_training.lineage.manifest import build_manifest, ensure_new, write_manifest
from diagnostic_ar_training.lineage.registry import LineageError, Purpose, open_source
from diagnostic_ar_training.ontology import Ontology

ARTIFACT = "onset-prompt-terms-v1"
ROOT = "HP:0000118"
TARGET = 0.90
CAP = 400
CURVE = (50, 100, 200, 300, 400)
OUT_DIR = RESULTS_DIR / "onset-informative-terms"
SCORES = OUT_DIR / "term-scores-v1.json"
SELECTION = "r1-train frequency, smallest N covering >=90% of R1-train patients"


def main() -> None:
    ensure_new(ARTIFACT)
    state = code_state()
    if state.dirty:
        raise LineageError("commit before producing artifacts")
    ontology = Ontology.from_json(open_source("hpo_ontology", Purpose.KB))
    train = splits.load_part("r1-v1", splits.Part.TRAIN, Purpose.TRAIN)
    patient_terms = []
    counts: Counter = Counter()
    for case in train:
        terms = {
            t
            for t in ({ontology.resolve(x) or x for x in case.present})
            if t != ROOT and ROOT in ontology.ancestors(t)
        }
        patient_terms.append(terms)
        counts.update(terms)
    ranked = sorted(counts, key=lambda t: (-counts[t], t))

    def coverage(n: int) -> float:
        top = set(ranked[:n])
        return sum(bool(p & top) for p in patient_terms) / len(patient_terms)

    curve = {str(n): round(coverage(n), 4) for n in CURVE}
    n_list = next((n for n in range(1, CAP + 1) if coverage(n) >= TARGET), CAP)
    reached = coverage(n_list)
    scored = {x["hpo_id"]: x for x in json.loads(SCORES.read_text())["scored_terms"]}
    terms = [
        {
            "hpo_id": t,
            "label_en": ontology.labels[t],
            "score_bits": scored[t]["score_bits"] if t in scored else None,
            "n_genes": scored[t]["n_genes"] if t in scored else None,
            "r1_train_count": counts[t],
        }
        for t in ranked[:n_list]
    ]
    out = OUT_DIR / f"{ARTIFACT}.json"
    out.write_text(
        json.dumps(
            {
                "version": "v1-most-reported",
                "kb": "kb-v3",
                "method": "Terms under Phenotypic abnormality (HP:0000118) ranked by the number of R1-train patients "
                f"reporting the exact term; the smallest N whose list is reported by at least {TARGET:.0%} of "
                f"R1-train patients (at least one listed term), capped at {CAP}. score_bits and n_genes are the "
                "onset-informative-terms-v1 mutual-information score, as data only.",
                "selection": SELECTION,
                "threshold_bits": None,
                "coverage_r1_train": round(reached, 4),
                "coverage_curve": curve,
                "r1_train_patients": len(patient_terms),
                "generated_from_commit": state.sha,
                "terms": terms,
            },
            indent=1,
            ensure_ascii=False,
        )
        + "\n"
    )
    inputs = [
        {"id": "source:hpo_ontology", "sha256": sha256_file(open_source("hpo_ontology", Purpose.KB))},
        {"id": "split:r1-v1/train", "sha256": sha256_file(splits.SPLITS_DIR / "r1-v1.json")},
        {"id": "artifact:onset-informative-terms-v1/term-scores", "sha256": sha256_file(SCORES)},
    ]
    params = {
        "root": ROOT,
        "target_coverage": TARGET,
        "cap": CAP,
        "n": n_list,
        "coverage": round(reached, 4),
        "curve": curve,
    }
    write_manifest(build_manifest(ARTIFACT, "onset-prompt-terms", inputs, params, [out], state=state))
    print(
        json.dumps(
            {"n": n_list, "coverage": reached, "curve": curve, "patients": len(patient_terms)}, indent=1
        )
    )
    for x in terms[:20]:
        print(x)


if __name__ == "__main__":
    main()
