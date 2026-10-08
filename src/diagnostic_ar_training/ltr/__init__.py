"""Phase 2 Track 2, `ltr-v1`: a re-ranker of E0's top 100 learned on r1-v1 train (docs/PHASE2.md).

- `bundle`: the features, the numpy LightGBM evaluator and `apply`, which production can ship.
- `knowledge`: builds the knowledge the features read (`ltr-kb/1`).
- `train`: per-case tables, the configurations, fitting and the ranks they give.
- `system`: `LtrV1`, the System the harness scores.
"""
