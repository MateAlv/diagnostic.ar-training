# EXP-B-001: rr-v1, a feature-weighted re-ranker over v3.0, searched on R1-dev

- **Front:** B
- **Registered:** 2026-09-29, by Mateo Alvarez
- **Status:** planned

## Hypothesis
Re-scoring v3.0's top-200 genes with knowledge-based compatibility features
for the patient's negated symptoms, sex, age and onset (`kb-v3`) improves R1
MRR over E0. Age and onset carry most of the gain, because 87% of v3.0 genes
have onset knowledge in `kb-v3`, against 4–7% for sex restriction or explicit
negation.

## Systems compared
| System | Artifact ids / code | Notes |
|---|---|---|
| E0 | `genphenia_v3` | Also the `identity` configuration. It must reproduce EXP-000's dev ranks exactly |
| rr-v1 | `rerank/features.py`, `rerank/model.py`, KB `kb-v3` | `score = log p_gnn + Σ w_f · feature_f` on the top-200 genes; the rest unchanged |

## Features (fixed before any result)
`FeatureParams`: `neg_strength` k = 0.5, `unknown_frequency` = 0.3 (the
qa-agent's prior), `epsilon` = 0.01, `onset_smoothing` = 0.1.

| Feature | Definition |
|---|---|
| **neg** | Σ over excluded terms t of log(1 − k·P(t\|gene)). P is the weight-mixture over the gene's diseases (`genes-v1`) of the noisy-OR of annotated frequencies of t and its descendants. It is 0 when the gene doesn't annotate t |
| **sex** | log(P(sex\|gene) / 0.5), with P(male) from inheritance (male-limited 0.99, female-limited 0.01, Y 0.99, XLR 0.9, XLD 0.33, X-linked 0.7, else 0.5), plus log(max(ε, P(t\|gene, sex) / P(t\|gene))) for each present term. The second part penalises findings the gene explains only through annotations restricted to the other sex |
| **age** | log(max(ε, P(onset ≤ age \| gene))), with onset intervals uniform. A disease without onset data counts as compatible |
| **onset** | log(P(onset bin \| gene) / P(onset bin \| background)) over 8 bins, smoothed with 0.1 uniform. Diseases without onset use the background |

Each feature is 0 when its input is missing, which makes the re-ranker
exactly the identity then (tested).

## Data
- **Fitting:** none. rr-v1 has four weights and no trained parameters.
- **Selection:** R1-dev (1,883 patients), publication-clustered bootstrap.
- **No sealed read in this experiment.** A test read for the chosen rr-v1
  happens only in Phase 4 under its own pre-registration.

## Search (budget: 16 configurations, all reported)
1. `identity`: all weights 0 (1 configuration).
2. **Stage 1:** each feature alone, w ∈ {0.5, 1, 2} (12 configurations).
   This doubles as the input-view ablation, because a weight of 0 is
   equivalent to removing that input.
3. **Stage 2, fixed by rule:** each feature takes its best stage-1 w if that
   configuration's dev Δ MRR > 0, else 0 (`stage2-combined`). The same
   combination runs at half strength (`stage2-combined-half`). That is 2
   configurations.

## Primary metric and selection rule
- **Primary:** Δ MRR vs E0 on R1-dev, all cases, with a paired
  publication-clustered 95% CI.
- **Also reported:** harmed/helped rates, top-1/10, subsets with each input.
- **rr-v1 := `stage2-combined`** if its Δ > 0 and its harmed rate ≤ 5%;
  otherwise the best single-feature configuration meeting the same rule;
  otherwise "no candidate".
- The candidate advances to the Phase 4 gate (R1-test, MCRD, DDD). Nothing
  here claims a confirmed improvement.

## Expectations (written before running)
| Component | Expectation |
|---|---|
| identity | Ranks identical to EXP-000 dev, case by case |
| age / onset alone | Small positive Δ (+0.005 to +0.03 MRR) |
| neg alone | ≈ 0, as the qa-agent measured with frequency-based negation |
| sex alone | ≈ 0 overall (few genes), possibly positive in the X-linked subset |
| Combined | Δ in [0, +0.04]; harmed rate < 5% |

## Results
(filled after running)

## Verdict

## Addenda
