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

## 7. R1c: the pipeline reproduces E0 (Gate A)
R1 with a cosine schedule (floor 0.05), 90 min, `configs/p3/b2/R1c.yaml`. Capped Δ vs E0:

| Checkpoint | SELECT uncited | FIT uncited | SELECT cited | FIT cited |
|---|---|---|---|---|
| best (step 450k, chosen on SELECT plain MRR) | −0.002 [−0.030, +0.025] | −0.003 [−0.015, +0.008] | −0.031 [−0.053, −0.004] | −0.033 [−0.049, −0.018] |
| **final** (step 1.28M, not chosen) | **−0.008 [−0.031, +0.015]** | **−0.005 [−0.017, +0.006]** | **−0.008 [−0.027, +0.013]** | −0.014 [−0.027, −0.002] |
| R1 (plateau), best | −0.024 [−0.052, +0.002] | −0.010 [−0.026, +0.007] | −0.085 [−0.128, −0.045] | −0.102 [−0.128, −0.078] |

- **Gate A passes on capped MRR:** the final checkpoint is within 0.02 of E0 on SELECT uncited, FIT uncited and
  SELECT cited. The schedule was the gap. Plain MRR on SELECT uncited is −0.030, almost all of it the ANKRD11 paper.
- Later steps raise cited MRR steadily, while SELECT uncited plain MRR swings between 0.35 and 0.41.
- Final checkpoint read with `final_checkpoint.py` (ranks in `data/interim/v4/final/`).

## 8. K2: harm controls, and K1 read out of fold over four folds
`k2.py`. Memory = every fold 0–3 patient; a query's own publication is left out of the memory and of the per-gene
null. Each outer fold's configuration is chosen on the other three folds' uncited queries (nested), so every
reading below is out of fold. K2 adds a cap B on the boost and a gate (no boost when E0's top probability ≥ τ).

| Capped MRR, uncited (incl. OOV) | Groups | E0 | K1 | Δ [CI] | Phenotype swapped, Δ |
|---|---|---|---|---|---|
| **Folds 0–3 pooled** | 402 | 0.213 | 0.289 | **+0.076 [+0.041, +0.111]** | −0.048 |
| fold 0 | 112 | 0.214 | 0.337 | +0.123 [+0.043, +0.209] | −0.063 |
| fold 1 | 113 | 0.195 | 0.291 | +0.096 [+0.045, +0.154] | −0.004 |
| fold 2 | 84 | 0.168 | 0.218 | +0.050 [−0.021, +0.123] | −0.056 |
| fold 3 (SELECT) | 93 | 0.282 | 0.306 | +0.024 [−0.033, +0.086] | −0.076 |
| in-vocabulary, pooled | 311 | 0.329 | 0.445 | +0.116 [+0.067, +0.171] | −0.074 |
| cited, pooled | 411 | 0.676 | 0.661 | −0.016 [−0.050, +0.020] | −0.140 |

- **Positive in every fold;** the swap control is negative or about 0 in every fold.
- SELECT is +0.024 here vs +0.059 with FIT-only memory (§6). Both lie within SELECT's CI (about ±0.06).
- **K2 does not help:** the nested selection picks no cap, and a gate only in two folds. Pooled +0.074
  [+0.039, +0.110], harmed 883 vs 916.
- **Harm is genes without memory.** Uncited pooled: 423 helped, 916 harmed. Harmed are 282 in PMID:36446582
  (ANKRD11), 156 in PMID:31021519 (SATB2), 62 in PMID:39191256 (TMEM216). Each is the only publication of its gene
  in folds 0–3, so the true gene gets no evidence while others do.
  - Under the cap, each such paper weighs at most 10 patients.
  - A compensating boost for genes without memory would be a cohort-presence prior, so it is not used (ADR-0019
    amendment).
- A first draft of `k2.py` left the query's own publication in the per-gene null. That raised the pooled Δ to
  +0.081; the version above removes it.

## 9. K3: similarity variants and the curated-terms stress test
`k2.py --sim {ic,idf,direct} --agg {max,top2} [--perturb parent]`, same nested out-of-fold protocol as §8. All six
variants were run; none was tuned beyond the nested (λ, t) grid.
- `ic`: disease-IC weights on the ancestor closure (K1).
- `idf`: inverse frequency among fold 0–3 patients.
- `direct`: disease IC on the present terms only, no ancestors.
- `top2`: mean of the gene's two best publications, each scored by its best patient (`max`: best patient).

**Stress test.** phenopacket-store curates each gene cohort into a shared term template, so exact-term matches can
reflect curation instead of the clinical picture. `--perturb parent` replaces every query term by one of its parents
(seeded) before the memory lookup. Memory, null and E0 keep the curated terms. Every phenopacket has the same
`createdBy`, so a different-curator check is not possible (`curators.py`).

| Uncited capped Δ, folds 0–3 pooled | Curated terms | Parent terms | Swap control (curated / parent) | Cited, curated |
|---|---|---|---|---|
| ic, max (K1) | +0.076 [+0.041, +0.111] | +0.055 [+0.030, +0.079] | −0.048 / −0.010 | −0.016 |
| **ic, top2** | +0.084 [+0.048, +0.119] | **+0.062 [+0.036, +0.087]** | −0.047 / −0.008 | −0.011 |
| idf, max | +0.070 [+0.042, +0.098] | +0.056 [+0.032, +0.080] | −0.020 / −0.005 | +0.022 |
| idf, top2 | +0.077 [+0.041, +0.114] | not run | −0.056 | −0.030 |
| direct, max | +0.094 [+0.062, +0.128] | +0.012 [+0.002, +0.023] | −0.029 / −0.003 | +0.020 |
| direct, top2 | +0.103 [+0.069, +0.138] | +0.008 [+0.002, +0.016] | −0.031 / −0.001 | +0.026 |

- **`direct` is rejected.** Its lead is exact template terms: it keeps under 15% of its gain with parent terms.
- **The ancestor-closure similarities keep 70–80%** of their gain when every term is moved to a parent.
- Carried forward: ic-max (K1) and ic-top2 (at most 3 finalists reach CONFIRM, PHASE3 §2e F). Choosing among them
  on these folds is a selection; CONFIRM reads it once.
- The vault is curated the same way, so its gate cannot detect template matching. The parent-term reading is
  reported next to any vault result.
