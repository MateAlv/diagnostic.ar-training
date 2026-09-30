"""EXP-A-002f addendum (exploratory, dev only): does A-neg2 read *which* terms were denied, or only *that* some were?

Scores one run's selected checkpoint on S3-dev and R1-dev with each case's own excluded terms, and with the
excluded terms of another case of the same cohort (a seeded derangement). If the gain or harm survives the
shuffle, the model is reacting to the presence of negations (a prior shift), not to their content.

Usage: PYTHONPATH=src .venv/bin/python scripts/exploratory/a002f_shuffled_negation.py EXP-A-002f <run-id>
"""

import json
import random
import sys

from diagnostic_ar_training import DATA_DIR, RESULTS_DIR, splits
from diagnostic_ar_training.cli import _gnn_setup
from diagnostic_ar_training.eval import harness, s3_run
from diagnostic_ar_training.gnn import experiment, frozen
from diagnostic_ar_training.gnn import train as training
from diagnostic_ar_training.lineage.manifest import load_manifest, output_path
from diagnostic_ar_training.lineage.registry import Purpose
from diagnostic_ar_training.systems.ginv3_torch import GinModelSystem


def shuffled(cases, seed=0):
    order = list(range(len(cases)))
    rng = random.Random(seed)
    while True:
        rng.shuffle(order)
        if all(i != j for i, j in enumerate(order)):
            break
    return [c.model_copy(update={"excluded": cases[j].excluded}) for c, j in zip(cases, order, strict=True)]


def main(exp: str, run_id: str) -> None:
    torch, dev, inputs, table, base = _gnn_setup("cuda", 1)
    run = json.loads((RESULTS_DIR / exp / run_id / "run.json").read_text())
    cfg = training.TrainConfig(**run["config"])
    model = training.build_model(base, cfg).eval()
    training.load_checkpoint(model, DATA_DIR / "interim" / "models" / run_id / "best.pt")
    system = GinModelSystem(model, inputs, run_id, cfg.negated)
    r1_groups = splits.publication_groups("r1-v1")
    base_ranks = frozen.e0_baselines(r1_groups, s3=True)
    s3_path = output_path(load_manifest("s3-v1-dev-interviews-kb-v5-c10-q7").outputs[0])
    s3_dev = s3_run.read_interviews(s3_path)
    s3_groups = {c.case_id: c.gene for c in s3_dev}
    r1_dev = [c for c in splits.load_part("r1-v1", "dev", Purpose.EVAL)]
    out = {"exp": exp, "run_id": run_id, "shuffle": "seeded derangement of excluded sets within the cohort"}
    for name, cases, groups, view, key in (
        ("s3_dev", s3_dev, s3_groups, "excluded", "s3_dev_all"),
        ("r1_dev", r1_dev, r1_groups, "excluded", "r1_dev_excluded"),
    ):
        for variant, cs in (("own", cases), ("shuffled", shuffled(cases))):
            recs = harness.run(system, cs, view=view, groups=groups)
            out[f"{name}_{variant}"] = experiment.versus(recs, base_ranks[key])
            m = out[f"{name}_{variant}"]
            print(name, variant, f"{m['delta']:+.4f} [{m['ci95'][0]:+.4f},{m['ci95'][1]:+.4f}] "
                  f"harmed {m['harmed']:.3f} helped {m['helped']:.3f}")  # fmt: skip
    path = RESULTS_DIR / exp / f"addendum-shuffled-negation-{run_id}.json"
    path.write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
    print("->", path)


if __name__ == "__main__":
    main(*sys.argv[1:3])
