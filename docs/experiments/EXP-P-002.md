# EXP-P-002: ltr-v1, a re-ranker of E0's top 100 learned on r1-v1 train, selected on dev

- **Front:** Phase 2, Track 2 ([PHASE2.md](../PHASE2.md), [ADR-0017](../decisions/0017-phase-2-real-patient-restart.md))
- **Registered:** 2026-10-08, before any dev number of these configurations
- **Status:** dev selection. This document is not a sealed-read pre-registration; a confirmation read of the
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
(Filled in after the run.)
