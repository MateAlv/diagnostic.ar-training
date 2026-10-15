"""Phase 3 (ADR-0019): training and evaluation harness for GenPhenAI v4.0.

- `config`: a run's configuration (simulator, encoding, architecture, training, seed), hashed into its run id.
- `patients`: `p3-v1` train patients with their publication group, E0-knowledge status and fold. The
  CONFIRM fold is refused here; it is read only by the main session through `sim4.folds`.
- `knowledge`: node information content from HPOA 2025-03-03 (E0's knowledge cut).
- `graphs`: E0's patient graph (present terms + ancestors in E0's DAG), built on integer indices.
- `samplers`: the simulator interface (`sim4.Sampler`) and how a configuration names one.
- `model`: `GinV4`, GinV3 plus the encoding and architecture options; with the defaults and a warm start it
  is E0, and every option starts at an exact zero.
- `data`: on-the-fly simulated cases (and real patients of `sim.real_folds`, FIT by default, optionally
  gene-balanced) as batches, one seeded RNG per worker.
- `train`: AdamW, cosine/plateau schedule, bf16 autocast, time and sample budgets, SELECT-fold selection.
- `report`: ranks records, strata, MRR / top-k per stratum, Δ vs E0 with the publication-cluster bootstrap.
- `runs`: run directories (`data/interim/v4/<run_id>/`) and results rows (`results/P3/runs/<run_id>.json`);
  readings of the best and final checkpoints, and their phenotype-swap controls.
- `grid`: sequential grids under a time budget, resumable, every configuration and seed logged.
- `addon`: the re-rank add-on (ft-v1.1's residual on the network's logits; sex, age, onset, excluded terms),
  its E0-knowledge build, out-of-fold fitting and the CONFIRM read (PHASE3 §2f).

Torch is needed only by `model`, `data`, `train`, `evaluate` and `throughput`; everything else is numpy.
See docs/PHASE3.md.
"""
