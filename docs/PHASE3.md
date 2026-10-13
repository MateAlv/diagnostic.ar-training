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
  - The new module is `sim4/`. From `rare-disease-simulator` it reuses only the budget-scaled sampling idea and
    frequency parsing.
- **Running:** `sim4/` (branch `p3/sim4`) and the training/evaluation harness `v4/` (branch `p3/v4-harness`).

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
