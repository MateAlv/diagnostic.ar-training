# P3-BATCH1-DIAG: why ladder batch 1 showed nothing, and where the room is

- **Date:** 2026-10-14. Exploratory (EVAL_PROTOCOL §9): `p3-v1` train, FIT and SELECT folds only. No CONFIRM read, no
  vault patient read.
- **Inputs:** batch 1 rank files (`data/interim/v4/<run>/ranks/`), E0 ranks (`R0`), the `sim4` knowledge.
- **Code:** `scripts/analysis/p3_batch1/` (`feat.py` per-patient features, `an.py` breakdowns, `gw.py`
  publication-weighted Δ, `knn.py` real-patient neighbours). Intermediates in `$P3_B1_DATA` (default
  `data/interim/p3-b1`).
- **Disclosure:** the vault's group sizes were counted from case-ID prefixes in the committed `p3-v1.json` (metadata
  only: no phenotype, gene, rank or score of a vault patient was read). This motivated the capped gate (§1).

## 1. The metric was mostly one publication
- SELECT uncited has 735 patients in 93 groups. **PMID:36446582 (ANKRD11, KBG syndrome) alone has 333 (45%).**
  - R2's whole SELECT loss vs R1 (−0.119) is that paper (−0.127). Without it, R2 − R1 = +0.013.
  - R4 − R1 = −0.033, of which −0.031 is that paper.
- FIT uncited: the largest group has 157 of 1,581 patients.
- **Vault uncited: the largest group has 462 of 2,678 patients (17%), the top 5 have 29%.** A patient-weighted gate
  would mostly measure one gene.
- **Decision (Mateo, 2026-10-14): cap each publication's weight at 10 patients** (ADR-0019 amendment). Effective
  size and weight of the largest group, uncited patients:

  | Cap | Vault effective n | Largest group | Top 5 |
  |---|---|---|---|
  | none | 2,678 | 17.3% | 28.8% |
  | 10 | 1,446 | 0.7% | 3.5% |
  | 1 (publication mean) | 417 | 0.2% | 1.2% |

## 2. Weighted by publication, the simulator rungs are noise
Uncited, in-vocabulary; each publication weight 1; Δ vs E0 with a group bootstrap CI.

| Rung | SELECT (77 groups), E0 0.426 | FIT (234 groups), E0 0.351 |
|---|---|---|
| R1 | −0.044 [−0.093, +0.005] | +0.006 [−0.027, +0.042] |
| R2 | −0.056 [−0.124, +0.012] | +0.003 [−0.038, +0.045] |
| R3 | −0.072 [−0.145, +0.000] | −0.009 [−0.050, +0.032] |
| R4 | −0.078 [−0.139, −0.018] | +0.016 [−0.024, +0.054] |

- R1 vs E0 is better on 31 SELECT groups and worse on 32: retraining alone moves single publications by as much as
  the effects we look for.
- Resolution: about ±0.05–0.07 on SELECT, ±0.04 on FIT. Effects under about 0.03 cannot be resolved.
- R1's gap to E0 is on cited and well-explained patients (FIT cited 0.475 vs 0.594; FIT uncited, ≥ 75% explained,
  0.306 vs 0.430), consistent with the collapsed schedule (PHASE3 §2c). R1c (cosine) tests it.

## 3. What cannot move under the ADR-0019 knowledge cut
| Slice (uncited) | SELECT | FIT | Every model |
|---|---|---|---|
| Gene outside E0's vocabulary | 140 / 735 (19%) | 543 / 1,581 (34%) | MRR 0 |
| In vocabulary, < 25% of present terms explained by the gene's annotations | 37 | 220 | MRR ≤ 0.09 |

- Where the rungs differ: in-vocabulary patients 25–75% explained. On FIT, R4 lifts 25–50% from 0.077 to 0.169 and
  50–75% from 0.345 to 0.418 (patient-weighted, not tested).
- A simulator of the same annotations adds robustness, not knowledge. Its plausible gain is below the resolution of §2.

## 4. Real patients carry knowledge E0 lacks
`knn.py`: each patient's IC-weighted ancestor closure; cosine similarity to FIT patients of *other* publications; gene
score = max similarity among that gene's FIT patients; fused as log p_E0 + λ · score, λ chosen on FIT
(publication-weighted). SELECT queries use FIT memory; FIT queries leave their own group out.

| Uncited, in-vocabulary | E0 | + kNN (λ 32) | + gene prior only (λ 4) |
|---|---|---|---|
| FIT, publication-weighted | 0.351 | 0.526 | 0.428 |
| SELECT, publication-weighted | 0.426 | 0.539, Δ +0.113 [+0.040, +0.186] | 0.524 |
| SELECT, patient-weighted | 0.498 | 0.312 (helped 96, harmed 398) | 0.418 |

- **"Gene prior only"** is phenotype-blind: log(1 + number of other FIT publications with the gene). It reaches most of
  the SELECT gain. Beyond it, phenotype similarity adds about +0.10 on FIT and +0.015 on SELECT.
- **The gain is a transfer between patients:**

  | SELECT, patient-weighted | E0 | + kNN (λ 32) |
  |---|---|---|
  | gene has other training patients (153) | 0.419 | 0.631 |
  | gene has none (442) | 0.526 | 0.201 |

- **Validity risks:**
  - phenopacket-store gene frequencies follow curation choices, not clinical incidence. The vault shares them, so a
    cohort prior can pass the gate without helping production patients.
  - Curators reuse term lists within a gene, so similarity may partly match curation style.
- λ 32 is the edge of the grid. The fusion is not tuned for harm.

## 5. Consequences (PHASE3 §2e)
- Gate, selection and ladder readings use capped MRR (cap 10).
- v4 is re-centred on real patients (Mateo, 2026-10-14). The simulator ladder shrinks to the R1 reproduction and one
  fixed-schedule R4.
- The cohort gene prior is reported separately, and the phenotype part is shown on its own. Its admissibility for
  the claim is an open decision (PHASE3 §2e).

## 6. K1: phenotype-only real-patient memory (after Mateo's no-prior decision)
`k1.py`: the same IC-cosine neighbours, with the prior removed.
- **Calibration:** each gene's best similarity is turned into a z-score against the best similarity that patients of
  *other* genes reach on its memory, so a gene's number of memory patients alone earns nothing.
- **Fusion:** log p_E0 + λ · max(0, z − t). The grid is 8 λ × 5 t, chosen on FIT (own group left out): λ 4, t 1.
- **Popularity control:** each query's phenotype is swapped for another query's of the same fold, true gene kept.

| Capped MRR, uncited (all, incl. OOV) | E0 | K1 | Δ [CI] | Phenotype swapped, Δ |
|---|---|---|---|---|
| FIT (λ, t tuned here) | 0.193 | 0.297 | +0.104 [+0.062, +0.152] | −0.052 |
| SELECT | 0.282 | 0.341 | **+0.059 [+0.002, +0.122]** | −0.049 |
| SELECT, in-vocabulary | 0.413 | 0.494 | +0.081 [+0.002, +0.169] | −0.071 |

- **The swap control is negative,** so no popularity gain remains: the gain needs the patient's own phenotype.
- **Harm on SELECT:**
  - 386 patients harmed and 80 helped, but 285 of the harmed (and 98 of the 129 that lose top-1) are the ANKRD11 paper.
  - ANKRD11 has no patient in FIT memory, so genes with memory overtake it.
  - Outside that paper, 101 patients are harmed in 29 publications and 80 helped in 32.
  - **In production the memory holds every curated patient,** so the "gene without memory" case is rarer than in
    this FIT-only memory.
- **Not yet done:** harm control (K2), learned similarity (K3), a parametric version (R5), and a second memory/query
  rotation to tighten SELECT's CI.
