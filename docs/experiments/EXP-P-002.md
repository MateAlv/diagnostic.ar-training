# EXP-P-002: ltr-v1, a re-ranker of E0's top 100 learned on r1-v1 train, selected on dev

- **Front:** Phase 2, Track 2 ([PHASE2.md](../PHASE2.md), [ADR-0017](../decisions/0017-phase-2-real-patient-restart.md))
- **Registered:** 2026-10-08, before any dev number of these configurations
- **Status:** dev selection done (2026-10-08). This document is not a sealed-read pre-registration; a confirmation read of the
  selected model needs its own pre-registration, an independent review and Mateo's go.

## Hypothesis
A LightGBM LambdaRank model over E0's top 100 genes, with gene-agnostic features and monotone constraints that only
let the new inputs lower a gene, fitted on `r1-v1` train, raises dev MRR over E0. Refitting it without the new-input
features (sex, age, onset, excluded terms) measures what those inputs add.

## Systems compared
| System | Artifact ids / code | Notes |
|---|---|---|
| E0 | `genphenia_v3` (model-v3.0.0), present terms | always included |
| `ltr-v1` | `ltr-kb-v1` (from `kb-v4` and `safe-kb-all-v1`), model artifact `ltr-v1`; `ltr/bundle.py` | E0's top 100 re-ordered by the model; every other gene keeps E0's order below them |
| `ltr-v1-ablation` | the same configuration refitted without the `new` features | the anteproyecto comparison |

## Features (`ltr/bundle.py`, `FEATURES`)
All are gene-agnostic: no gene identity and no statistic of R1 patients per gene.

| Group | Features | Monotone |
|---|---|---|
| `e0` | log-probability, log-rank, log-ratio to E0's top 1 | +, −, + |
| `present` | frequency-aware log-likelihood ratio of the present terms (sum and mean; P(term \| gene) over the masked annotations vs its mean over E0's genes, ε = 0.01), share of present terms the gene annotates, IC-weighted best-match (Resnik) similarity | none |
| `richness` | log(1 + annotated terms), annotated diseases | none |
| `new` | sex-limited mismatch; X-linked recessive only × female; X-linked dominant only × male; strict onset incompatible (Track 1 flag); onset gap, strict and lenient (gene earliest onset − patient onset or age, clipped at 0); negation-contradicted (Track 1 flag); excluded terms by the gene's best annotated frequency band of the term or a descendant: obligate (≥ 0.99), very frequent (0.80–0.99), frequent (0.30–0.80), occasional (< 0.30), unknown frequency | all non-increasing |

- **Knowledge:** every source masks every `r1-v1` publication (`mask_pmids("r1-v1", "all")`), for train and dev
  alike: `kb-v4` (frequencies by ADR-0007) and `safe-kb-all-v1` (the Track 1 knowledge, curated sex overrides,
  built with `--mask-scope all`).
- **Ablation:** the `new` group removed. For the `residual_new` family that leaves only E0's own order, so its
  ablation is E0.

## Families
- `residual_new`: score = log p_E0 + f(e0, new). With no new input set on any candidate the order is E0's, and the
  bundle returns E0's probabilities bit for bit.
- `residual`: score = log p_E0 + shrink × f(all features); shrink is applied after fitting.
- `free`: score = f(all features), no E0 starting score.

## Data
- **Fit:** `r1-v1` train (4,103 patients; the 3,008 whose gene is in E0's top 100 carry a label). Early stopping
  (MAP@100, patience 100, at most 2,000 rounds) on an inner 20% of train publication groups (sha256 of
  `ltr-v1-inner:<group>`).
- **Selection:** `r1-v1` dev, 1,883 patients. Free parts only; no sealed part is loaded.

## Dev search
- **Budget:** 18 of the 20 allowed configurations, fixed in `ltr/train.py` `grid()` before any dev number:
  - `residual_new`: leaves {3, 7} × min data in leaf {100, 1000};
  - `residual`: leaves {3, 7, 15} × min data {100, 1000} × shrink {1, 0.25};
  - `free`: (leaves 15, min data 100) and (leaves 31, min data 1000).
  - Common: learning rate 0.05, L2 1, LambdaRank truncation 100, monotone method "advanced", deterministic, seed 0.
- **Selection rule:** the highest dev Δ MRR among configurations with dev harmed ≤ 5% (the Phase 2 confirmation
  cap); if none qualifies, the highest dev Δ MRR, reported as such. The median over all configurations is reported
  with the winner.
- **Train-only development before the grid was fixed** (inner 20% of train, BITACORA 2026-10-08): the `residual`
  family moved 11–16% of the inner patients down at shrink 1, and about 5% at shrink 0.25. The shrink values come
  from there.

## Primary metric
- Dev Δ MRR vs E0 over all 1,883 patients, misses counted as 0; paired publication-cluster bootstrap (2,000
  resamples, seed 0, 95% CI).
- Also: harmed and helped shares, top-1 and top-10 entries and exits, the post-E0 dev subset (groups with no PMID in
  phenopacket-store 0.1.25 and none cited in HPO 2025-11-24), the known-input subsets, the ablation, ltr − ablation,
  and every number on train (in sample, except the inner 20%).

## Results
Run `dxt ltr select --kb ltr-kb-v1 --id ltr-v1` from `13d1efc` (clean tree), about 8 minutes on CPU. Outputs:
`results/EXP-P-002/` (manifest `results-EXP-P-002-r1-v1-ltr-v1`), model artifact `ltr-v1` (`data/ltr/ltr-v1/`).
Dev n = 1,883 (324 publications), E0 MRR 0.4485; train n = 4,103, E0 MRR 0.4396. Δ is vs E0, paired
publication-cluster bootstrap, 2,000 resamples, seed 0. Harmed/helped: true gene lower/higher than under E0.

### Every configuration
| Configuration | Rounds | Dev Δ MRR [95% CI] | Harmed | Helped | Top 1 | Top 10 | Train Δ MRR [95% CI] | Train harmed |
|---|---|---|---|---|---|---|---|---|
| residual_new-l3-m100 | 49 | +0.00100 [−0.00110, +0.00321] | 76 (4.04%) | 98 | +5/−0 | +2/−4 | +0.00146 [+0.00046, +0.00242] | 0.90% |
| residual_new-l3-m1000 | 25 | +0.00070 [−0.00170, +0.00292] | 47 (2.50%) | 71 | +5/−0 | +1/−4 | +0.00113 [+0.00022, +0.00200] | 0.49% |
| residual_new-l7-m100 | 14 | +0.00085 [−0.00126, +0.00309] | 77 (4.09%) | 88 | +5/−0 | +1/−4 | +0.00125 [+0.00031, +0.00213] | 0.97% |
| residual_new-l7-m1000 | 9 | +0.00084 [−0.00101, +0.00290] | 77 (4.09%) | 71 | +5/−0 | +1/−4 | +0.00100 [+0.00009, +0.00184] | 1.05% |
| residual-l3-m100-s1 | 274 | +0.11639 [+0.03324, +0.19428] | 182 (9.67%) | 544 | +315/−29 | +61/−19 | +0.07710 [+0.04901, +0.10563] | 6.48% |
| residual-l3-m1000-s1 | 256 | +0.11454 [+0.03275, +0.19137] | 187 (9.93%) | 541 | +314/−31 | +62/−19 | +0.07526 [+0.04750, +0.10374] | 6.70% |
| residual-l7-m100-s1 | 748 | +0.12954 [+0.03976, +0.21320] | 222 (11.79%) | 585 | +380/−54 | +80/−38 | +0.15509 [+0.11963, +0.18966] | 4.19% |
| residual-l7-m1000-s1 | 496 | +0.13446 [+0.04537, +0.21630] | 216 (11.47%) | 585 | +385/−42 | +84/−39 | +0.13529 [+0.10020, +0.16966] | 4.83% |
| residual-l15-m100-s1 | 98 | +0.12924 [+0.04353, +0.20705] | 194 (10.30%) | 586 | +354/−34 | +82/−28 | +0.11325 [+0.07991, +0.14765] | 5.87% |
| residual-l15-m1000-s1 | 495 | +0.13541 [+0.04629, +0.21846] | 208 (11.05%) | 576 | +387/−39 | +84/−41 | +0.17333 [+0.13208, +0.21159] | 4.39% |
| **residual-l3-m100-s0.25** | 274 | **+0.05129 [+0.01257, +0.10568]** | **88 (4.67%)** | 435 | +111/−4 | +29/−2 | +0.02340 [+0.01211, +0.03503] | 3.56% |
| residual-l3-m1000-s0.25 | 256 | +0.04995 [+0.01134, +0.10501] | 89 (4.73%) | 428 | +109/−5 | +29/−2 | +0.02291 [+0.01160, +0.03466] | 3.70% |
| residual-l7-m100-s0.25 | 747 | +0.06409 [+0.02141, +0.11970] | 104 (5.52%) | 498 | +139/−7 | +49/−6 | +0.05237 [+0.03766, +0.06677] | 1.73% |
| residual-l7-m1000-s0.25 | 496 | +0.06243 [+0.02105, +0.11868] | 116 (6.16%) | 499 | +133/−5 | +49/−5 | +0.04463 [+0.03105, +0.05758] | 2.07% |
| residual-l15-m100-s0.25 | 98 | +0.05308 [+0.01483, +0.10820] | 98 (5.20%) | 467 | +111/−3 | +37/−5 | +0.03516 [+0.02176, +0.04862] | 2.90% |
| residual-l15-m1000-s0.25 | 495 | +0.06172 [+0.02001, +0.11766] | 102 (5.42%) | 497 | +132/−6 | +49/−2 | +0.05648 [+0.04082, +0.07175] | 1.75% |
| free-l15-m100 | 362 | +0.12587 [+0.03651, +0.21038] | 223 (11.84%) | 583 | +368/−51 | +87/−49 | +0.16416 [+0.12635, +0.20029] | 3.46% |
| free-l31-m1000 | 281 | +0.12567 [+0.03302, +0.21284] | 256 (13.60%) | 561 | +382/−54 | +95/−49 | +0.18478 [+0.14223, +0.22456] | 4.19% |

- 6 of 18 configurations have dev harmed ≤ 5%. Median dev Δ over all 18: +0.06326 (range +0.00070 to +0.13541).
- **Selected by the rule:** `residual-l3-m100-s0.25` (3 leaves, min data 100, shrink 0.25, 274 rounds).
- Train numbers are in sample except for the inner 20% of publication groups.

### Selected model, dev
| Comparison | n | Δ MRR [95% CI] | Helped | Harmed | Top 1 | Top 10 |
|---|---|---|---|---|---|---|
| ltr-v1 vs E0 | 1,883 | +0.05129 [+0.01257, +0.10568] | 435 (23.10%) | 88 (4.67%) | +111/−4 | +29/−2 |
| ablation (no new inputs) vs E0 | 1,883 | +0.04993 [+0.01146, +0.10461] | 428 (22.73%) | 90 (4.78%) | +108/−5 | +29/−2 |
| **ltr-v1 vs ablation** | 1,883 | **+0.00136 [+0.00036, +0.00273]** | 54 (2.87%) | 18 (0.96%) | +4/−0 | +0/−0 |
| ltr-v1 vs E0, post-E0 publications | 351 | +0.00151 [−0.00019, +0.00474] | 9 (2.56%) | 12 (3.42%) | +1/−0 | +0/−0 |
| ablation vs E0, post-E0 | 351 | +0.00151 [−0.00020, +0.00474] | 9 | 12 | +1/−0 | +0/−0 |
| ltr-v1 vs ablation, post-E0 | 351 | −0.00000 [−0.00004, +0.00003] | 3 | 3 | +0/−0 | +0/−0 |

- MRR 0.4485 → 0.4998; top 1 0.339 → 0.396; top 10 0.669 → 0.684.
- ltr-v1 vs E0 by subset: in vocabulary (1,680) +0.05749 [+0.01407, +0.11585]; sex known (1,703) +0.05229; age
  known (1,636) +0.05719; onset known (534) +0.02164 [+0.00600, +0.04282]; excluded known (1,764) +0.05424.
- ltr-v1 vs ablation by subset: sex known +0.00122 [+0.00024, +0.00266]; age known +0.00123 [+0.00022, +0.00269];
  onset known +0.00328 [+0.00020, +0.00770]; excluded known +0.00117 [+0.00018, +0.00270].
- The System (numpy trees, `apply`) gives the same rank as the selection's LightGBM predictions for every dev and
  train patient (0 mismatches).

### Selected model, train
ltr-v1 vs E0 +0.02340 [+0.01211, +0.03503], harmed 146 (3.56%), helped 824, top 1 +107/−8, top 10 +84/−9.
Ablation +0.02280 [+0.01181, +0.03434]. ltr-v1 vs ablation +0.00061 [−0.00029, +0.00143], harmed 41, helped 236.

### Where the dev gain comes from (descriptive, from the committed ranks)
- **One publication carries 60% of the dev gain.** PMID:26178382 (136 NF1 patients): E0 ranks NF1 first for 45 of
  them; ltr-v1 for 120. The five largest contributors (two of them LMNA cohorts, PMID:37843397 with 115 patients
  and PMID:10939567 with 41) carry 85%. Dev without PMID:26178382 (1,747 patients): ltr-v1 +0.0221, ablation
  +0.0206.
- **`richness_terms` has 57.5% of the model's split gain**, then `present_resnik_bma` 13.8%, `present_llr_sum`
  11.8%, `present_llr_mean` 9.2%; every `new` feature is below 0.6%.
- **Richness can stand in for gene identity.** Among E0's 5,229 genes, the number of annotated terms takes 272
  values and is unique for 53 genes, NF1 (306 terms) and LMNA (485, the highest) among them. Train has 158 NF1 and
  64 LMNA patients. A per-gene prior learned this way is what P2-PROBES-v1 §3 found not to carry to new
  publications; the post-E0 dev Δ is +0.00151.
