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
- **Curation, done by agents.** Each sex-limited gene (141) and each onset-bounded gene with an earliest onset of 1 year
  or more (596) is checked against the pinned GeneReviews and MedlinePlus snapshots. Curation may only remove a gene
  from a rule or lower its onset bound. Mateo spot-checks 20 random genes.
- **Dev expectation (P2-PROBES-v1):** sex + onset about +0.0009 MRR with 0 harmed; negation about +0.0007.

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

### Track 4: vocabulary update (future work)
48% of post-E0 patients have a gene outside E0's 5,229 genes. Covering them is probably the largest gain on new
publications, but it is not about the new inputs (ADR-0006, ADR-0017).

## Schedule
| Date | Step | Status |
|---|---|---|
| 10-07 | ADR-0017, P2-PROBES-v1, sources pinned | done |
| 10-07 to 10-09 | `p2-v1` split code and freeze; `safe-v1` code; gene curation | in progress |
| 10-10 | `safe-v1` on dev; pre-register EXP-P-001; independent review | planned |
| 10-11 | EXP-P-001 confirmation read, after Mateo's go | planned |
| 10-09 to 10-17 | Tracks 2 and 3 on dev | planned |
| 10-18 to 10-19 | Pre-register the best learned candidate; confirmation read | planned |
| 10-20 | Freeze `p2-fresh-v1`; final check (one read) | planned |
| 10-21 to 10-27 | Release (`diagnostic.ar-model`), docs, informe evidence | planned |

Informe draft: 10-15. Informe delivery: 11-01.

## Gates (fixed here, repeated in each pre-registration)
- **Confirmation:** Δ MRR CI lower bound > 0, with Holm correction across Phase 2 confirmation reads, and harmed ≤ 5%
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
