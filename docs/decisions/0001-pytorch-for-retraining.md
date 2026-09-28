# ADR-0001: Retrain in PyTorch, warm-started from v3.0

- **Status:** Accepted, 2026-09-28.
- **Deviation:** the anteproyecto names Keras 3 + JAX.

## Context
- Production serves GenPhenia v3.0, a PyTorch GIN (3 layers, 768 → 512 →
  5,229 genes), exported to ONNX.
- The upstream Keras + JAX trainer (`GraPhens/training/`) can only build
  v2.0, a 4-layer GCN (`SUPPORTED_MODEL_VERSIONS = ("2.0",)`).
- No trained Keras GNN checkpoint exists.
- v3.0's training data (26M simulated samples) is not available.

## Decision
- Re-implement v3.0 in PyTorch inside `diagnostic_ar_training.gnn`, loading
  `best_model.pt` with a logits-parity gate against the production ONNX.
- Extend it with zero-initialised new inputs (negated-node channel, patient
  covariates), so that the extended model equals v3.0 at step 0.
- Export to ONNX for the existing runtime.

## Alternatives dropped
- **Keras + JAX from scratch.** It discards the production weights, and
  retraining 5,229 classes from scratch without the original data would start
  below production.
- **Porting GIN to Keras and converting the weights.** Extra work and a second
  source of parity bugs, for no runtime benefit: production runs ONNX anyway.

## Consequences
- The informe must explain the deviation from the proposal (criterion 6:
  planned vs actual).
- Needs torch with CUDA in this repo's environment (the `gnn` extra).
