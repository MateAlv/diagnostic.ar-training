# EXP-P-007: new-row training, the leave-genes-out standards test (Track 4, dev)

- **Front:** Phase 2, Track 4 ([PHASE2.md](../PHASE2.md); [ADR-0006](../decisions/0006-gene-vocabulary-stays-frozen.md),
  [ADR-0017](../decisions/0017-phase-2-real-patient-restart.md))
- **Registered:** 2026-10-08, by the Track 4 agent for Mateo, before any run that scores a patient with a relearned
  row
- **Status:** done (2026-10-08). Dev read once; FAIL against the registered criterion. Free parts only (`r1-v1`
  train and dev); no sealed read.

## Question
Mateo's condition for Track 4: new genes must be learned to GenPhenAI's own standard. New genes cannot be tested
directly: the R1 patients whose gene is outside E0's 5,229 mostly have no annotation left once their own papers are
masked (2 train patients under the all-mask; 20 dev patients, 5 genes, under the held-out mask). So the method is
tested on genes E0 already knows: their rows are deleted and relearned from random initialisation, and the relearned
rows are compared with E0's own rows on the same real patients.

## Hypothesis
With v3.0's encoder and every other row frozen, rows relearned from random initialisation on pseudo-patients sampled
from the all-mask HPO annotations reach at least 90% of E0's MRR on the `r1-v1` dev patients of those genes, and
change the MRR of every other dev patient by no less than −0.001.

## Systems compared
| System | Artifact ids / code | Notes |
|---|---|---|
| E0 | `genphenia_v3` (model-v3.0.0), present terms | production ONNX logits |
| `relearned-<config>-s<seed>` | `dxt vocab final`; `vocab/rows.py`, `vocab/standards.py`, `vocab/runs.py` | E0 with the relearned genes' logits replaced by new rows · v3.0's pooled vector |
| `relearned-<config>-ens` | the same command | the mean of the 3 seeds' rows (the logits are linear in the rows, so this is the mean logit): the form the criterion reads |

## Method: new-row training (`vocab/rows.py`)
- **Frozen:** v3.0's encoder (eval mode, so a case's 512-d pooled vector is fixed) and every classifier row that is
  not relearned. The head keeps v3.0's weight and bias as buffers; only the new rows are parameters.
- **New rows:** weight vector and bias per relearned gene, initialised from a seeded uniform(±1/√512) draw (the
  `nn.Linear` default), never from E0's rows. The same head can append genes after index 5,228 (step 2); the tests
  cover replacement and extension.
- **Data, no patients:** upstream-style pseudo-patients from `ft/replay.py`: for each gene, uniform subsets of 1 to
  12 of its masked profile terms that v3.0's DAG knows (size uniform), the graph adding their ancestors, passed
  through the frozen encoder to pooled vectors. Pseudo-patients whose (gene, present set) equals any `r1-v1`
  patient's are dropped (EVAL_PROTOCOL §9.7).
  - Relearned genes: `new_per_gene` pseudo-patients each (seed 20261009).
  - Every other gene with a profile: `replay_per_gene` each (EXP-P-003's replay seed 20261008), so the new rows are
    calibrated against the fixed ones in the full 5,229-way softmax.
  - Early stopping: held-out pools, 16 per relearned gene (seed 20261010) and 2 per other gene (seed 20261011).
- **Knowledge:** `ft-kb-all-v2`, the profiles of HPO 2026-02-16 with every `r1-v1` PMID masked
  (`mask_pmids("r1-v1", "all")`).
- **Loss:** cross-entropy over all 5,229 genes, the relearned genes' batch weighted by their share of genes
  (|relearned| / (|relearned| + |replay genes|)) and the replay batch by the rest, so each gene counts once, as in a
  uniform-prior simulator.
- **Optimiser:** Adam on the new rows only, no weight decay; per step 256 relearned-gene and 1,024 replay
  pseudo-patients; an epoch is one pass over the relearned genes' pool. Early stopping on the held-out pools'
  weighted loss: patience 10, min Δ 1e-4, at most 300 epochs; the best state is kept.
- **Scoring a patient:** E0's production ONNX logits, with the relearned genes' entries replaced by row · pooled +
  bias (the pooled vector from the PyTorch GinV3, `load_v3`). Every other gene keeps E0's logit bit for bit.

## Gene choice (the rule, fixed before any run)
- **Eligible:** a gene of E0's vocabulary with at least one patient in the part, and a non-empty masked profile (at
  least one profile term in `ft-kb-all-v2` that v3.0's DAG knows). A row cannot be learned from no annotation; step 2
  would add only annotated genes.
- **Chosen:** all eligible genes if there are at most 200; otherwise `random.Random(20261008).sample` of the sorted
  eligible list, 200 genes (`vocab/standards.choose_genes`).
- **Counts, computed from gene lists only before registration (no score):**
  - dev: 235 genes, 208 in the vocabulary, 173 eligible, so **all 173 genes are relearned** (1,547 of the 1,883 dev
    patients). The 35 in-vocabulary genes without a masked profile (133 patients) keep E0's rows and count in (b).
  - selection (the held-out train groups of `ft/configs.inner_split`, EXP-P-003's 20%): 108 genes, 96 in the
    vocabulary, **76 eligible and relearned** (381 of the 512 patients).

## Primary metrics and the criterion (written before any run)
On `r1-v1` dev, "all" view, misses count 0, for `relearned-<config>-ens` vs E0:
- **(a)** the patients whose gene is relearned: MRR with relearned rows / MRR with E0's rows (point estimate), with
  a 95% percentile CI from the publication-cluster bootstrap (2,000 resamples of publication groups, seed 0; the
  ratio of the resampled sums). Also the Δ MRR with its paired publication-cluster CI, top-1 and top-10 of both, and
  helped and harmed counts.
- **(b)** every other dev patient (genes not relearned, including the 35 genes without a masked profile and the
  out-of-vocabulary genes): Δ MRR vs E0 with its CI; this measures calibration harm.

**PASS** if and only if (a)'s ratio ≥ 0.90 (point estimate; the CI is reported) **and** (b)'s Δ ≥ −0.001 (point
estimate). Otherwise FAIL. (`vocab/standards.criterion`.)

## Configuration choice (train only)
- **Budget: 6 configurations** (`vocab/standards.CONFIGS`), each × seeds 0, 1, 2:

  | Id | Pseudo-patients per relearned gene | Replay per other gene | Adam lr |
  |---|---|---|---|
  | c1-n128-r8 | 128 | 8 | 0.01 |
  | c2-n512-r32 | 512 | 32 | 0.01 |
  | c3-n512-r128 | 512 | 128 | 0.01 |
  | c4-n512-r128-lr3e-3 | 512 | 128 | 0.003 |
  | c5-n2048-r128 | 2,048 | 128 | 0.01 |
  | c6-n512-r256 | 512 | 256 | 0.01 |

- **Selection runs (`dxt vocab select`, dev never loaded):** relearn the 76 selection genes, score `r1-v1` train.
  (a) is read on the held-out train groups' patients whose gene is relearned (381); (b) on every train patient whose
  gene is not relearned. No patient enters a fit (the rows learn from pseudo-patients only), so (b) can use all of
  train.
- **Rule (`vocab/standards.select`, `dxt vocab choose`):**
  1. Feasible: all three seeds ran and the seed-mean (b) Δ ≥ −0.001.
  2. The highest seed-mean (a) ratio; among the feasible configurations within 0.01 of it, the one with the fewest
     pseudo-patients per gene (relearned + replay), then the lower learning rate.
  3. If none is feasible: the highest seed-mean (b) Δ.
- **Dev is read once,** for the selected configuration only (`dxt vocab final` refuses any other): seeds 0-2 and their
  ensemble, relearning the 173 dev genes.

## Also reported (descriptive)
- Seeds 0-2 individually (mean ± sd of (a) ratio and (b) Δ); EVAL_PROTOCOL §9.5 (no best seed).
- Subsets of (a): post-E0 dev publications; dev patients whose gene does / does not appear in `r1-v1` train.
- Per relearned gene: patients, E0 MRR, relearned MRR.
- **Train check** (all-mask, as for dev): the same dev-relearned rows on all 4,103 train patients: (a) the train
  patients of the 173 genes, (b) the rest. The train selection set is part of train, so this is not independent of
  the configuration choice.
- Pipeline checks: E0's ranks equal EXP-P-001's; E0's own rows through the pipeline give E0's ranks; frozen rows
  unchanged bit for bit; non-relearned logits equal E0's bit for bit; the cosine of the initial and final rows to
  E0's rows.
- GPU time.

## Pipeline checks before registration (no patient metric was computed)
- **Pseudo-patients only** (100 random profiled genes, chosen without patients, never scored on a patient), to set the
  scale of the grid:
  - v3.0's rows have norm ≈ 290 and bias ≈ −2.7, while the pooled vectors have norm ≈ 1.8. With Adam at lr 0.05 the
    first epoch overshoots (held-out replay loss 68 before recovering).
  - **Weight decay toward 0 is harmful here:** E0's logits are mostly far below 0, so a small row (logit ≈ 0)
    outranks most genes. With weight decay 1e-3 the held-out replay MRR fell to 0.01. The grid has no weight decay.
  - A larger replay pool lowers the replay (calibration) loss: held-out replay pseudo-MRR 0.7502 with E0's rows;
    0.7477 (128/8), 0.7492 (512/32), 0.7498 (512/128) with relearned rows.
  - On held-out pseudo-patients of the relearned genes, relearned rows reach 0.80-0.85 pseudo-MRR vs 0.79 with E0's
    rows. These pseudo-patients come from the masked profiles the relearned rows are trained on, so this does not
    predict the real-patient ratio.
- **Train dry run** (`c2-n512-r32`, seed 0, the 76 selection genes; only checks printed): E0's train ranks equal
  EXP-P-001's (0 differ); E0's own rows through the pipeline change 0 train ranks; frozen rows and v3.0's classifier
  unchanged bit for bit; non-relearned logits equal E0's on every checked case; initial rows' largest |cosine| to
  E0's rows 0.088; fit 14 s, pools 36 s, peak GPU 0.65 GB.

## Expectations (written before any run)
| Quantity | Expected |
|---|---|
| (a) ratio, dev | 0.75 to 0.95. E0's rows were trained on HPO 2025-11-24 annotations, which cite many dev papers; the relearned rows see the all-mask annotations, so dev patients whose phenotypes were curated from their own paper favour E0 |
| (a) ratio, post-E0 dev patients | closer to 1 (no home advantage for E0), but few patients |
| (b) Δ, dev | −0.002 to 0 |
| Final cosine to E0's rows | about 0.9 |

## Results
Code and registration at `9661a42`; selection runs from `9661a42`, `dxt vocab choose` from `532a293`
(`results-EXP-P-007-selection`), the dev read from `dd81f73` (the code under `src/` is the same in all three). Outputs: `results/EXP-P-007/` (`select/<config>-s<seed>/`,
`selection.json`, `final/c2-n512-r32-s<seed>/`, `final/c2-n512-r32-ens/`), 22 manifests
`results-EXP-P-007-*`. The rows (`rows.pt`) stay in `data/interim/models/vocab/EXP-P-007/`; their sha256 are manifest
outputs. No sealed part was loaded.

**Selection (train only; (a) on 381 held-out-group patients of 76 genes, E0 MRR 0.5157; (b) on 2,979 train
patients; mean ± sd over seeds 0-2):**

| Config | (a) MRR ratio | (b) Δ MRR | Best epochs | Feasible |
|---|---|---|---|---|
| c1-n128-r8 | 0.518 ± 0.002 | −0.00272 | 253-255 | no |
| **c2-n512-r32** | **0.382 ± 0.016** | −0.00031 | 91-104 | yes, **selected** |
| c3-n512-r128 | 0.346 ± 0.018 | +0.00012 | 102-127 | yes |
| c4-n512-r128-lr3e-3 | 0.368 ± 0.014 | +0.00034 | 162-203 | yes |
| c5-n2048-r128 | 0.289 ± 0.003 | +0.00049 | 48-53 | yes |
| c6-n512-r256 | 0.292 ± 0.008 | +0.00043 | 121-134 | yes |

The highest feasible ratio is c2 (0.382); no other feasible configuration is within 0.01. Across the grid, more
pseudo-patients per gene lower (a) and raise (b).

**Dev read (`c2-n512-r32`, 173 genes relearned; ensemble of seeds 0-2):**

| | Patients (groups) | E0 MRR | Relearned MRR | Ratio [95% CI] | Δ MRR [95% CI] | Top-1 E0 → new | Top-10 E0 → new | Helped / harmed |
|---|---|---|---|---|---|---|---|---|
| **(a) gene relearned** | 1,547 (260) | 0.4818 | 0.1991 | **0.413 [0.305, 0.516]** | −0.28267 [−0.35650, −0.22141] | 0.352 → 0.105 | 0.745 → 0.412 | 227 / 1,100 |
| **(b) every other patient** | 336 (64) | 0.29520 | 0.29549 | 1.0010 [1.0001, 1.0024] | **+0.00029 [+0.00003, +0.00068]** | 0.280 → 0.280 | 0.321 → 0.321 | 18 / 5 |
| All dev | 1,883 (324) | 0.4485 | 0.2163 | | −0.23218 [−0.29081, −0.18385] | 0.339 → 0.136 | 0.669 → 0.396 | 245 / 1,105 |

(b) holds 133 patients of the 35 vocabulary genes without a masked profile and 203 out-of-vocabulary patients (rank
∞ under both systems).

- **Seeds:** (a) ratio 0.433, 0.411, 0.396 (0.413 ± 0.019); (b) Δ +0.00029, +0.00029, +0.00030.
- **Subsets of (a):** post-E0 publications 167 patients (35 groups): E0 MRR 0.0754, relearned 0.0615, ratio 0.816
  [0.618, 0.989], top-10 0.108 → 0.102. Gene in train 1,239: ratio 0.427 [0.290, 0.553]. Gene not in train 308:
  ratio 0.357 [0.229, 0.509].
- **Per gene (173):** median ratio of gene MRRs 0.379; 58 genes at ≥ 0.90; 53 genes with relearned MRR ≥ E0's.
- **Train check** (same rows, all 4,103 train patients): (a) 1,622 patients, E0 0.5372, relearned 0.2321, ratio 0.432
  [0.283, 0.556], top-10 0.696 → 0.356; (b) 2,481 patients, Δ +0.00220 [+0.00051, +0.00406], 515 helped / 125 harmed.
- **Rows:** final mean cosine to E0's rows 0.917-0.922; mean norm 237-255 (E0's rows: 268); initial largest |cosine|
  0.09-0.14. Best epochs 47-57.
- **Pipeline checks:** E0's dev and train ranks equal EXP-P-001's (0 differ). E0's own rows through the pipeline
  change 0 train ranks and 1 dev rank (the torch pooled vector reproduces the ONNX logits within 1e-3). Frozen rows
  and v3.0's classifier unchanged bit for bit; non-relearned logits equal E0's on every checked case (300 per part).
- **Ensemble rows** sha256 `2d3a9372b4055a129e958a4ff57166e31cbe87938f6f2b8cf8ff359e902eeff0`; seeds 0-2
  `8ff67ccd…`, `f1689b6e…`, `9c9495c3…`.
- **GPU (RTX 4070 Ti):** fitting 350 s for the 18 selection runs and 57 s for the 3 final seeds (peak 0.78 GB). Pooled
  vectors of pseudo-patients 521 s and 45 s, mostly CPU graph building. Wall time 14.8 min (selection) and 2.0 min
  (dev read).

## Verdict
**FAIL** against the registered criterion. (a) ratio 0.413 [0.305, 0.516] is below 0.90; (b) Δ +0.00029
[+0.00003, +0.00068] meets ≥ −0.001.

- Relearned rows keep calibration: they move other patients' ranks by less than E0's rows do.
- They place the relearned genes' own patients much lower than E0's rows: top-10 0.745 → 0.412.
- On post-E0 publications, where E0 has no home advantage, the ratio is 0.816 [0.618, 0.989]. This covers 167
  patients, with E0 MRR 0.075.
- The selection grid points the same way. More pseudo-patients per gene fit the masked annotations better (EXP-P-007
  pre-registration pilot: pseudo-MRR 0.80-0.85 vs E0's rows 0.79), while real-patient MRR falls (ratio 0.52 → 0.29).
- The step-2 description (adding the 133 annotated new genes) and the `p2-v1` test pre-registration are not written:
  the registration made them conditional on PASS.

## Addenda
