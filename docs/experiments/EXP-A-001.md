# EXP-A-001: fine-tuning v3.0 on our simulator's positives only

- **Front:** A
- **Registered:** 2026-09-29, by the Front A agent for Mateo Alvarez
- **Status:** running

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
- **Tried:** (filled in as runs complete)

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
(filled after running; `results/EXP-A-001/`)

## Verdict
(filled after running)

## Addenda
