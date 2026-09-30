# ANALYSIS-004: How much gene signal real "noise" carries, and what candidate 3 taught

- **Date:** 2026-09-30.
- **Data:** R1-train only, plus simulated candidate 3
  (`ds-sim0.4.2c3-full-n100-s1001`, 1 in 160 cases).
- **Scripts:** `scripts/analysis/{unexplained_signal,unexplained_in_g2p}.py`.
- **Outputs:** `results/analyses/ANALYSIS-004/`.

## 1. Candidate 3's train-side go/no-go
Candidate 3 recalibrated noise on uncited patients vs kb-v3. It failed
G2c (1.732), G2d (0.764) and G2e (gap 0.142), so the last R1-dev read was
**not** spent (PR #39). It improved G2a on the truth layer (0.305) and
G2b-train (0.536).

## 2. Real unexplained terms carry gene signal; the simulator's vocabulary noise carries none
E0 in-vocab MRR, scored on only these terms:

| Terms | Cases | MRR |
|---|---|---|
| Real uncited patients, kb-v3-unexplained terms | 775 | **0.059** |
| … of those, annotated to the gene in unmasked `genes_to_phenotype` (13.5% of the terms) | 149 | 0.305 |
| … of those, not annotated to the gene in `genes_to_phenotype` | 740 | **0.026** |
| Real uncited patients, explained terms | 1,086 | 0.498 |
| Simulated vocabulary noise (candidate 3) | 2,063 | **0.001** (chance) |
| Simulated related noise (candidate 3) | 1,423 | 0.030 |

**Reading:**
- 13.5% of the "unexplained" terms are knowledge that E0 has (the
  unmasked annotations) and the simulator deliberately does not. For a
  simulator they count as explained, not noise.
- The rest carry weak gene signal (0.026), about what the related-noise
  mechanism produces (0.030). Vocabulary noise is pure chance.
- A noise model that is mostly vocabulary is therefore more damaging per
  term than real noise. This is why every candidate so far is too hard for
  E0.

## 3. Consequences for candidate 4 (ADR-0011 amendment 5)
- **Noise share:** ρ = 0.239 × (1 − 0.135) ≈ 0.207.
- **Noise composition:** the related share is set by pilots against a
  component target measured on R1-train: E0 MRR on noise terms alone ≈
  0.026. This is declared as a component target, distinct from the G2e
  whole-case target.
- **Reporting:** independent per-term reporting (simulator 0.5.0), with a
  report model refit on uncited patients vs kb-v3. The construction audit
  found hallmark features under-reported in 10 of 16 cards.
- **Age:** the duration mean per onset category comes from R1-train.
