# EXP-B-002: rr-v2, feature weights learned on R1-train

- **Front:** B
- **Registered:** 2026-09-29, by Mateo Alvarez
- **Status:** planned

## Hypothesis
EXP-B-001 failed because its feature signs were assumed. In R1, for example,
negated findings are *more* often the true disease's own features. Learning
each component's weight from R1-train patients gives a positive R1-dev Δ MRR
over E0 with a harmed rate ≤ 5%.

## Systems compared
| System | Artifact ids / code | Notes |
|---|---|---|
| E0 | `genphenia_v3` | Recomputed in the same run; β = 0 reproduces it exactly |
| rr-v2 | `rerank/learned.py`, `rerank/features.py` (`components`), KB `kb-v4` | `score = log p_gnn + β·x` on the top-200; the GNN coefficient is fixed at 1 |

## Components x (each 0 without its input)
| Component | Definition |
|---|---|
| `neg_llr` | Σ log(1 − 0.5·P(t\|gene)) over excluded terms |
| `neg_annotated_share` | Share of excluded terms the gene annotates (P > 0) |
| `sex_prior` | log(P(sex\|gene)/0.5), from inheritance |
| `sex_restricted` | Penalty for present findings the gene explains only through other-sex annotations |
| `age_mean` | log P(onset ≤ age), averaging listed onset classes (EXP-B-001's feature) |
| `age_any` | log P(onset ≤ age), where a disease fits if any listed class fits (EXP-B-001 Addendum 3) |
| `onset` | Onset-bin likelihood ratio vs background |

The `FeatureParams` are as in EXP-B-001, unchanged.

## Data
- **KB `kb-v4` masks ALL R1 publications**, not only the held-out ones. A
  train patient's features must not come from annotations curated from
  their own paper, while dev patients' papers are masked. That gap would
  make train look easier than dev.
- **Fit β** on R1-train patients whose true gene is in the GNN's top-200 and
  who have at least one nonzero component. The loss is L2-penalised
  conditional-logit likelihood over those candidates.
- **Select the penalty** on R1-dev among {0.01, 0.1, 1, 10}. That is the
  budget: 4 configurations, all reported with their β.
- **No sealed read.** A test read happens only in Phase 4, under its own
  pre-registration.

## Primary metric and selection rule
- **Primary:** R1-dev Δ MRR vs E0, all cases, with a paired
  publication-clustered 95% CI.
- **Also reported:** train (in-sample) Δ, harmed/helped rates, and β
  (signs).
- **rr-v2 := the penalty with the highest dev Δ** among those with dev Δ > 0
  and harmed ≤ 5%; otherwise "no candidate".
- **Exploratory, labelled as such:** per-component ablations of the chosen
  model on dev, evaluation only.

## Expectations (written before running)
| Component | Expected coefficient |
|---|---|
| `neg_annotated_share` | **positive** (absent findings belong to the true disease more often) |
| `neg_llr` | small or positive; the negative-direction assumption doesn't hold on R1 |
| `age_any` | positive (incompatibility penalised) |
| `age_mean` | near 0 once `age_any` is present |
| `sex_prior` | small positive |
| `onset` | small positive |

Expected result: dev Δ in [0, +0.02], harmed ≤ 5%. A train Δ well above the
dev Δ would signal overfitting to train publications.

## Results
(filled after running)

## Verdict

## Addenda
