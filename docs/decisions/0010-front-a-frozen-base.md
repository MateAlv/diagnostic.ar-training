# ADR-0010: Front A keeps v3.0 frozen and trains only the new inputs' parameters

- **Status:** Accepted, 2026-09-29 (Mateo).
- **Refines:** ADR-0001, ADR-0009.
- **Replaces:** the A-002–A-004 plan of fine-tuning all weights.

## Context
EXP-A-001 fine-tuned all of v3.0's weights on simulated positives:
- R1-dev MRR fell by 0.09–0.21 in every configuration, harming 46–61% of
  patients;
- forgetting on S2 went from 0.81 to 0.68–0.75;
- every warning flag fired from epoch 1.

The cause is a distribution shift from an overconfident start: sim-val MRR
0.166, loss 24.6. It is not unlearning the held-out annotations (EXP-A-001
addendum). Any design that updates v3.0's weights on this data inherits the
harm.

## Decision
1. **v3.0's weights are frozen** (`requires_grad=False`, BatchNorm in eval
   mode). Only the zero-initialised parameters of ADR-0009 train:
   - the negated-node message gates and type projection (A-neg), or the
     separate negated pool and classifier (A-neg2);
   - the covariate MLP and its classifier contribution (A-cov).

   The "present only" view is then **exactly E0 by construction**. The
   no-regression anchor of EVAL_PROTOCOL §9.4 holds trivially, and every Δ
   is attributable to the new inputs.
2. **Training negatives are produced the way the app produces them.**
   - The simulator's own negatives follow R1's reporting mix (43% the
     disease's own absent features). S3 showed that a model learning that
     mix *hurts* in deployment (rr-v2: −0.030, harmed 28%).
   - So Front A training cases are **interviewed** like S3 cases: E0 ranks
     the reported presentation; the questioner (E0 top-10, `kb-v5`, Q = 7)
     picks questions; the simulated truth answers them. "Yes" answers join
     `present`; "no" answers become `excluded`.
   - This uses only half-A knowledge, same as S3's systems.
3. **Covariates** (sex, age, onset) come from the simulated patient, with
   `simcal-train-v1` missingness.

## Evaluation (unchanged protocol, with two declared caveats)
- **R1-dev** is the real-patient check for **sex, age and onset**, since R1
  covariates are real. For negation, R1 reflects papers' reporting (EXP-B-001
  Addendum 1), so it is reported but not decisive.
- **S3-dev** is the check for **negation** as the app produces it. Front A
  models are trained on the same simulator family, so S3 can overstate them
  relative to Front B's knowledge-only re-ranker (EXP-A-001 showed the same
  effect). This is declared next to every comparison.

## Alternatives considered
- **Anchored fine-tuning** (KL/distillation to v3.0). Still drifts under the
  same shift; not chosen.
- **Adding R1-train patients** (A-005). Deferred; it would use the most
  valuable real data.

## Consequences
- The experiments become A-002f (negation), A-003f (covariates) and A-004f
  (both). Each is pre-registered with ≤ 8 configurations and ≥ 3 seeds for
  the selected one.
- Frozen-base Front A and Front B's re-ranker converge in spirit: both add
  the new inputs on top of an unchanged v3.0. They differ in *learned from
  simulated data inside the network* vs *knowledge-based outside it*. The
  informe can compare the two directly.
