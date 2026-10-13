# SIM4-v1: the Phase 3 simulator `sim4`, its knowledge, its fit and its realism on the SELECT fold

- **Date:** 2026-10-13. Development work under ADR-0019 (PHASE3.md §1b–§1c). No sealed part, no CONFIRM fold, no
  ledger row.
- **Data:** `p3-v1` train only, through `splits.load_part`: FIT folds 0–2 for every patient statistic, SELECT fold 3
  for validation. Only publications uncited by E0's knowledge are used (fit and validation); excluded terms are never
  read.
- **Code:** `src/diagnostic_ar_training/sim4/` (`knowledge`, `frequency`, `fit`, `moves`, `sampler`, `config`,
  `folds`, `validate`), CLI `dxt sim4 knowledge|fit|validate|sample`, tests `tests/test_sim4.py`.
- **Outputs:** `results/analyses/SIM4-v1/` (fitted params, validation JSON and table, gap control);
  `data/sim4/sim4-kb-v1.stats.json`; manifests `sim4-kb-v1`, `sim4-fit-v1`, `sim4-validation-v1`.

```bash
dxt sources fetch hpo_ontology_2025_03_03 e0_genes_to_phenotype hpo_annotations_2025_03_03
dxt sim4 knowledge --id sim4-kb-v1
dxt sim4 fit --folds 0,1,2 --manifest-id sim4-fit-v1
dxt sim4 validate --fit-folds 0,1,2 --eval-fold 3 \
  --presets e0,freq,real,real_noise,real_noise_nbhd,real_noise_mix,real_noslope --manifest-id sim4-validation-v1
PYTHONPATH=src python scripts/analysis/sim4/gap_control.py
```

## 1. Knowledge (`sim4-kb-v1`, content sha256 `b2956745…`)

Inputs: `hpo_ontology_2025_03_03` (`hp.json`, sha256 `bcf3c7ca…`, downloaded and verified),
`hpo_annotations_2025_03_03` (`e12a07b4…`) and `e0_genes_to_phenotype` (GraPhens@7aef83d, `54272c87…`; the raw
GitHub URL was downloaded once and gives the same bytes). Nothing else.

| Filter | `phenotype.hpoa` 2025-03-03 | E0 `genes_to_phenotype` |
|---|---|---|
| Rows read | 271,776 | 424,276 (5,229 symbols) |
| Qualifier NOT | 704 (aspect P) + 7 (H) rows dropped | — |
| Frequency 0/n, 0% or HP:0040285, dropped before pooling | 2,011 rows (1,958 pairs zero-only) | 1,980 rows |
| (disease, term) stated only as NOT in HPOA | 704 pairs | 774 rows dropped |
| Not a phenotypic abnormality (inheritance, clinical course, onset, frequency, HP:0000118 itself) | 8 pairs | 17,027 rows |
| `"-"` gene | — | 289 rows (index 0 kept, never simulated) |
| Exact duplicates among the no-disease rows | — | 53,916 collapsed (kept for the `e0` recipe) |
| Kept | 251,422 pairs, 12,683 diseases | 404,206 rows |

- **E0's index** is the sorted set of its gene symbols; `sim4`'s gene index equals the bundle's `genes.json`
  (checked: `e0_index_matches_bundle: true`). 5,226 genes are simulable (not `"-"`; 2 genes have no finding left).
- **Entities per gene:** 10,100 specific diseases, 2,189 ORPHA groups (an ORPHA id linking ≥ 5 genes), 2,285
  no-disease pools (E0's 107,558 rows without a disease id, one pseudo-disease per gene, deduplicated; 101 genes
  have only that).
- **Weights:** each disease 1; a group or the no-disease pool 0.2 when the gene has a specific disease
  (`group_weight`, a knob, not fitted). OMIM/ORPHA duplicates are detectable only by name in this knowledge
  (no cross-references in HPOA 2025-03-03): 428 ORPHA entities have the same normalised name as an OMIM entity of the
  same gene, and each member of such a pair counts half. Term-set overlap does not detect the rest (best Jaccard
  < 0.3 for most ORPHA–OMIM pairs), so other diseases are weighted equally.
- **Frequencies** (ADR-0007 convention): pooled counts as the Jeffreys mean, else mean percentage, else mean HPO
  category midpoint; unknown for 28% of (entity, term)s, which get the fitted default `f0`.
- **Declared deviation from E0's knowledge:** the 774 NOT-only and 1,980 zero-frequency rows E0 trained on as
  positives are dropped (ADR-0019 §4). The `e0` preset drops them too.

## 2. Model

A case for a gene of E0's index:
1. **`e0` recipe** (R1): E0's own selector (GraPhens@7aef83d `SIM/selector.py`): uniform over the gene's rows,
   duplicates included; ancestor distance 0–3 drawn from E0's distance file; term count from E0's demo count file
   (both regenerated bit for bit from `demo.py`, seed 42). Deviations: sim4's rules 2, 4, 5 (no negation rows,
   findings only, no term with its ancestor).
2. **`disease` recipe** (R2–R4): pick one entity by weight; draw the term count; split it into off-profile
   (Beta-binomial) and on-profile terms; pick the base terms with budget-scaled probabilities `min(1, c·f^γ)`;
   report each as itself, an ancestor `d` steps up or a descendant `d` steps down (the fitted category shares);
   fill unfilled slots with further moves, never with duplicates; then off-profile terms (pooled vocabulary and/or
   the profile's ontology neighbourhood). Every case is an antichain of findings.

| Preset | Entity | Term choice | Count | Imprecision / specificity | Off-profile |
|---|---|---|---|---|---|
| `e0` (R1) | gene level | uniform over rows | E0 | E0 distances | none |
| `freq` (R2) | per disease | fitted `γ`, `f0` | E0 | E0 distances | none |
| `real` (R3) | per disease | fitted | fitted + slope | fitted shares | none |
| `real_noise` (R4) | per disease | fitted | fitted + slope | fitted shares | pooled vocabulary |

Variants validated alongside: `real_noise_nbhd` (neighbourhood noise), `real_noise_mix` (half each),
`real_noslope` (no profile-size slope).

## 3. Fitted parameters (FIT folds 0–2, `sim4-fit-v1`)

1,581 uncited FIT-fold patients; 1,038 with a simulable gene and a finding (234 publications), each weighted
1 / (patients of its publication). Fit data hash `1fc78f06…`.

| Parameter | Value | How |
|---|---|---|
| `γ` (frequency exponent) | 0.755 | composite Bernoulli likelihood of which annotated terms a patient reports, under the sampler's own budget-scaled probabilities (patient's own disease when its id matches); log-lik −3150.4 vs −3232.3 uniform and −3164.2 proportional |
| `f0` (frequency of rows without one) | 0.302 | same likelihood |
| Count histogram | 25 bins (1–20, 21–25, 26–30, 31–40, 41–60, 61–100); weighted mean 10.2 terms | after removing the slope |
| Count slope on log(profile size) | 0.110 (centred at 4.31) | weighted least squares of log k |
| Category shares (on-profile terms) | exact 0.760; ancestor d1–d4 0.039 / 0.003 / 0.001 / 0.001; descendant d1–d4 0.101 / 0.040 / 0.027 / 0.028 | weighted pooled shares |
| Off-profile share | Beta(0.861, 2.263), mean 0.276 (observed weighted mean 0.263) | Beta-binomial maximum likelihood |
| Male share, X-linked recessive-only genes | 0.708 (12 publication weights) | covariates only |
| Pooled off-profile vocabulary | 104 terms seen off-profile in ≥ 3 publications, weighted per publication | gene-agnostic |

- **Count:** 14 scalars (`γ`, `f0`, slope, centre, 9 shares, α, β, male share; 12 free) + one 25-bin histogram + one
  vocabulary. Nothing is per gene or per term.
- **Reading:** real patients report frequent annotations more often than rare ones, but less than proportionally
  (`γ` < 1). They over-specify about four times as often as they generalise (descendants 0.196 vs ancestors 0.044 of
  on-profile terms). About a quarter of their terms are off-profile.

## 4. Validation on the SELECT fold (fit on 0–2; 595 uncited patients with a simulable gene, 5 cases each)

`validation-fit012-eval3.md`. Explained share = P3-AUDIT-v1's definition (term annotated to the gene or an
ancestor of an annotation; descendants count as unexplained). Per-gene rho: genes with ≥ 5 patients in both the
SELECT fold and the FIT folds (9 genes), fit-fold patients subsampled to the SELECT count; gap CI by gene bootstrap.
C2ST: logistic regression on `CaseFeatures`, folds and CI by publication.

| Preset | Terms/case | W1 terms | Explained bins <25/25–50/50–75/≥75% | W1 explained | Category TV | Off share | C2ST AUC [95% CI] | Per-gene rho SELECT | rho FIT (matched n) | Gap [95% CI] |
|---|---|---|---|---|---|---|---|---|---|---|
| real (SELECT fold) | 8.44 | — | 0.06/0.07/0.19/0.68 | — | — | 0.199 | — | — | — | — |
| e0 | 4.96 | 3.48 | 0.00/0.00/0.00/1.00 | 0.129 | 0.381 | 0.000 | 0.918 [0.877, 0.954] | 0.276 | 0.301 | 0.025 [−0.017, 0.062] |
| freq | 4.80 | 3.63 | 0.00/0.00/0.00/1.00 | 0.129 | 0.325 | 0.000 | 0.834 [0.768, 0.922] | 0.212 | 0.287 | 0.075 [0.030, 0.119] |
| real | 9.86 | 1.44 | 0.01/0.01/0.10/0.88 | 0.091 | 0.213 | 0.000 | 0.884 [0.745, 0.933] | 0.249 | 0.314 | 0.065 [0.013, 0.130] |
| **real_noise** | 10.33 | 1.90 | 0.10/0.17/0.32/0.42 | 0.105 | 0.105 | 0.285 | **0.714 [0.513, 0.796]** | 0.202 | 0.289 | 0.086 [0.019, 0.153] |
| real_noise_nbhd | 10.06 | 1.63 | 0.08/0.17/0.33/0.43 | 0.096 | 0.095 | 0.271 | 0.789 [0.627, 0.865] | 0.233 | 0.295 | 0.061 [−0.000, 0.125] |
| real_noise_mix | 10.11 | 1.70 | 0.09/0.17/0.33/0.42 | 0.103 | 0.101 | 0.281 | 0.775 [0.598, 0.850] | 0.208 | 0.306 | 0.098 [0.026, 0.190] |
| real_noslope | 9.83 | 1.40 | 0.01/0.01/0.10/0.88 | 0.092 | 0.214 | 0.000 | 0.883 [0.777, 0.928] | 0.223 | 0.278 | 0.055 [0.003, 0.112] |

E0 (fixed) on the same patients and on one simulated case per patient, by explained-share bin:

| E0 MRR | all | <25% | 25–50% | 50–75% | ≥75% |
|---|---|---|---|---|---|
| real (SELECT fold) | 0.490 (n=595) | 0.003 (37) | 0.044 (41) | 0.323 (114) | 0.627 (403) |
| e0 | 0.711 | — | — | — | 0.711 (595) |
| freq | 0.578 | — | — | — | 0.578 (595) |
| real | 0.753 | 0.029 (7) | 0.111 (8) | 0.514 (50) | 0.795 (530) |
| real_noise | 0.432 | 0.007 (53) | 0.042 (107) | 0.357 (197) | 0.764 (238) |
| real_noise_nbhd | 0.508 | 0.036 (45) | 0.109 (91) | 0.465 (200) | 0.763 (259) |
| real_noise_mix | 0.475 | 0.004 (48) | 0.093 (86) | 0.381 (175) | 0.727 (286) |
| real_noslope | 0.806 | 0.002 (4) | 0.061 (7) | 0.565 (56) | 0.848 (528) |

**Reading.**
- Each rung moves toward the real patients: C2ST 0.918 (`e0`) → 0.834 → 0.884 → 0.714 (`real_noise`, the only
  configuration below ADR-0012's 0.75; the CIs overlap). Off-profile terms are what makes the explained-share mix and
  E0's difficulty realistic: without them E0 scores 0.71–0.81, with them 0.43–0.51 vs 0.490 on the real patients.
- **Per bin, E0 behaves like on real patients except at ≥ 75% explained** (0.76 simulated vs 0.63 real): a
  well-explained simulated case is still easier than a real one.
- **Remaining gaps:** `real_noise` puts too many cases in the middle bins (0.32 at 50–75% vs 0.19) and too few at
  ≥ 75% (0.42 vs 0.68). The SELECT fold has fewer off-profile terms (0.199) than the FIT folds (0.263); a single
  Beta also cannot make most cases fully explained while a few are mostly unexplained.
- **Overfitting gap.** All gaps are small and 9 genes is a small sample. A control with no patient-fitted parameter
  (frequency-proportional, `f0` 0.5, E0 counts; `gap-control.json`) shows the same gap: 0.092, 0.053 and 0.051 over
  three seeds. The gap therefore comes from fold composition: the FIT-fold patients of a gene come from more
  publications. It is not memorisation; the old simulator gave 0.52 vs 0.16.
- **Choice of `real_noise`'s off-profile source.** The pooled vocabulary has the lowest C2ST. The neighbourhood
  source matches E0's difficulty and the category shares better. Both stay available as options; R4 can try both.
  This choice was made on SELECT, and every configuration above is on record.

## 5. What was taken from `rare-disease-simulator` (commit `cfc20da7…`)

| Piece | Status | Where | Why |
|---|---|---|---|
| `profiles/frequency.py`: midpoints, `parse_frequencies`, `jeffreys_mean`, ADR-0007 precedence | **ported** | `sim4/frequency.py` | Correct and shared with this repo. Fix: 0/n, 0% and HP:0040285 rows are dropped before pooling (the original pooled a 0/n row into the counts). The interval and category label are not needed |
| `simulation/simulator.py` `budget_scaled_probabilities` | **ported** verbatim | `sim4/sampler.py` | Kept as the reference; `fit.budget_scale` solves the same equation exactly by sorting (equality tested), so both fit and sampler are fast |
| `_RelatedTerms` | **ported** | `sim4/moves.RelatedTerms` | Equal/ancestor/descendant test; keeps every case an antichain |
| `_maybe_generalize` | **ported**, adapted | `sim4/moves.generalize` | The fitted ancestor distance replaces the pilot-tuned `ontology_smoothing_rate` |
| `_specialize` | **ported**, adapted | `sim4/moves.specialize` | The fitted descendant depth replaces the 0.5 grandchild coin; children are weighted by HPOA 2025-03-03 annotation counts instead of uniform |
| `_related_noise_term` | **ported**, adapted | `sim4/moves.related_noise_term` | The neighbourhood off-profile option. The sex and negative checks and the IC cap are dropped |
| `data_sources/hpo.py` `HpoOntology` | not ported | — | This repo's `ontology.Ontology` already reads `hp.json` with alt_id / replaced_by |
| Reporting model, per-term report probabilities, calibration, shrinkage of n/m toward a fitted mean, recount | dropped | — | Patient-fitted per term or per gene: the layers that memorised (per-gene rho 0.52 vs 0.16) |
| Negatives (`_sample_negatives`, negation pools), cardinal/obligate rules | dropped | — | No literature negation (ADR-0019 §4) |
| Noise counts and confounders with pilot constants, difficulty presets | dropped | — | Replaced by the fitted Beta-binomial off-profile share |
| Orphanet 2026 / literature profiles, genes-v2 weights, onset ages | dropped | — | Not E0's knowledge cut (rule 1) |
| Sex-specific term filter | dropped | — | Covariates are low priority, behind a flag; sex comes only from HPOA 2025-03-03 inheritance |

## 6. Decisions taken here (for the main session to review)
1. **Disease term sets come from E0's file.** HPOA's positive rows of each disease are a subset of them (0 HPOA
   terms of a linked disease are missing). Frequencies come from HPOA's pooled rows, falling back to E0's row.
2. **ORPHA groups and the no-disease pool are down-weighted to 0.2** when the gene has a specific disease. This is
   a knob, not fitted; `group_weight` is in every config hash.
3. **Rules 4 and 5 apply to the `e0` preset too** (findings only; no term with an ancestor). E0's pools included
   inheritance and clinical-course rows. R1 is therefore E0's recipe on sim4's knowledge, not a byte-level replica.
4. **`freq` (R2) uses the fitted `γ` and `f0`.** `frequency="proportional"` (`γ` = 1) is available for an R2 with no
   patient-fitted parameter.
5. **Ancestors and descendants move by walks of `d` steps** (the ported mechanics), so a term's shortest distance to
   the profile can be below `d`.
6. **Fit and validation use uncited publications only** (`--all-citations` adds cited ones). A patient's terms are
   mapped to HPO 2025-03-03 and restricted to findings; a term that is an ancestor of another is dropped (real
   patients have none).
7. **The fitting likelihood** uses the patient's own disease when one of its ids is an entity of the gene, else the
   gene's mixture. This uses the label only to pick the entity; nothing is stored per gene.
