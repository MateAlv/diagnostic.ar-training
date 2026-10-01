# ANALYSIS-006: Candidate 6a and the last two gaps

- **Date:** 2026-10-01.
- **Data:** R1-train only, plus `ds-sim0.5.2-full-n100-s1001` (candidate 6a,
  PR #61).
- **Script:** `scripts/analysis/explained_exactness.py`.
- **Outputs:** `results/analyses/ANALYSIS-006/`.

## 1. Candidate 6a's train-side go/no-go
No R1-dev read was made.

| Check | Candidate 6a | Candidate 5 | Result |
|---|---|---|---|
| G2a | 0.306 | — | pass |
| G2e gap | **0.011** (E0 0.394) | 0.049 | pass |
| G2b-train | 0.507 | — | pass |
| G2c | 2.955 | 1.908 | **fail** |
| G2d | 0.764 [0.737, 0.794] | 0.809 | **fail**, close to the 0.75 limit |

Per-gene Spearman of record size vs true-term count fell from 0.966 to 0.658
(real: 0.50–0.53). Budget normalisation fixed record-size coupling.

## 2. Records are now too short (G2c)
- Simulated: 5.74 terms per case, against 8.70 for all of R1-train.
- p10/p25/median/p75/p90: simulated 1/2/5/8/11 vs real 2/4/7/11/17.
- **Why:**
  - the budget covered only explained terms, drawn from uncited patients
    (mean 5.38), while G2c compares with every present term in all of
    R1-train;
  - noise was added proportionally on top (1.19 per case);
  - truth sometimes runs out (realised profile terms 4.57 vs drawn k 5.65).

## 3. Simulated reports generalise too often (part of G2d)
Among explained terms (vs kb-v3), the share that are a **strict ancestor**
of an annotated term rather than the exact term:

| | Ancestor share | Explained terms |
|---|---|---|
| R1-train, uncited patients | **0.093** | 6,130 |
| Candidate 6a (1 in 50 sample) | 0.152 | 41,376 |

This matches candidate 6a's top C2ST features: mean depth (AUC 0.386; real
6.56 vs simulated 6.23) and annotated share (0.404).

## 4. Consequences for candidate 6 (ADR-0011 amendment 8)
1. **Record-level budget.** Draw the total present terms per case from all
   R1-train patients: report-model-v2's `term_budget` histogram, mean 8.70,
   the same population G2c uses.
2. **Noise inside that budget.** Noise takes Binomial(k, ρ = 0.207) slots,
   at most k − 1. Profile terms fill k − n by budget-normalised q.
3. **Generalisation rate** (`ontology_smoothing_rate`) piloted to an
   ancestor share of 0.093.
4. Literature-enriched profiles and presentation ages (ADR-0013) when ready.
