# EXP-B-006: release candidate rr-v1[neg=0.5] + onset 0.25 (rerank-v1.1.0)

- **Front:** B
- **Registered:** 2026-10-04, by Mateo Alvarez (approved 2026-10-04; written by the assistant)
- **Status:** phase 1 (dev justification), not final. The full pre-registration of the sealed read replaces this
  text in a later commit, before any sealed load.
- **Governing decisions:** ADR-0015 (onset), ADR-0014 (rr-v1 and S3).

## Hypothesis
Adding the `onset` feature at weight 0.25 to the production re-ranker (rr-v1[neg=0.5], `rerank-v1.0.0`) improves
ranking on interviewed simulated patients without exceeding the 5% harm cap, and does not harm real patients.

## Dev justification (written before the dev run)
EXP-B-005 measured onset on top of F, not on top of the rr-v1 formula. One dev configuration, S3-v3b-dev only:
- **Arms:** rr-v1 (`neg_llr` 0.5) and rr-v1 + onset 0.25, both on kb-v6 (S3 needs a KB without half B of
  `annot-split-v2`; kb-v3 would leak half B into S3 patients).
- **Interview:** one Q2b interview (lambda 0.6, budget 9, noise 0) driven by rr-v1; both arms are scored on the same
  answers. Exclusion list `s3-data-v3b-excl-v1` applied.
- **Primary population:** the literature-onset dev cases, as in EXP-B-005. CI over genes (seed 0, 2,000 resamples).
- **Checks:** paired delta (rr-v1 + onset 0.25) minus rr-v1; harmed share against E0+answers; the R1-dev no-harm check
  with EXP-B-005's rule (CI upper bound >= 0 and point estimate >= -0.02, "all" view).
- **Stop rule:** if the delta CI lower bound is not > 0, or harmed > 5%, or the R1-dev check fails, there is no
  candidate, nothing is pre-registered for a sealed read, and this experiment is reported as a dev failure.
