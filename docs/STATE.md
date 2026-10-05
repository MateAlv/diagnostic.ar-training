# Current state (handoff snapshot)

**Snapshot: 2026-10-05, close-out.** Overwritten at each checkpoint; history lives in
[BITACORA.md](BITACORA.md). Entry points: [INDEX.md](INDEX.md), [PLAN.md](PLAN.md),
[EVAL_PROTOCOL.md](EVAL_PROTOCOL.md), [evidence/EVIDENCE_INDEX.md](evidence/EVIDENCE_INDEX.md).
Final decisions: [ADR-0016](decisions/0016-final-deployment-and-close-out.md).

## Summary

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
   (`rerank-v1.0.0`) stays in staging only, for the data reason in the Data limitations section. Route to production:
   the pinned image (no shadow mode).
2. **`rerank-v1.1.0` (onset) is not released.** It is built and merged in diagnostic.ar-model (PR #7) but never
   tagged.
3. **No more model experiments.** Front B's candidate budget and the R1 vault are both spent.
4. **The web keeps asking for onset age** in Precisar (MateAlv/diagnostic.ar PR #87), and it is being added to the final
   output the doctor sees (results and the saved consultation; a web PR is in progress). It is kept as clinical
   information for the doctor, not as a model input: the model ignores it.

## Deadlines (from `/home/mate/diagnostic.ar/informe/`)
- informe draft to the director: **2026-10-15**;
- informe delivery: **2026-11-01**. The project plan's end date stays **2026-11-07** (PLAN.md).

## Sealed-data budget (all spent)
- R1-dev realism reads: 3 of 3 used ([ledger](../results/realism/LEDGER.md)).
- R1-test: read by EXP-000, EXP-B-003 and EXP-B-006. R1-vault: read once, by EXP-V-001.
- Every sealed read is in [TEST_LEDGER.md](TEST_LEDGER.md).

## Open items for Mateo
- Production go-ahead after staging is verified.
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
- Disk is tight (about 11 GB free on `/` at last check).
