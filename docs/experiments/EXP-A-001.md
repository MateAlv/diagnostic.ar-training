# EXP-A-001: fine-tuning v3.0 on our simulator's positives only

- **Front:** A
- **Registered:** 2026-09-29, by the Front A agent for Mateo Alvarez
- **Status:** done (2026-09-29)

## Hypothesis
**H1 (primary):** fine-tuning v3.0 on `ds-sim0.3.1-A-n100-s1001`'s training
split, with **present terms only** (no negated terms, no sex, no age), does
not hurt real patients: on R1-dev, present-only view, the selected
configuration's ΔMRR vs E0 has a publication-clustered 95% CI lower bound
≥ −0.01 in each of its 3 seeds.

**H1b (secondary):** it helps: the 3-seed mean Δ > 0 and each seed's CI
lower bound > 0.

This is the ladder's first rung (PLAN §6): the answer to "does our
simulator's data alone help or hurt?", before any new input is added.

## Systems compared
| System | Artifact ids / code | Notes |
|---|---|---|
| E0 | `genphenia_v3` (model-v3.0.0): EXP-000's per-case ranks (R1-dev present view, S2), EXP-S3-001's `E0+answers` ranks (S3-dev) | always included; ONNX Runtime, CPU |
| candidate | `a001-*`: `GinV3Extended.from_v3` with every new parameter frozen at 0 (`lr_new = 0`), so it is v3.0's architecture with fine-tuned v3.0 tensors | `dxt gnn train`, code `80a61b3`; PyTorch 2.14.0+cu130, RTX 4070 Ti |

## Data
- **Gradients:** `ds-sim0.3.1-A-n100-s1001` (manifest, sha-verified on
  load), simulator split `train`, minus exclusion artifact
  `ds-sim0.3.1-A-n100-s1001-excl-v1`. Measured before registration by
  reading the dataset only: 130 train, 6 val and 7 test cases dropped (143);
  **450,747 training cases**, 5,011 genes (218 of v3.0's 5,229 genes have no
  training case).
  - Positives only: each case enters as its `present` terms. `excluded`,
    sex, age and onset are not given to the model.
  - **Contamination (§9.7):** `dxt gnn train` refuses to run unless the
    residual (gene, present set) overlap of train + val with R1-train,
    R1-dev and S3-dev is 0 (case-insensitive gene, the artifact's key). The
    sealed cohorts are not read; their residual 0 is certified by the
    artifact's manifest, which the command also asserts. The S2 overlap is
    reported, not required to be 0.
- **Early stopping:** sim-val, the dataset's own `split == "val"` cases
  (25,294 after exclusion). Never R1.
- **Selection between configurations:** R1-dev (1,883) and S3-dev.
- **Curves, every epoch including epoch 0 (= v3.0 before any step):**
  - training loss;
  - sim-val loss and MRR;
  - R1-dev MRR, present-only view, with Δ vs E0 (publication CI) and
    harmed/helped. For this model every view is identical, since it sees
    present terms only, so the "all inputs" curve is the same curve;
  - S2 MRR (5,228, one upstream-style patient per gene) with Δ vs E0.
- **At the best checkpoint of each run:** the same, plus **S3-dev**: the
  10,210 interviewed S3-dev cases of EXP-S3-001 (same questions and
  answers), scored on present + "yes" answers; "no" answers are unused by
  an A-001 model. Δ vs EXP-S3-001's `E0+answers` ranks, CI resampling genes.
  The interviewed cases are produced once by `dxt s3 interviews`, which
  checks that E0 on them reproduces EXP-S3-001's `E0+answers` ranks.
- **S1** (the dataset's `split == "test"`, 24,916): once, at the end, for
  the selected configuration's seeds. Never a headline number.
- **Sealed reads:** none. No R1-test, R1-vault, MCRD, DDD or S3-test.

## Fixed recipe (not tuned)
| Setting | Value |
|---|---|
| Optimiser | AdamW, weight decay 5e-4 (v3.0's upstream default) |
| Parameter groups | v3.0 tensors at `lr_base`; new tensors frozen (`lr_new = 0`) |
| Batch | 256 cases |
| Schedule | linear warmup over 200 steps, then cosine decay to 0.1 × `lr_base` at `max_epochs` |
| Epochs | `max_epochs = 10`; early stopping on sim-val MRR, patience 2 epochs, min Δ 1e-4 |
| Checkpoint kept | best by sim-val MRR (epoch 0 included) and last |
| Clipping | global grad norm 1.0 |
| Dropout | v3.0's 0.3, active in training |
| Precision | float32. bf16 autocast was measured at 1.7× the training-step speed, but logits reach the hundreds, where bf16's resolution is about one logit unit; float32 already runs about 12,500 training cases/s, so it is not needed |
| Loss | cross-entropy over the 5,229 genes, no label smoothing |
| Loader | 10 workers, seeded permutation per epoch (`seed × 1000 + epoch`) |

Throughput measured before registration (`dxt gnn throughput`, simulated
training split only): loader 4,474 cases/s with 0 workers, 30,782 with 10;
training step 12,509 cases/s float32, 21,124 bf16; 1.0 GB GPU memory.

**Determinism:** data order and dropout are seeded. CUDA's `index_add`
backward uses atomics, so two runs with the same seed are not bit-identical.

## Primary metric and gate
- **Primary:** ΔMRR vs E0 on R1-dev, present-only view (identical to "all
  inputs" for this model), paired bootstrap resampling publications (2,000,
  seed 0).
- **No-regression anchor (§9.4), per run:** Δ CI lower bound ≥ −0.01, or the
  run is rejected.
- **Forgetting check (§9.3), per run:** S2 MRR ≥ 0.7917 (E0's 0.8117 −
  0.02), or the run is rejected.
- **H1 holds** if the selected configuration passes the anchor in all 3
  seeds. **H1b holds** if, in addition, the 3-seed mean Δ > 0 and each seed's
  CI lower bound > 0.
- **Warning flags, reported per run:**
  - sim-val MRR up while R1-dev MRR down, epoch over epoch, and from epoch 0
    to the best epoch;
  - S2 below 0.7917 at any epoch.

## Dev search
- **Budget: 8 configurations.** Every one is logged with its curves,
  failures included.
- **Grid (6):** `lr_base` ∈ {1e-5, 5e-5, 2e-4} × BatchNorm ∈ {`train`
  (batch statistics, running statistics updated), `frozen` (v3.0's running
  statistics kept; affine parameters trained)}. Seed 0.
  - Why BatchNorm: in training mode the running statistics drift toward our
    simulator's distribution at any learning rate, which is itself a route
    to forgetting.
- **Reserved (2), used only by this rule:** if the selected configuration
  sits at an edge of the learning-rate grid, one more learning rate is run
  in that direction with the same BatchNorm mode: 5e-4 (the §9.6 cap) above
  2e-4, or 2e-6 below 1e-5. Selection is then repeated over all passing
  runs. At most 2 such runs; otherwise the budget stays unused.
- **Run ids:** `a001-c<k>-lr<lr>-bn<mode>-s<seed>`.
- **Selection rule:**
  1. Keep the runs that pass the anchor and the forgetting check, each
     evaluated at its best-sim-val checkpoint.
  2. S3-dev acts as a veto: drop a run whose S3-dev Δ CI upper bound is
     < 0.
  3. Pick the highest R1-dev MRR. Within 0.001 of it, prefer the lower
     learning rate, then BatchNorm `frozen`.
  4. Re-run the selected configuration with seeds 1 and 2. It is reported
     as the mean ± sd of seeds 0, 1 and 2, never its best seed.
- **If no run passes:** A-001 has no candidate. The configuration with the
  highest R1-dev CI lower bound is still re-run with seeds 1 and 2, labelled
  "not a candidate", to size the effect and its variance.
- **Also reported:** the median R1-dev MRR of all configurations (§5).
- **Pipeline check (not a configuration; not used for selection):** before
  the grid, one run `a001-pipeline-check` with `lr_base = 1e-5`, 2,560
  training cases and 1 epoch. It verifies that every output and the
  manifest are written, and that epoch 0 reproduces E0: on R1-dev exactly
  (Δ = 0, harmed 0, as EXP-A-000's GPU run), on S2 up to float32 rounding
  (EXP-A-000 saw 1 GPU rank change in 1,000 cases). Its numbers are
  reported and not used.
- **Infrastructure failures** (a crash or a bug in the command) are logged
  and re-run under a new run id. They do not count as configurations, and
  their partial curves are kept.
- **Tried:** the pipeline check, the 6 grid configurations, and seeds 1
  and 2 of `c1` under the "no run passes" rule. The 2 reserved runs were
  not triggered: their rule requires a *selected* configuration, and there
  was none. Every run is in the Results table.

## Expectations (written before running)
Known before registration: E0 on sim-val has MRR **0.166** (top-1 0.126,
top-10 0.244), far below its 0.448 on R1-dev and 0.812 on S2. Our simulator's
patients are hard for v3.0: noise terms, missing findings, profiles without
half B.

| Quantity | Expected |
|---|---|
| Sim-val MRR | Rises a lot, to 0.3–0.5. This is not evidence of real-patient gains |
| R1-dev Δ | Between −0.04 and +0.01. Most likely ≈ 0 at 1e-5 and negative at 2e-4 |
| S2 | Falls with the learning rate. The 218 genes without training cases (4.2% of S2) are pushed down by the softmax; that alone could cost up to ~0.03, so the forgetting flag is likely at 2e-4 |
| S3-dev Δ | Positive (+0.01 to +0.05). S3 comes from the same simulator family (§8 residual dependency), so this overstates real gains |
| BatchNorm frozen vs train | Within ±0.005 on R1-dev; frozen slightly safer on S2 |
| Warning "sim-val up, R1-dev down" | Likely at 5e-5 and 2e-4 |

## Results
- **Code:** pre-registered in `4d51b63`, with the training code from
  `80a61b3`. Every run ran from `66c6ff6`, which adds only `dxt gnn report`
  and the S3 interview manifest; the training code is unchanged.
- **Files:** `results/EXP-A-001/<run-id>/`, each with `curves.json` (every
  epoch), `summary.json`, `run.json` (config, data counts, contamination),
  R1-dev per-case ranks (full records), and S2/S3-dev per-case ranks
  (compact).
  - The whole table, with every curve: `results/EXP-A-001/report.json`
    (`dxt gnn report`).
  - One manifest per run, `results-EXP-A-001-<run-id>`; per S1 read,
    `…-s1`.
  - Checkpoints stay local, in `data/interim/models/<run-id>/`
    (best + last, 72 MB per run, 623 MB in total).
- **S3-dev interview** (`s3-v1-dev-interviews-kb-v5-c10-q7`, run once):
  10,210 cases, 6.88 questions, 0.75 "yes" and 6.13 "no" per case. **E0 on
  them reproduces EXP-S3-001's `E0+answers` ranks on 10,210 of 10,210
  cases.**
- **Data as loaded:** 143 excluded cases dropped (130 train, 6 val, 7 test).
  Every `gene_index` matches `genes.json` on all 500,957 kept cases.
  - Residual (gene, present set) overlap of train + val: **0** with
    R1-train (4,103), R1-dev (1,883) and S3-dev (10,210).
  - S2 (reported only): 2 of 5,228.
- **Pipeline check** (`a001-pipeline-check`; not a configuration):
  - Epoch 0 = E0: R1-dev Δ 0.0 exactly, harmed 0, helped 0.
  - S2: 1 rank change in 5,228 (Δ −8e-9). S3-dev: 11 of 10,210 changed
    (Δ +8e-8). Both are float32 GPU rounding against the CPU ONNX
    reference.
  - After just 10 steps at lr ≤ 5e-7 (BatchNorm `train`), R1-dev had
    already moved by −0.0035.
- **Throughput:**
  - Training: 14,300 cases/s (31.5 s per epoch of 450,747 cases, float32,
    10 loader workers; the GPU waits on data 0.6 s per epoch).
  - Per-epoch evaluation (sim-val 25,294 + R1-dev + S2): 8.3 s.
  - A 10-epoch run: 7.3 min wall. Peak GPU memory 1.63 GB.

**Every configuration, at its best-sim-val checkpoint** (Δ vs E0; R1-dev
CI resamples publications, S3-dev CI resamples genes):

| Run | lr | BN | Best / run epochs | Sim-val MRR (E0 0.166) | R1-dev MRR (E0 0.4485) | R1-dev Δ [95% CI] | Harmed / helped | S2 MRR (E0 0.8117) | S3-dev Δ vs E0+answers [95% CI] | Anchor | S2 check |
|---|---|---|---|---|---|---|---|---|---|---|---|
| c1-s0 | 1e-5 | train | 10 / 10 | 0.281 | 0.3572 | −0.0913 [−0.1223, −0.0588] | 46.1% / 14.4% | 0.7501 | +0.1116 [+0.1044, +0.1188] | ❌ | ❌ |
| c2-s0 | 5e-5 | train | 10 / 10 | 0.427 | 0.2664 | −0.1821 [−0.2235, −0.1381] | 58.0% / 12.2% | 0.7115 | +0.2177 [+0.2084, +0.2266] | ❌ | ❌ |
| c3-s0 | 2e-4 | train | 10 / 10 | 0.499 | 0.2438 | −0.2047 [−0.2445, −0.1627] | 60.3% / 11.7% | 0.6806 | +0.2643 [+0.2543, +0.2736] | ❌ | ❌ |
| c4-s0 | 1e-5 | frozen | 10 / 10 | 0.315 | 0.3208 | −0.1277 [−0.1640, −0.0910] | 52.5% / 13.4% | 0.7318 | +0.1397 [+0.1318, +0.1472] | ❌ | ❌ |
| c5-s0 | 5e-5 | frozen | 10 / 10 | 0.450 | 0.2594 | −0.1891 [−0.2305, −0.1465] | 60.3% / 10.6% | 0.6988 | +0.2303 [+0.2210, +0.2393] | ❌ | ❌ |
| c6-s0 | 2e-4 | frozen | 10 / 10 | 0.504 | 0.2410 | −0.2075 [−0.2478, −0.1641] | 60.7% / 11.2% | 0.6762 | +0.2649 [+0.2550, +0.2745] | ❌ | ❌ |
| c1-s1 | 1e-5 | train | 10 / 10 | 0.281 | 0.3575 | −0.0909 [−0.1221, −0.0584] | 46.1% / 14.4% | 0.7498 | +0.1117 [+0.1046, +0.1191] | ❌ | ❌ |
| c1-s2 | 1e-5 | train | 10 / 10 | 0.281 | 0.3555 | −0.0929 [−0.1245, −0.0599] | 46.4% / 14.2% | 0.7497 | +0.1117 [+0.1045, +0.1190] | ❌ | ❌ |

- **Median R1-dev MRR** of the 6 configurations: 0.2629. Best: c1,
  0.3572.
- **Warning flags, in every run:**
  - "sim-val up, R1-dev down" from epoch 0 to the best epoch, and on most
    epochs (c1: epochs 1 and 3–10);
  - S2 below 0.7917 at **every** epoch from 1 on.
- **Early stopping never fired:** sim-val MRR still rose at epoch 10 in every
  run (+0.0003 to +0.0015 over epoch 9), so every best checkpoint is the
  last epoch.
- **R1-dev after one epoch** was already Δ −0.077 (c1) to −0.186 (c6). The
  loss is largest at the start: sim-val cross-entropy fell from 24.6 (E0) to
  7.3 after one epoch at 1e-5, while sim-val MRR only went from 0.166 to
  0.187.
- **Gradient clipping** (norm 1.0) was active on 100% of steps in every run.
  Mean grad norm was 70–75 in epoch 1 at 1e-5 (13–14 at 2e-4) and 1.8–3.3
  in epoch 10.
- **BatchNorm:** `frozen` was worse than `train` at 1e-5 (−0.128 vs
  −0.091) and about equal at 5e-5 and 2e-4. The running-statistics drift is
  not the main cause of the drop.

**S2 by gene** (exploratory; c1-s0 shown, the others are in
`report.json`):

| Subset | n | E0 | c1-s0 |
|---|---|---|---|
| Genes with training cases | 5,011 | 0.8097 | 0.7497 |
| Genes without (218 in v3.0, 217 in S2) | 217 | 0.8584 | 0.7590 |

The expectation that forgetting would concentrate on the untrained genes was
wrong: S2 falls about as much on genes that do have training cases.

**The configuration re-run with 3 seeds** (c1: lr 1e-5, BN `train`;
labelled **not a candidate**, since it fails the anchor), mean ± sd over
seeds 0, 1, 2:

| Metric | Mean ± sd |
|---|---|
| R1-dev MRR | 0.3567 ± 0.0011 (E0 0.4485) |
| R1-dev Δ | **−0.0917 ± 0.0011**; CI lower bounds −0.1230 ± 0.0013 |
| R1-dev harmed | 46.2% ± 0.2% |
| S2 MRR | 0.7499 ± 0.0002 |
| S3-dev Δ vs E0+answers | +0.1117 ± 0.0001 |
| Sim-val MRR | 0.2810 ± 0.0002 |
| S1 MRR (`dxt gnn s1`, 24,916 cases; E0 0.1683) | 0.2863 ± 0.0003 (Δ +0.1180) |

Seeds barely matter: every sd is ≤ 0.0013, far below the effect.

**Expectations vs outcome:**

| Quantity | Expected | Observed |
|---|---|---|
| Sim-val MRR | 0.3–0.5 | 0.28–0.50 ✓ |
| R1-dev Δ | −0.04 to +0.01 | **−0.09 to −0.21** ✗ (much worse) |
| S2 | falls; the flag likely at 2e-4 | falls at every lr and every epoch; the flag fires everywhere ✗ |
| Forgetting mechanism | the 218 untrained genes | general, not concentrated on them ✗ |
| S3-dev Δ | +0.01 to +0.05 | **+0.11 to +0.26** (larger) |
| BN frozen vs train | ±0.005 | frozen worse at 1e-5 (−0.036); ≈ equal at higher lr |
| "Sim-val up, R1-dev down" | likely at 5e-5 and 2e-4 | at every lr |

## Verdict
❌ **H1 rejected. Fine-tuning v3.0 on our simulator's positives alone hurts
real patients.**
- No configuration passes the no-regression anchor or the S2 forgetting
  check. A-001 has **no candidate**.
- The least harmful configuration (lr 1e-5, BN `train`, 3 seeds) loses
  **0.092 ± 0.001** R1-dev MRR, with 46% of R1-dev patients ranked worse.
  It also drops S2 from 0.812 to 0.750.
- **H1b** (helps) is moot.

What the curves show:
- The model learns our simulator, not patients. The gain is large on
  everything our generator produced:
  - sim-val +0.11 to +0.34;
  - S1 +0.118;
  - S3-dev +0.11 to +0.26.

  It is negative on everything it did not produce: R1 (real) and S2 (the
  upstream generator v3.0 was trained on).
- The damage happens in the first epoch, even at the smallest learning
  rate, and grows with the learning rate.
- This is exactly the failure §9 was written to catch. It also confirms
  that S3's gains cannot be read as real gains for a model trained on the
  same generator family (§8's declared residual dependency). Here the S3-dev
  Δ has the opposite sign to R1-dev.

Evidence for the next rungs (Mateo's call; nothing here was tried):
- A-002 to A-004 add inputs to this same training signal. Their Δ would be
  measured against a starting point this experiment shows is harmful.
  Something that keeps the model near v3.0 seems to be needed first.
  Options:
  - a smaller total update (fewer steps than one epoch, or lr below 1e-5;
    the reserved 2e-6 run was not triggered);
  - a penalty toward v3.0's outputs (distillation/KL);
  - mixing in upstream-style simulations;
  - R1-train patients (A-005).
- The epoch-0 sim-val loss (24.6 for an MRR of 0.166) says v3.0 is extremely
  confident on cases it ranks poorly. Part of the early movement may be the
  logit scale shrinking rather than the ranking changing. The pipeline
  check's 10 near-zero-lr steps already moved R1-dev by −0.0035.

## Addenda

### 2026-09-29, Addendum (lead, exploratory, R1-dev only): is the harm "unlearning half B"?
Hypothesis: the training data comes from profiles without half B, so
fine-tuning might teach the model to forget the held-out associations v3.0
knew.

**Rejected.**
- Only 7.5% of R1-dev present terms are explained by half B alone (in the
  held-out-masked KB); 56 of 1,611 cases (3.5%) rely on half B entirely.
- A-001 c1's damage is *smaller* on cases with ≥ 30% half-B-only terms
  (Δ −0.057, n = 86) than on the rest (Δ −0.107, n = 1,525).

The harm is distribution shift. v3.0 scores MRR 0.166 on our simulated
patients (0.81 on the upstream-style S2) with a loss of 24.6: it is highly
overconfident on noisier, less complete presentations. Gradient clipping was
active on every step, and the model moves away from what makes it strong on R1
within one epoch.
