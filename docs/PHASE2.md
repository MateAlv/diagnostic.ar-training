# Phase 2: real-patient restart (plan and tracker)

Decision record: [ADR-0017](decisions/0017-phase-2-real-patient-restart.md). Evidence that shaped it:
[P2-PROBES-v1](analyses/P2-PROBES-v1.md). Each run is logged in [BITACORA.md](BITACORA.md).

## Goal
Make GenPhenAI rank the causal gene higher by using what the doctor knows beyond the present symptoms: sex, age, onset
and absent symptoms. Show it on real patients that no decision was based on, with a pre-registered read. A small gain
is a success when it is real; safe candidates go first.

## Data
- **Development:** `p2-v1` train (fit) and dev (select). These are `r1-v1` train and dev: 5,986 patients.
- **Confirmation:** `p2-v1` test, about 3,587 patients. One pre-registered read per candidate, at most 3.
- **Final check:** `p2-v1` vault plus `p2-fresh-v1` vault, about 1,081 patients from publications E0 never saw. Read
  once, all candidates together.

## Tracks

### Track 1: `safe-v1`, knowledge-only constraints
- **Sex.** Genes whose every disease is limited to the other sex go below every other gene. This covers:
  - Y-chromosome genes outside the pseudo-autosomal regions;
  - Y-linked-only inheritance;
  - male-infertility diseases;
  - female-only reproductive diseases.

  Sex-reversal and DSD diseases block the rule.
- **Onset.** A gene goes below every other gene when its earliest onset is later than the patient's onset, or the
  patient's current age when onset is unknown.
  - The gene's earliest onset is the lowest onset class among its diseases, from HPO onset annotations and Orphanet.
  - The rule applies only when every OMIM disease of the gene has onset data ("strict").
  - Ages below 0 count as 0. Infantile onset counts as 0, a conservative choice.
- **Negation.** The probability is multiplied by 0.1 when the patient's excluded terms cover an obligate phenotype of
  every annotated disease of the gene. Obligate means HP:0040280, "100%", or n/n with n ≥ 5.
- **Curation, done by agents:** only the 141 sex-limited genes, 49 removed (BITACORA 2026-10-08). The agents used
  their own knowledge rather than quotes; see the EXP-P-001 deviations. Curation may only remove a gene or lower a
  bound. Mateo spot-checks 20 random genes. Onset genes are not curated; the ×0.01 factor bounds them.
- **Dev expectation (P2-PROBES-v1):** sex + onset about +0.0009 MRR with 0 harmed; negation about +0.0007.
- **Status (2026-10-07):** code and `safe-kb-v1a` (uncurated) built; curation queue of 756 genes ready
  (`results/P2/safe-kb-v1a/curation_queue.csv`). Dry run vs E0: dev +0.00196 [−0.00002, +0.00392], 3 harmed
  (0.16%); train −0.00004 [−0.00132, +0.00095], 28 harmed (0.68%). Per rule and subset in
  [BITACORA.md](BITACORA.md) (2026-10-07).
- **Open before pre-registration (decided on dev, logged):**
  - **Onset as a hard block can bury a correct gene.** On dev, one TRIM63 patient went from rank 1 to 5,028: the
    disease's juvenile-onset row cites the patient's own paper, which is masked, and the remaining row says middle
    age. Tomorrow's dev comparison: onset ×0.1 and ×0.01 instead of the hard block. The choice is made for a bounded
    worst case, not for the dev Δ.
  - **Negation on train harms 31 patients.** For 24 of them the obligate row cites the patient's own train paper,
    which the held-out mask keeps. Dev, where the patient's paper is masked: +0.00146 [+0.00014, +0.00309], 2 harmed.
  - **Curation scope.** GeneReviews can cite held-out papers, so evidence that cites a held-out PMID must not be
    used. Tomorrow's decision: curate only the 141 sex genes, or all 756 with that guard.

### Track 2: `ltr-v1`, a re-ranker learned on real patients
- **Model:** a LightGBM ranker over E0's top 100, fitted on `p2-v1` train and selected on dev, with at most 20
  configurations.
- **Gene-agnostic features**, with no gene identity and no per-gene patient statistics (P2-PROBES-v1 §3):
  - E0 log-probability and rank;
  - the Track 1 flags, plus graded distances between the patient's age and the gene's onset range;
  - X-linked inheritance × sex;
  - excluded-term evidence by annotated frequency band;
  - how well the present terms fit the gene, with a frequency-aware likelihood ratio over the masked HPO knowledge;
  - annotation richness.
- **Monotone constraints:** see the Phase 1 lessons below.
- **Status (2026-10-08):** `ltr-v1` selected on dev among 18 configurations (EXP-P-002): +0.05129 [+0.01257,
  +0.10568], harmed 4.67%; new inputs over the ablation +0.00136 [+0.00036, +0.00273]; post-E0 dev +0.00151
  [−0.00019, +0.00474]. 60% of the dev gain is one NF1 publication, and annotation richness can act as a gene
  proxy (BITACORA 2026-10-08).
- **Ablation:** the same model without sex, age, onset and excluded terms. The difference measures the anteproyecto's
  inputs.

### Track 3: `ft-v1`, retrain the network
- **Starting point:** fine-tune the PyTorch GinV3 (EXP-A-000 parity) with a zero-initialised branch for sex, age, onset
  and excluded terms (ADR-0009), so step 0 is exactly E0.
- **Training data:** `p2-v1` train patients, plus replayed upstream-style simulated patients covering all 5,229 genes
  so the model keeps its coverage.
- **Discipline:**
  - early stopping on a held-out slice of `p2-v1` train;
  - selection on dev;
  - at most 8 runs × 3 seeds, all logged.
- **Status (2026-10-08):** EXP-P-003 dev grid done (8 configurations × 3 seeds, all logged). Selected `c1-lin-all`
  (linear residual, 8 θ): ensemble `ft-v1-c1-lin-all-ens` dev +0.00313 [+0.00159, +0.00485], 2 harmed (0.11%),
  top-10 +4/−0; post-E0 dev +0.00009; train +0.00023. Without sex, age and onset: +0.00146. The classifier
  configurations (not selectable) reach +0.025 and +0.087 through learned per-gene weights. Details in
  [EXP-P-003](experiments/EXP-P-003.md) and BITACORA 2026-10-08.
- **ft-v1.1 (2026-10-08, EXP-P-003 addendum):** `xlr_female` now needs explicit HP:0001419 and `xld_male` is gone;
  the same grid and rule select `c1-lin-all` again. `ft-v1.1-c1-lin-all-ens`: dev +0.00289 [+0.00136, +0.00461],
  2 harmed (0.11%), top-10 +4/−0; post-E0 dev +0.00007; train +0.00034 with 13 harmed (`ft-v1`: 21).

### Track 4: vocabulary update (future work)
48% of post-E0 patients have a gene outside E0's 5,229 genes. Covering them is probably the largest gain on new
publications, but it is not about the new inputs (ADR-0006, ADR-0017).

## Schedule
| Date | Step | Status |
|---|---|---|
| 10-07 | ADR-0017, P2-PROBES-v1, sources pinned | done |
| 10-07 | `p2-v1` split code and freeze (#122); `safe-v1` code, `safe-kb-v1a`, dev dry run (#123) | done |
| 10-08 | Track 1 onset form chosen on dev: ×0.01 (BITACORA 2026-10-08) | done |
| 10-08 | Sex-gene curation (141 → 92), `safe-kb-v1`, EXP-P-001 pre-registered | done |
| 10-08 | EXP-P-001 read: safe-v1 Δ +0.00029 [−0.00053, +0.00097], harmed 0.25%; gate not passed; sex and onset alone: 0 harmed | done |
| 10-08 | Track 3 fixed (ft-v1.1); EXP-P-005 read: Δ +0.00138 [+0.00070, +0.00232], harmed 0.17%, **gate passed** | done |
| 10-08 | EXP-P-006 (final check) pre-registered; ft-v1.1 feature attribution | done |
| 10-08 | `p2-fresh-v1` frozen now (ADR-0017 Amendment 2): 340 patients; EXP-P-006 reviewed (GO) | done |
| 10-08 | EXP-P-006 final check: `safe-v1[sex+onset]` +0.00029 [+0.00001, +0.00075] (**H1 passed**); `ft-v1.1` +0.00054 [+0.00005, +0.00129] (**H2 holds**); 3 harmed of 1,072 | done |
| next | Summary and evidence docs for the informe; production decision (Mateo) | next |
| 10-08 | Track 3 `ft-v1` dev grid (EXP-P-003), candidate `ft-v1-c1-lin-all-ens` | done |
| 10-08 | `dxt final-check` (both vaults loaded once, every candidate on the same cases); `safe-v1[sex+onset]` dev +0.00100 [+0.00030, +0.00179], train +0.00036 [+0.00007, +0.00080], 0 harmed | done |
| 10-08 | Track 3 X-linked fix, grid rerun (EXP-P-003 addendum), candidate `ft-v1.1-c1-lin-all-ens` | done |
| 10-09 to 10-17 | Tracks 2 and 3 on dev | planned |
| 10-18 to 10-19 | Pre-register the best learned candidate; confirmation read | planned |
| 10-21 to 10-27 | Release (`diagnostic.ar-model`), docs, informe evidence | planned |

Informe draft: 10-15. Informe delivery: 11-01.

## Gates (fixed here, repeated in each pre-registration)
- **Confirmation:** Δ MRR CI lower bound > 0, at level 1 − 0.05/3 (Bonferroni across Phase 2's 3 confirmation reads; conservative relative to Holm), and harmed ≤ 5%
  (Phase 1's cap for re-rankers).
- **Final check:** reported for every candidate, with no gate. It is the clean, post-E0 estimate.
- **Production:**
  - `safe-v1` may go to production when it passes confirmation with harmed ≤ 0.5% and Mateo says go.
  - Learned candidates also need a final-check Δ CI lower bound ≥ 0.

## Lessons from Phase 1 that bind Tracks 2 and 3
- **R1's excluded terms favour the true gene.** Authors report as absent the features typical of the syndrome they
  suspect. A model learned on R1 therefore rewards genes that annotate the patient's absent findings: EXP-B-002 reached
  dev +0.056, almost all of it from negation, and that gain cannot be deployed (EXP-B-002 Verdict and Addendum 1). In
  the app, absent findings come from questions about the candidates' features.
- **Phase 2 learned models only let absent findings lower a gene's score.** Every negation-conflict feature has a
  monotone non-increasing constraint, so the model cannot learn the reporting pattern. Sex, age and onset
  incompatibility features are constrained the same way.
- **Sex, age and onset added at most +0.002 each as soft features** (EXP-B-002), consistent with P2-PROBES-v1. Their
  gains come from knowledge-complete constraints, not from learned per-gene statistics.
