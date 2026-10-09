"""Phase 2 Track 4: gene-vocabulary update by new-row training (docs/PHASE2.md, EXP-P-007).

v3.0's encoder and every existing classifier row stay frozen. Classifier rows (weight vector and bias) are
added, or replace existing ones, and only they are trained, on upstream-style pseudo-patients sampled from
each gene's masked HPO annotations, with replay pseudo-patients of the other genes so the new rows are
calibrated in the full softmax.
- `rows`: the torch head with frozen and trainable rows, the pseudo-patient pools and the fit.
- `standards`: the leave-genes-out standards test: gene choice, the relearned-rows system, the report and the
  pre-registered criterion and selection rule.

Everything but the pure-numpy parts of `standards` needs the `gnn` extra (torch).
"""
