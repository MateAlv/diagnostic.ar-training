# EXP-B-002: rr-v2, feature weights learned on R1-train

- **Front:** B
- **Registered:** 2026-09-29, by Mateo Alvarez
- **Status:** done (2026-09-29)

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
Run from commit `6eacff6` (the pre-registration was committed first, at
`3db05de`). Everything is in `results/EXP-B-002/` (`rr-v2-fits.json`, a
ranks file and β per penalty); manifest `results-EXP-B-002-rr-v2-fits`. The
run took about 4.5 min, CPU.

A first run from `3db05de` finished its computation but was refused a
manifest, because I had edited files while it ran. Its outputs were deleted
unrecorded. The rerun from a clean tree reproduced the same numbers
exactly.

Fitting used 2,544 R1-train patients whose true gene is in the top-200 and
who have at least one nonzero component. R1-dev, n = 1,883; Δ is vs E0 with
a paired publication-clustered 95% CI.

| L2 | Train Δ MRR | Dev Δ MRR | Dev 95% CI | Harmed | Helped |
|---|---|---|---|---|---|
| 0.01 | +0.0255 | +0.0562 | [+0.0084, +0.1172] | 0.103 | 0.249 |
| **0.1** | +0.0254 | **+0.0565** | [+0.0086, +0.1179] | 0.103 | 0.249 |
| 1 | +0.0257 | +0.0564 | [+0.0086, +0.1179] | 0.103 | 0.245 |
| 10 | +0.0235 | +0.0494 | [+0.0048, +0.1105] | 0.100 | 0.227 |

Fitted β at L2 = 0.1, in component order:

| Component | β |
|---|---|
| `neg_llr` | −0.52 |
| `neg_annotated_share` | **+3.90** |
| `sex_prior` | −0.94 |
| `sex_restricted` | +1.86 |
| `age_mean` | +1.37 |
| `age_any` | −1.69 |
| `onset` | +0.02 |

**Exploratory ablations** at L2 = 0.1. "Zeroed" drops a group from the
fitted model; "refit" fits again without it.

| Without | Zeroed Δ | Refit Δ | Refit CI | Refit harmed |
|---|---|---|---|---|
| negation | +0.0019 | **+0.0014** | [−0.0021, +0.0054] | 0.084 |
| sex | +0.0560 | +0.0563 | [+0.0084, +0.1176] | 0.105 |
| age | +0.0542 | +0.0547 | [+0.0064, +0.1161] | 0.102 |
| onset | +0.0565 | +0.0565 | [+0.0086, +0.1179] | 0.102 |

**Applying the pre-registered selection rule:** every penalty has dev Δ > 0,
but every harmed rate is 10.0–10.3%, above the 5% cap. **Result: no
candidate.**

**Expectations vs outcome:**

| Component | Expected | Measured | Met? |
|---|---|---|---|
| `neg_annotated_share` | positive | +3.9, the dominant weight | ✅ |
| `neg_llr` | small or positive | −0.52 | ✅ (as β·x: −0.52 × a non-positive value raises annotating genes) |
| `age_any` | positive | negative, collinear with `age_mean` | ❌ (together they carry about +0.002) |
| `sex_prior` | small positive | −0.94 | ❌ |
| `onset` | small positive | ≈ 0 | ≈ |
| dev Δ | [0, +0.02] | +0.056 | above |
| harmed | ≤ 5% | 10% | ❌ |

Train Δ (+0.025) is below dev Δ (+0.056). That is no overfitting signal; the
gap sits within publication-level variability.

## Verdict
❌ **No candidate under the pre-registered rule** (harmed > 5%).

The ablation also shows what the dev gain is made of:
- **Almost all of it (+0.055 of +0.056) comes from the negation
  components**, which learned R1's reporting pattern: genes that annotate
  the patient's absent findings are favoured (EXP-B-001 Addendum 1).
- **Sex, age and onset** add nothing measurable over the GNN
  (≤ +0.002 each, CIs covering 0).

**The negation gain is not deployable, whatever the harmed rate.** In the
web app, negated findings come from the question agent asking about the
*candidates'* distinguishing features. A model rewarding genes that annotate
denied features would push toward exactly the candidates the patient ruled
out. The gain measures how phenopacket-store papers report negatives, not how
patients deny symptoms.

## Addenda

### 2026-09-29, Addendum 1: what this settles for the project (interpretation)
- **R1 cannot validate negation for deployment.** Its excluded findings are
  selected by authors because they are characteristic of the syndrome. A
  deployment-like negation evaluation needs negatives produced the way the
  app produces them: questions about candidates' features, answered from the
  patient's record. That calls for a new evaluation design, to be decided
  with Mateo.
- **The sex, age and onset signals are real in the KB but redundant with
  the GNN's phenotype input on R1.** No compatibility feature or learned
  weight moved dev beyond ±0.002. Front A, a network that sees these inputs
  jointly with the phenotypes, remains the open question for them.
