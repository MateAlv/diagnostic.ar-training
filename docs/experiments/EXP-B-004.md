# EXP-B-004: Re-ranker v1.1 (L1 negation limit, L2 enriched frequencies, L3 fair sex and age) on S3 v2

- **Front:** B
- **Registered:** 2026-10-03, by Mateo Alvarez (written by the assistant)
- **Status:** planned. The design is fixed now. The **final system list for
  the sealed read is added as a dated addendum before the read** (phase 4),
  chosen by the selection rule below.
- **Governing decision:** ADR-0014.

## Hypotheses
- **H1 (L1):** some negation penalty form or weight beats rr-v1[neg=0.5] on
  S3-v2-dev under the harm cap (harmed ≤ 5%).
- **H2 (L2):** P(term | gene) from the enriched knowledge (`kb-v7`) beats
  `kb-v6`'s on the same penalty. It must also hold on half-B-only excluded
  terms.
- **H3 (L3):** on the lit-onset subset, age and onset features improve over
  negation-only. Sex features improve over negation-only on cases with known
  sex.
- **H0 (expected for L3, given EXP-B-001):** no gain from sex or age.

## Systems
- **E0+answers** (the reference). Every Δ is against it.
- **rr-v1[neg=0.5] on kb-v5:** the released system, tuned on S3-v1-dev and
  never seeing S3 v2. It is the bar to beat.
- **Search arms (dev only):**

| Lever | Arms | Budget |
|---|---|---|
| L1 | Penalty form × weight × k: (i) the current log(1 − k·P); (ii) frequency-gated, only terms with P(t \| g) ≥ τ, τ ∈ {0.2, 0.4}; (iii) per-gene penalty cap; (iv) ancestor-propagated "no" (a "no" to a term also counts against its descendants). Weights {0.5, 0.75, 1, 1.5, 2, 3}, k {0.5, 0.8} | ≤ 48 configurations |
| L2 | The best L1 forms on kb-v6 vs kb-v7 | ≤ 6 |
| L3 | Sex (sex_prior, sex_restricted) and age (age_mean, age_any, onset) added to the best L1+L2, weights {0.5, 1, 2} | ≤ 12 |

## Data
- **Patients:** `s3-data-v2` (ADR-0014), split `s3-v2`. Search reads dev
  only; test is sealed, one read.
- **Interview:** the S3 v1 questioner (Q0, E0 top-10 information gain,
  non-adaptive), Q = 9.
- **Knowledge:** half B of `annot-split-v2` dropped (`kb-v6`, `kb-v7`).
- **Real patients:** R1-dev during the search (no harm: CI upper bound ≥ 0
  and point estimate ≥ −0.02); **one** R1-test read for the final system.

## Primary metric and selection rule (fixed now)
- **Primary metric:** Δ MRR vs E0+answers, with a paired bootstrap 95% CI
  over **genes**.
- **Selection on dev:** maximise Δ MRR subject to harmed ≤ 5%, CI lower
  bound > 0 and the R1-dev no-harm check. A tie (within 0.001) goes to the
  simpler system.
- **L1 also reports the frontier:** Δ MRR against harmed for every arm, and
  "the limit" is the best Δ at harmed ≤ 5%, ≤ 7.5% and ≤ 10%.
- **The sealed read** scores in one read: the final system, rr-v1, and
  pre-registered ablations (the final system minus L2, minus L3).
- **The gate for `rerank-v1.1.0`:**
  - S3-v2-test: the final system beats rr-v1 with CI lower bound > 0 on the
    paired difference, and harmed ≤ 5% vs E0+answers;
  - R1-test: no regression (EXP-B-003 N1/N2 rules).

## Declared residual dependencies
- E0 knows half B.
- The generator and kb-v7 share half-A frequencies (L2 is checked on
  half-B-only terms).
- Inheritance is shared truth.
- Candidate 6 did not pass the Front A data gate (declared in ADR-0014).

## Dev search log
(Filled in during phase 3. Every configuration, not only the winner.)

## Results
(After the sealed read.)
