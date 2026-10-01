# ANALYSIS-005: What still separates candidate 5 from real patients

- **Date:** 2026-10-01.
- **Data:** R1-train only, plus `ds-sim0.5.1-full-n100-s1001` (candidate 5,
  PR #53).
- **Scripts:** `scripts/analysis/c2st_features.py`; the record-size
  computation is reproduced in the output JSON's provenance.
- **Outputs:** `results/analyses/ANALYSIS-005/`.

## 1. Candidate 5's train-side go/no-go
**Passes:**
- G2a: 0.306;
- G2e: gap 0.049, E0 MRR 0.356. This is the first candidate to pass G2e;
- G2b-train: 0.537.

**Fails:**
- G2c: 1.908;
- G2d: AUC 0.809.

No R1-dev read was made.

## 2. Which features separate simulated from real (univariate AUC)
3,514 R1-train patients, each paired with one simulated case of the same
gene:

| Feature | AUC | Real mean | Simulated mean |
|---|---|---|---|
| term count | **0.655** | 8.06 | **14.26** |
| annotated share (kb-v5) | 0.398 | 0.570 | 0.475 |
| mean depth | 0.406 | 6.56 | 6.31 |
| eye / ear / growth system shares | 0.58 / 0.58 / 0.57 | | |
| noise share | 0.551 | 0.374 | 0.409 |

## 3. Record size follows profile richness in simulation, not in reality
Over the 84 genes with at least 10 R1-train patients:

| | Value |
|---|---|
| mean terms per case, real | 8.60 |
| mean terms per case, simulated | **13.38** (median gene ratio 1.33) |
| Spearman, simulated record size vs simulated true-term count | **0.966** |
| Spearman, real record size vs the same simulated true-term count | 0.532 |

**Reading:**
- Independent reporting makes a record's length proportional to how many
  true terms the profile yields, so well-studied genes with rich profiles
  over-report.
- Real authors report a bounded number of terms, only partly tied to how
  rich the disease is.
- The global q_scale was calibrated on pilot genes, so it cannot fix this.

## 4. Consequence for candidate 6 (ADR-0011 amendment 7)
**Budget-normalised independent reporting:**
1. Draw the number of explained terms k for each case from uncited R1-train
   patients' distribution of explained terms (vs kb-v3).
2. Scale the per-term q so that Σ min(1, c·q) = min(k, true terms).
3. Report each term with that probability.

This keeps hallmark concentration (q ratios) and makes record size
realistic.

Candidate 6 also adds the literature-enriched profiles and presentation
ages (ADR-0013) once they are ready.
