# ONSET-INFORMATIVE-TERMS-v1: for which symptoms does the onset age help

Evidence for the web app's "Precisar" button with an onset-age selector. Artifact `onset-informative-terms-v1`
(`results/onset-informative-terms/`), script `scripts/onset_informative_terms.py`, code in
`src/diagnostic_ar_training/rerank/onset_terms.py`. This is a product input, not an evaluation.

## Method
- **Knowledge base:** `kb-v3`, the one rr-v1 uses in production (R1 held-out PMIDs masked, no S3 half-B drop).
- **Score per HPO term t** (only under Phenotypic abnormality, only where at least 3 genes with onset data annotate t,
  directly or through a descendant): genes weighted by P(t | g) times a uniform gene prior; each gene carries the onset
  distribution of the re-ranker's `onset` feature (`GeneKnowledge.onset_distribution`, 8 bins, smoothing 0.1).
  `score_bits` is the mutual information between gene and onset bin given t is present. The maximum possible is
  log2(8) = 3 bits.
- 8040 terms scored. Score quantiles (0, 10, 25, 50, 75, 90, 95, 100%):
  0.00, 0.17, 0.32, 0.54, 0.73, 0.86, 0.93, 1.32.
  Even a term with no onset structure scores above 0 once many genes with different onsets annotate it, so read scores
  relatively, not as absolute information. Terms with few genes are biased upward (a handful of genes with distinct
  onsets reach high mutual information by construction).
- `r1_train_count` is the number of R1-train patients (through `splits.load_part`, purpose train) whose present terms
  include exactly that term (no propagation to ancestors).

## Dev check (dev, exploratory)
S3-v3b-dev, 4,562 interviewed cases, per-case ranks of F and F + onset 0.25 from `results/EXP-B-005/dev/` (Q2b
interview, the dev outputs of EXP-B-005; no test part, S3-v2-test, R1-test or vault read). Cases are split into tertiles
by the maximum score of their reported present terms; the paired gain has a bootstrap CI over genes (seed 0, 2,000
resamples). 3 cases without any scored term are left out. Cases without a reported
onset have exactly zero gain by construction (the feature is absent), so tertiles are shown for all cases and for
onset-known cases.

Specified split (max score of the case's terms):

| population | tertile | max/mean score range (bits) | n | Δ MRR (F+onset 0.25 − F) [95% CI over genes] | harmed share | mean F MRR |
|---|---|---|---|---|---|---|
| all | low | 0.09–0.89 | 1528 | +0.0042 [+0.0025, +0.0061] | 5.0% | 0.290 |
| all | mid | 0.89–1.00 | 1516 | +0.0024 [+0.0003, +0.0048] | 5.1% | 0.344 |
| all | high | 1.00–1.32 | 1515 | +0.0010 [-0.0010, +0.0029] | 3.8% | 0.421 |
| onset_known | low | 0.09–0.89 | 918 | +0.0069 [+0.0043, +0.0100] | 8.4% | 0.295 |
| onset_known | mid | 0.89–1.00 | 918 | +0.0040 [+0.0003, +0.0078] | 8.4% | 0.330 |
| onset_known | high | 1.00–1.32 | 918 | +0.0017 [-0.0016, +0.0052] | 6.3% | 0.431 |

**The check does not validate the score.** The gain falls as the maximum score rises (onset-known: +0.0069, +0.0040,
+0.0017), the opposite of the expectation; the case-level Pearson correlation between max score and the
reciprocal-rank gain is -0.037 (all) and
-0.048 (onset known). Two
confounders are visible: the maximum saturates (cases with many terms nearly always contain one high-scoring term, and
a tertile edge at 0.89 bits is already above the list threshold), and the high tertile has the least headroom (mean F
MRR 0.43 against 0.30 in the low tertile; specific terms already rank the gene well).

Variant, also reported (second aggregation tried, not chosen after the fact; both are logged): mean score of the case's
scored terms.

| population | tertile | max/mean score range (bits) | n | Δ MRR (F+onset 0.25 − F) [95% CI over genes] | harmed share | mean F MRR |
|---|---|---|---|---|---|---|
| all | low | 0.09–0.72 | 1520 | +0.0022 [+0.0000, +0.0044] | 3.9% | 0.388 |
| all | mid | 0.72–0.81 | 1519 | +0.0021 [+0.0004, +0.0040] | 5.7% | 0.345 |
| all | high | 0.81–1.07 | 1520 | +0.0033 [+0.0012, +0.0056] | 4.3% | 0.322 |
| onset_known | low | 0.09–0.72 | 918 | +0.0036 [-0.0000, +0.0073] | 6.5% | 0.393 |
| onset_known | mid | 0.72–0.81 | 918 | +0.0035 [+0.0006, +0.0064] | 9.4% | 0.348 |
| onset_known | high | 0.81–1.07 | 918 | +0.0055 [+0.0019, +0.0094] | 7.2% | 0.315 |

With the mean the order is as expected (onset-known: +0.0036, +0.0035, +0.0055) but the CIs overlap, so it is at most a
weak sign. Cases with and without a term on the final list (onset-known cases and all cases):

| subset | n | Δ MRR [95% CI over genes] | harmed share |
|---|---|---|---|
| all, has a listed term | 3986 | +0.0016 [+0.0004, +0.0029] | 4.5% |
| all, no listed term | 576 | +0.0087 [+0.0042, +0.0141] | 5.7% |
| onset known, has a listed term | 2408 | +0.0027 [+0.0007, +0.0047] | 7.4% |
| onset known, no listed term | 347 | +0.0144 [+0.0072, +0.0237] | 9.5% |

Cases without any listed term gain more. Read together: on simulated patients the knowledge-based score does not predict
where the onset feature helps. The list is a reasonable, transparent product heuristic, not an empirically validated
selector.

## The list
- **Rule:** score >= 0.75 bits (tau, about the 75th percentile of all scored terms) **and** at least 8
  R1-train patients report the term. The count requirement is the tie-breaker toward terms patients actually report. Both numbers were fixed from the score
  distribution and the R1-train counts, before the dev check was computed. The target was 150 to 400 terms.
- **Size:** 354 terms (score range 0.750 to 1.250).
- Commonly reported presenting complaints and whether they pass:

| HPO id | label | score (bits) | n_genes | R1-train count | listed |
|---|---|---|---|---|---|
| HP:0001250 | Seizure | 0.809 | 1986 | 322 | yes |
| HP:0001263 | Global developmental delay | 0.764 | 1932 | 1154 | yes |
| HP:0001251 | Ataxia | 0.972 | 1147 | 120 | yes |
| HP:0000365 | Hearing impairment | 0.784 | 1648 | 77 | yes |
| HP:0000572 | Visual loss | 0.726 | 286 | 0 | no |
| HP:0000505 | Visual impairment | 0.853 | 1160 | 29 | yes |
| HP:0001324 | Muscle weakness | 0.979 | 1140 | 43 | yes |
| HP:0001252 | Hypotonia | 0.740 | 1843 | 623 | no |
| HP:0001256 | Mild intellectual disability | 0.915 | 390 | 106 | yes |
| HP:0001249 | Intellectual disability | 0.810 | 2054 | 740 | yes |
| HP:0000750 | Delayed speech and language development | 0.805 | 1219 | 796 | yes |
| HP:0002376 | Developmental regression | 0.657 | 507 | 68 | no |
| HP:0002317 | Unsteady gait | 0.975 | 233 | 34 | yes |
| HP:0001297 | Stroke | 0.884 | 191 | 7 | no |

Hypotonia (0.74), developmental regression (0.66) and visual loss (0.73, never reported as that exact term in R1-train)
fall just under tau.

## Top 30 terms
| # | HPO id | label | score (bits) | n_genes | R1-train count |
|---|---|---|---|---|---|
| 1 | HP:0100785 | Insomnia | 1.250 | 67 | 8 |
| 2 | HP:0032037 | Mildly reduced visual acuity | 1.215 | 5 | 33 |
| 3 | HP:0033383 | Decreased compound muscle action potential amplitude | 1.212 | 19 | 23 |
| 4 | HP:0009129 | Upper limb amyotrophy | 1.209 | 87 | 8 |
| 5 | HP:0007149 | Distal upper limb amyotrophy | 1.205 | 72 | 9 |
| 6 | HP:0012548 | Fatty replacement of skeletal muscle | 1.157 | 38 | 12 |
| 7 | HP:0001310 | Dysmetria | 1.155 | 195 | 42 |
| 8 | HP:0000744 | Low frustration tolerance | 1.154 | 32 | 14 |
| 9 | HP:0040218 | Reduced total natural killer cell count | 1.151 | 28 | 9 |
| 10 | HP:0030948 | Elevated gamma-glutamyltransferase level | 1.142 | 58 | 16 |
| 11 | HP:0006855 | Cerebellar vermis atrophy | 1.137 | 67 | 31 |
| 12 | HP:0005978 | Type II diabetes mellitus | 1.113 | 152 | 9 |
| 13 | HP:0002307 | Drooling | 1.081 | 169 | 19 |
| 14 | HP:0000473 | Torticollis | 1.076 | 92 | 14 |
| 15 | HP:0003557 | Increased variability in muscle fiber diameter | 1.071 | 123 | 11 |
| 16 | HP:0002900 | Hypokalemia | 1.060 | 74 | 8 |
| 17 | HP:0003691 | Scapular winging | 1.057 | 116 | 8 |
| 18 | HP:0002066 | Gait ataxia | 1.056 | 282 | 43 |
| 19 | HP:0001284 | Areflexia | 1.050 | 344 | 36 |
| 20 | HP:0003281 | Increased circulating ferritin concentration | 1.049 | 54 | 8 |
| 21 | HP:0002071 | Abnormality of extrapyramidal motor function | 1.048 | 417 | 10 |
| 22 | HP:0000819 | Diabetes mellitus | 1.048 | 376 | 11 |
| 23 | HP:0001272 | Cerebellar atrophy | 1.046 | 553 | 89 |
| 24 | HP:0006970 | Periventricular leukomalacia | 1.038 | 51 | 18 |
| 25 | HP:0000739 | Anxiety | 1.036 | 490 | 39 |
| 26 | HP:0007210 | Lower limb amyotrophy | 1.036 | 88 | 26 |
| 27 | HP:0003551 | Difficulty climbing stairs | 1.027 | 76 | 12 |
| 28 | HP:0003202 | Skeletal muscle atrophy | 1.024 | 696 | 21 |
| 29 | HP:0011900 | Hypofibrinogenemia | 1.018 | 30 | 13 |
| 30 | HP:0002070 | Limb ataxia | 1.018 | 100 | 12 |

## Caveats
- The evidence is simulated patients (S3-v3b); the onset effect on them is small (+0.0023 [+0.0013, +0.0034] MRR on
  literature-onset sealed-test cases, EXP-B-005 / ADR-0015) and comes entirely from cases that report an onset.
- The dev check above did not support the score as a selector (see the first table); the list is knowledge-based only.
- The app must collect the onset age for any effect: without it the feature is absent and the gain is zero. Harm
  among onset-known cases exceeded 5% in EXP-B-005 (5.58% on literature-onset sealed-test cases).
- kb-v3 onset comes from HPOA and Orphanet disease-level onsets; genes without onset data are not scored, and diseases
  without onset contribute the background distribution.
- Scores depend on the 8-bin discretisation and the uniform gene prior; terms with 3 to 10 genes are noisy.

## Decision 2026-10-04 (Mateo): the score is not the selection rule
The Precisar button goes on the **most reported symptoms**, not on the high-score terms. Reason: the re-ranker uses one
patient-level onset, all the gain comes from cases that report any onset, and the dev check above showed no term-level
selectivity. The goal is therefore to maximise how many patients give at least one onset.

- **Rule:** rank terms under Phenotypic abnormality (HP:0000118, so onset and clinical-modifier terms are out) by the
  number of R1-train patients reporting the exact term (`splits.load_part`, train only; no R1-dev, R1-test or vault).
  The list is the smallest N whose terms cover at least 90% of R1-train patients (at least one listed term reported),
  capped at 400.
- **Result:** N = 206, coverage 0.9001 of 4103 R1-train patients.
- **Coverage curve:**

| N | 50 | 100 | 200 | 300 | 400 |
|---|---|---|---|---|---|
| patients with at least one listed term | 0.7165 | 0.7972 | 0.8981 | 0.9344 | 0.9464 |

- **File for the app:** `results/onset-informative-terms/onset-prompt-terms-v1.json` (artifact `onset-prompt-terms-v1`,
  version `v1-most-reported`, sorted by `r1_train_count`; `score_bits` and `n_genes` kept as data). The score-based
  `onset-informative-terms-v1.json` stays as the record of the first attempt and its failed dev check.
- Top 20 of the new list:

| # | HPO id | label | R1-train count | score (bits) |
|---|---|---|---|---|
| 1 | HP:0001263 | Global developmental delay | 1154 | 0.764 |
| 2 | HP:0000750 | Delayed speech and language development | 796 | 0.8054 |
| 3 | HP:0001249 | Intellectual disability | 740 | 0.81 |
| 4 | HP:0001252 | Hypotonia | 623 | 0.7395 |
| 5 | HP:0004322 | Short stature | 475 | 0.776 |
| 6 | HP:0000252 | Microcephaly | 360 | 0.7939 |
| 7 | HP:0001270 | Motor delay | 346 | 0.8403 |
| 8 | HP:0000316 | Hypertelorism | 335 | 0.6842 |
| 9 | HP:0031936 | Delayed ability to walk | 329 | 0.8646 |
| 10 | HP:0001250 | Seizure | 322 | 0.8089 |
| 11 | HP:0011968 | Feeding difficulties | 320 | 0.725 |
| 12 | HP:0000369 | Low-set ears | 246 | 0.7211 |
| 13 | HP:0000729 | Autistic behavior | 246 | 0.7698 |
| 14 | HP:0002650 | Scoliosis | 242 | 0.7843 |
| 15 | HP:0000343 | Long philtrum | 221 | 0.651 |
| 16 | HP:0001572 | Macrodontia | 218 | 0.5227 |
| 17 | HP:0001508 | Failure to thrive | 194 | 0.7069 |
| 18 | HP:0000486 | Strabismus | 189 | 0.7626 |
| 19 | HP:0001155 | Abnormality of the hand | 189 | 0.7854 |
| 20 | HP:0000463 | Anteverted nares | 184 | 0.7302 |
