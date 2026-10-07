# ADR-0016: Final deployment and close-out of the model experiments

- **Status:** Accepted, 2026-10-05 (Mateo). Decision 3 (no more model experiments) superseded by [ADR-0017](0017-phase-2-real-patient-restart.md) on 2026-10-07.
- **Context:**
  - Front B's three candidates are decided: `rerank-v1.0.0` (EXP-B-003), the
    sex/age and onset variants (EXP-B-004, EXP-B-005) and `rerank-v1.1.0`
    (EXP-B-006).
  - The R1 vault was read once (EXP-V-001) and is spent. R1-dev's realism budget
    (3 reads) was spent earlier (ADR-0012).
  - Front A's retraining stopped at the data-quality gate (ADR-0012).

## Decisions

| # | Decision | Rationale |
|---|---|---|
| 1 | **Q2b goes into production** (the question agent with Q2b on). The re-ranking on missing symptoms, `rerank-v1.0.0` (the "no" answers), **stays in staging only** (see Data limitations). Route to production: the pinned image (no shadow mode). | Q2b vs the baseline questioner Q0 (the S3 v1 questioner), sealed simulated test: EXP-Q-001, +0.0049 [+0.0027, +0.0069] final MRR (n = 9,565). Q2b vs Q1, the previous production selector: +0.0017 [−0.0006, +0.0043]; Q2b is deployed on the first result and the re-ranker-aware design. Re-ranker, sealed simulated test: EXP-B-003, S3-test +0.0044 [+0.0032, +0.0057] (n = 9,990); on real patients, R1-test, it passed its pre-registered no-regression gate (−0.0025 [−0.0070, +0.0013], n = 2,548). |
| 2 | **`rerank-v1.1.0` (onset) is not released.** It is built and merged in diagnostic.ar-model (PR #7) but never tagged. | R1-test (EXP-B-006, pre-registered no-regression gate, passed): candidate vs rr-v1 −0.0003 [−0.0019, +0.0008], n = 2,548. Vault (EXP-V-001, descriptive): MRR 0.4106 for v1.1 against 0.4136 for E0 (−0.0031 [−0.0055, −0.0005], n = 1,771). The simulated onset result is EXP-B-005, +0.0023 [+0.0013, +0.0034]. Kept for the record. |
| 3 | **No more model experiments.** | Front B's candidate budget and the R1 vault are both spent. |
| 4 | **The web keeps asking for onset age** in Precisar (MateAlv/diagnostic.ar PR #87), and it is being added to the final output the doctor sees (results and the saved consultation; a web PR is in progress). | It gives the doctor a more precise clinical summary. Kept as clinical information for the doctor, not as a model input: the API ignores it, because no released re-ranker uses onset. |

## What the vault result does and does not say

- Vault (1,771 patients, 352 publications), MRR: E0 0.4136; `rerank-v1.0.0`
  0.4114 (−0.0022 [−0.0046, +0.0002]); `rerank-v1.1.0` 0.4106 (−0.0031
  [−0.0055, −0.0005]). Descriptive, not a gate ([EXP-V-001](../experiments/EXP-V-001.md)).
- **E0 is favoured on R1.** E0 (GenPhenAI v3.0) was trained upstream on the full
  HPO annotations, which derive in part from the same published case reports R1
  is built from. We could not retrain or mask it (EVAL_PROTOCOL §4, item 5;
  [ADR-0014](0014-reranker-v11-and-s3-v2.md)).
- **R1's excluded terms are publication negatives**, not interview "no" answers,
  which is the production input. R1 therefore does not measure what the
  re-ranker is for; it is used as a no-regression check: EXP-B-003 −0.0025
  [−0.0070, +0.0013] vs E0, [EXP-B-006](../experiments/EXP-B-006.md) −0.0003
  [−0.0019, +0.0008] vs rr-v1.
- The efficacy evidence for the interview path is simulated (S3), with the
  knowledge split and source separation described in ADR-0014 and ADR-0015.
  There is no real-user measurement.

## Data limitations
We lack the data to test or simulate, correctly, whether these changes improve or reduce performance on real patients. This is why the re-ranking on missing symptoms (`rerank-v1.0.0`) stays in staging only (Q2b goes into production), and why the GNN retraining and `rerank-v1.1.0` were not deployed.
- **Interview negations:** no real-patient dataset with interview yes/no answers exists. R1 has only negatives written in publications, a different input from the agent's "no" answers. The effect on real patients is estimated in simulation only (S3; EXP-B-003 +0.0044 [+0.0032, +0.0057], n = 9,990). `rerank-v1.0.0` stays in staging until real sessions (interview answers plus confirmed diagnoses) can be collected and evaluated.
- **Training data:** no synthetic data was realistic enough to retrain the GNN on. The simulator's realism gate (ADR-0012) was measured: G2b 0.159 on R1-dev vs UP 0.231 and V03-full 0.095. Real patients are few and reserved for evaluation (R1 splits). Retraining with age, sex and negations could not be validated.
- **Literature data:** literature onset ages cover part of the entities (S3 v2: 1,027 cases, 5.25%, with literature onset; S3 v3: 120 eligible genes), so the onset effect is simulated on that subset. Real-patient reads: EXP-B-006 vs rr-v1 -0.0003 [-0.0019, +0.0008] (n = 2,548); EXP-V-001 MRR v1.1 0.4106, v1.0 0.4114, E0 0.4136 (n = 1,771). `rerank-v1.1.0` was not released.
- **E0 on R1:** E0's training annotations derive in part from the same publications as R1, so E0 is favoured there and real-patient comparisons against it are conservative.
- **Future work:** collect consented real sessions on the platform to evaluate the points above.

## Alternatives dropped
- Tagging `rerank-v1.1.0` for staging: dropped, given the vault numbers above (v1.1 0.4106, v1.0 0.4114, E0 0.4136).
- A further candidate, or a second vault read: dropped; both budgets are spent
  and the protocol forbids re-reading.

## Consequences
- Q2b goes into production; staging keeps `rerank-v1.0.0` only. The diagnostic.ar-model handoff for
  v1.1 is marked not to be executed (diagnostic.ar-model PR #8).
- The close-out summary is in [STATE.md](../STATE.md); numbers are in
  [evidence/EVIDENCE_INDEX.md](../evidence/EVIDENCE_INDEX.md).
- Supersedes nothing; it completes ADR-0014 and ADR-0015.
