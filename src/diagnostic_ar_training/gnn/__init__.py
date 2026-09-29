"""Front A: GenPhenia v3.0 re-implemented in PyTorch, and its zero-initialised extension.

- `graphs`: cases -> graph arrays (production construction + negated nodes), PyG-style batching.
- `model`: `GinV3` (loads `best_model.pt` strictly), `GinV3Extended` (equal to v3.0 until trained).
- `export`: ONNX in the production runtime's format.
- `parity`: torch vs production ONNX (EXP-A-000).
- `data`: simulator export v2 -> batches (exclusion applied, embeddings gathered on the device).
- `train`: fine-tuning from v3.0 with early stopping on sim-val (EVAL_PROTOCOL §9).
- `experiment`: a run's evaluation hooks (R1-dev, S2, S3-dev vs E0), contamination check, flags.

Graph construction and graph arrays need only numpy; everything else needs the `gnn` extra (torch).
See docs/PLAN.md §6 and docs/decisions/0009-step-zero-identity.md.
"""
