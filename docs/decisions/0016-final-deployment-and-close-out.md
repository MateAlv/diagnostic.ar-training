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
| 1 | **Deployed in staging:** the question agent with **Q2b** on, plus `rerank-v1.0.0` (the "no" answers) on. Production later, by routing to the pinned image (no shadow mode). | Q2b beats the baseline questioner Q0 (the S3 v1 questioner) in a sealed simulated test (EXP-Q-001, +0.0049 [+0.0027, +0.0069] final MRR). Against Q1, the previous production selector, the difference is not distinguishable from zero (+0.0017 [−0.0006, +0.0043]); Q2b is deployed on the first result and the re-ranker-aware design. The re-ranker has a sealed simulated gain (EXP-B-003, S3-test +0.0044 [+0.0032, +0.0057]) and no regression on real patients in R1-test (−0.0025 [−0.0070, +0.0013]). |
| 2 | **`rerank-v1.1.0` (onset) is not released.** It is built and merged in diagnostic.ar-model (PR #7) but never tagged. | It passed its R1-test gate (EXP-B-006) with no measurable real-patient gain, and scored slightly lower than E0 on the vault (EXP-V-001: v1.1 vs E0 −0.0031 [−0.0055, −0.0005]). Its only positive evidence is simulated (EXP-B-005 +0.0023). Kept for the record. |
| 3 | **No more model experiments.** | Front B's candidate budget and the R1 vault are both spent. |
| 4 | **The web keeps asking for onset age** in Precisar (MateAlv/diagnostic.ar PR #87), and it is being added to the final output the doctor sees (results and the saved consultation; a web PR is in progress). | It is clinically useful to the doctor even though it does not improve the ranking model. Kept as clinical information for the doctor, not as a model input: the API ignores it, because no released re-ranker uses onset. |

## What the vault result does and does not say

- Vault (1,771 patients, 352 publications), MRR: E0 0.4136; `rerank-v1.0.0`
  0.4114 (−0.0022 [−0.0046, +0.0002]); `rerank-v1.1.0` 0.4106. Descriptive, not
  a gate ([EXP-V-001](../experiments/EXP-V-001.md)).
- **E0 is favoured on R1.** E0 (GenPhenAI v3.0) was trained upstream on the full
  HPO annotations, which derive in part from the same published case reports R1
  is built from. We could not retrain or mask it (EVAL_PROTOCOL §4, item 5;
  [ADR-0014](0014-reranker-v11-and-s3-v2.md)).
- **R1's excluded terms are publication negatives**, not interview "no" answers,
  which is the production input. R1 therefore cannot measure what the
  re-ranker is for; it measures only that it does no meaningful harm there
  (EXP-B-003, [EXP-B-006](../experiments/EXP-B-006.md)).
- The efficacy evidence for the interview path is simulated (S3), with the
  knowledge split and source separation described in ADR-0014 and ADR-0015.
  There is no real-user measurement.

## Alternatives dropped
- Tagging `rerank-v1.1.0` for staging: dropped, for the vault result above.
- A further candidate, or a second vault read: dropped; both budgets are spent
  and the protocol forbids re-reading.

## Consequences
- Staging runs Q2b plus `rerank-v1.0.0`. The diagnostic.ar-model handoff for
  v1.1 is marked not to be executed (diagnostic.ar-model PR #8).
- The close-out summary is in [STATE.md](../STATE.md); numbers are in
  [evidence/EVIDENCE_INDEX.md](../evidence/EVIDENCE_INDEX.md).
- Supersedes nothing; it completes ADR-0014 and ADR-0015.
