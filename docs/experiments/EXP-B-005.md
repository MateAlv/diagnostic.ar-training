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
Phase 2, 2026-10-04. Data: `s3-data-v3b`, split `s3-v3b`, dev part only, exclusion list `s3-data-v3b-excl-v1`
applied (4,577 dev cases, 15 excluded, 4,562 interviewed). One Q2b interview (λ 0.6, budget 9, noise 0) driven by F;
F and the three candidates scored on the same answers (F's ranks from the interview and from the scoring path agree on
every case). Primary population: the 2,934 literature-onset dev cases. CI over genes (seed 0, 2,000 resamples).
Files: `results/EXP-B-005/dev-search.tsv`, `dev-analysis.md`, `dev/`.

| arm | config | Δ vs F [95% CI] | harmed vs E0+answers | R1-dev Δ [CI] | R1-dev no-harm | feasible |
|---|---|---|---|---|---|---|
| F + onset 0.25 | `871fd89b8368` | +0.0021 [+0.0006, +0.0036] | 4.16% | −0.0006 [−0.0086, +0.0060] | pass | yes |
| F + onset 0.5 | `458768f1bca4` | +0.0035 [+0.0011, +0.0058] | 6.00% | −0.0004 [−0.0086, +0.0069] | pass | no (harmed) |
| F + onset 1 | `0f34fe094b7d` | +0.0038 [+0.0000, +0.0076] | 7.81% | −0.0052 [−0.0133, +0.0024] | pass | no (harmed) |

Reference F (`8ecd5b320f33`) vs E0+answers on the same cases: +0.0089 [+0.0067, +0.0115], harmed 3.03%.

Secondary (dev, Δ vs F): all cases +0.0025 / +0.0042 / +0.0053 for w = 0.25 / 0.5 / 1; known-onset cases +0.0042 /
+0.0069 / +0.0088 (harmed 5.84% / 8.28% / 11.40% vs E0+answers). Full tables in `dev-analysis.md`.

**Selected by the fixed rule: w = 0.25** (the only candidate with harmed ≤ 5%).

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

## Addendum, 2026-10-04 (after dev, before any S3-v3b-test read): final pre-registration
Written after the dev search above and before `s3-v3b/test` was ever loaded (no ledger row for it).
- **Selected system:** F + onset **w = 0.25**, config hash **`871fd89b8368`** (F's config, `8ecd5b320f33`, with the `onset`
  weight 0.25; arms in `results/EXP-B-005/arms-sealed.json`). Reference: F (`8ecd5b320f33`).
- **The read:** one `dxt s3 onset-session --part test` invocation on S3-v3b-test (exclusion list applied, all cases),
  with `DXT_SEALED_READ=EXP-B-005` set on that command only. One Q2b interview (λ 0.6, budget 9, noise 0) driven by F;
  F and F + onset 0.25 are scored on the same answers. No re-run.
- **P1 (unchanged):** on the literature-onset test cases (`literature-onset-cases.txt`), the paired Δ (F + onset 0.25) − F
  in MRR has a bootstrap 95% CI over genes (seed 0, 2,000 resamples) with lower bound > 0, **and** the harmed share of
  F + onset 0.25 vs E0+answers is ≤ 5%. Both conditions are needed.
- **Secondaries (descriptive):** all cases; known-onset cases; literature-onset cases split by the kb `onset_source`
  (hpoa, orphanet, orphanet_exact_alignment, none).
- **Analysis:** `scripts/exp_b005_analysis.py test`, committed before the read.
- Nothing is chosen or tuned after seeing a test number. A failed P1 is reported as such.

## Addendum, 2026-10-04 (after the sealed read): Results and verdict
One `dxt s3 onset-session --part test` run on S3-v3b-test (ledger row `2026-10-04T18:31:09+00:00`, code `a7f83f5`, pre-registered
at `a7f83f5`), `DXT_SEALED_READ=EXP-B-005`. 10,458 cases interviewed (51 excluded), one Q2b interview driven by F, F and
F + onset 0.25 scored on the same answers; F's ranks from the interview and from the scoring path agree on every case.
Analysis: `scripts/exp_b005_analysis.py test` -> `results/EXP-B-005/sealed-analysis.{md,json}`. CI over genes, seed 0, 2,000 resamples.

**P1 (6,745 literature-onset test cases): Δ (F + onset 0.25) − F = +0.0023 [+0.0013, +0.0034]; harmed vs E0+answers 4.63%
(helped 28.35%). CI lower bound > 0 and harmed ≤ 5%: P1 PASSES.** F alone vs E0+answers: +0.0076 [+0.0060, +0.0092], harmed 3.45%.

Secondaries (Δ vs F [CI]; harmed of F + onset 0.25 vs E0+answers):
| subset | n | Δ vs F | harmed |
|---|---|---|---|
| all cases | 10,458 | +0.0027 [+0.0019, +0.0036] | 4.75% |
| known-onset cases (any source) | 6,200 | +0.0046 [+0.0031, +0.0061] | 5.40% |
| literature, onset known | 3,993 | +0.0039 [+0.0021, +0.0056] | 5.58% |
| literature, onset unknown | 2,752 | +0.0000 (no onset feature) | 3.23% |
| literature, kb source hpoa | 4,802 | +0.0025 [+0.0013, +0.0038] | 4.56% |
| literature, kb source orphanet | 355 | +0.0004 [−0.0033, +0.0036] | 3.94% |
| literature, kb source orphanet_exact_alignment | 978 | +0.0023 [−0.0001, +0.0046] | 5.42% |
| literature, kb source none | 610 | +0.0022 [−0.0012, +0.0062] | 4.26% |

Reading: the gain is small (+0.0023 MRR) but its CI excludes 0 on cases whose onset comes from a source independent of the
knowledge base, so it is not only the source overlap seen on S3 v2. It comes entirely from cases that report an onset; the
harm among them exceeds 5% (5.58%) and the overall harm cap holds only because cases without a reported onset dilute it.
The deployment prerequisite of ADR-0015 stands: the app does not collect symptom-onset age today.
