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
