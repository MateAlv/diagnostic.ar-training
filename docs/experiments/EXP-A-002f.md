# EXP-A-002f: negated answers into a frozen v3.0 (ADR-0010)

- **Front:** A
- **Registered:** 2026-09-29, by the Front A agent for Mateo Alvarez
- **Status:** planned

## Hypothesis
**H1 (primary):** with v3.0's weights frozen, training only the negation
parameters of ADR-0009 on interviewed simulated cases improves ranking when
the patient's "no" answers are given as excluded terms: on S3-dev, the
selected configuration's Δ MRR vs `E0+answers` (all inputs view) has a
gene-clustered 95% CI lower bound > 0 and harmed ≤ 5%, in each of its 3
seeds.

**H0 is a valid outcome:** if no configuration meets it, A-002f has no
candidate and that is reported as such.

## Systems compared
| System | Artifact ids / code | Notes |
|---|---|---|
| E0 | `genphenia_v3` (model-v3.0.0): EXP-000's R1-dev ranks, EXP-000's S2 ranks, EXP-S3-001's `E0+answers` ranks | E0 reads present terms only, so its ranks are the same on every view |
| candidate `a002f-*` | `GinV3Extended.from_v3` via `dxt gnn train-frozen` (`frozen_base`), design `neg` (A-neg: gated negated messages + negated type column) or `neg2` (A-neg2: + separate negated pool and zero-init classifier) | v3.0 frozen; only the new negation tensors train |
| reference, not re-run | rr-v1[neg=0.5] (EXP-S3-001): S3-dev Δ +0.0045 [+0.0034, +0.0056], harmed 4.0% | Front B's knowledge-only re-ranker, same cases and answers |

## Frozen base: what is trained and what cannot move
- Every v3.0 tensor has `requires_grad = False` and the whole model runs in
  eval mode during training (BatchNorm running statistics, no dropout).
- Trainable: `neg_gates` (3 layers), the **negated column** of `type_proj`
  (its observed/ancestor columns are held at 0 by a gradient mask: they
  would otherwise be a new input of the present-only view), and for `neg2`
  the negated pool and `neg_classifier`.
- By construction a case without negated terms gives v3.0's logits bit for
  bit, before and after training (tested on a toy model through training
  and on the production weights with random new tensors).
- **Every run ends with these checks** at its selected checkpoint, and a run
  failing any of them is invalid (logged, not a configuration):
  - present-only logits bit-identical to v3.0 on CPU for every scorable
    R1-dev and S2 case;
  - R1-dev present-view ranks equal to EXP-000's on all 1,883 cases;
  - S2 ranks equal to the untrained model's (S2 has no new input);
  - every v3.0 tensor unchanged; the positive `type_proj` columns still 0.
- Checkpoints hold the new tensors only (v3.0's come from the pinned
  bundle); best and last, under `data/interim/models/<run-id>/`.

## Data
- **Gradients:** `ds-sim0.3.1-A-iv-v1`, split `train`: 100,217 cases (20
  per gene, 5,011 genes), from `ds-sim0.3.1-A-n100-s1001` minus
  `…-excl-v1`, each interviewed like S3 (E0 top-10, `kb-v5` without half B,
  Q = 7, answers from `true_present`). Before registration, reading only the
  artifact's manifest: 6.97 questions, 0.49 "yes" and 6.47 "no" per case;
  466 cases got no question.
  - Input: reported present + "yes" answers as present; "no" answers as
    negated nodes. Sex, age and onset are **not** given (A-003f).
  - Contamination (§9.7): the artifact certifies 0 residual (gene, present
    set) overlap with R1 (all parts), the raw S3 presentations and the
    interviewed S3-dev cases (3 cases dropped at build). The command
    re-checks train + val against R1-train, R1-dev and S3-dev and refuses to
    run on any overlap.
- **Early stopping:** the artifact's `val` split (20,864 interviewed cases),
  MRR. E0 on it: 0.1759 (from the manifest). Never R1, never S3.
- **Curves every epoch, epoch 0 = v3.0:** training loss; sim-val loss and
  MRR; R1-dev "present" and "+excluded" views, Δ vs E0 with publication CI;
  S2.
- **At the selected checkpoint:** every R1-dev view (present, excluded,
  sex, age, all); S2; S3-dev "present" (must be `E0+answers` up to GPU
  float rounding) and "all" (+ "no" answers as excluded) on the 10,210
  interviewed cases of `s3-v1-dev-interviews-kb-v5-c10-q7`, Δ vs
  EXP-S3-001's `E0+answers`, CI resampling genes.
- **Sealed reads:** none.

## Fixed recipe (not tuned)
| Setting | Value |
|---|---|
| Optimiser | AdamW on the new tensors only, weight decay 5e-4 |
| Batch | 256 cases |
| Schedule | linear warmup 200 steps, cosine to 0.1 × `lr_new` at `max_epochs` |
| Epochs | `max_epochs = 15`; early stopping on sim-val MRR, patience 3, min Δ 1e-4 |
| Clipping | global grad norm 1.0 |
| Precision | float32 |
| Loss | cross-entropy over 5,229 genes |
| Loader | 10 workers, seeded permutation per epoch |

## Primary metric and gate
- **Primary (selection):** S3-dev Δ MRR vs `E0+answers`, "all" view,
  paired bootstrap resampling genes (2,000, seed 0), with harmed rate.
- **H1 holds** if the selected configuration has, in each of seeds 0, 1
  and 2, CI lower bound > 0 and harmed ≤ 5%.
- **R1-dev "+excluded" and "all" views:** reported, not decisive. R1's
  absent findings are the authors' choice of the syndrome's typical
  negatives (EXP-B-001 Add. 1, EXP-B-002), the opposite process to the
  app's. A negative R1 "+excluded" Δ is expected and is flagged, not a
  veto.
- **No-regression anchor (§9.4):** holds by construction (the checks above).
- **Warning flag (§9.3):** sim-val MRR up while R1-dev "+excluded" MRR
  down, per epoch and from epoch 0 to the selected one. S2 cannot fall.
- **Declared caveat on every S3 number:** the training cases come from the
  same simulator family as S3 (EVAL_PROTOCOL §8; EXP-A-001 saw S3-dev rise
  +0.11 while R1 fell −0.09). A Front A S3 gain is therefore an upper bound
  relative to Front B's knowledge-only rr-v1, and the comparison with
  rr-v1[neg=0.5] is reported with that caveat, never as a win by itself.

## Dev search
- **Budget: 8 configurations.** Every one is logged with its curves.
- **Grid (6):** design ∈ {`neg`, `neg2`} × `lr_new` ∈ {1e-4, 1e-3, 1e-2}.
  Seed 0.
- **Reserved (2), used only by this rule:** if the selected configuration
  sits at an edge of the learning-rate grid, one more learning rate in that
  direction with the same design: 3e-2 above 1e-2, or 1e-5 below 1e-4.
  Selection is then repeated over all runs. At most 2.
- **Run ids:** `a002f-c<k>-<design>-lr<lr>-s<seed>`.
- **Selection rule:**
  1. Valid runs pass every identity check.
  2. Eligible runs: S3-dev "all" Δ CI lower bound > 0 and harmed ≤ 5%.
  3. Pick the highest S3-dev Δ. Within 0.001 of it, prefer `neg` (fewer
     parameters), then the lower learning rate.
  4. Re-run it with seeds 1 and 2; report mean ± sd of seeds 0–2.
- **If no run is eligible:** no candidate. The valid run with the highest
  S3-dev CI lower bound is still re-run with seeds 1 and 2, labelled "not a
  candidate", to size the effect.
- **Also reported:** the median S3-dev Δ of the grid.
- **Pipeline check (not a configuration, not used for selection):**
  `a002f-pipeline-check`, design `neg2`, `lr_new` 1e-3, 2,560 training
  cases, 1 epoch. It verifies outputs, manifest and the end-of-run checks.
- **Infrastructure failures** are logged and re-run under a new id; they
  are not configurations.
- **Tried:** (filled in as runs complete).

## Expectations (written before running)
| Quantity | Expected |
|---|---|
| Sim-val MRR | Rises from 0.176 to 0.20–0.30 (`neg`) and more for `neg2`; not evidence of anything real |
| S3-dev Δ ("all") | Positive, +0.005 to +0.03; `neg2` ≥ `neg`. Larger than rr-v1[neg=0.5]'s +0.0045 is likely and would still carry the same-simulator caveat |
| S3-dev harmed | Around 5%; higher at 1e-2 |
| R1-dev "+excluded" | Negative, −0.005 to −0.04: R1's negatives are the reporting pattern |
| R1-dev present / sex / age | Exactly E0 (Δ 0, harmed 0) |
| S2 | Exactly E0's untrained-model ranks |

## Results
(filled after running)

## Verdict
(filled after running)

## Addenda
