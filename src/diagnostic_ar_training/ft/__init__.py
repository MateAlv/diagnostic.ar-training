"""Phase 2 Track 3, `ft-v1`: v3.0 plus a zero-initialised, knowledge-conditioned residual (docs/PHASE2.md).

logits' = logits_E0 + r, with r_g = Σ_k w_k(patient) · c_k(patient, g):
- `knowledge`: the per-gene knowledge the features read (`ft-kb/1`), built with every R1 PMID masked.
- `bundle`: pure numpy. The features c_k, the patient covariates, the residual and `apply`; what ships.
- `model`: the torch residual that is trained (and the optional classifier delta); weights export to `bundle`.
- `train`: fitting on R1-train with early stopping on held-out train publication groups.
- `replay`: annotation-sampled pseudo-patients and v3.0's pooled vectors (optional configuration).
- `system`: `FtV1`, the System the harness (and a future sealed read) scores.
- `evaluate`: reports vs E0 on a free part.
"""
