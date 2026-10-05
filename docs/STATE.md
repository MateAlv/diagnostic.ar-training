# Current state (handoff snapshot)

**Snapshot: 2026-10-05, close-out.** Overwritten at each checkpoint; history lives in
[BITACORA.md](BITACORA.md). Entry points: [INDEX.md](INDEX.md), [PLAN.md](PLAN.md),
[EVAL_PROTOCOL.md](EVAL_PROTOCOL.md), [evidence/EVIDENCE_INDEX.md](evidence/EVIDENCE_INDEX.md).
Final decisions: [ADR-0016](decisions/0016-final-deployment-and-close-out.md).

## Summary

### What was built
- **A literature-enriched patient simulator** (`rare-disease-simulator` 0.5.4), built with strong curation: 97
  literature shards (build v2), onset and presentation ages from the literature, PMID masking, pinned sources and
  manifests. The AI extraction was checked: Codex cross-check 96.1% agreement
  ([LIT-CROSSCHECK-v1](analyses/LIT-CROSSCHECK-v1.md)); audit row error 2.0% [1.25, 3.17] and recall 93.3%
  ([LIT-AUDIT-v1](analyses/LIT-AUDIT-v1.md)).
- **An evaluation infrastructure**, which the anteproyecto itself names as an open problem in the field:
  frozen splits `r1-v1` (train/dev/test/vault) split by publication, with held-out PMID masking; pre-registration;
  a code-enforced sealed-read guard (`DXT_SEALED_READ`) and a ledger; S3 simulated-interview benchmarks (v1, v2,
  v3b) with a knowledge split (half B held out) and source separation for age and sex; every claim reported as a
  paired-bootstrap Δ vs E0 with a CI and the harmed share.
- **Two components, deployed in staging:** question selection **Q2b** and the "no"-answer re-ranker
  `rerank-v1.0.0`. The GNN was also reimplemented in PyTorch (`gnn/`) with parity tests against production.

### What was measured
| Result | Δ MRR [95% CI] | Where |
|---|---|---|
| Q2b over the baseline questioner Q0 (sealed, simulated) | **+0.0049 [+0.0027, +0.0069]** | [EXP-Q-001](experiments/EXP-Q-001.md) |
| "No"-answer re-ranker vs E0+answers (sealed, simulated) | **+0.0044 [+0.0032, +0.0057]** | [EXP-B-003](experiments/EXP-B-003.md) |
| Same re-ranker vs E0 on real patients (R1-test) | −0.0025 [−0.0070, +0.0013]: no regression | EXP-B-003 |
| Sex and age, tested fairly with source separation | no gain | [EXP-B-004](experiments/EXP-B-004.md) |
| Onset (simulated) | +0.0023 [+0.0013, +0.0034] | [EXP-B-005](experiments/EXP-B-005.md) |
| Onset on real patients (R1-test; R1 vault) | no gain on R1-test; vault v1.1 vs E0 −0.0031 [−0.0055, −0.0005]; not released | [EXP-B-006](experiments/EXP-B-006.md), [EXP-V-001](experiments/EXP-V-001.md) |

The realism of the simulated data was also **measured**, against a gate fixed in advance
([ADR-0012](decisions/0012-data-quality-gate.md)). The gate was not passed (G2b on R1-dev 0.159, against UP 0.231
and V03-full 0.095), and that measurement is why GNN retraining stopped. Front A's three retraining attempts
(EXP-A-001, A-002f, A-003f) were run and recorded; with v0.3-era simulated data they were below E0 on real
patients.

### Limits, with their context
- **E0 is favoured on R1.** GenPhenAI v3.0 was trained upstream on the full HPO annotations, which derive in part
  from the same published case reports R1 is built from, and we could not retrain or mask it (EVAL_PROTOCOL §4,
  item 5; ADR-0014). Every real-patient comparison here is made against that advantage.
- **R1 cannot measure the interview "no" answers.** Its excluded terms are publication negatives, which is not the
  production input. The efficacy evidence for the interview path is simulated (S3); there is no real-user
  measurement.
- **Onset** helped in simulation but not on real patients, so `rerank-v1.1.0` is not released (vault, for the
  record: E0 0.4136, v1.0 0.4114 [−0.0022 (−0.0046, +0.0002)], v1.1 0.4106).
- **Q2b vs the previous production selector (Q1):** +0.0017 [−0.0006, +0.0043], not distinguishable from zero.

## Decisions of 2026-10-05 (Mateo; [ADR-0016](decisions/0016-final-deployment-and-close-out.md))
1. **Deployed (staging):** the question agent with Q2b on, plus `rerank-v1.0.0`. Production later, by routing to the
   pinned image (no shadow mode).
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
