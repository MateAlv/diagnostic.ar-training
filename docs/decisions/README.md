# Decision records

One file per architectural or methodological decision: context, decision,
alternatives dropped, consequences. Never rewrite an accepted ADR; supersede it
with a new one and link both ways.

| ADR | Title | Status | Outcome |
|---|---|---|---|
| [0001](0001-pytorch-for-retraining.md) | Retrain in PyTorch, warm-started from v3.0 | Accepted 2026-09-28 | In force |
| [0002](0002-separate-training-repo.md) | A separate `diagnostic.ar-training` repo | Accepted 2026-09-28 | In force |
| [0003](0003-publication-grouped-sealed-split.md) | Publication-grouped R1 split with sealed test and vault | Accepted 2026-09-28 | In force |
| [0004](0004-two-fronts-one-harness.md) | Two fronts (retrain, re-rank) judged by one harness | Accepted 2026-09-28 | In force |
| [0005](0005-release-assets-not-dvc.md) | Manifests in git + GitHub release assets instead of DVC | Accepted 2026-09-28 | In force |
| [0006](0006-gene-vocabulary-stays-frozen.md) | The gene vocabulary stays v3.0's 5,229 genes | Accepted 2026-09-29 | In force |
| [0007](0007-frequency-estimation.md) | How phenotype frequencies are read from HPOA (both fronts) | Accepted 2026-09-29 | In force |
| [0008](0008-gene-profiles.md) | Gene profiles from open sources, and how a gene's diseases are weighted | Accepted 2026-09-29 | In force |
| [0009](0009-step-zero-identity.md) | How new inputs enter the GNN so that the untrained extension is exactly v3.0 | Accepted 2026-09-29 (Front A only) | In force |
| [0010](0010-front-a-frozen-base.md) | Front A keeps v3.0 frozen and trains only the new inputs' parameters | Accepted 2026-09-29 | Front A trained on real patients failed (A-001, A-002f, A-003f); A-004f not run |
| [0011](0011-simulator-v04.md) | Simulator v0.4: realism-first rebuild (recounted masking, merged profiles, reporting model, cardinal features) | Accepted 2026-09-30 | In force |
| [0012](0012-data-quality-gate.md) | No retraining until the simulated data passes a pre-registered quality gate | Accepted 2026-09-30 | Closed without passing: candidate 6 not frozen (G2b dev 0.159 vs UP 0.231); R1-dev budget exhausted; no Front A retraining |
| [0013](0013-literature-enrichment.md) | Enrich construction profiles from GeneReviews and open-access cohorts | Accepted 2026-10-01 | Done: build v2, cross-check 96.1%, audit row error 2.0% [1.25, 3.17], recall 93.3% |
| [0014](0014-reranker-v11-and-s3-v2.md) | Re-ranker v1.1 and better questions, evaluated on a new sealed S3 v2 | Accepted 2026-10-03 | Done: `rerank-v1.0.0` stays the released re-ranker; EXP-B-004 descriptive (F does not beat rr-v1 under the 5% cap); EXP-Q-001 P1 passed (Q2b beats Q0, +0.0049 [+0.0027, +0.0069]), Q2b is the question agent default |
| [0015](0015-onset-follow-up-s3-v3.md) | Does symptom-onset age help the re-ranker? A fair test on S3 v3 | Accepted 2026-10-04 | EXP-B-005 P1 passed (+0.0023 [+0.0013, +0.0034], harmed 4.63%); S3 v3 superseded by S3 v3b; EXP-B-006 (`rerank-v1.1.0`) pre-registered, R1-test read pending; onset-score selector failed dev, web uses `onset-prompt-terms-v1` |
| [0016](0016-final-deployment-and-close-out.md) | Final deployment and close-out of the model experiments | Accepted 2026-10-05 | Q2b + `rerank-v1.0.0` deployed in staging; `rerank-v1.1.0` not released (EXP-V-001); no more model experiments (superseded by 0017, 2026-10-07) |
| [0017](0017-phase-2-real-patient-restart.md) | Phase 2: a restart on real patients with a post-E0 final check | Accepted 2026-10-07 | Done: EXP-P-005 and EXP-P-006 passed; see 0018 |
| [0018](0018-ft-v11-production-ready.md) | `ft-v1.1-c1-lin-all-ens` is the production-ready model; integration later | Accepted 2026-10-08 | In force |
| [0019](0019-phase-3-v4-retraining.md) | Phase 3: a v4.0 retrained on a pristine simulator and real patients, with one sealed read (`p3-v1` vault) | Accepted 2026-10-13 | In force; gate form open |
