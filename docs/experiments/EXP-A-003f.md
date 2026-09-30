# EXP-A-003f: sex, age and onset into a frozen v3.0 (ADR-0010)

- **Front:** A
- **Registered:** 2026-09-29, by the Front A agent for Mateo Alvarez
- **Status:** **paused 2026-09-29 (graceful stop)**; resumes 2026-09-30.
  - Completed with manifests: `a003f-c1-cov16-lr1e-4-s0`,
    `a003f-c4-cov64-lr1e-4-s0` and the pipeline check.
  - Interrupted, no outputs kept: c2 and c5.
  - Not started: c3 and c6.
  - No verdict until the pre-registered grid is complete.

## Hypothesis
**H1 (primary):** with v3.0's weights frozen, training only a covariate head
(ADR-0009's `cov_mlp` → `cov_classifier`) on simulated patients' sex, age and
onset improves real patients: on R1-dev, "all" view (sex + age + onset; this
model ignores excluded terms), the selected configuration's Δ MRR vs E0 has a
publication-clustered 95% CI lower bound > 0 and harmed ≤ 5%, in each of its
3 seeds.

**H0 is a valid outcome.** Front B found sex, age and onset redundant with
the GNN's phenotype input on R1 (EXP-B-002: ≤ +0.002 each).

## Systems compared
| System | Artifact ids / code | Notes |
|---|---|---|
| E0 | `genphenia_v3` (model-v3.0.0): EXP-000's R1-dev and S2 ranks, EXP-S3-001's `E0+answers` | E0 ignores covariates, so its ranks are the same on every view |
| candidate `a003f-*` | `dxt gnn train-frozen --design cov` (`frozen_base`), width `cov_hidden` | v3.0 frozen; only `cov_mlp` and `cov_classifier` train |

## Frozen base and the covariate path
- As in EXP-A-002f: every v3.0 tensor frozen, eval mode throughout, and the
  same end-of-run identity checks (present-only logits bit-identical to
  v3.0 on CPU for all scorable R1-dev and S2 cases; R1-dev present-view
  ranks equal to EXP-000's; S2 ranks equal to the untrained model's; v3.0
  tensors unchanged). A run failing them is invalid.
- **Refinement of ADR-0009 §5 for the frozen base (`cov_neutral_zero`):**
  `cov_mlp` is two bias-free Linear + ReLU layers that read
  `[male, female, log1p(age), age_known, log1p(onset), onset_known]`, not
  the `sex_unknown` flag. A patient with no known sex, age or onset
  therefore gets exactly 0 from the covariate path whatever the weights, so
  the present-only view stays v3.0 after training too, as ADR-0010 requires.
  The known-flags play the role of the biases when a value is known.
- `cov_classifier` starts at 0 (no bias); `cov_mlp` is randomly initialised.

## Data
- **Gradients:** `ds-sim0.3.1-A-iv-v1`, split `train`, 100,217 interviewed
  cases (as EXP-A-002f). Input: reported present + "yes" answers, with the
  simulated patient's sex, age and onset (`simcal-train-v1` missingness):
  sex known in 92.3%, age in 74.6%, onset in 59.7% of training cases
  (counted from the artifact before registration). "No" answers are **not**
  given.
- **Early stopping:** the artifact's `val` split (20,864), MRR. Never R1.
- **Curves every epoch, epoch 0 = v3.0:** training loss; sim-val loss and
  MRR; R1-dev "present", "+sex", "+age" (age and onset) and "all" views,
  Δ vs E0 with publication CI; S2.
- **At the selected checkpoint:** every R1-dev view; S2; S3-dev "present"
  and "all" (sex/age/onset as reported).
- R1-dev has sex for 1,703, age for 1,636 and onset (value or term) for
  1,046 of its 1,883 patients (split statistics).
- **S3-dev is reported, not decisive:** S3 v1 shares the onset and
  inheritance knowledge that drives the simulator's age and sex with the
  systems, so it is circular for covariates (EXP-S3-001 Addendum 1).
- **Sealed reads:** none.

## Fixed recipe (not tuned)
As EXP-A-002f: AdamW on the new tensors (weight decay 5e-4), batch 256,
warmup 200 steps then cosine to 0.1 × `lr_new`, `max_epochs = 15`, early
stopping on sim-val MRR (patience 3, min Δ 1e-4), clipping 1.0, float32.

## Primary metric and gate
- **Primary (selection):** R1-dev Δ MRR vs E0, "all" view, paired bootstrap
  resampling publications (2,000, seed 0), with harmed rate. The "+sex" and
  "+age" views attribute it.
- **H1 holds** if the selected configuration has, in each of seeds 0, 1 and
  2, "all"-view CI lower bound > 0 and harmed ≤ 5%.
- **No-regression anchor (§9.4):** holds by construction (checked).
- **Warning flag (§9.3):** sim-val MRR up while R1-dev "all" MRR down, per
  epoch and from epoch 0 to the selected one. S2 cannot fall.

## Dev search
- **Budget: 8 configurations.** Every one is logged with its curves.
- **Grid (6):** `cov_hidden` ∈ {16, 64} × `lr_new` ∈ {1e-4, 1e-3, 1e-2}.
  Seed 0.
- **Reserved (2), used only by this rule:** if the selected configuration
  sits at an edge of the learning-rate grid, one more learning rate in that
  direction with the same width: 3e-2 above 1e-2, or 1e-5 below 1e-4. At
  most 2; selection is then repeated over all runs.
- **Run ids:** `a003f-c<k>-cov<width>-lr<lr>-s<seed>`.
- **Selection rule:**
  1. Valid runs pass every identity check.
  2. Eligible runs: R1-dev "all" Δ CI lower bound > 0 and harmed ≤ 5%.
  3. Pick the highest R1-dev "all" Δ. Within 0.001 of it, prefer width 16,
     then the lower learning rate.
  4. Re-run it with seeds 1 and 2; report mean ± sd of seeds 0–2.
- **If no run is eligible:** no candidate. The valid run with the highest
  R1-dev "all" CI lower bound is still re-run with seeds 1 and 2, labelled
  "not a candidate", to size the effect.
- **Also reported:** the median R1-dev "all" Δ of the grid.
- **Pipeline check (not a configuration):** `a003f-pipeline-check`, width
  16, `lr_new` 1e-3, 2,560 cases, 1 epoch.
- **Tried:** (filled in as runs complete).

## Expectations (written before running)
| Quantity | Expected |
|---|---|
| Sim-val MRR | Rises from 0.176; the head can learn the simulator's gene priors per sex and age, which says nothing about patients |
| R1-dev "all" Δ | Between −0.02 and +0.005; most likely ≈ 0 or slightly negative, with harmed above 5% at 1e-2 |
| "+sex" vs "+age" | Neither clearly > 0; any gain from sex concentrated on X-linked genes |
| R1-dev present | Exactly E0 |
| S3-dev "all" | Positive (circular; not evidence) |

## Results
(filled after running)

## Verdict
(filled after running)

## Addenda
