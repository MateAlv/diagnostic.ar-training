# Current state (handoff snapshot)

**Snapshot: 2026-10-07 (night), Phase 2 day 1 checkpoint.** Overwritten at each checkpoint; history lives in
[BITACORA.md](BITACORA.md). Entry points: [INDEX.md](INDEX.md), [PHASE2.md](PHASE2.md), [PLAN.md](PLAN.md),
[EVAL_PROTOCOL.md](EVAL_PROTOCOL.md), [evidence/EVIDENCE_INDEX.md](evidence/EVIDENCE_INDEX.md).

## Phase 3 (opened 2026-10-13): toward a v4.0 ([ADR-0019](decisions/0019-phase-3-v4-retraining.md), [PHASE3.md](PHASE3.md))
- **2026-10-15: the v4 candidate passed the vault read ([EXP-V-002](experiments/EXP-V-002.md)).**
  - The candidate is the network `R5x-f4` (R1c fine-tuned with 4,369 real patients) plus the sex/age/onset add-on.
  - On 2,678 vault patients from publications E0's knowledge never cited: capped MRR 0.196 → 0.261, +0.0649
    [+0.0473, +0.0833]; the network alone +0.0639.
  - Moving every term to its parent keeps 35% of the gain.
  - Production needs Mateo's decision and an integration into `diagnostic.ar-model`.
  - The gain comes from genes with real training patients (+0.137 vs +0.001; EXP-V-002 Addendum 1). The earlier
    re-rankers add nothing on top, and `rerank-v1.0.0` lowers it (P3-ADDON).
- **Phase 4 done ([ADR-0020](decisions/0020-v4-validated-and-next.md), accepted 2026-10-15):**
  - **Final model F3** = the network + the add-on + a hard sex rule (`sex-kb-v3`); age is dropped as a hard rule
    (P4-AGE).
  - **Second CONFIRM read** (P4-CONFIRM): F3 vs E0 +0.0717 [+0.0332, +0.1200]; sex rule 31 helped, 0 harmed; add-on
    101 helped, 5 harmed.
  - **Full record for the informe:** [evidence/RETRAINING-RECORD.md](evidence/RETRAINING-RECORD.md).
- **Next:** production of F3 through `diagnostic.ar-model`, staging first, then Mateo's go:
  - ONNX export of the network with E0's input contract, checked for score parity;
  - the add-on and sex rule as numpy code;
  - the API's sex, age and onset fields.
- Audit: [P3-AUDIT-v1](analyses/P3-AUDIT-v1.md), on R1 train + dev only. E0 was trained only on simulated patients
  (HPO 2025-03-03, no off-profile noise) and selected on simulated data; on new patients with a known gene its MRR is
  about 0.13 to 0.42, not 0.6.
- Scope (Mateo): a pristine frequency-weighted simulator fitted on real training patients, plus input encoding, as an
  ablation ladder; no literature negation anywhere; knowledge = E0's (HPOA 2025-03-03).
- `p3-v1` frozen (`3e928b3d…`): train 5,986 (free; cross-validation); vault 4,659 (sealed; one read, only on Mateo's
  go). Agents never open the vault.
- Gate (Mateo): improvement on data v3.0 never saw; Δ MRR CI lower bound > 0 on the 2,678 vault patients uncited by
  E0's knowledge. Grid search before the single read.
- Ladder batch 1 (2026-10-13): no rung improved; the learning-rate schedule collapsed and R1 did not reproduce E0.
  Next: batch 2 plan in [PHASE3.md](PHASE3.md) §2d (harness fix and R1 reproduction first; two decisions for Mateo).
- 2026-10-14: [P3-BATCH1-DIAG](analyses/P3-BATCH1-DIAG.md). The gate uses capped MRR (10 patients per publication). v4 is
  re-centred on real patients (PHASE3 §2e). No cohort gene prior (Mateo).
- 2026-10-14: R1c (cosine schedule) reproduces E0 on capped MRR (Gate A). K1, a phenotype-only real-patient memory
  fused with E0, gives uncited capped Δ +0.076 [+0.041, +0.111] out of fold over folds 0–3, with the popularity
  control at −0.048. Next: K3, R5 (P3-BATCH1-DIAG §7–§8).

## Production-ready model (2026-10-08; [ADR-0018](decisions/0018-ft-v11-production-ready.md))
- `ft-v1.1-c1-lin-all-ens` (git tag `ft-v1.1-production-ready`):
  - EXP-P-005: +0.00138 [+0.00070, +0.00232] on 3,587 sealed patients;
  - EXP-P-006: +0.00054 [+0.00005, +0.00129] on 1,072 post-E0 patients.
- Integration into `diagnostic.ar-model` comes later: an unmasked production knowledge build, API inputs and staging
  first.

## Phase 2: real-patient restart (done; [ADR-0017](decisions/0017-phase-2-real-patient-restart.md))
- **Goal:** a pre-registered gain on real patients from sex, age, onset and absent symptoms over GenPhenAI v3.0 (E0).
  Safe candidates go first.
- **Data:** development on `p2-v1` train and dev (`r1-v1` train and dev, 5,986 patients); confirmation on `p2-v1` test
  (3,587); a final check on about 1,072 patients from publications E0 never saw (`p2-v1` vault, 732, plus
  `p2-fresh-v1`, 340, frozen on 2026-10-08 by ADR-0017 Amendment 2).
- **Done (2026-10-07):**
  - ADR-0017 and the plan;
  - two sources pinned (phenopacket-store 0.1.25, HPO 2025-11-24);
  - [P2-PROBES-v1](analyses/P2-PROBES-v1.md): sex + strict age/onset Δ MRR +0.00088 [+0.00039, +0.00151] with 0 harmed
    on R1 train + dev; E0 MRR 0.612 on cited vs 0.066 on post-E0 publications.
  - `p2-v1` frozen (`b1ccdada…`): test 3,587 patients in 567 groups; vault 732 in 135 post-E0 groups. The
    `p2-fresh-v1` builder is ready; a dry run on `main@85ffd78` keeps 340 patients.
  - `safe-v1` (Track 1) code and `safe-kb-v1a` (#123). Dry run vs E0: dev +0.00196 [−0.00002, +0.00392], 3 harmed
    (0.16%); train −0.00004 [−0.00132, +0.00095], 28 harmed. Details in BITACORA (2026-10-07).
- **Next (2026-10-08), in order:**
  1. Track 1 onset form on dev: hard block vs ×0.1 vs ×0.01 (PHASE2.md, "Open before pre-registration").
  2. Curation scope (141 sex genes, or all 756 with a held-out-PMID guard); agents; `safe-kb-v1`.
  3. EXP-P-001 pre-registration, independent review, Mateo's go, then the confirmation read on `p2-v1` test.
  4. Launch Tracks 2 (`ltr-v1`) and 3 (`ft-v1`): agents reuse `safe/`; absent findings may only lower a score.
  5. `p2-fresh-v1` frozen on 2026-10-08 (Amendment 2); next is the final check (EXP-P-006).
- **Phase 2 sealed budget:**
  - `p2-v1` test: 2 of 3 confirmation reads used.
    - EXP-P-001, safe-v1: Δ +0.00029 [−0.00053, +0.00097], gate not passed. The onset rule alone gave +0.00016
      [+0.00007, +0.00032] with 0 harmed (descriptive).
    - **EXP-P-005, ft-v1.1** (the network with the new inputs, trained on real patients): **Δ +0.00138 [+0.00070,
      +0.00232], harmed 0.17%, gate passed.**
  - Final check, EXP-P-006 (1,072 post-E0 patients, read once): `safe-v1[sex+onset]` +0.00029 [+0.00001, +0.00075],
    H1 passed; `ft-v1.1` +0.00054 [+0.00005, +0.00129], H2 holds; 3 harmed (0.28%).

## Phase 1 summary (closed 2026-10-05; [ADR-0016](decisions/0016-final-deployment-and-close-out.md))

### What was built
- **Question agent with Q2b selection** (`diagnosticar-question-agent`, `feat/agente-v2`): enriches each case with
  follow-up questions and adds the confirmed and ruled-out findings of each round, which gives the model and the
  doctor's summary a more precise phenotype. Per case on the sealed simulated test (S3-v2-test, n = 9,565, Q2b
  λ = 0.6, noise 0): 1.04 confirmed ("yes") and 7.87 ruled-out ("no") findings added, over 8.90 questions
  (`results/EXP-B-004/sealed/s3-v2-test__Q2b-lam0.6__cfg-8ecd5b320f33__noise0.report.json`; the answers are the
  simulator's). Goes into production.
- **"No"-answer re-ranker `rerank-v1.0.0`**: reorders the GNN's genes using the ruled-out findings. Stays in
  staging only (see Data limitations).
- **Onset age** gives the doctor a more precise clinical summary: it is shown in the final output (results and the
  saved consultation; a web PR is in progress), after the age selector in Precisar (PR #87).
- **A literature-enriched patient simulator** (`rare-disease-simulator` 0.5.4), built with strong curation: 97
  literature shards (build v2), onset and presentation ages from the literature, PMID masking, pinned sources and
  manifests. The AI extraction was checked: Codex cross-check 96.1% agreement, 715 of 744 rows
  ([LIT-CROSSCHECK-v1](analyses/LIT-CROSSCHECK-v1.md)); audit row error 2.0% [1.25, 3.17] and recall 93.3%
  ([LIT-AUDIT-v1](analyses/LIT-AUDIT-v1.md)).
- **An evaluation infrastructure**, which the anteproyecto itself names as an open problem in the field:
  frozen splits `r1-v1` (train/dev/test/vault) split by publication, with held-out PMID masking; pre-registration;
  a code-enforced sealed-read guard (`DXT_SEALED_READ`) and a ledger; S3 simulated-interview benchmarks (v1, v2,
  v3b) with a knowledge split (half B held out) and source separation for age and sex; every claim reported as a
  paired-bootstrap Δ vs E0 with a CI and the harmed share.
- **A PyTorch reimplementation of the GNN** (`gnn/`) with parity tests against production.

### What was measured
| Result | Δ MRR [95% CI] | Split, n | Where |
|---|---|---|---|
| Q2b over the baseline questioner Q0 | **+0.0049 [+0.0027, +0.0069]** | S3-v2-test (sealed, simulated), 9,565 | [EXP-Q-001](experiments/EXP-Q-001.md) |
| Q2b over Q1, the previous production selector | +0.0017 [−0.0006, +0.0043] | S3-v2-test, 9,565 | EXP-Q-001 |
| "No"-answer re-ranker vs E0+answers | **+0.0044 [+0.0032, +0.0057]** | S3-test (sealed, simulated), 9,990 | [EXP-B-003](experiments/EXP-B-003.md) |
| Same re-ranker vs E0, pre-registered no-regression gate (passed) | −0.0025 [−0.0070, +0.0013] | R1-test (sealed, real), 2,548 | EXP-B-003 |
| Sex and age in the re-ranker vs F | sex 0.5 +0.0003 [+0.0000, +0.0007]; age_mean 0.5 +0.0007 [−0.0001, +0.0014] | S3-v2-test (sealed, simulated), 9,565 | [EXP-B-004](experiments/EXP-B-004.md) |
| Onset, F + onset 0.25 vs F | +0.0023 [+0.0013, +0.0034] | S3-v3b-test (sealed, simulated), 6,745 | [EXP-B-005](experiments/EXP-B-005.md) |
| Onset candidate vs rr-v1, pre-registered no-regression gate (passed) | −0.0003 [−0.0019, +0.0008] | R1-test (sealed, real), 2,548 | [EXP-B-006](experiments/EXP-B-006.md) |
| R1 vault, MRR (descriptive): E0 0.4136; `rerank-v1.0.0` 0.4114 (−0.0022 [−0.0046, +0.0002]); `rerank-v1.1.0` 0.4106 (−0.0031 [−0.0055, −0.0005]) | see cell | R1 vault (real), 1,771 | [EXP-V-001](experiments/EXP-V-001.md) |

`rerank-v1.1.0` (onset) is built and merged in diagnostic.ar-model and not tagged (ADR-0016).

The realism of the simulated data was also **measured**, against a gate fixed in advance
([ADR-0012](decisions/0012-data-quality-gate.md)): G2b on R1-dev 0.159, against UP 0.231 and V03-full 0.095. GNN
retraining stopped at that gate. Front A's three retraining attempts (EXP-A-001, A-002f, A-003f) were run with
v0.3-era simulated data and recorded: R1-dev Δ vs E0 from −0.0913 [−0.1223, −0.0588] to −0.2788 [−0.3306, −0.2232]
([EVIDENCE_INDEX.md §3](evidence/EVIDENCE_INDEX.md)).

### Context for the real-patient numbers
- **E0 is favoured on R1.** GenPhenAI v3.0 was trained upstream on the full HPO annotations, which derive in part
  from the same published case reports R1 is built from, and we could not retrain or mask it (EVAL_PROTOCOL §4,
  item 5; ADR-0014). Every real-patient comparison here is made against that advantage.
- **R1's excluded terms are publication negatives**, not interview "no" answers, which is the production input.
  The interview path is measured on simulated interviews (S3); there is no real-user measurement.

## Data limitations
We lack the data to test or simulate, correctly, whether these changes improve or reduce performance on real patients. This is why the re-ranking on missing symptoms (`rerank-v1.0.0`) stays in staging only (Q2b goes into production), and why the GNN retraining and `rerank-v1.1.0` were not deployed.
- **Interview negations:** no real-patient dataset with interview yes/no answers exists. R1 has only negatives written in publications, a different input from the agent's "no" answers. The effect on real patients is estimated in simulation only (S3; EXP-B-003 +0.0044 [+0.0032, +0.0057], n = 9,990). `rerank-v1.0.0` stays in staging until real sessions (interview answers plus confirmed diagnoses) can be collected and evaluated.
- **Training data:** no synthetic data was realistic enough to retrain the GNN on. The simulator's realism gate (ADR-0012) was measured: G2b 0.159 on R1-dev vs UP 0.231 and V03-full 0.095. Real patients are few and reserved for evaluation (R1 splits). Retraining with age, sex and negations could not be validated.
- **Literature data:** literature onset ages cover part of the entities (S3 v2: 1,027 cases, 5.25%, with literature onset; S3 v3: 120 eligible genes), so the onset effect is simulated on that subset. Real-patient reads: EXP-B-006 vs rr-v1 -0.0003 [-0.0019, +0.0008] (n = 2,548); EXP-V-001 MRR v1.1 0.4106, v1.0 0.4114, E0 0.4136 (n = 1,771). `rerank-v1.1.0` was not released.
- **E0 on R1:** E0's training annotations derive in part from the same publications as R1, so E0 is favoured there and real-patient comparisons against it are conservative.
- **Future work:** collect consented real sessions on the platform to evaluate the points above.

## Decisions of 2026-10-05 (Mateo; [ADR-0016](decisions/0016-final-deployment-and-close-out.md))
1. **Q2b goes into production** (the question agent with Q2b on). The re-ranking on missing symptoms
   (`rerank-v1.0.0`) stays in staging only, for the data reason in the Data limitations section. Production change:
   a web release including 785060d, with `PREGUNTAS_RERANK_NEGATIONS=false`; the model route stays as it is.
   Handoff: diagnostic.ar-model `docs/HANDOFF-deploy-prod-q2b.md` (PR #10).
2. **`rerank-v1.1.0` (onset) is not released.** It is built and merged in diagnostic.ar-model (PR #7) but never
   tagged.
3. **No more model experiments.** Front B's candidate budget and the R1 vault are both spent.
4. **The web keeps asking for onset age** in Precisar (MateAlv/diagnostic.ar PR #87), and it is being added to the final
   output the doctor sees: results, the saved consultation and the question-session summary (PR #95, merged
   2c3ce11). It is kept as clinical information for the doctor, not as a model input: the model ignores it.

## Deadlines (from `/home/mate/diagnostic.ar/informe/`)
- informe draft to the director: **2026-10-15**;
- informe delivery: **2026-11-01**. The project plan's end date stays **2026-11-07** (PLAN.md).

## Phase 1 sealed-data budget (all spent)
- R1-dev realism reads: 3 of 3 used ([ledger](../results/realism/LEDGER.md)).
- R1-test: read by EXP-000, EXP-B-003 and EXP-B-006. R1-vault: read once, by EXP-V-001.
- Every sealed read is in [TEST_LEDGER.md](TEST_LEDGER.md).

## Open items for Mateo
- Phase 2: a "go" before each sealed read; spot-check 20 curated genes; approval before anything goes to production.
- Hand `docs/HANDOFF-deploy-prod-q2b.md` (diagnostic.ar-model) to the deploy agent for the production rollout.
- The GeneReviews permission email (Mateo is sending it; not blocking).
- Informe: written by the students; this repo only supplies evidence.

## Invariants
- Never touch `GenPhenAI/`. No AI attribution in commits or PRs.
- Sealed data is read only under a committed pre-registration, from a clean
  tree, with a ledger row (`DXT_SEALED_READ`).
- Commit before any run that writes a manifest; do not edit tracked files
  during a long run.
- Chain critical shell steps with `&&` and check exit codes; never pipe a
  step through `grep` when a later step depends on it; never write numbers
  before reading them.
- `pkill -f` can match your own shell; kill by exact PID.
- Worktree agents push with `PYTHONPATH=<worktree>/src`.
- Disk: about 43 GB free on `/` (2026-10-06). Heavy data lives on `/mnt/windows/tp-data` through symlinks.
- Agents work in their own worktrees; a worktree is removed once its PR is merged.
