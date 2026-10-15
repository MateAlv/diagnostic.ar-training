# P3-ADDON: the re-rank add-on refitted on the network's out-of-fold scores

- **Date:** 2026-10-15. PHASE3 §2f step 2 (ADR-0019 amendment 2026-10-15). `p3-v1` train folds 0–3 only, read
  out of fold. No CONFIRM read, no vault patient read.
- **Code:** `src/diagnostic_ar_training/v4/addon.py`, `scripts/analysis/p3_addon/` (`kb.py`, `logits.py`,
  `read.py`; `confirm.py` is written, tested with fakes, not run). Numbers: `results/P3/addon/oof.json`; ranks
  `data/interim/p3-addon/ranks/`.
- **Metric:** capped MRR (10 patients per publication), Δ with the publication-cluster bootstrap
  (`v4.report`). Helped / harmed are patient counts.

## 1. Results, pooled over folds 0–3 (5,053 patients)

| Variant | Stratum | n (pubs) | capped MRR (E0) | Δ vs E0 [95% CI] | helped / harmed |
|---|---|---|---|---|---|
| a. network | uncited | 2,316 (402) | 0.2840 (0.2126) | **+0.0714 [+0.0488, +0.0962]** | 631 / 551 |
| | uncited in-vocab | 1,633 (311) | 0.4375 (0.3287) | +0.1088 [+0.0755, +0.1445] | 631 / 551 |
| | cited | 2,737 (412) | 0.7355 (0.6758) | +0.0597 [+0.0368, +0.0829] | 832 / 442 |
| b. network + add-on, sex / age / onset | uncited | | 0.2841 | **+0.0714 [+0.0485, +0.0965]** | 640 / 545 |
| | uncited in-vocab | | 0.4376 | +0.1089 [+0.0762, +0.1449] | 640 / 545 |
| | cited | | 0.7359 | +0.0601 [+0.0373, +0.0832] | 836 / 438 |
| c. network + add-on, all features | uncited | | 0.2840 | **+0.0713 [+0.0484, +0.0963]** | 636 / 550 |
| | uncited in-vocab | | 0.4375 | +0.1087 [+0.0758, +0.1449] | 636 / 550 |
| | cited | | 0.7357 | +0.0599 [+0.0371, +0.0829] | 834 / 439 |
| d. E0 + add-on, all features (reference) | uncited | | 0.2130 | +0.0003 [−0.0006, +0.0014] | 409 / 43 |
| | uncited in-vocab | | 0.3292 | +0.0005 [−0.0009, +0.0021] | 409 / 43 |
| | cited | | 0.6771 | +0.0013 [+0.0004, +0.0023] | 159 / 26 |

**The add-on on top of the network (Δ vs a), pooled:**

| | uncited | uncited in-vocab | cited |
|---|---|---|---|
| b − a | +0.0001 [−0.0014, +0.0014], 340 / 26 | +0.0001 [−0.0021, +0.0022] | +0.0004 [−0.0002, +0.0012], 146 / 7 |
| c − a | −0.0000 [−0.0016, +0.0013], 353 / 44 | −0.0001 [−0.0024, +0.0021] | +0.0002 [−0.0003, +0.0010], 151 / 26 |

**Per fold, uncited** (network of the fold: `R5x-f0-34cd370c47`, `R5x-f1-fc60f6a846`, `R5x-f2-bcb6ff0d93`,
`R5-r30-fa772ffa7e`):

| Fold | n (pubs) | a vs E0 | b vs E0 | c vs E0 | d vs E0 | b − a (helped / harmed) | c − a (helped / harmed) |
|---|---|---|---|---|---|---|---|
| 0 | 498 (112) | +0.0588 | +0.0571 | +0.0567 | −0.0009 [−0.0040, +0.0013] | −0.0017 [−0.0061, +0.0002] (105 / 3) | −0.0021 [−0.0072, +0.0004] (116 / 21) |
| 1 | 630 (113) | +0.0890 | +0.0908 | +0.0908 | +0.0017 [+0.0001, +0.0044] | +0.0018 [−0.0016, +0.0055] (113 / 7) | +0.0018 [−0.0016, +0.0055] (115 / 7) |
| 2 | 453 (84) | +0.0833 | +0.0832 | +0.0832 | +0.0002 [−0.0000, +0.0007] | −0.0001 [−0.0007, +0.0003] (33 / 16) | −0.0001 [−0.0007, +0.0003] (33 / 16) |
| 3 | 735 (93) | +0.0511 | +0.0513 | +0.0513 | +0.0003 [+0.0001, +0.0006] | +0.0002 [+0.0000, +0.0005] (89 / 0) | +0.0002 [+0.0000, +0.0005] (89 / 0) |

**Learned θ** (mean of the three seeds' max(θ, 0); the residual subtracts θ · feature):

| Fit | sex_mismatch | onset_strict_late | onset_strict_gap | onset_lenient_gap | xlr_female | neg_obligate | neg_embed |
|---|---|---|---|---|---|---|---|
| b, fold 0 / 1 / 2 / 3 | 1.53 / 2.60 / 2.61 / 2.36 | 0 / 0.08 / 0.03 / 0 | 0 / 0 / 0.27 / 0 | 0.16 / 0.15 / 0.03 / 0 | 2.44 / 3.92 / 3.56 / 3.22 | — | — |
| c, fold 0 / 1 / 2 / 3 | 2.22 / 2.60 / 2.61 / 2.36 | 0 / 0.08 / 0.03 / 0 | 0 / 0 / 0.27 / 0 | 0.24 / 0.15 / 0.03 / 0 | 3.65 / 3.92 / 3.56 / 3.22 | 0.68 / 0.15 / 0 / 0 | 0 / 0 / 0 / 0 |
| d, fold 0 / 1 / 2 / 3 | 3.19 / 2.35 / 3.10 / 2.28 | 0 / 0 / 0 / 0 | 0 / 0 / 0.05 / 0 | 0.21 / 0.00 / 0.21 / 0 | 5.49 / 3.71 / 3.78 / 3.74 | 0.38 / 0.12 / 0 / 0 | 0 / 0 / 0 / 0 |
| **final `p3-addon-v1-sex-age-onset`** | 2.85 | 0.05 | 0.02 | 0.06 | 3.75 | — | — |
| **final `p3-addon-v1-all`** | 2.85 | 0.05 | 0.02 | 0.06 | 3.75 | 0 | 0 |

- **The add-on adds nothing measurable on top of the network:** pooled uncited +0.0001 [−0.0014, +0.0014] (b)
  and −0.0000 (c). Helped outnumber harmed (b: 340 and 26), but the harms are larger moves.
- **Sex carries it.** `sex_mismatch` and `xlr_female` get θ 2–4 in every fit; onset gets almost nothing.
- **Negated symptoms get no weight.** `neg_embed` is 0 in every fit. `neg_obligate` is small in folds 0–1 and
  0 in folds 2–3 and in all three seeds of the final fit, so **the final (c) bundle equals (b)** (θ equal
  within 1e-5). In (c), 36 of the 70 harmed patients are lowered through `neg_obligate`: 20 FBXO11 (16 of PMID
  30679813; the n/n obligate artefact known from ft-v1.1, ADR-0018) and 15 ATP6V0C.
- **E0 + add-on (d)** is the size of ft-v1.1's sealed reads (+0.0014 on `p2-v1` test): +0.0003 uncited,
  +0.0013 cited.
- **Reproduction:** variant (a) and E0 have 0 rank differences from the harness's rank files on every fold,
  and pooled uncited Δ (a) = +0.07136 (crossfit.py: +0.0714). An untrained add-on (θ = 0) gives 0 rank
  differences.

## 2. Variants
- **a. network:** each fold scored by the R5 run that never trained on its patients (final checkpoints, DIAG
  §11), present terms only.
- **b / c. network + add-on:** ft-v1.1's residual (`ft/`, unchanged) on the network's logits: scores = logits
  − Σ_k θ_k c_k(patient, gene), θ ≥ 0, no per-gene parameter. (b) uses `sex_mismatch`, `onset_strict_late`,
  `onset_strict_gap`, `onset_lenient_gap`, `xlr_female`; (c) adds `neg_obligate` and `neg_embed`.
- **d. E0 + add-on (c's features):** a reference for the add-on's own size.
- **Fitting, for fold k:** ft-v1.1's recipe (`c1-lin-all`, lr 0.05, batch 128, patience 20, seeds 0–2, mean of
  the residuals), on the in-vocabulary, scorable patients of the other three folds, with their out-of-fold
  network logits (E0's for d); early stopping on `ft.configs.inner_split`'s held-out publication groups (20%)
  among them. 3,053–3,393 fitting patients per fold. CPU only.
- **Final fit:** (b) and (c) on folds 0–3 (4,369 patients), on the out-of-fold network logits. Bundles
  `p3-addon-v1-sex-age-onset` and `p3-addon-v1-all` (`ft-v1-bundle/2`, kb `p3-addon-kb-v1`, manifests in
  `data/manifests/`), for the network `R5x-f4-ef2f309462`. `addon.score_patients` applies a bundle to any
  patient list; it agrees with the reading's fast path to 0.0.
- **Ranks:** all genes, pessimistic ties; the network on its logits (`v4.evaluate`), E0 on the softmax
  (`eval.harness`); rank inf for genes outside E0's vocabulary or unscorable patients (every patient
  here was scorable).

## 3. Knowledge: `p3-addon-kb-v1` (`ft-kb/2`, unmasked)

| Source | Use |
|---|---|
| `hpo_annotations_2025_03_03` | phenotypes, onset terms, inheritance, obligate phenotypes, disease names (sex rule). NOT rows are never read; 2,011 zero-frequency rows are dropped from the profiles |
| `hpo_ontology_2025_03_03` | ancestors of the obligate phenotypes (an excluded term covers its descendants) |
| `e0_genes_to_phenotype` (GraPhens@7aef83d) | E0's gene list and gene → disease links: 5,129 of 5,229 genes have a disease |
| E0's term embeddings (`genphenia_v3`) | `neg_embed` only, at use |

**What ft-kb / safe-kb read and this build does not** (Phase 2's `ft-kb-all-v2`, `ft-kb-prod-v1`): HPO
2026-02-16 annotations, genes_to_disease and ontology; Orphanet onsets (2026-06); HGNC locations; the 49 Phase
2 curation overrides (all sex-rule removals). No feature becomes empty without them:

| | `p3-addon-kb-v1` | with Orphanet | with HGNC | `ft-kb-prod-v1` (2026 sources, overrides) |
|---|---|---|---|---|
| male- / female-limited genes | 101 / 42 | 101 / 42 | 103 / 42 (DAZ4, TSPY1) | 75 / 17 |
| strict onset genes (≥ 16 y) | 2,743 (312) | 3,024 (252) | 2,743 (312) | 3,073 (212) |
| lenient onset genes | 3,426 | 4,442 | 3,426 | 4,735 |
| X-linked-recessive-only genes | 128 | 128 | 128 | 124 |
| negatable genes (obligate phenotypes) | 708 | 708 | 708 | 711 |

**Declared deviations from ft-v1.1's knowledge:** E0's gene → disease file instead of HPO's 2026
genes_to_disease; zero-frequency rows dropped from the `neg_embed` profiles (ADR-0019 §4); no Orphanet
(HPO-only onsets are later for some genes, so onset features flag more genes); no HGNC (2 Y-chromosome genes
lose the sex limit); no curation overrides (26 more male-limited and 25 more female-limited genes than
production).

## 4. Caveats
- **Stacking leak, small:** the base logits of a fitting patient in fold j come from the network that skipped
  fold j but trained on fold k, so fold k's labels reach θ (7 scalars) through those networks. Strictly nested
  networks would remove it.
- **The final bundles are fitted on out-of-fold logits but will run on `R5x-f4`,** which trained on all of
  folds 0–3. The shift between the two networks' score scales is not measured; CONFIRM will be the first
  reading.
- **Early stopping is weak:** held-out MRR moves by about 0.001; best epochs range from 0 to 34 and seeds
  differ (final `sex_mismatch` 4.2, 3.1 and 1.3).
- **Harms come from the knowledge rules:** ZIC3 in a female (`xlr_female`, rank 1 → 3, the largest);
  SMARCB1, IKZF1, SOCS1 and TAF4 through HPO-only onsets; FBXO11 and ATP6V0C through `neg_obligate`. Phase 2
  corrected some rules of this kind with its overrides (sex) and Orphanet (earlier onsets); the knowledge rule
  here drops both.
- **ADR-0019 decision 4** says no obligate rule is derived from n/n rows; the amendment lets the add-on use
  absent symptoms "built like ft-v1.1", whose `neg_obligate` is that rule. It was fitted as specified; it ends
  with θ = 0 in the final bundle. Mateo to confirm the reading of the amendment.
- **Cited patients** may see annotations curated from their own paper (unmasked knowledge); uncited is
  primary.
- **Excluded terms are literature negatives,** not interview answers (as ADR-0018). Patient HPO ids are
  matched as given, not remapped to the 2025-03-03 ontology (as ft-v1.1).
- **Input coverage** (5,053 patients): sex 4,631, age 3,956, onset 1,316, at least one excluded term 4,635.
- **No phenotype-swap control for the add-on:** it has no per-gene parameter and no patient-count input; the
  network's control stands (DIAG §11).
