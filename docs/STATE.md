# Current state (handoff snapshot)

**Snapshot: 2026-10-05.** Overwritten at each checkpoint; history lives in
[BITACORA.md](BITACORA.md), which this file does not repeat. Entry points:
[INDEX.md](INDEX.md), [PLAN.md](PLAN.md), [EVAL_PROTOCOL.md](EVAL_PROTOCOL.md),
[evidence/EVIDENCE_INDEX.md](evidence/EVIDENCE_INDEX.md).

**Deadlines** (from `/home/mate/diagnostic.ar/informe/`):
- informe draft to the director: **2026-10-15** (10 days left);
- informe delivery: **2026-11-01** (27 days left).

PLAN.md still carries the original project window ending 2026-11-07; the
informe delivery date above is the binding one.

**Repo:** main at d0e4b2a or later; PRs #107 to #110 merged today, CI green.

## Front A: no retraining planned
- **Retraining failed on real patients:** EXP-A-001, EXP-A-002f and
  EXP-A-003f all lost to E0 on R1-dev (details in
  [EVIDENCE_INDEX.md §3](evidence/EVIDENCE_INDEX.md)). EXP-A-004f was not run,
  by the rule ADR-0010 set for it.
- **The simulator gate (ADR-0012) closed without passing.** Candidate 6 was
  not frozen: G2b on R1-dev is 0.159, against UP 0.231 and V03-full 0.095.
  The R1-dev realism budget (3 reads) is exhausted. No further candidates.
- No Front A retraining is planned. Its data and negative results go to the
  informe as evidence.

## Literature enrichment (ADR-0013)
- Build **v2** published (`hpoa-enriched-v2`, `onset-ages-v2`,
  `presentation-ages-v2`); 97 shards, 7,083 rows in.
- Cross-check: 96.1% agreement (715 of 744 rows), [LIT-CROSSCHECK-v1](analyses/LIT-CROSSCHECK-v1.md).
- Audit (98 sources, 852 rows): row error 2.0% [1.25, 3.17], recall 93.3%,
  [LIT-AUDIT-v1](analyses/LIT-AUDIT-v1.md).

## Front B
| Experiment | Outcome | Doc |
|---|---|---|
| EXP-B-003 | `rerank-v1.0.0` released in diagnostic.ar-model (GitHub release 2026-10-03). **Not yet deployed to production.** | [EXP-B-003](experiments/EXP-B-003.md) |
| EXP-B-004 | Descriptive. F does not beat rr-v1 under the 5% harm cap. Not a release candidate. | [EXP-B-004](experiments/EXP-B-004.md) |
| EXP-Q-001 | Q2b beats Q0 in final MRR: +0.0049 [+0.0027, +0.0069]; re-ranker harmed 4.77%. Q2b is the default selector in the question agent (`feat/agente-v2` at 495bfac, agent PRs #1 to #3); the previous selector stays as `legacy`. Not yet deployed. | [EXP-Q-001](experiments/EXP-Q-001.md) |
| EXP-B-005 | Onset P1 passed: +0.0023 [+0.0013, +0.0034] over F, harmed 4.63%. | [EXP-B-005](experiments/EXP-B-005.md) |
| EXP-B-006 | **Pre-registered**, sealed read not done: rr-v1 + onset 0.25 on kb-v3 (`71713c8d15b0`), the one R1-test no-regression read approved by Mateo. Dev numbers (S3-v3b-dev, labelled dev): +0.0021 [+0.0007, +0.0035] over rr-v1, harmed 4.40%. It is the 3rd and last Front B candidate (Mateo, 2026-10-04). | [EXP-B-006](experiments/EXP-B-006.md) |

All Front B gains are measured on simulated interviews (S3); on real
patients (R1) the re-ranker is neutral by construction when there are no
negations. There is no real-user measurement.

## The onset web feature
- **MateAlv/diagnostic.ar PR #87, merged 2026-10-05** (merge commit 84db86b on
  main; cloud-copy publish succeeded, **production on nodo0 unchanged**): the
  age selector in Precisar. The button shows on the 206 most-reported symptoms
  (`onset-prompt-terms-v1`, 90.01% of R1-train patients) and on refinable ones.
  The API ignores the new fields until the re-ranker uses onset.
- The onset-score selector (354 terms) **failed its dev check**; it is not
  the selection rule. See
  [ONSET-INFORMATIVE-TERMS-v1](analyses/ONSET-INFORMATIVE-TERMS-v1.md).

## Next steps, in Mateo's order
1. **Deploy the re-ranker and Q2b to production.** Handoff:
   diagnostic.ar-model `docs/HANDOFF-deploy-rerank-v1.md`. The web pin
   `QUESTION_AGENT_COMMIT` moves from 53a4107 to 495bfac.
2. **EXP-B-006 sealed R1-test read** (after step 1, per Mateo's 2026-10-04
   ruling), then release `rerank-v1.1.0` if it passes.
3. **Final R1-vault read**: opens once, final system against E0
   ([EVAL_PROTOCOL.md](EVAL_PROTOCOL.md)).
4. **Informe evidence refresh** (evidence only; the students write the informe).

## Sealed-data budget
- R1-dev realism reads: 3 of 3 used ([ledger](../results/realism/LEDGER.md)).
- R1-test: read by EXP-000 and EXP-B-003; EXP-B-006's read is approved, not done.
- R1-vault: never read.
- Every sealed read is in [TEST_LEDGER.md](TEST_LEDGER.md).

## Open items for Mateo
- Production route for the re-ranker (brainy, not the pinned image) and
  shadow mode: open decisions in the deploy handoff.
- The GeneReviews permission email: Mateo is sending it; not blocking.

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
