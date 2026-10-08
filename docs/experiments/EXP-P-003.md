# EXP-P-003: ft-v1, v3.0 plus a knowledge-conditioned residual for sex, age/onset and excluded terms, learned from real patients (dev selection)

- **Front:** Phase 2, Track 3 ([PHASE2.md](../PHASE2.md), [ADR-0017](../decisions/0017-phase-2-real-patient-restart.md))
- **Registered:** 2026-10-08, by the Track 3 agent for Mateo, before any dev run
- **Status:** dev search done (2026-10-08); selected `c1-lin-all`. No sealed read is planned here; a confirmation read of the selected candidate needs its own
  pre-registration (`dxt ft confirm`, implemented and tested with mocks only).

## Hypothesis
A residual added to E0's logits, r_g = Σ_k w_k(patient) · c_k(patient, g), trained on `r1-v1` train patients with
w_k ≤ 0 and zero at step 0, ranks the causal gene higher than E0 on `r1-v1` dev: the seed-mean Δ MRR of the selected
configuration is > 0.

## Systems compared
| System | Artifact ids / code | Notes |
|---|---|---|
| E0 | `genphenia_v3` (model-v3.0.0), present terms | the production ONNX; its logits are the base of every candidate |
| `ft-v1-<config>-s<seed>` | `dxt ft grid`; `ft/bundle.py`, `ft/model.py`, `ft/train.py` | one seed of a configuration |
| `ft-v1-<config>-ens` | `dxt ft ensemble` | the mean of the seed residuals: the candidate form of a configuration |

**Design** (binding, from the Track 3 brief and ADR-0009/0010):
- **Base frozen.** logits' = logits_E0 + r. E0's logits come from the production ONNX, so an untrained residual (θ =
  0) gives E0's probabilities bit for bit. The optional classifier configurations (c7, c8) add a change ΔW, Δb to
  v3.0's classifier, starting at 0, on v3.0's pooled vector (v3.0 is frozen and in eval mode, so the pooled vector
  of a case is fixed).
- **Features c_k ≥ 0**, gene-agnostic, 0 when their patient input is unknown (`ft/bundle.py`): `sex_mismatch`,
  `onset_strict_late`, `onset_strict_gap`, `onset_lenient_gap`, `xlr_female`, `xld_male`, `neg_obligate` (the Track
  1 rule) and `neg_embed` (the mean over excluded terms of the highest cosine similarity to a term of the gene's
  annotated profile, in v3.0's input embeddings). Reference age: onset if known, else age; negatives count as 0.
- **Weights** w(patient) = −θ ⊙ softplus(m(z)) / ln 2. θ ≥ 0 (projected after each step) starts at 0. m is an MLP
  over the covariates z = (male, female, log1p age, age known, log1p onset, onset known, log1p #present, log1p
  #excluded) whose last layer starts at 0, or absent (linear configurations: w = −θ). Every feature can therefore only
  lower a gene's score: the R1 reporting pattern (EXP-B-002: excluded terms favour the true gene) cannot be learned.
- **No per-gene parameter learned from patients** in c1–c6. c7–c8 have them (the classifier).

## Data
- **Knowledge:** `ft-kb-all-v1` (`dxt ft kb`): HPO 2026-02-16 annotations with every `r1-v1` PMID masked
  (`r1-v1.all-pmids.txt`, train included), Orphanet ages 2026-06, HGNC, HPO genes_to_disease, and the safe-v1 sex
  curation overrides (49 rows) where they still apply. Used for training and evaluation alike.
- **Fitting:** `r1-v1` train (4,103 patients). Patients whose gene is outside E0's vocabulary (581) cannot enter a
  cross-entropy over E0's genes. Of the 3,522 usable, the cases of 20% of train publication groups (salted hash of the
  group, `configs.inner_split`; 461 usable cases) are held out for early stopping; the rest fit.
- **Early stopping:** MRR on the held-out train groups, every epoch, patience 20, min Δ 1e-5, at most 200 epochs. Epoch
  0 is E0. Never dev.
- **Selection:** `r1-v1` dev (1,883 patients), read once per run, after training.
- **Classifier configurations only:** pseudo-patients for replay, 8 per gene with an annotated profile (4,887 genes),
  each a uniform subset of 1–12 of the gene's masked profile terms (size uniform), seed 20261008; any with the
  (gene, present set) of an `r1-v1` patient is dropped (EVAL_PROTOCOL §9.7).
- **Sealed reads:** none.

## Primary metric and selection rule (written before any dev run)
- **Primary:** dev Δ MRR vs E0, "all" view, over all 1,883 patients with misses counted as 0; paired publication-
  cluster bootstrap (2,000 resamples, seed 0, 95% CI).
- **Seeds:** 0, 1, 2 for every configuration. Reported as mean ± sd; the best seed is never picked.
- **Validity of a run:** the untrained residual is exactly 0 (checked); θ ≥ 0; the numpy residual that ships equals
  the torch one (max |Δr| ≤ 1e-3); for c1–c6 the dev present-only view equals E0 bit for bit on every case.
- **Rule (`configs.select`):**
  1. Selectable: c1–c6 (EVAL_PROTOCOL §10: learned Phase 2 candidates use gene-agnostic features; c7 and c8 learn
     per-gene weights and are measured and reported only), with all three seeds valid and mean harmed ≤ 5%.
  2. The highest seed-mean dev Δ. A configuration with fewer parameters within 0.0005 of it is preferred (fewest
     first, then the lower θ learning rate).
  3. No candidate if that mean is not above 0.
- **Candidate form:** the 3-seed ensemble of the selected configuration (mean residual). Its dev CI is the headline
  interval; seed 0's CI is the pre-declared single-seed interval.

## Also reported (descriptive)
- harmed and helped shares and counts; top-1 and top-10 entries and exits;
- subsets: in-vocabulary; sex, age, onset and excluded terms known; **post-E0 dev publications**; dev patients whose
  gene does (not) appear in `r1-v1` train;
- the dev present-only view (Δ = 0 by construction for c1–c6; for c7–c8 it measures the classifier change alone);
- train Δ (in-sample) and the held-out train groups' Δ;
- θ per feature and seed; the median seed-mean dev Δ over the 8 configurations;
- **ablation** (not a configuration, never selectable): the selected configuration without sex, age and onset
  (features `neg_obligate`/`neg_embed` only of those it has, covariates #present and #excluded only), 3 seeds and the
  ensemble. If the selected configuration has no negation feature, its ablation is E0 and is reported as such.
- GPU time.

## Dev search
- **Budget: 8 configurations × 3 seeds** (`ft/configs.py`). Adam; θ at `lr`, the MLP at `lr_mlp` with weight decay
  1e-4, batch 128.

  | Id | Residual | Features | θ lr / MLP lr | Classifier |
  |---|---|---|---|---|
  | c1-lin-all | linear (w = −θ) | all 8 | 0.05 / – | frozen |
  | c2-lin-safe3 | linear | sex_mismatch, onset_strict_late, neg_obligate | 0.05 / – | frozen |
  | c3-lin-noxl | linear | all but xlr_female, xld_male | 0.05 / – | frozen |
  | c4-mlp16 | MLP, hidden 16 | all 8 | 0.05 / 0.01 | frozen |
  | c5-mlp16-lr0.01 | MLP, hidden 16 | all 8 | 0.01 / 0.002 | frozen |
  | c6-mlp64 | MLP, hidden 64 | all 8 | 0.05 / 0.01 | frozen |
  | c7-cls-l2sp1e-2 | as c4 | all 8 | 0.05 / 0.01 | ΔW, Δb at lr 1e-4, L2-SP 1e-2, replay weight 1 |
  | c8-cls-l2sp1e-4 | as c4 | all 8 | 0.05 / 0.01 | ΔW, Δb at lr 1e-4, L2-SP 1e-4, replay weight 1 |

- **Pipeline checks before registration** (train only, no dev read; logged in BITACORA 2026-10-08): the held-out
  train groups' MRR moved from E0's 0.5545 to 0.5559–0.5563 for linear and MLP residuals, and to 0.565 (L2-SP 1e-2)
  and 0.600 (L2-SP 1e-4) with the classifier. `neg_embed` and `onset_lenient_gap` ended at θ = 0.
- **Tried:** all 8 configurations × 3 seeds, plus the ablation of the selected one × 3 (Results).

## Expectations (written before any dev run)
| Quantity | Expected |
|---|---|
| c1–c6 dev Δ (seed mean) | +0.001 to +0.003, harmed < 1% (Track 1's `safe-v1` dev: +0.00246) |
| θ of `neg_embed` | 0 in every run (the reporting pattern pushes it positive; the constraint holds it at 0) |
| c1–c6 train Δ | ≈ +0.001 (the held-out pipeline check) |
| c7–c8 dev Δ | larger (+0.01 or more) on dev patients whose gene is in train, through learned per-gene weights; harmed > 5%; near 0 or negative on genes not in train and on post-E0 publications |
| Ablation | most of the residual configurations' Δ comes from sex and onset; the negation-only residual ≈ +0.001 |
| Post-E0 dev | about +0.0001 for c1–c6 (E0's MRR there is 0.066) |

## Results
Code at `c70070e` (registration and code), knowledge `ft-kb-all-v1` built from it (`d2e9182`); every run from `d2e9182`.
Outputs: `results/EXP-P-003/` (`report.json` from `dxt ft report`; per run `summary.json`, `curves.json`, compact
dev and train ranks), 27 `ft-run` manifests, and the bundles `ft-v1-c1-lin-all-ens` and
`ft-v1-c1-lin-all-nosexage-ens`.

- **Setup checks:** E0 through the production logits gives the EXP-P-001 E0 ranks on all 1,883 dev and 4,103 train
  patients (0 differ). Every run is valid: untrained residual exactly 0; θ ≥ 0; numpy vs torch residual within
  1e-3; c1–c6 dev present-only view bit-identical to E0 on every scorable case. Pooled vectors reproduce the ONNX
  logits within 9.8e-4. Replay: 39,096 pseudo-patients over 4,887 genes, 0 dropped for overlap.
- **Train:** 3,522 of 4,103 usable (581 genes outside E0's vocabulary); 3,061 fit rows, 461 held-out rows (512 of
  4,103 train patients in the held-out groups).

**Dev, all 1,883 patients, Δ MRR vs E0 (E0 0.4485); mean ± sd over seeds 0–2:**

| Config | Params | Dev Δ | Mean CI | Harmed | Present view | Post-E0 (351) | Train Δ | Held-out train Δ |
|---|---|---|---|---|---|---|---|---|
| **c1-lin-all** | 8 | **+0.00313 ± 0.00000** | [+0.00159, +0.00485] | 0.11% | 0 | +0.00009 | +0.00022 | +0.00125 |
| c2-lin-safe3 | 3 | +0.00230 ± 0.00000 | [+0.00080, +0.00399] | 0.11% | 0 | +0.00007 | +0.00060 | +0.00158 |
| c3-lin-noxl | 6 | +0.00241 ± 0.00006 | [+0.00087, +0.00409] | 0.11% | 0 | +0.00007 | +0.00060 | +0.00158 |
| c4-mlp16 | 288 | +0.00239 ± 0.00076 | [−0.00009, +0.00462] | 0.23% | 0 | +0.00010 | +0.00047 | +0.00128 |
| c5-mlp16-lr0.01 | 288 | +0.00313 ± 0.00000 | [+0.00160, +0.00486] | 0.11% | 0 | +0.00008 | +0.00043 | +0.00132 |
| c6-mlp64 | 1,104 | +0.00231 ± 0.00046 | [−0.00010, +0.00452] | 0.25% | 0 | +0.00011 | +0.00080 | +0.00129 |
| c7-cls-l2sp1e-2 | 2,682,765 | +0.02480 ± 0.00294 | [+0.00535, +0.04904] | 1.63% | +0.02517 | +0.00005 | +0.03126 | +0.00881 |
| c8-cls-l2sp1e-4 | 2,682,765 | +0.08740 ± 0.00703 | [+0.03511, +0.14732] | 6.30% | +0.08830 | +0.00781 | +0.13057 | +0.04230 |

"Mean CI" is the mean over seeds of each seed's 95% CI bounds. Median seed-mean dev Δ of the 8 configurations:
+0.00277.

- **θ (seed 0, feature order of `ft/bundle.py`):** c1 [3.28, 3.38, 2.85, 0, 3.03, 5.52, 3.12, 0]. `neg_embed` and
  `onset_lenient_gap` are 0 in every run of every configuration (c4 seed 1: `onset_lenient_gap` 0.008).
- **Early stopping:** best epochs 22–25 (c1), 8 (c2, c3), 1–14 (MLPs), 27–185 (classifier).
- **c7, c8 (classifier, not selectable):** almost the whole Δ is in the present-only view, i.e. the retrained
  classifier without the new inputs (c8: +0.0883 of +0.0874). On dev patients whose gene is not among train genes
  (555) it is +0.003 to +0.006; harmed 29–32 (c7) and 113–123 (c8) patients; top-10 +25 to +94.

**Selected configuration, `c1-lin-all`:**

| | Dev Δ [95% CI] | Helped / harmed | Top-1 | Top-10 |
|---|---|---|---|---|
| Seed 0 (pre-declared single seed) | +0.00313 [+0.00159, +0.00485] | 346 / 2 | +7 / −0 | +4 / −0 |
| **Ensemble of seeds 0–2 (`ft-v1-c1-lin-all-ens`)** | **+0.00313 [+0.00159, +0.00485]** | 345 / 2 (0.11%) | +7 / −0 | +4 / −0 |
| Ablation ensemble, no sex/age/onset (`neg_obligate` only; θ 2.92–2.99) | +0.00146 [+0.00013, +0.00309] | 118 / 2 | +5 / −0 | +0 / −0 |

Ensemble subsets (dev): in-vocabulary 1,680 +0.00350; sex known 1,703 +0.00342; age known 1,636 +0.00357; onset
known 534 +0.00688 [+0.00274, +0.01169]; excluded known 1,764 +0.00302; **post-E0 351 +0.00009 [+0.00001,
+0.00023]**, 0 harmed; gene in train 1,328 +0.00270; gene not in train 555 +0.00414 [+0.00095, +0.00825].
Train (4,103, in-sample): +0.00023 [−0.00152, +0.00181], 21 harmed (0.51%), top-10 +12/−4; held-out train groups
(512): +0.00125 [−0.00112, +0.00389], 7 harmed.

- **GPU:** RTX 4070 Ti; 32.7 s of fitting over the 27 runs, peak 1.6 GB. The grid's wall time (82.8 min, plus the
  ablation and ensembles) is CPU evaluation through the numpy apply, most of it the classifier runs' per-case CPU
  pooling.

## Selection outcome
By the registered rule: c1–c6 are eligible (every seed valid, harmed ≤ 5%). The highest seed mean is c5
(+0.003133); c1 (+0.003127) is within 0.0005 with 8 parameters instead of 288, so **`c1-lin-all` is selected**, in
its candidate form `ft-v1-c1-lin-all-ens` (bundle sha256 `5a26e537…`). c7 and c8 are not selectable (§10,
per-gene weights).

## Addenda
