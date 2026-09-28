# Decision records

One file per architectural or methodological decision: context, decision,
alternatives dropped, consequences. Never rewrite an accepted ADR; supersede it
with a new one and link both ways.

| ADR | Title | Status |
|---|---|---|
| [0001](0001-pytorch-for-retraining.md) | Retrain in PyTorch, warm-started from v3.0 | Accepted 2026-09-28 |
| [0002](0002-separate-training-repo.md) | A separate `diagnostic.ar-training` repo | Accepted 2026-09-28 |
| [0003](0003-publication-grouped-sealed-split.md) | Publication-grouped R1 split with sealed test and vault | Accepted 2026-09-28 |
| [0004](0004-two-fronts-one-harness.md) | Two fronts (retrain, re-rank) judged by one harness | Accepted 2026-09-28 |
| [0005](0005-release-assets-not-dvc.md) | Manifests in git + GitHub release assets instead of DVC | Accepted 2026-09-28 |
