# ADR-0016: Final deployment and close-out of the model experiments

- **Status:** Accepted, 2026-10-05 (Mateo).
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
| 1 | **Deployed in staging:** the question agent with **Q2b** on, plus `rerank-v1.0.0` (the "no" answers) on. Production later, by routing to the pinned image (no shadow mode). | Q2b vs the baseline questioner Q0 (the S3 v1 questioner), sealed simulated test: EXP-Q-001, +0.0049 [+0.0027, +0.0069] final MRR (n = 9,565). Q2b vs Q1, the previous production selector: +0.0017 [−0.0006, +0.0043]; Q2b is deployed on the first result and the re-ranker-aware design. Re-ranker, sealed simulated test: EXP-B-003, S3-test +0.0044 [+0.0032, +0.0057] (n = 9,990); on real patients, R1-test, it passed its pre-registered no-regression gate (−0.0025 [−0.0070, +0.0013], n = 2,548). |
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

## Alternatives dropped
- Tagging `rerank-v1.1.0` for staging: dropped, given the vault numbers above (v1.1 0.4106, v1.0 0.4114, E0 0.4136).
- A further candidate, or a second vault read: dropped; both budgets are spent
  and the protocol forbids re-reading.

## Consequences
- Staging runs Q2b plus `rerank-v1.0.0`. The diagnostic.ar-model handoff for
  v1.1 is marked not to be executed (diagnostic.ar-model PR #8).
- The close-out summary is in [STATE.md](../STATE.md); numbers are in
  [evidence/EVIDENCE_INDEX.md](../evidence/EVIDENCE_INDEX.md).
- Supersedes nothing; it completes ADR-0014 and ADR-0015.
