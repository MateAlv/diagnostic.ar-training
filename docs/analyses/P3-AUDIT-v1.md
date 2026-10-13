# P3-AUDIT-v1: audit of GenPhenAI v3.0 and ft-v1.1, and options for a v4.0

- **Date:** 2026-10-13, opening Phase 3. Exploratory (EVAL_PROTOCOL §9): no claim, no sealed part, no ledger row.
- **Data:** `p2-v1` train + dev only (= `r1-v1` train + dev), 5,986 patients in 1,030 publication groups, through
  `splits.load_part`. Phase 1 and Track 4 rank files already on disk for `r1-v1` dev.
- **Code:** `scripts/analysis/p3_audit/` (run from the repo root with `PYTHONPATH=src`; intermediate files go to
  `$P3_AUDIT_DATA`, default `data/interim/p3-audit`). Outputs: `results/analyses/P3-AUDIT-v1/`.
- **Upstream reading:** GenPhenAI repos read only; the deleted PyTorch trainer was read from git history
  (`GraPhens@52c6a3e:training/training.py`, simulator at `GraPhens@7aef83d:src/simulation/phenotype_simulation/`).
- **Conventions:** "cited" = the patient's PMID is cited by a row of HPO annotations 2025-11-24 (as in P2-PROBES-v1);
  inV / OOV = the gene is in / out of E0's 5,229 outputs. CIs: paired bootstrap over publication groups, 2,000
  resamples, seed 0.

## 1. How E0 was built (upstream audit)

| Aspect | Finding | Evidence |
|---|---|---|
| Training data | Only simulated patients: 26,144,810 samples, 5,000 per gene, from HPO annotations **2025-03-03** (OMIM + Orphanet rows). No real patient in training. | `GraPhens/data/simulation/output/metadata.json`; hp.json / phenotype.hpoa at `7aef83d` |
| Terms per patient | `phenotype_counts.csv` is `np.random.poisson(5, 1000)` clipped at ≥ 1 (a demo file, reproduced bit for bit), range 1–12. | `SIM/demo.py:88-99` |
| Term choice | Uniform over the gene's annotated rows (no frequency), or a d-step ancestor (imprecision, about 27% of terms). **No off-profile noise**: no unrelated, sibling or more specific terms, no negation. | `SIM/simulator.py:60-90`, `SIM/selector.py:47-215` |
| Output genes | Every `gene_symbol` in `genes_to_phenotype.txt`, no minimum annotation filter (177 genes with ≤ 3 terms), plus a junk class `"-"` at index 0. | `genes.json`, `GraPhens/data/genes_to_phenotype.txt` |
| Node features | `gsarti/biobert-nli` on `"name: definition"`, chosen for cosine spread, not task performance. 19,534 terms embedded (2025-03); later terms get a zero vector. | `7aef83d:build_phenotype_vector_db.py:66-100` |
| Training | Cross-entropy, no class weights or smoothing; AdamW lr 5e-4, wd 5e-4; batch 128; ReduceLROnPlateau on val MRR; best at epoch 18. | `52c6a3e:training/training.py:276-280`; checkpoint |
| Model selection | val MRR 0.781 on 12,800 **simulated** patients from the same annotation pools (random 70/15/15 split of the simulations). No real-patient signal in selection. | `training.py:170-179, 629, 701-716` |
| Graph | Present terms + all ancestors, edges child → parent only; observed terms are about 18% of nodes and carry no "observed" mark. | `genphenia_v3.py:105-115` |

**Reading.** E0 learned "these annotated terms → this gene". It never saw a patient with terms outside the gene's
profile, and it was never selected on real patients.

## 2. Where E0 fails on real patients (p2-v1 train + dev)

| Slice | n | pubs | E0 MRR | top-1 | top-10 |
|---|---|---|---|---|---|
| cited & inV | 3,487 | 593 | 0.597 | 0.50 | 0.80 |
| uncited & inV | 1,715 | 330 | **0.330** [0.244, 0.404] | 0.25 | 0.49 |
| ≤ 0.1.25 & uncited & inV | 1,178 | 214 | 0.423 | 0.32 | 0.62 |
| post-0.1.25 & cited | 548 | 108 | 0.237 | 0.20 | 0.31 |
| post-0.1.25 & uncited & inV | 537 | 116 | **0.127** [0.076, 0.198] | 0.09 | 0.21 |
| OOV (cited or not) | 784 | 108 | 0 | 0 | 0 |

1. **A production patient is never "cited".** For a new patient whose gene E0 knows, the honest range is about 0.13
   (recent papers) to 0.42 (older papers E0's annotations do not cite), not 0.6.
2. **The "cited" mark overstates E0's exposure.** E0 trained on HPO 2025-03-03, not 2025-11-24. Post-0.1.25
   papers cited in 2025-11-24 (548 patients) score 0.237, so most were probably not in E0's annotations. A recount
   against 2025-03-03 is listed below.
3. **Vocabulary is really missing knowledge.** 99% of uncited OOV patients' genes have no annotation in HPO
   2025-11-24 either. In 2026-02-16, 71% are annotated, but for 77% of those the only rows cite the patient's own
   paper. HPO 2026-02-16 annotates 145 genes outside E0's outputs (`q7_coverage.txt`).
4. **The main driver is how much of the phenotype the gene's annotations explain.** Uncited & inV, by explained
   share: < 25% → MRR 0.041 (n = 289); ≥ 75% → 0.493 (n = 894), the same as cited patients at that share (0.504,
   own PMID masked). Re-weighting uncited patients to the cited share mix would give 0.464 instead of 0.330.
5. **Other weak slices (uncited & inV):** genes with 1–9 annotated terms (0.027), 1–2 present terms (0.142),
   single-disease genes (0.113), AR (0.209), low-IC neurodevelopmental phenotypes (e.g. ANKRD11, SATB2).
6. **Not a problem:** terms without an embedding are 0.20% of present terms (72 of 5,986 patients); no patient lists
   a present term that is an ancestor of another.

## 3. Phase 1 retraining, re-read by citation (r1-v1 dev, descriptive)

`q6_fronta.txt`. The Front A fine-tunes (EXP-A-001) and Track 4's relearned rows (EXP-P-007) lost mostly on cited
patients, i.e. memory of the annotated papers:

| Run | Δ all | Δ cited | Δ uncited | Δ uncited & inV |
|---|---|---|---|---|
| A-001 c1 (lr 1e-5, BN train), s1 | −0.091 | −0.125 [−0.162, −0.084] | **−0.010 [−0.036, +0.014]** | −0.015 [−0.054, +0.023] |
| A-001 c4 (lr 1e-5, BN frozen) | −0.128 | −0.177 | −0.012 [−0.045, +0.022] | −0.018 |
| A-001 c3 (lr 2e-4) | −0.205 | −0.280 | −0.027 [−0.057, −0.001] | −0.042 |
| EXP-P-007 ensemble | −0.232 | −0.315 | −0.036 [−0.066, −0.008] | −0.055 |

A-002f and A-003f have identical present-term ranks to E0 (frozen base, zero-init branches). **Retraining on the
Phase 1 simulators did not help unseen patients either, but its large headline losses were mostly lost
memorisation.** A model trained without the case-report annotations will lose on cited patients by construction.

## 4. Training-free scorers and fusion

Knowledge = HPO 2025-11-24 with every row citing the patient's own PMID dropped; all 5,052 annotated genes ranked
(`q13.json`, `q4.json`; all 15 fusion configurations in `configs_tried.txt`).
- Best scorer (gene Resnik best-match average): 0.200 overall, 0.229 uncited & inV vs E0 0.330 (Δ −0.101
  [−0.164, −0.018]). **No training-free scorer beats E0, even on uncited patients.**
- Fusion with disease-level Resnik, tuned on uncited train (z-blend λ = 0.05): dev uncited +0.0028
  [−0.0026, +0.0085], dev cited −0.0112. Fusion only helps where E0 has not memorised the paper, and every dev CI
  includes 0.
- For reference, ft-v1.1 on dev uncited: +0.0023 [+0.0009, +0.0036], 0 harmed.

## 5. Leakage risks for any v4.0

1. **Knowledge from the patient's own paper.** HPO rows cite PMIDs, but OMIM- and Orphanet-derived rows summarise
   case reports without citing each one, so PMID masking is incomplete. The strongest guard is a time split: knowledge
   frozen at date T, patients from papers first published (and biocurated) after T.
2. **Same publication in training and evaluation.** Group every split by publication; also deduplicate patients
   reported twice (same family in two papers).
3. **Selection on the evaluation set.** Nested, publication-grouped cross-validation for development; one sealed read
   for the claim.
4. **Pretrained language models** saw the literature, so an LLM component cannot be measured honestly on published
   cases; only on prospective ones.
5. **Gene priors** learned from patient counts act as per-gene proxies (the Track 2 lesson: one NF1 paper drove 60%
   of the gain); cap each publication's weight.

## 6. Options for v4.0

Ranked by expected gain on new patients (the production population), given §2–§4.

| # | Option | Targets | Evidence | Cost |
|---|---|---|---|---|
| 1 | **Retrain on realistic data:** a simulator with frequency-weighted sampling, real term-count distribution, off-profile terms drawn from the unexplained terms of real training patients, over-specification; mixed with real phenopacket-store training patients. Select on real, uncited, publication-grouped folds. | low explained share (the 0.04 vs 0.49 gap); 1,715 + 537 dev-like patients | §1 (no off-profile noise), §2.4, §3 | 1–2 weeks, GPU |
| 2 | **Knowledge-conditioned scoring (open vocabulary):** score a patient against a gene embedding built from the gene's current annotation profile (two-tower), with a learned residual for genes with training data. New genes and HPO updates enter without retraining. | OOV genes with annotations; knowledge freshness in production | §2.3; EXP-P-007 (closed rows cannot be relearned from annotations) | 1–2 weeks |
| 3 | **Input encoding:** an observed-term flag and IC on nodes, bidirectional typed edges, negated terms, sex and age as native inputs (subsuming ft-v1.1), drop `"-"`, re-embed the current HPO with synonyms. | all patients; small each | §1 | days; together with 1 |
| 4 | **Gene knowledge beyond HPO** (SHEPHERD-like): mouse phenotypes (MGI/IMPC via uPheno), GO, interaction neighbours of known disease genes, constraint (gnomAD LOEUF). | genes with no human annotation (37.9% of uncited top-10 misses) | §2.3, §5 of the error analysis | 2+ weeks; MRR gain likely small |
| 5 | **Confidence and abstention:** the explained share separates 0.04 from 0.49 MRR, so the doctor can be told when the list is unreliable. Temperature scaling on real folds. | usefulness, not MRR | §2.4 | days |
| 6 | **Learned fusion / learning to rank** with features (E0, Resnik, explained share, annotation count), group-aware. | uncited | §4: small, CI includes 0 | days; low priority |
| 7 | **LLM re-ranking of the top 50.** | — | not measurable without leakage (§5.4) | not recommended now |

**Not recommended again:** a training-free scorer alone or naive fusion (§4); relearning closed rows from masked
annotations (EXP-P-007).

## 7. Evaluation needed before any v4.0 claim

- **Primary population:** new patients, i.e. uncited publications with knowledge masked (and time-split where
  possible). v4.0 is expected to lose on cited patients, because E0 memorised their papers; that loss is reported, not
  optimised.
- **Development:** publication-grouped cross-validation over phenopacket-store, with knowledge masked per fold.
- **Sealed claim:** options are (a) a new held-out set carved now from post-E0 publications, disclosing any earlier
  read; (b) a prospective phenopacket-store release (0.1.28+, likely early 2027, about 150–220 patients per month);
  (c) both.
- **Recount:** recompute "cited" against HPO 2025-03-03, the release E0 actually trained on.
