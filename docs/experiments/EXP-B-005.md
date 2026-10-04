# EXP-B-005: Symptom-onset age in the re-ranker, fair test on S3 v3

- **Front:** B
- **Registered:** 2026-10-04, by Mateo Alvarez (written by the assistant)
- **Status:** planned. The chosen w is added as a dated addendum before the
  sealed read.
- **Governing decision:** ADR-0015.

## Hypothesis
When the patient's onset comes from a source independent of the
re-ranker's knowledge, adding the `onset` feature to F improves ranking on
interviewed simulated patients without exceeding the 5% harm cap.

## Systems
| System | Config |
|---|---|
| F | `8ecd5b320f33` |
| F + onset w | w ∈ {0.25, 0.5, 1}, chosen on S3-v3-dev |

Interview: Q2b (λ 0.6), budget 9.

## Data
- `s3-data-v3` (ADR-0015), split `s3-v3`: dev 30%, test 70% (sealed, one
  read).
- R1-dev for the no-harm check during selection.

## Primary metric and gate (fixed now)
- **Metric:** the paired Δ (F + onset_w) − F in MRR, bootstrap 95% CI over
  genes (seed 0, 2,000 resamples).
- **The gate:** CI lower bound > 0, and harmed (F + onset_w vs
  E0+answers) ≤ 5%.

## Expectation (written before running)
A small or null effect. On S3 v2's fair subset the gain over F was
+0.0021 [−0.0027, +0.0063]. A null result is a valid outcome.

## Dev search log
(Filled in during phase 2.)

## Results
(After the sealed read.)

## Addendum, 2026-10-04 (before any S3 v3b data): S3 v3b, literature-onset primary
Same change as the ADR-0015 addendum of this date.
- S3 v3 (120 genes) is superseded and was never evaluated. The data is `s3-data-v3b` (397 genes, "any entity" rule,
  about 15,000 cases, seed 4005), split `s3-v3b` (dev 30% / test 70%, test sealed, one read).
- **Primary analysis:** both the dev selection of w and the sealed gate (P1) are computed on **literature-onset
  cases only** (`metadata.onset_age_source == "literature"`, ids in the `s3-data-v3b` outputs). The bootstrap CI
  is over genes (seed 0, 2,000 resamples), among genes with at least one such case in the part.
- **Secondary:** the same on all cases; known-onset only; split by the kb `onset_source`.
