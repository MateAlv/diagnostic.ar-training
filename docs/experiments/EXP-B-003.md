# EXP-B-003: Phase-4 gate for rr-v1[neg=0.5] (one sealed S3-test read + R1-test no-regression)

- **Front:** B
- **Registered:** 2026-09-30, by Mateo Alvarez (approved 2026-09-30; written
  by the assistant)
- **Status:** planned

## Hypothesis
On S3-test, rr-v1[neg=0.5] improves on E0+answers with CI lower bound > 0
and harms ≤ 5% of patients. This is the configuration selected on S3-dev in
EXP-S3-001 (+0.0045 [+0.0034, +0.0056], harmed 4.0%). On R1-test it does
not cause clear harm.

## Systems compared
| System | Artifact ids / code | Notes |
|---|---|---|
| E0+answers | genphenia_v3 (model-v3.0.0) on reported present + "yes" answers | S3 reference |
| E0 | genphenia_v3 (model-v3.0.0) | R1 reference |
| **rr-v1[neg=0.5]** | `rerank.model.Weights(neg=0.5)`, `neg_strength` k = 0.5 | the only candidate |

- **Knowledge:**
  - S3 uses `kb-v5` (half B of `annot-split-v1` dropped), as in EXP-S3-001.
  - R1 uses `kb-v3` (R1 held-out PMIDs masked), as in EXP-B-001.
- **Settings:** the questioner uses Q = 7 over E0's top-10 genes, with
  top-k 200.
- **Nothing is new.** No weight, KB or setting differs from the dev runs
  that selected this configuration.
- **Only this candidate is scored.** `dxt s3 run --system "rr-v1[neg=0.5]"`
  scores only it (plus the E0 references), so no other system gets a
  test number.

## Data and reads
- **Step 0: reproduction on dev (not sealed).** Both commands below must
  reproduce the dev numbers exactly. **If either does not, stop: no
  sealed read happens.** The mismatch is logged and investigated.
  - `dxt s3 run --exp EXP-B-003 --part dev --system "rr-v1[neg=0.5]"`
    must give Δ +0.0045 [+0.0034, +0.0056], harmed 0.040
    (EXP-S3-001).
  - `dxt rerank eval --exp EXP-B-003 --cohort r1-v1/dev --neg 0.5` must
    give an "all" view Δ of −0.0067 [−0.0235, +0.0051], harmed 0.116
    (EXP-B-001).
- **Step 1: S3-test, sealed, read once.**
  `dxt s3 run --exp EXP-B-003 --part test --system "rr-v1[neg=0.5]" --reason "EXP-B-003 Phase-4 gate"`.
  `s3-v1/test` has 9,990 cases.
- **Step 2: R1-test, sealed, read once.**
  `dxt rerank eval --exp EXP-B-003 --cohort r1-v1/test --neg 0.5 --reason "EXP-B-003 no-regression"`.
  `r1-v1/test` has 2,548 patients.
- **Not read:**
  - the R1 vault;
  - MCRD and DDD, which have no excluded terms, so the feature cannot act
    on them.

## Primary metric and gate (fixed before any read)
- **Primary:** S3-test Δ MRR vs E0+answers, with a paired bootstrap 95% CI
  resampling genes.
  - **P1 passes** if the CI lower bound is > 0 **and** harmed is ≤ 0.05.
- **R1-test no-regression.** Resampling is by publication. R1's negations
  are features the authors chose to report as absent (EXP-B-001
  Addendum 1), not answers to the app's questions. So R1 is a harm
  tripwire, not an efficacy test.
  - **N1, "present" view** (excluded terms removed): Δ must be exactly 0.
    With no excluded terms the feature cannot act, so any other value is a
    code error, and the gate fails.
  - **N2, "all" view:** passes unless the CI upper bound is < 0
    (significant harm) **or** the point estimate is < −0.02 (three times
    the R1-dev estimate).
  - The "all" view is also reported on the cases that have excluded
    terms. That is descriptive only.
- **Gate verdict:** PASS only if P1, N1 and N2 all pass.
  - A PASS makes rr-v1[neg=0.5] a release candidate. Deployment still goes
    through `diagnostic.ar-model`, with optional API fields, and needs
    Mateo's decision.
  - A FAIL is final for this configuration on these splits. Nothing is
    re-tuned on test.

## Expectations (written before running)
| Check | Expected |
|---|---|
| P1 | Δ ≈ +0.004 to +0.005, harmed ≈ 4%; a pass is likely but not certain (dev harmed 4.0% is close to the 5% cap) |
| N1 | exactly 0 |
| N2 | Δ ≈ −0.007, CI including 0; passes |

## Declared residual dependencies
The same as EXP-S3-001 (EVAL_PROTOCOL §8):
- E0 knows half B;
- `genes-v1` weights are shared between the generator and the KB.

## Results
(filled after running)

## Verdict
(filled after running)
