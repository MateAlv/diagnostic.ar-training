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
| [0006](0006-gene-vocabulary-stays-frozen.md) | The gene vocabulary stays v3.0's 5,229 genes | Accepted 2026-09-29 |
| [0007](0007-frequency-estimation.md) | How phenotype frequencies are read from HPOA (both fronts) | Accepted 2026-09-29 |
| [0008](0008-gene-profiles.md) | Gene profiles from open sources, and how a gene's diseases are weighted | Accepted 2026-09-29 |
| [0009](0009-step-zero-identity.md) | How new inputs enter the GNN so that the untrained extension is exactly v3.0 | Accepted 2026-09-29 (Front A only) |
