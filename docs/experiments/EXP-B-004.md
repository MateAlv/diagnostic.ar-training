# EXP-B-004: Re-ranker v1.1 (L1 negation limit, L2 enriched frequencies, L3 fair sex and age) on S3 v2

- **Front:** B
- **Registered:** 2026-10-03, by Mateo Alvarez (written by the assistant)
- **Status:** planned. The design is fixed now. The **final system list for
  the sealed read is added as a dated addendum before the read** (phase 4),
  chosen by the selection rule below.
- **2026-10-03:** the dev search (phase 3) is done and logged below; the sealed read has not happened.
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
Phase 3 of ADR-0014, run on `phase4/dev-search`. **S3-v2-dev only** (9,872 cases minus 122 in
`s3-data-v2-excl-v1` = **9,750**), plus R1-dev (1,883 cases, "all" view) for the no-harm check.
S3-v2-test, R1-test and the vault were not read, and `DXT_SEALED_READ` was never set. Every
configuration is a row of `results/EXP-B-004/dev-search.tsv` (the header there fixes the
prioritisation and the interpretation of the rule before the first run); per-stage reports, arms
and per-case ranks are in `results/EXP-B-004/dev-search/`.

- **Interview.** Q0 (kb-v6, top-10 information gain, non-adaptive), budget 9, run once:
  8.93 questions per case, 1.10 "yes" and 7.82 "no" per case. E0-initial MRR 0.3185;
  E0+answers MRR 0.3397. Every arm scores those same answers.
- **Budget used.** L1 48/48, L2 6/6, L3 12/12. Reference rows (rr-v1 on kb-v5, the L3 base
  re-scored) are not search arms.
- **Metric.** Δ MRR vs E0+answers, 95% CI by cluster bootstrap over genes (2,000 resamples);
  `harmed` is the share of all cases whose rank got worse. R1-dev: Δ vs E0, CI over publications;
  pass = CI upper bound ≥ 0 and point ≥ −0.02.
- **Scorer check.** The vectorised scorer gives the same rank as the legacy path
  (`learned.table` + `Table.combine` + `s3_run.rank`) on 400 cases × 5 configurations (0 differing;
  `results/EXP-B-004/dev-search/parity.txt`). The L2 kb-v6 rows reproduce the L1 rows to the last digit.

### Weight-sum check (ADR-0014 addendum)
Each gene's disease weights should sum to 1; `onset` and `term_probability` assume it. They do not
for a minority of genes, in all three KBs. Nothing was changed.

| KB | genes | sum ≠ 1 (>1e-6) | sum < 0.99 | sum < 0.9 | sum < 0.6 | min | max |
|---|---|---|---|---|---|---|---|
| kb-v6 | 5188 | 633 | 14 | 11 | 4 | 0.500 | 1.000005 |
| kb-v7 | 5019 | 601 | 11 | 8 | 3 | 0.500 | 1.000005 |
| kb-v8 | 5188 | 633 | 14 | 11 | 4 | 0.500 | 1.000005 |

The largest excess is 1.000005 (rounding of 6-digit weights). Only 14 genes (kb-v6, kb-v8) and 11 (kb-v7)
sum below 0.99, the lowest at 0.5 (MAOA, RAD54B); the missing mass acts as "no known disease", so
those genes' P(t | g) and onset mixtures are understated. kb-v6 and kb-v8 have identical sums
(same `genes-v1` weights). `scripts/kb_weight_sums.py`, `results/EXP-B-004/kb-weight-sums.json`.

### L1: negation form, weight and strength (48 configurations)
| arm | hash | Δ MRR | 95% CI | harmed | helped | R1-dev Δ | R1-dev CI | R1 pass |
|---|---|---|---|---|---|---|---|---|
| L1:llr:k0.5:w0.5 | 2b6a00674f4c | +0.0079 | [+0.0065, +0.0093] | 0.055 | 0.253 | -0.0020 | [-0.0097, +0.0044] | 1 |
| L1:llr:k0.5:w0.75 | 022d08bba4ef | +0.0103 | [+0.0086, +0.0122] | 0.064 | 0.288 | -0.0061 | [-0.0203, +0.0042] | 1 |
| L1:llr:k0.5:w1 | c0aa705df747 | +0.0129 | [+0.0109, +0.0150] | 0.073 | 0.318 | -0.0086 | [-0.0266, +0.0040] | 1 |
| L1:llr:k0.5:w1.5 | d99deb89262b | +0.0151 | [+0.0125, +0.0176] | 0.083 | 0.353 | -0.0111 | [-0.0334, +0.0049] | 1 |
| L1:llr:k0.5:w2 | 7a049149fb15 | +0.0151 | [+0.0122, +0.0180] | 0.093 | 0.379 | -0.0124 | [-0.0381, +0.0058] | 1 |
| L1:llr:k0.5:w3 | 3b09b1cd408a | +0.0135 | [+0.0101, +0.0169] | 0.111 | 0.413 | -0.0177 | [-0.0505, +0.0064] | 1 |
| L1:gated:tau0.2:k0.5:w0.5 | 3c5494823313 | +0.0079 | [+0.0065, +0.0093] | 0.055 | 0.247 | +0.0011 | [-0.0037, +0.0054] | 1 |
| L1:gated:tau0.2:k0.5:w0.75 | d1a0f08e733b | +0.0100 | [+0.0083, +0.0118] | 0.065 | 0.284 | -0.0003 | [-0.0066, +0.0055] | 1 |
| L1:gated:tau0.2:k0.5:w1 | 458b78788223 | +0.0122 | [+0.0102, +0.0143] | 0.074 | 0.316 | +0.0005 | [-0.0072, +0.0076] | 1 |
| L1:gated:tau0.2:k0.5:w1.5 | e898052a6df9 | +0.0145 | [+0.0119, +0.0171] | 0.085 | 0.350 | +0.0009 | [-0.0109, +0.0110] | 1 |
| L1:gated:tau0.2:k0.5:w2 | 90a58acdd4a6 | +0.0138 | [+0.0109, +0.0167] | 0.094 | 0.375 | -0.0039 | [-0.0253, +0.0127] | 1 |
| L1:gated:tau0.2:k0.5:w3 | a4ade4b87607 | +0.0106 | [+0.0070, +0.0140] | 0.113 | 0.412 | -0.0058 | [-0.0290, +0.0127] | 1 |
| L1:capped:cap2:k0.5:w0.5 | aa2e98c3b9fc | +0.0066 | [+0.0053, +0.0079] | 0.055 | 0.244 | -0.0020 | [-0.0097, +0.0044] | 1 |
| L1:capped:cap2:k0.5:w0.75 | 0981d1697b61 | +0.0092 | [+0.0076, +0.0109] | 0.065 | 0.279 | -0.0062 | [-0.0205, +0.0041] | 1 |
| L1:capped:cap2:k0.5:w1 | 780c4f554bfe | +0.0120 | [+0.0101, +0.0139] | 0.073 | 0.309 | -0.0088 | [-0.0267, +0.0037] | 1 |
| L1:capped:cap2:k0.5:w1.5 | 9c44fcd5fb28 | +0.0151 | [+0.0127, +0.0175] | 0.083 | 0.344 | -0.0115 | [-0.0336, +0.0044] | 1 |
| L1:capped:cap2:k0.5:w2 | 84296576dc8e | +0.0161 | [+0.0133, +0.0188] | 0.092 | 0.367 | -0.0125 | [-0.0382, +0.0057] | 1 |
| L1:capped:cap2:k0.5:w3 | 407e0d70ad8a | +0.0155 | [+0.0123, +0.0188] | 0.109 | 0.401 | -0.0177 | [-0.0506, +0.0065] | 1 |
| L1:propagated:k0.5:w0.5 | 8ecd5b320f33 | +0.0063 | [+0.0051, +0.0075] | 0.049 | 0.233 | -0.0020 | [-0.0097, +0.0044] | 1 |
| L1:propagated:k0.5:w0.75 | 2d35a0f3dae4 | +0.0089 | [+0.0073, +0.0104] | 0.059 | 0.270 | -0.0061 | [-0.0203, +0.0042] | 1 |
| L1:propagated:k0.5:w1 | 53c67989ab01 | +0.0109 | [+0.0092, +0.0127] | 0.065 | 0.298 | -0.0086 | [-0.0266, +0.0040] | 1 |
| L1:propagated:k0.5:w1.5 | f14a794c5ddf | +0.0135 | [+0.0114, +0.0157] | 0.079 | 0.332 | -0.0111 | [-0.0334, +0.0049] | 1 |
| L1:propagated:k0.5:w2 | 5a80f575f46e | +0.0154 | [+0.0130, +0.0179] | 0.086 | 0.355 | -0.0124 | [-0.0381, +0.0058] | 1 |
| L1:propagated:k0.5:w3 | 953454658fce | +0.0160 | [+0.0131, +0.0190] | 0.099 | 0.393 | -0.0177 | [-0.0505, +0.0064] | 1 |
| L1:propagated:k0.8:w0.5 | 8309ce9b889e | +0.0106 | [+0.0089, +0.0124] | 0.061 | 0.296 | -0.0065 | [-0.0220, +0.0046] | 1 |
| L1:propagated:k0.8:w0.75 | c34cb31bd53f | +0.0132 | [+0.0111, +0.0154] | 0.074 | 0.331 | -0.0091 | [-0.0300, +0.0056] | 1 |
| L1:propagated:k0.8:w1 | bfc6de1adab0 | +0.0144 | [+0.0120, +0.0168] | 0.082 | 0.356 | -0.0107 | [-0.0329, +0.0060] | 1 |
| L1:propagated:k0.8:w1.5 | a372fb5fb72a | +0.0152 | [+0.0124, +0.0181] | 0.094 | 0.396 | -0.0149 | [-0.0449, +0.0074] | 1 |
| L1:propagated:k0.8:w2 | e0c177520e5e | +0.0142 | [+0.0110, +0.0177] | 0.108 | 0.420 | -0.0182 | [-0.0521, +0.0067] | 1 |
| L1:propagated:k0.8:w3 | 2a4b77988e3e | +0.0071 | [+0.0030, +0.0112] | 0.138 | 0.457 | -0.0279 | [-0.0682, +0.0029] | 0 |
| L1:capped:cap2:k0.8:w0.5 | dcc9988853f5 | +0.0085 | [+0.0070, +0.0100] | 0.066 | 0.271 | -0.0069 | [-0.0223, +0.0040] | 1 |
| L1:capped:cap2:k0.8:w0.75 | e34a4777ac48 | +0.0114 | [+0.0095, +0.0132] | 0.080 | 0.306 | -0.0107 | [-0.0309, +0.0034] | 1 |
| L1:capped:cap2:k0.8:w1 | d547718a010c | +0.0131 | [+0.0110, +0.0152] | 0.086 | 0.328 | -0.0123 | [-0.0346, +0.0035] | 1 |
| L1:capped:cap2:k0.8:w1.5 | 519485fef7fc | +0.0162 | [+0.0136, +0.0189] | 0.101 | 0.363 | -0.0150 | [-0.0446, +0.0071] | 1 |
| L1:capped:cap2:k0.8:w2 | edacb67ca05d | +0.0169 | [+0.0139, +0.0200] | 0.115 | 0.383 | -0.0182 | [-0.0520, +0.0066] | 1 |
| L1:capped:cap2:k0.8:w3 | a26afc57846d | +0.0127 | [+0.0088, +0.0165] | 0.141 | 0.411 | -0.0273 | [-0.0674, +0.0042] | 0 |
| L1:gated:tau0.4:k0.5:w0.5 | 8e8b70d00a1c | +0.0065 | [+0.0052, +0.0078] | 0.045 | 0.237 | +0.0028 | [+0.0006, +0.0050] | 1 |
| L1:gated:tau0.4:k0.5:w0.75 | f09a0f3b5076 | +0.0087 | [+0.0071, +0.0103] | 0.054 | 0.278 | +0.0030 | [+0.0002, +0.0058] | 1 |
| L1:gated:tau0.4:k0.5:w1 | 78870ab362be | +0.0100 | [+0.0081, +0.0120] | 0.061 | 0.307 | +0.0039 | [+0.0005, +0.0075] | 1 |
| L1:gated:tau0.4:k0.5:w1.5 | 01299ec656c6 | +0.0112 | [+0.0088, +0.0137] | 0.072 | 0.345 | +0.0065 | [+0.0012, +0.0117] | 1 |
| L1:gated:tau0.4:k0.5:w2 | 889d20b4d418 | +0.0106 | [+0.0079, +0.0134] | 0.080 | 0.375 | +0.0074 | [+0.0015, +0.0134] | 1 |
| L1:gated:tau0.4:k0.5:w3 | ca9750d4283f | +0.0066 | [+0.0033, +0.0099] | 0.096 | 0.414 | +0.0067 | [-0.0011, +0.0138] | 1 |
| L1:capped:cap1:k0.5:w1 | d5a298c1b1f2 | +0.0089 | [+0.0074, +0.0104] | 0.070 | 0.272 | -0.0094 | [-0.0271, +0.0026] | 1 |
| L1:capped:cap1:k0.5:w2 | 5885f1c46a34 | +0.0136 | [+0.0115, +0.0156] | 0.090 | 0.328 | -0.0140 | [-0.0390, +0.0035] | 1 |
| L1:capped:cap1:k0.5:w3 | c9f21caac5c8 | +0.0168 | [+0.0141, +0.0194] | 0.106 | 0.360 | -0.0177 | [-0.0502, +0.0060] | 1 |
| L1:capped:cap3:k0.5:w1 | ef72d959baec | +0.0127 | [+0.0107, +0.0148] | 0.073 | 0.317 | -0.0086 | [-0.0266, +0.0040] | 1 |
| L1:capped:cap3:k0.5:w2 | a8165098813f | +0.0153 | [+0.0124, +0.0182] | 0.093 | 0.376 | -0.0124 | [-0.0381, +0.0058] | 1 |
| L1:capped:cap3:k0.5:w3 | b2d3888804ea | +0.0139 | [+0.0106, +0.0173] | 0.111 | 0.410 | -0.0177 | [-0.0505, +0.0064] | 1 |

Reference, not an arm: rr-v1[neg=0.5] on kb-v5 (`8488e32fc7c2`): Δ +0.0067 [+0.0055, +0.0079],
harmed 0.054, R1-dev Δ −0.0052 [−0.0176, +0.0039]. kb-v5 drops half B of annot-split-v1, not v2, so it
can know S3-v2 held-out pairs (a declared advantage for this reference).

Frontier (best Δ at each harm limit, over this lever's arms):
- harmed <= 0.050: L1:gated:tau0.4:k0.5:w0.5 Δ +0.0065 [+0.0052, +0.0078] harmed 0.045, CI lower bound > 0: True, R1-dev pass: True
- harmed <= 0.075: L1:propagated:k0.8:w0.75 Δ +0.0132 [+0.0111, +0.0154] harmed 0.074, CI lower bound > 0: True, R1-dev pass: True
- harmed <= 0.100: L1:capped:cap2:k0.5:w2 Δ +0.0161 [+0.0133, +0.0188] harmed 0.092, CI lower bound > 0: True, R1-dev pass: True

Selection rule (harmed <= 5%, CI lower bound > 0, R1-dev no-harm, ties within 0.001 -> simpler):
- winner: L1:propagated:k0.5:w0.5 8ecd5b320f33
- feasible arms within 0.001 of the best Δ, passed over for the simpler winner: ['L1:gated:tau0.4:k0.5:w0.5']

- **The limit.** At harmed ≤ 5% the best gain is Δ +0.0065 (gated, τ = 0.4, weight 0.5, harmed 4.5%);
  at ≤ 7.5% it is +0.0132 (propagated, k = 0.8, weight 0.75); at ≤ 10% it is +0.0161 (capped C = 2,
  weight 2). The frontier is steep: +0.0065 at 5%, +0.0132 at 7.5%, +0.0161 at 10%.
- **Winner by the rule: `L1:propagated:k0.5:w0.5` (`8ecd5b320f33`)**, Δ +0.0063 [+0.0051, +0.0075],
  harmed 4.85%. Only two arms satisfy harmed ≤ 5% together with the other conditions (propagated w0.5
  and gated τ = 0.4 w0.5, Δ +0.0065); they are within 0.001, so the simpler form wins. rr-v1's own
  form and weight on kb-v6 (`llr`, w0.5) has harmed 5.5% and is excluded by the cap.
- **Stage b ranking** (declared in the header): after stage a only propagated had an arm satisfying the
  rule; the other forms are ranked by their best Δ, and capped (+0.0161) came second (llr +0.0151, gated
  +0.0145). Stage b therefore ran k = 0.8 for propagated and capped; gated got its τ = 0.4 variants in stage c.
- **Reading the frontier:** larger weights buy gain with extra harm. k = 0.8 sits on about the same
  gain-versus-harm curve as k = 0.5 with a larger weight (propagated k0.8 w0.5: +0.0106 at 6.1% harm;
  k0.5 w1: +0.0109 at 6.5%); for capped it is slightly worse (k0.8 w1.5: +0.0162 at 10.1%; k0.5 w2: +0.0161 at 9.2%).

### L2: enriched frequencies and gene weights (6 configurations)
Best two forms of L1 (the winner's, propagated; and gated τ = 0.4, the best other form with a feasible
arm) at their best L1 parameters, on kb-v6 (old frequencies, genes-v1), kb-v8 (enriched frequencies,
genes-v1) and kb-v7 (enriched frequencies, genes-v2). kb-v6 → kb-v8 isolates frequencies; kb-v8 → kb-v7 isolates gene weights.

| arm | hash | Δ MRR | 95% CI | harmed | helped | R1-dev Δ | R1-dev CI | R1 pass |
|---|---|---|---|---|---|---|---|---|
| L2:propagated:k0.5:w0.5:kb-v6 | 8ecd5b320f33 | +0.0063 | [+0.0051, +0.0075] | 0.049 | 0.233 | -0.0020 | [-0.0097, +0.0044] | 1 |
| L2:propagated:k0.5:w0.5:kb-v8 | 8d48a53224aa | +0.0064 | [+0.0052, +0.0076] | 0.047 | 0.236 | -0.0094 | [-0.0241, +0.0007] | 1 |
| L2:propagated:k0.5:w0.5:kb-v7 | af6da5cdbf19 | +0.0064 | [+0.0052, +0.0076] | 0.048 | 0.235 | -0.0095 | [-0.0241, +0.0007] | 1 |
| L2:gated:tau0.4:k0.5:w0.5:kb-v6 | 8e8b70d00a1c | +0.0065 | [+0.0052, +0.0078] | 0.045 | 0.237 | +0.0028 | [+0.0006, +0.0050] | 1 |
| L2:gated:tau0.4:k0.5:w0.5:kb-v8 | 262466604de5 | +0.0066 | [+0.0053, +0.0079] | 0.044 | 0.242 | +0.0008 | [-0.0039, +0.0048] | 1 |
| L2:gated:tau0.4:k0.5:w0.5:kb-v7 | 2767e4ab88ca | +0.0066 | [+0.0053, +0.0079] | 0.045 | 0.243 | +0.0007 | [-0.0039, +0.0047] | 1 |

Selection rule (harmed <= 5%, CI lower bound > 0, R1-dev no-harm, ties within 0.001 -> simpler):
- winner: L2:propagated:k0.5:w0.5:kb-v6 8ecd5b320f33
- feasible arms within 0.001 of the best Δ, passed over for the simpler winner: ['L2:propagated:k0.5:w0.5:kb-v8', 'L2:propagated:k0.5:w0.5:kb-v7', 'L2:gated:tau0.4:k0.5:w0.5:kb-v6', 'L2:gated:tau0.4:k0.5:w0.5:kb-v8', 'L2:gated:tau0.4:k0.5:w0.5:kb-v7']

Paired differences and subsets (`results/EXP-B-004/dev-search/summary-L2-subsets.md`):

| arm | all vs E0+answers | with_excluded vs E0+answers | halfB_only_excluded vs E0+answers | halfB_any_excluded vs E0+answers | excluded_none_halfB vs E0+answers | all vs L2:propagated:k0.5:w0.5:kb-v6 | with_excluded vs L2:propagated:k0.5:w0.5:kb-v6 | halfB_only_excluded vs L2:propagated:k0.5:w0.5:kb-v6 | halfB_any_excluded vs L2:propagated:k0.5:w0.5:kb-v6 | excluded_none_halfB vs L2:propagated:k0.5:w0.5:kb-v6 |
|---|---|---|---|---|---|---|---|---|---|---|
| L2:gated:tau0.4:k0.5:w0.5:kb-v6 | +0.0065 [+0.0052, +0.0078] | +0.0065 [+0.0053, +0.0079] | +0.0000 [+0.0000, +0.0000] | +0.0074 [+0.0035, +0.0115] | +0.0064 [+0.0050, +0.0078] | +0.0002 [-0.0006, +0.0010] | +0.0002 [-0.0006, +0.0011] | +0.0000 [+0.0000, +0.0000] | +0.0016 [-0.0013, +0.0045] | +0.0000 [-0.0009, +0.0009] |
| L2:gated:tau0.4:k0.5:w0.5:kb-v7 | +0.0066 [+0.0053, +0.0079] | +0.0067 [+0.0054, +0.0081] | +0.0000 [+0.0000, +0.0000] | +0.0076 [+0.0038, +0.0117] | +0.0065 [+0.0050, +0.0079] | +0.0003 [-0.0005, +0.0012] | +0.0003 [-0.0005, +0.0012] | +0.0000 [+0.0000, +0.0000] | +0.0018 [-0.0012, +0.0047] | +0.0001 [-0.0008, +0.0010] |
| L2:gated:tau0.4:k0.5:w0.5:kb-v8 | +0.0066 [+0.0053, +0.0079] | +0.0067 [+0.0054, +0.0081] | +0.0000 [+0.0000, +0.0000] | +0.0076 [+0.0038, +0.0117] | +0.0066 [+0.0051, +0.0079] | +0.0003 [-0.0005, +0.0012] | +0.0003 [-0.0005, +0.0012] | +0.0000 [+0.0000, +0.0000] | +0.0018 [-0.0011, +0.0047] | +0.0001 [-0.0008, +0.0010] |
| L2:propagated:k0.5:w0.5:kb-v6 | +0.0063 [+0.0051, +0.0075] | +0.0063 [+0.0052, +0.0076] | +0.0000 [+0.0000, +0.0000] | +0.0058 [+0.0025, +0.0094] | +0.0064 [+0.0052, +0.0076] | +0.0000 [+0.0000, +0.0000] | +0.0000 [+0.0000, +0.0000] | +0.0000 [+0.0000, +0.0000] | +0.0000 [+0.0000, +0.0000] | +0.0000 [+0.0000, +0.0000] |
| L2:propagated:k0.5:w0.5:kb-v7 | +0.0064 [+0.0052, +0.0076] | +0.0065 [+0.0053, +0.0077] | +0.0000 [+0.0000, +0.0000] | +0.0059 [+0.0025, +0.0095] | +0.0065 [+0.0053, +0.0077] | +0.0001 [-0.0001, +0.0004] | +0.0001 [-0.0001, +0.0004] | +0.0000 [+0.0000, +0.0000] | +0.0001 [-0.0004, +0.0006] | +0.0001 [-0.0001, +0.0004] |
| L2:propagated:k0.5:w0.5:kb-v8 | +0.0064 [+0.0052, +0.0076] | +0.0064 [+0.0052, +0.0076] | +0.0000 [+0.0000, +0.0000] | +0.0059 [+0.0025, +0.0094] | +0.0065 [+0.0052, +0.0076] | +0.0001 [-0.0001, +0.0002] | +0.0001 [-0.0001, +0.0002] | +0.0000 [+0.0000, +0.0000] | +0.0001 [-0.0004, +0.0005] | +0.0001 [-0.0001, +0.0003] |

- **H2 is not supported.** The enriched frequencies change Δ MRR by +0.0001 (propagated, kb-v8 vs kb-v6,
  CI [−0.0001, +0.0002]) to +0.0003 (gated), CIs including 0; the gene weights add nothing more
  (kb-v7 and kb-v8 differ by less than 0.0001). On cases with at least one excluded term that is a half-B
  (disease, term) pair (n = 1,121, where the re-ranker cannot know the generator's number),
  the paired Δ of kb-v8/kb-v7 over kb-v6 is +0.0001 [−0.0004, +0.0006] (propagated) and
  +0.0018 [−0.0011, +0.0047] (gated): no detectable gain.
- **The stricter subset has 3 cases.** "All excluded terms are half-B pairs for the case's disease"
  (the definition written for this subset) holds for only 3 of 9,750 cases, so it cannot say anything;
  the "at least one" version above is reported instead and labelled as such.
- **Selected: `L2:propagated:k0.5:w0.5:kb-v6` (`8ecd5b320f33`).** All six arms satisfy the rule and sit
  within 0.001 (Δ +0.0063 to +0.0066); the simplest is propagated on kb-v6. The R1-dev check passes for all six,
  narrowly for kb-v8/kb-v7 (CI upper bound +0.0007).

### L3: sex, age and onset (12 configurations)
Added to the L1+L2 system. Base re-scored as `L3:base` (same hash `8ecd5b320f33`, not a search arm).

| arm | hash | Δ MRR | 95% CI | harmed | helped | R1-dev Δ | R1-dev CI | R1 pass |
|---|---|---|---|---|---|---|---|---|
| L3:sex:w0.5 | 96e69f9e62fa | +0.0064 | [+0.0052, +0.0076] | 0.053 | 0.241 | -0.0022 | [-0.0098, +0.0043] | 1 |
| L3:sex:w1 | b092d2638407 | +0.0063 | [+0.0051, +0.0076] | 0.057 | 0.248 | -0.0026 | [-0.0102, +0.0037] | 1 |
| L3:sex:w2 | 53c63313d5d2 | +0.0063 | [+0.0050, +0.0076] | 0.066 | 0.258 | -0.0032 | [-0.0107, +0.0031] | 1 |
| L3:age_mean:w0.5 | 5b30ab00d1a0 | +0.0070 | [+0.0057, +0.0083] | 0.065 | 0.255 | -0.0055 | [-0.0148, +0.0022] | 1 |
| L3:age_mean:w1 | 96ccbfe4fc09 | +0.0066 | [+0.0052, +0.0080] | 0.073 | 0.275 | -0.0069 | [-0.0171, +0.0017] | 1 |
| L3:age_mean:w2 | b27ec949866a | +0.0059 | [+0.0042, +0.0076] | 0.092 | 0.302 | -0.0111 | [-0.0241, -0.0003] | 0 |
| L3:age_any:w0.5 | f8da149bd12a | +0.0071 | [+0.0057, +0.0083] | 0.058 | 0.257 | -0.0068 | [-0.0177, +0.0017] | 1 |
| L3:age_any:w1 | e669682d5786 | +0.0069 | [+0.0055, +0.0082] | 0.064 | 0.277 | -0.0089 | [-0.0208, +0.0004] | 1 |
| L3:age_any:w2 | 0947e2065d55 | +0.0066 | [+0.0050, +0.0081] | 0.072 | 0.308 | -0.0123 | [-0.0260, -0.0013] | 0 |
| L3:onset:w0.5 | 458768f1bca4 | +0.0117 | [+0.0101, +0.0133] | 0.052 | 0.300 | -0.0004 | [-0.0086, +0.0069] | 1 |
| L3:onset:w1 | 0f34fe094b7d | +0.0150 | [+0.0131, +0.0171] | 0.065 | 0.320 | -0.0052 | [-0.0133, +0.0024] | 1 |
| L3:onset:w2 | d73946db2f87 | +0.0172 | [+0.0147, +0.0197] | 0.084 | 0.339 | -0.0127 | [-0.0228, -0.0024] | 0 |

Selection rule (harmed <= 5%, CI lower bound > 0, R1-dev no-harm, ties within 0.001 -> simpler):
- winner: none

Evaluation subsets, paired against the base (`summary-L3-subsets.md`; n: known sex 9,049, lit-onset 515,
lit-onset with known age 401):

| arm | sex_known vs E0+answers | lit_onset vs E0+answers | lit_onset_age_known vs E0+answers | sex_known vs L3:base | lit_onset vs L3:base | lit_onset_age_known vs L3:base |
|---|---|---|---|---|---|---|
| L3:age_any:w0.5 | +0.0067 [+0.0054, +0.0079] | +0.0079 [+0.0016, +0.0143] | +0.0068 [-0.0007, +0.0150] | +0.0008 [+0.0002, +0.0014] | +0.0004 [-0.0030, +0.0037] | +0.0006 [-0.0038, +0.0046] |
| L3:age_any:w1 | +0.0066 [+0.0053, +0.0079] | +0.0083 [+0.0019, +0.0146] | +0.0073 [+0.0000, +0.0154] | +0.0007 [-0.0001, +0.0015] | +0.0008 [-0.0034, +0.0049] | +0.0011 [-0.0040, +0.0064] |
| L3:age_any:w2 | +0.0063 [+0.0048, +0.0078] | +0.0094 [+0.0018, +0.0174] | +0.0088 [-0.0001, +0.0195] | +0.0004 [-0.0007, +0.0016] | +0.0020 [-0.0036, +0.0075] | +0.0025 [-0.0040, +0.0098] |
| L3:age_mean:w0.5 | +0.0067 [+0.0054, +0.0080] | +0.0088 [+0.0027, +0.0154] | +0.0080 [+0.0011, +0.0156] | +0.0008 [+0.0001, +0.0015] | +0.0014 [-0.0033, +0.0063] | +0.0018 [-0.0040, +0.0078] |
| L3:age_mean:w1 | +0.0064 [+0.0050, +0.0077] | +0.0089 [+0.0025, +0.0155] | +0.0082 [+0.0009, +0.0159] | +0.0004 [-0.0004, +0.0013] | +0.0015 [-0.0034, +0.0065] | +0.0019 [-0.0042, +0.0082] |
| L3:age_mean:w2 | +0.0057 [+0.0041, +0.0074] | +0.0072 [-0.0005, +0.0156] | +0.0059 [-0.0026, +0.0161] | -0.0002 [-0.0015, +0.0011] | -0.0003 [-0.0063, +0.0055] | -0.0004 [-0.0078, +0.0073] |
| L3:base | +0.0059 [+0.0047, +0.0071] | +0.0075 [+0.0023, +0.0132] | +0.0063 [+0.0007, +0.0128] | +0.0000 [+0.0000, +0.0000] | +0.0000 [+0.0000, +0.0000] | +0.0000 [+0.0000, +0.0000] |
| L3:onset:w0.5 | +0.0115 [+0.0100, +0.0131] | +0.0138 [+0.0056, +0.0224] | +0.0135 [+0.0046, +0.0247] | +0.0056 [+0.0045, +0.0068] | +0.0063 [+0.0010, +0.0125] | +0.0073 [+0.0004, +0.0147] |
| L3:onset:w1 | +0.0150 [+0.0131, +0.0171] | +0.0193 [+0.0094, +0.0303] | +0.0164 [+0.0057, +0.0295] | +0.0091 [+0.0075, +0.0108] | +0.0119 [+0.0037, +0.0208] | +0.0101 [+0.0012, +0.0199] |
| L3:onset:w2 | +0.0170 [+0.0145, +0.0195] | +0.0208 [+0.0085, +0.0341] | +0.0183 [+0.0043, +0.0341] | +0.0111 [+0.0088, +0.0135] | +0.0133 [+0.0019, +0.0255] | +0.0120 [-0.0013, +0.0265] |
| L3:sex:w0.5 | +0.0060 [+0.0048, +0.0072] | +0.0088 [+0.0040, +0.0142] | +0.0080 [+0.0032, +0.0142] | +0.0001 [-0.0002, +0.0005] | +0.0014 [-0.0002, +0.0038] | +0.0018 [-0.0002, +0.0048] |
| L3:sex:w1 | +0.0059 [+0.0047, +0.0071] | +0.0098 [+0.0045, +0.0160] | +0.0091 [+0.0036, +0.0161] | +0.0000 [-0.0005, +0.0005] | +0.0023 [-0.0003, +0.0060] | +0.0028 [-0.0004, +0.0075] |
| L3:sex:w2 | +0.0059 [+0.0045, +0.0072] | +0.0087 [+0.0032, +0.0149] | +0.0076 [+0.0020, +0.0146] | -0.0000 [-0.0007, +0.0007] | +0.0012 [-0.0019, +0.0051] | +0.0014 [-0.0023, +0.0063] |

By the kb `onset_source` of the case's disease, lit-onset cases (n: hpoa 376, orphanet 30,
orphanet exact alignment 64, none 45) and all age-known cases (`summary-L3-by-onset-source.md`):

| arm | lit_onset_src_hpoa vs E0+answers | lit_onset_src_orphanet vs E0+answers | lit_onset_src_orphanet_exact_alignment vs E0+answers | lit_onset_src_none vs E0+answers | age_known vs E0+answers | lit_onset_src_hpoa vs L3:base | lit_onset_src_orphanet vs L3:base | lit_onset_src_orphanet_exact_alignment vs L3:base | lit_onset_src_none vs L3:base | age_known vs L3:base |
|---|---|---|---|---|---|---|---|---|---|---|
| L3:age_any:w0.5 | +0.0066 [-0.0007, +0.0142] | +0.0156 [-0.0030, +0.0577] | +0.0196 [+0.0014, +0.0436] | -0.0028 [-0.0110, +0.0020] | +0.0077 [+0.0061, +0.0092] | +0.0007 [-0.0036, +0.0052] | -0.0011 [-0.0034, +0.0002] | -0.0003 [-0.0016, +0.0006] | +0.0001 [-0.0000, +0.0002] | +0.0010 [+0.0003, +0.0018] |
| L3:age_any:w1 | +0.0071 [-0.0002, +0.0147] | +0.0156 [-0.0030, +0.0577] | +0.0196 [+0.0014, +0.0435] | -0.0027 [-0.0109, +0.0021] | +0.0075 [+0.0060, +0.0091] | +0.0013 [-0.0041, +0.0068] | -0.0011 [-0.0034, +0.0003] | -0.0004 [-0.0016, +0.0006] | +0.0002 [+0.0000, +0.0004] | +0.0009 [-0.0002, +0.0019] |
| L3:age_any:w2 | +0.0092 [+0.0001, +0.0194] | +0.0153 [-0.0033, +0.0573] | +0.0152 [-0.0047, +0.0402] | -0.0008 [-0.0097, +0.0054] | +0.0071 [+0.0053, +0.0090] | +0.0033 [-0.0035, +0.0109] | -0.0014 [-0.0040, +0.0003] | -0.0047 [-0.0147, +0.0004] | +0.0021 [+0.0001, +0.0052] | +0.0004 [-0.0010, +0.0019] |
| L3:age_mean:w0.5 | +0.0093 [+0.0018, +0.0175] | +0.0154 [-0.0031, +0.0575] | +0.0110 [+0.0001, +0.0295] | -0.0025 [-0.0106, +0.0023] | +0.0076 [+0.0061, +0.0092] | +0.0034 [-0.0020, +0.0091] | -0.0013 [-0.0038, +0.0003] | -0.0089 [-0.0262, -0.0002] | +0.0004 [+0.0001, +0.0011] | +0.0010 [+0.0001, +0.0019] |
| L3:age_mean:w1 | +0.0092 [+0.0015, +0.0177] | +0.0150 [-0.0038, +0.0571] | +0.0111 [+0.0001, +0.0295] | -0.0005 [-0.0095, +0.0056] | +0.0071 [+0.0055, +0.0087] | +0.0034 [-0.0024, +0.0094] | -0.0017 [-0.0044, +0.0004] | -0.0088 [-0.0261, -0.0001] | +0.0024 [+0.0004, +0.0055] | +0.0004 [-0.0006, +0.0015] |
| L3:age_mean:w2 | +0.0075 [-0.0021, +0.0177] | +0.0142 [-0.0054, +0.0568] | +0.0061 [-0.0097, +0.0258] | +0.0016 [-0.0087, +0.0111] | +0.0062 [+0.0043, +0.0082] | +0.0016 [-0.0057, +0.0090] | -0.0025 [-0.0060, +0.0003] | -0.0139 [-0.0333, -0.0012] | +0.0045 [+0.0004, +0.0116] | -0.0005 [-0.0021, +0.0011] |
| L3:base | +0.0059 [+0.0005, +0.0122] | +0.0167 [-0.0001, +0.0577] | +0.0199 [+0.0016, +0.0437] | -0.0029 [-0.0110, +0.0019] | +0.0066 [+0.0053, +0.0081] | +0.0000 [+0.0000, +0.0000] | +0.0000 [+0.0000, +0.0000] | +0.0000 [+0.0000, +0.0000] | +0.0000 [+0.0000, +0.0000] | +0.0000 [+0.0000, +0.0000] |
| L3:onset:w0.5 | +0.0140 [+0.0044, +0.0250] | +0.0154 [-0.0031, +0.0573] | +0.0223 [+0.0042, +0.0463] | -0.0013 [-0.0099, +0.0049] | +0.0122 [+0.0103, +0.0142] | +0.0082 [+0.0006, +0.0165] | -0.0013 [-0.0036, +0.0000] | +0.0024 [+0.0001, +0.0058] | +0.0016 [+0.0003, +0.0035] | +0.0056 [+0.0041, +0.0069] |
| L3:onset:w1 | +0.0176 [+0.0060, +0.0305] | +0.0147 [-0.0055, +0.0571] | +0.0449 [+0.0115, +0.0904] | +0.0007 [-0.0105, +0.0115] | +0.0154 [+0.0130, +0.0176] | +0.0117 [+0.0014, +0.0223] | -0.0020 [-0.0069, +0.0011] | +0.0250 [+0.0011, +0.0642] | +0.0036 [-0.0027, +0.0120] | +0.0087 [+0.0068, +0.0106] |
| L3:onset:w2 | +0.0191 [+0.0043, +0.0347] | -0.0062 [-0.0648, +0.0524] | +0.0424 [+0.0107, +0.0835] | +0.0228 [-0.0086, +0.0605] | +0.0173 [+0.0143, +0.0201] | +0.0132 [-0.0007, +0.0274] | -0.0229 [-0.0717, +0.0038] | +0.0224 [-0.0025, +0.0600] | +0.0257 [-0.0029, +0.0626] | +0.0107 [+0.0080, +0.0132] |
| L3:sex:w0.5 | +0.0077 [+0.0031, +0.0137] | +0.0167 [-0.0001, +0.0577] | +0.0200 [+0.0016, +0.0439] | -0.0029 [-0.0111, +0.0018] | +0.0067 [+0.0054, +0.0082] | +0.0019 [-0.0002, +0.0050] | +0.0000 [+0.0000, +0.0000] | +0.0001 [-0.0000, +0.0002] | -0.0000 [-0.0003, +0.0001] | +0.0001 [-0.0003, +0.0005] |
| L3:sex:w1 | +0.0088 [+0.0033, +0.0158] | +0.0168 [+0.0000, +0.0578] | +0.0213 [+0.0016, +0.0458] | -0.0030 [-0.0111, +0.0017] | +0.0066 [+0.0052, +0.0081] | +0.0030 [-0.0005, +0.0079] | +0.0001 [+0.0000, +0.0003] | +0.0014 [+0.0000, +0.0044] | -0.0001 [-0.0004, +0.0002] | -0.0000 [-0.0005, +0.0005] |
| L3:sex:w2 | +0.0073 [+0.0016, +0.0144] | +0.0168 [+0.0000, +0.0578] | +0.0213 [+0.0016, +0.0458] | -0.0030 [-0.0113, +0.0017] | +0.0065 [+0.0050, +0.0080] | +0.0014 [-0.0028, +0.0068] | +0.0001 [-0.0000, +0.0003] | +0.0014 [+0.0000, +0.0044] | -0.0001 [-0.0008, +0.0003] | -0.0002 [-0.0009, +0.0006] |

- **No L3 arm is selected: H0 stands under the pre-declared rule.** The only arm with harmed ≤ 5% is
  the base itself; every arm that adds a feature harms 5.2% to 9.2% of cases.
- **Sex: no gain.** Paired Δ on known-sex cases is +0.0001 [−0.0002, +0.0005] (w0.5), +0.0000 and −0.0000
  at w1 and w2, and harm rises with the weight (5.3% to 6.6%).
- **Age (`age_mean`, `age_any`): no demonstrated gain.** On the lit-onset cases with known age the paired
  Δ is +0.0018 [−0.0040, +0.0078] (age_mean w0.5) and +0.0006 [−0.0038, +0.0046] (age_any w0.5), CIs including 0,
  with harm of 5.8% to 9.2%. On all age-known cases the gain is +0.0010, but that subset shares its onset
  source with the generator (declared dependency), so it is not evidence.
- **Onset is the exception, and it fails only the harm cap.** On the lit-onset cases (independent sources) the paired Δ
  of `onset` over the base is +0.0063 [+0.0010, +0.0125] (w0.5), +0.0119 [+0.0037, +0.0208] (w1) and
  +0.0133 [+0.0019, +0.0255] (w2); on those with a known age +0.0073 [+0.0004, +0.0147] at w0.5.
  By source the gain is clear for HPOA-sourced diseases (n = 376: +0.0082 [+0.0006, +0.0165] at w0.5). Harm is 5.2%
  (w0.5), 6.5% (w1), 8.4% (w2), and R1-dev fails at w2 (CI upper bound −0.0024). The 5.2% at w0.5 misses
  the 5% cap by 0.2 points. The rule is applied as written, so `onset` is **not** in the selected system;
  it is a candidate contrast for Mateo to decide before phase 4 (see the proposal).
  Overall dev Δ for `onset` (+0.0117 at w0.5) is inflated: for the non-lit cases the generator's onset comes from
  Orphanet categories, which the re-ranker's onset also draws on.

### Selected system (dev)
**F = `RerankConfig(kb-v6, neg_form = propagated, k = 0.5, neg_llr weight = 0.5)`, hash `8ecd5b320f33`**,
no sex, age or onset term. Dev Δ MRR vs E0+answers +0.0063 [+0.0051, +0.0075], harmed 4.85%,
helped 23.3%; R1-dev Δ −0.0020 [−0.0097, +0.0044] (pass).

Versus the bar, on S3-v2-dev (paired, 9,750 cases, CI over genes;
`results/EXP-B-004/dev-search/paired-final-vs-rr-v1.txt`):
- F − rr-v1[kb-v5]: -0.0004 [-0.0013, +0.0004] harmed 0.128 helped 0.075 n=9750;
- F − rr-v1's form and weight on kb-v6: -0.0016 [-0.0023, -0.0009] harmed 0.099 helped 0.025 n=9750;
- rr-v1's form on kb-v6 − rr-v1[kb-v5]: +0.0012 [+0.0004, +0.0020] harmed 0.089 helped 0.098 n=9750.

**F does not beat rr-v1 on dev** (the difference is −0.0004 with a CI containing 0): the 5% harm cap
costs the gain that `llr` at weight 0.5 would give (+0.0079, harmed 5.5%). The phase 4 gate
("the final system beats rr-v1 with CI lower bound > 0 on the paired difference") is therefore not expected to pass for F.
rr-v1[kb-v5] also has the declared advantage of a KB that may hold S3-v2 held-out pairs.

### Proposal for the sealed read (not committed; Mateo approves before phase 4)
Hashes are the `RerankConfig` hashes in the log; every system scored in the one S3-v2-test read.
1. **Final re-ranker F**, `8ecd5b320f33`.
2. **rr-v1[neg=0.5] on kb-v5**, `8488e32fc7c2` (the bar).
3. **Ablations.** "F minus L2" and "F minus L3" are both F itself (F has no enriched frequency and no L3 term), so
   they add no information. To test H2 and H3 on the sealed set instead, contrast arms (not release candidates):
   - F on kb-v7 (`af6da5cdbf19`) for H2, and optionally kb-v8 (`8d48a53224aa`);
   - F + onset w0.5 (`458768f1bca4`), F + sex w0.5 (`96e69f9e62fa`), F + age_mean w0.5 (`5b30ab00d1a0`) for H3.
4. **L4:** the winner Q2b (λ = 0.6), Q0 and Q1, each with F (see EXP-Q-001).
5. One R1-test no-regression read for the final system.

Open points for Mateo: whether to add `onset` w0.5 as a candidate despite 5.2% harm (it would change
F and the L4 re-ranker); whether the gate against rr-v1 should be restated given that the
harm-capped F is not better than rr-v1 on dev.

## Results
(After the sealed read.)

## Addendum (2026-10-03): final pre-registration, descriptive contrasts in the sealed read
This is written after the dev search and before any S3-v2-test read.
Mateo approved it on 2026-10-03.
- **Decision:** the **5% harm cap is kept**. No re-ranker candidate beat
  rr-v1 on dev (F − rr-v1 = −0.0004 [−0.0013, +0.0004]), so **no
  `rerank-v1.1` is gated**. rr-v1 stays the released re-ranker.
- **Scored in the same sealed session, all with interview Q0 at budget 9,
  descriptive only (no gate):**

  | System | Config |
  |---|---|
  | F | `8ecd5b320f33` |
  | rr-v1 on kb-v5 | `8488e32fc7c2` (it may know some S3-v2 half-B pairs; declared) |
  | F on kb-v7 | `af6da5cdbf19` (H2) |
  | F + onset 0.5 | `458768f1bca4` (H3) |
  | F + sex 0.5 | `96e69f9e62fa` |
  | F + age_mean 0.5 | `5b30ab00d1a0` |
  | Frontier points | the dev ≤ 7.5% winner (propagated, k 0.8, weight 0.75) and the ≤ 10% winner (capped, C 2, weight 2) |

  The configs come from `results/EXP-B-004/dev-search.tsv`.
- **H3 reporting:** onset and age are also reported on the lit-onset subset,
  split by `onset_source`.
- **No R1-test read:** the released re-ranker is unchanged, and rr-v1
  already passed R1-test (EXP-B-003).
