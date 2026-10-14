# Phase 3: toward GenPhenAI v4.0

Decision record: [ADR-0019](decisions/0019-phase-3-v4-retraining.md). Evidence: [P3-AUDIT-v1](analyses/P3-AUDIT-v1.md).
Data: `p3-v1` (train 5,986 free; vault 4,659 sealed, one read on Mateo's go).

## 1. Status
- **Done (2026-10-13):**
  - audit;
  - `p3-v1` frozen;
  - HPO 2025-03-03 registered.
- **Simulator audit: rewrite, do not reuse.**
  - Every layer of `rare-disease-simulator` fitted on patients memorised: per-gene rho 0.52 on train vs 0.16 on dev
    (candidate 6); the upstream simulator gave 0.24 vs 0.23.
  - It also turns literature negations into negatives and uses newer knowledge.
  - The new module is `sim4/`. From `rare-disease-simulator@cfc20da` it ports frequency parsing,
    `budget_scaled_probabilities` and the related-term moves (generalise, specialise, related noise), now driven by
    the fitted global parameters (SIM4-v1).
- **Done:** `sim4/` (PR #149), harness `v4/` (PR #150), ladder batch 1 (§2c, no rung improved).
- **Next:** batch 2 (§2d), starting with the harness fix and the reproduction of E0.

## 1b. Folds of `p3-v1` train (`sim4/folds.py`)
Each publication group gets fold = sha256(`diagnostic.ar-training/p3-v1-cv:` + group) mod 5.

| Folds | Role |
|---|---|
| 0, 1, 2 | **FIT:** simulator statistics, real patients mixed into training |
| 3 | **SELECT:** early stopping, ladder comparisons, grid selection |
| 4 | **CONFIRM:** untouched internal check of the finalists, read only by the main session (`DXT_P3_CONFIRM=1`, logged in `results/P3/CONFIRM_LEDGER.md`), before the vault pre-registration |

- **Why not k-fold retraining:** a training run takes hours, and the simulator's patient-fitted part is global
  (about 15 parameters plus one pooled vocabulary), so one fit/select/confirm split is affordable.
- **Selection bias:** reusing SELECT across many configurations biases its estimate upward. CONFIRM and then the
  vault measure without that bias.

## 1c. Simulator rules (`sim4`, from the simulator audit)
- **Knowledge:** E0's own: HPOA 2025-03-03 and E0's `genes_to_phenotype` (GraPhens@7aef83d).
- **Literature negations dropped, a declared deviation from E0's knowledge:**
  - E0's `genes_to_phenotype` has about 788 NOT-only rows and about 1,981 rows at frequency 0/n;
  - E0 trained on them as positives;
  - `sim4` drops them, together with NOT rows, 0/n and 0% rows and HP:0040285.
- **Patient-fitted parameters are global and low-dimensional:**
  - about 15 parameters;
  - one pooled, gene-agnostic vocabulary of off-profile terms;
  - no per-gene or per-term parameter fitted on patients.
- **Fitting set:** only FIT-fold patients whose publication E0's knowledge does not cite, weighted per publication.
- **Findings emitted:** phenotypic-abnormality terms only; never a term together with one of its ancestors.

## 2. Ablation ladder (cross-validation on `p3-v1` train, publication-grouped)

Every rung keeps the previous ones and changes one thing, so each effect is measured on its own. The primary metric is
MRR on uncited patients (ADR-0019 §6). Every rung also reports cited, in- and out-of-vocabulary, and harmed counts.

| Rung | Change | Question it answers |
|---|---|---|
| R0 | E0 as released | baseline in each fold |
| R1 | E0's architecture retrained from scratch on E0's simulator recipe, re-implemented | does our training pipeline reproduce E0 (sanity)? |
| R2 | per-disease, frequency-weighted term sampling | does sampling by frequency help? |
| R3 | term count, imprecision and over-specification fitted on training folds | does realistic reporting help? |
| R4 | off-profile terms from training folds' unexplained terms | does robustness to unexplained terms help (the 0.04 vs 0.49 gap)? |
| R5 | real training patients mixed in (ratio tuned) | does real data add on top of simulation? |
| R6 | input encoding: observed flag, IC, both edge directions, no `"-"` | does the encoding help? also tried on R2 alone, to separate it from the simulator |
| R7 | sex and age/onset as inputs (simulated from HPOA 2025-03-03 inheritance and onset rows) | do covariates help natively? |
| R8 | hyperparameters and architecture grid on the best rung (hidden size, layers, pooling, dropout, lr, warm start from E0 vs scratch) | how much is left on the table? |

- **Budget:** the GPU (RTX 4070 Ti) may run grid searches of several hours.
- **Nested selection:** configurations are selected on inner folds, and the outer-fold estimate is reported. Every
  configuration and seed is logged.

## 2b. Reading rule for the ladder (fixed before any rung is trained, 2026-10-13)
- SELECT's uncited stratum is small: 93 publication groups, E0 MRR 0.403. On FIT folds, E0's uncited MRR is 0.178.
- Every rung is therefore read on two sets, each against E0:
  - **SELECT uncited:** the primary set; Δ MRR with its CI;
  - **FIT uncited:** the train check. It is admissible for rungs that do not mix in real patients, because the
    simulator's patient-fitted part is global (SIM4-v1).
- **A rung counts as an improvement** when Δ is positive on both sets and SELECT's CI lower bound is above −0.01.
  Otherwise it is "not shown".
- **Reported for every rung:** cited, out-of-vocabulary and harmed counts.
- **First batch (`configs/p3/L1-grid.yaml`):** R1–R4 from scratch and R4 warm-started from E0 (R4w), 90 min each.

## 2c. Batch 1 results (2026-10-13; exploratory, train folds only)
Run rows: `results/P3/runs/`, `results/P3/GRID_LOG.jsonl`; histories and log in `data/interim/v4/`. Seed 0 only.

| Rung | SELECT uncited Δ vs E0, best eval [CI] | SELECT uncited MRR at plateau (E0 0.403) | FIT uncited Δ [CI] | SELECT cited Δ |
|---|---|---|---|---|
| R1 (e0 recipe) | +0.002 [−0.053, +0.026] | 0.372 | −0.030 [−0.071, +0.002] | −0.093 |
| R2 (`freq`) | −0.117 [−0.185, +0.003] | 0.274 | +0.006 [−0.029, +0.038] | −0.077 |
| R3 (`real`) | −0.056 [−0.081, −0.001] | 0.316 | +0.005 [−0.029, +0.039] | −0.085 |
| R4 (`real_noise`) | −0.031 [−0.057, −0.014] | 0.326 | +0.036 [−0.008, +0.084] | −0.045 |
| R4w (E0 init, lr 1e-4) | stopped at 55 of 90 min | 0.351; its best eval is step 0 (E0 itself) | — | — |

- **Verdict by the §2b rule:** no rung is an improvement.
- **The batch is not a clean test of the simulator, for three reasons found afterwards:**
  1. **The learning rate collapsed.** The `plateau` schedule halves the rate after 3 evaluations without a new best
     SELECT MRR, and it has no floor (`min_lr_ratio` applies only to `cosine`). SELECT has 93 uncited groups, so
     its MRR stalls early. Every run fell from 5e-4 to below 2.5e-5 by step about 150k (10–35 min, about 19M
     samples) and to about 4e-6 by step 185k. Each run therefore trained for less than one E0 epoch at a useful
     rate, and the remaining 55–80 min did nothing. E0 lowered its rate once per epoch on simulated validation,
     over 18 epochs (about 330M samples).
  2. **R1 does not reproduce E0** (plateau 0.372 vs 0.403 on SELECT uncited, −0.09 on cited). Every later rung
     carries that deficit, so comparing a rung with E0 mixes the deficit with the rung's own effect. Candidate
     causes, to separate in §2d: the schedule (1); the dropped literature negations (about 2,800 rows that E0
     learned as positives); E0's fixed 5,000-per-gene set vs our fresh stream.
  3. **R2 changed two things:** `freq` sets `recipe: disease` (pick one disease, then its findings) and
     `frequency: fitted` together. Its −0.117 cannot be attributed to frequency weighting alone.
- **The best-eval column is biased upward:** it is the best of 50–260 noisy evaluations on SELECT itself. The plateau
  value (median of evaluations from step 200k) is the fairer reading.
- **SELECT and FIT disagree:** relative to R1, R2–R4 lose on SELECT but gain on FIT (R4 +0.066). FIT is where the
  simulator's global parameters were fitted, which may favour R3/R4 there (not R2, which uses no fitted
  parameters). The per-group drivers of the disagreement are not yet analysed (§2d, step A3).
- **R4w:** warm-starting E0 and training on `real_noise` at lr 1e-4 lowers SELECT uncited from 0.403 to about 0.35
  within 60k steps. Continued simulated training erodes E0.

## 2d. Plan for batch 2 (written 2026-10-13, before any batch-2 run)
Order matters: each step is read before the next one is launched. GPU estimates are on the RTX 4070 Ti.

**A. Fix the harness and reproduce E0 (gate before any rung is re-read).**
- **A1. Schedule fix (code, no GPU):**
  - The plateau scale gets a floor at `min_lr_ratio`.
  - The ladder default becomes `cosine` over a fixed sample budget, so the rate does not depend on SELECT noise.
  - SELECT is still evaluated every 10k steps, for monitoring and checkpoint choice only.
  - Every run reports two readings: its best checkpoint, and its *final* checkpoint (not chosen on SELECT).
  - A test pins the floor and the cosine shape.
- **A2. R1 reproduction runs:**

  | Run | Change from R1 | Budget | Question |
  |---|---|---|---|
  | R1c-90 | cosine, 90 min (about 165M samples) | 1.5 h | does the schedule alone close the gap? |
  | R1c-180 | cosine, 180 min (about 330M, E0's total exposure) | 3 h | does it need E0's exposure? |
  | R1c-90 s1 | seed 1 | 1.5 h | seed noise of the reading |
  | R1neg (diagnostic only, **needs Mateo's OK**) | knowledge with E0's negation rows kept as positives | 1.5 h | how much of the gap is the negation deviation? Never a v4 candidate. |

  - **Gate A:** R1's final checkpoint is within 0.02 of E0 on SELECT uncited, FIT uncited and SELECT cited.
  - If the gap stays, the next diagnostic is E0's fixed 5,000-per-gene set (a replay of a fixed sample) before any
    rung is re-read. The ladder does not proceed against a control that is far below E0.
- **A3. SELECT vs FIT diagnosis (CPU, from the batch 1 rank files):** per-group Δ for R2 and R4 vs R1 on both
  sets; whether a few SELECT groups drive the loss; Δ by explained share and by annotation count.

**B. Re-run the simulator rungs on the fixed harness** (budget from A2, 2 seeds each, about 12 h).
- R2 is split so each change is measured on its own:
  - **R2a** `recipe: disease`, `frequency: uniform`;
  - **R2b** R2a + `frequency: fitted` (the γ, f0 defaults from SIM4-v1).
- Then R3 (`real`) and R4 (`real_noise`).
- **Reading:** each rung against the previous rung and against R1 (its matched control); the §2b rule against E0 is
  still reported. The vault gate (ADR-0019) is unchanged and is always against E0.
- **The reading uses the final checkpoint and the seed mean,** plus the best checkpoint for reference.

**C. Real patients (R5).**
- **R5:** the best simulator rung from B (or R1 if none helped) with real FIT-fold patients mixed in at a ratio of
  0.05, 0.1, 0.25 or 0.5. Each publication's weight is capped (the Track 2 lesson). Read on SELECT only: FIT
  patients are in training, so the FIT train check no longer applies.
- **R5w:** E0 warm start, low lr (1e-5 and 3e-5), the same mix. R4w showed that simulated data alone erodes E0;
  this asks whether real patients can add to E0 without that.
- About 8 h.

**D. Encoding and covariates (R6, R7)** on the best of B/C, and R6 also on R1, to separate the encoding from the
simulator. About 6 h.

**E. Grid (R8)** on the best rung: hidden size, layers, pooling, dropout, lr, batch size, scratch vs E0 start. About
5–8 h, with the configurations and seeds logged.

**F. Claim.** CONFIRM check of at most 3 finalists (main session), pre-registration, independent review, then
Mateo's go for the one vault read.

## 2e. Re-centred plan (2026-10-14, after [P3-BATCH1-DIAG](analyses/P3-BATCH1-DIAG.md); replaces §2d B–E)
- **Metric:** capped MRR, at most 10 patients per publication (ADR-0019 amendment), for selection, ladder readings
  and the gate.
- **Mateo:** re-centre v4 on real patients. The simulator rungs measured noise when publications were weighted equally,
  and a simulator of the same annotations adds no knowledge.
- **Steps:**

  | Step | What | Reading |
  |---|---|---|
  | A | R1c (cosine schedule, running) and a fixed-schedule R4, 2 seeds | does our pipeline reach E0? keep R4 only if it beats R1c on capped FIT and SELECT |
  | K1 | **Real-patient memory**: kNN over training patients from other publications, fused with E0 | capped Δ on SELECT, λ tuned on FIT (leave own group out); helped and harmed counts |
  | K2 | Harm control: fusion weight scaled by memory confidence (best similarity, number of same-gene publications), and a cap on how far a gene without memory can fall | harmed count at equal gain |
  | K3 | Similarity learned on FIT pairs (same gene, other publication) vs IC cosine | capped Δ beyond K1 |
  | R5 | GNN trained with real FIT patients mixed in (from E0 or R1c), ratio grid, per-publication cap | capped Δ beyond K1; does a parametric model beat the memory? |
  | F | finalists on CONFIRM, pre-registration, independent review, Mateo's go | the single vault read |

- **Always reported, separately:** E0 + cohort gene prior alone (phenotype-blind) as a control, so the phenotype
  part of any gain is visible.
- **Production memory** = every curated patient available at release (the claim uses `p3-v1` train only).

**Decision (Mateo, 2026-10-14): no cohort gene prior in the claimed v4.**
- The real-patient module may use only phenotype evidence. A gene must not gain from how many training patients or
  publications it has.
- Enforced by a **popularity control:** the module is re-run with each query's phenotype swapped for another query's
  (true gene kept). Its gain there must be about 0. Any remaining gain is popularity, and the design is changed.
- E0 + cohort prior is reported as a control, never as a candidate. An external clinical prior is out of scope.

**Decisions for Mateo before batch 2 (superseded by §2e for B–E):**
1. R1neg: allow a diagnostic run with E0's negation rows kept, only to measure the gap, never as a candidate?
2. The ladder's control changes from E0 to R1 for rung-to-rung readings; the vault gate stays against E0.

## 3. Rules specific to Phase 3
- **Knowledge:** HPOA 2025-03-03 and E0's gene list only, for the evaluated model.
- **No literature negations anywhere:** no NOT rows, no 0/n rows, no excluded terms in training or evaluation
  inputs.
- **Fitting:** simulator statistics come from training folds only.
- **No vault access:** no agent and no script touches the vault. Only the main session reads it, after
  pre-registration, independent review and Mateo's go.

## 4. Backlog: other improvements found by the audit (not in the current scope)

| # | Idea | Why | Notes |
|---|---|---|---|
| B1 | **Knowledge-conditioned / open-vocabulary scoring** (two-tower: patient vs gene profile) | new genes and HPO updates without retraining; 145 genes annotated in HPO 2026-02 are outside E0 | Track 4 showed closed rows cannot be relearned from annotations |
| B2 | **Gene knowledge beyond HPO** (MGI/IMPC mouse phenotypes via uPheno, GO, interaction neighbours, gnomAD constraint) | 37.9% of uncited top-10 misses are genes with no human annotation | SHEPHERD-like; MRR gain probably small |
| B3 | **Confidence / abstention for the doctor** | the explained share separates MRR 0.04 from 0.49; tell the doctor when the list is unreliable | temperature scaling on real folds; cheap |
| B4 | **Learned fusion / learning to rank** (E0, Resnik, explained share, annotation count) | uncited fusion +0.0028 [−0.0026, +0.0085] untuned | group-aware; cap per-publication weight (Track 2 lesson) |
| B5 | **Absent symptoms on top of v4.0** (refit ft-v1.1's branch, interview-style negatives only) | production input is interview "no" answers, not literature negatives | measured separately; never literature negatives |
| B6 | **Production knowledge freshness** (rebuild v4.0 on HPO 2026-09-01) | genes and terms added since 2025-03 | only measurable on a prospective set |
| B7 | **Prospective check** on phenopacket-store 0.1.28+ (probably 2027) with knowledge frozen before it | the cleanest test of new patients | ~150–220 patients/month |
| B8 | **Disease-level output** (OMIM/ORPHA) and inheritance mode | doctors read diseases, not only genes | product |
| B9 | **Spanish text → HPO extraction quality** | likely a large real-world error source; unmeasured | needs consented real sessions |
| B10 | **LLM re-ranking of the top 50** | literature reports gains | not measurable without leakage on published cases; only prospective |
| B11 | **Recount "cited" against HPO 2025-03-03** in Phase 2 reports | E0 trained on 2025-03-03, not 2025-11-24 | done for `p3-v1`; Phase 2 documents keep their own definition |
