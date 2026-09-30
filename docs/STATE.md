# Current state (handoff snapshot)

The fastest way back into the work after an interruption. It is overwritten
at each checkpoint; the history lives in `BITACORA.md`.

**Snapshot:** 2026-09-30, night (v0.4 candidate 2 in the data-quality gate). Disk: about 40 GB free on TARS.

## Where each front stands

| Front | Status | Evidence |
|---|---|---|
| Shared | E0 measured on every cohort; R1 CIs resample publications | `EXP-000.md` |
| B on R1 | rr-v1 null; rr-v2 (learned on R1-train) +0.056 dev but harmed 10%, and its gain is R1's negation reporting pattern; sex/age/onset ≈ 0 | `EXP-B-001.md`, `EXP-B-002.md` |
| B on S3 | **rr-v1[neg=0.5] passed its sealed Phase-4 gate (EXP-B-003):** S3-test +0.0044 [+0.0032, +0.0057], harmed 3.9%; R1-test no regression (−0.0025 [−0.0070, +0.0013]). It is a release candidate; deploying is Mateo's call | `EXP-S3-001.md`, `EXP-B-003.md` |
| A | **All three trained designs fail on real patients:** A-001 (full fine-tune), A-002f (negation, frozen), A-003f (sex/age, frozen). Each gains on S3, which is the same simulator. A-004f not run (nothing to combine) | `EXP-A-001.md`, `EXP-A-002f.md`, `EXP-A-003f.md`, `EXP-A-004f.md` |

## In progress: simulator v0.4 data-quality gate (ADR-0011, ADR-0012)
**Retraining is blocked until the ADR-0012 gate passes.**

**R1-dev realism reads used: 1 of 3** (see `results/realism/LEDGER.md`).

| Piece | Status |
|---|---|
| Candidate 1 (sim 0.4.1) | G1 pass; G2 fails on a, b and e (PR #27) |
| ANALYSIS-002 | Real "noise" is structured: 11.5% more specific, 10.8% related, 23.9% weak. E0 on R1-train: 0.562 cited in HPOA vs 0.405 uncited |
| ADR-0012 amendment 1 | G2e target 0.405; G2 scores full-profile runs. Made after candidate 1's read and disclosed; **awaiting Mateo's OK** |
| Simulator 0.4.2 | Merged (PR #7, ddb1ec1): specialisation plus disease-related noise |
| G4 literature panel v2 | Merged (PR #29): 56 diseases, 531 rows, 497 independent; Codex cross-check agreement 96.3%. Evaluation split `litpanel-split-v3` (120 units) is never used for construction |
| Candidate 2 | **Running** (agent, branch `phase3/sim-v04-cand2`). Phase A: G2a on panel v2 and a V03-full baseline. Phase B: ≤ 2 R1-train pilot rounds, then `simcal-v04-v4`. Phase C: full and half-A datasets, G1, then G2 = **R1-dev read 2 of 3** |
| G3 disease cards | Not started; comes after candidate 2 |

**Next:**
1. Review candidate 2.
2. If it passes G2: 30 disease cards (G3) for Mateo, then freeze (G5).
3. If it fails: one last candidate (read 3 of 3), or write up the simulator's limits.

## Latest analysis
**ANALYSIS-001 (dataset realism).** The simulator is internally
consistent but not realistic per disease. Over-masking guts some
profiles (UMOD keeps 3 of 33 rows), and the emission model mismatches how
real patients are reported. Front A's negatives are about *this*
simulator. See `docs/analyses/ANALYSIS-001-dataset-realism.md` §6 for the
proposed fixes.

## Open decisions for Mateo
1. **ADR-0012 amendment 1.** It corrects two gate criteria after
   candidate 1's read, and doesn't change candidate 1's verdict. Accept it,
   or revert to the original criteria.
2. **GeneReviews email** (`docs/TODO.md`): request written confirmation
   for fact extraction.
3. **Deploy rr-v1[neg=0.5]?** It passed EXP-B-003. A release goes through
   `diagnostic.ar-model`, with the negation input as an optional API
   field.
4. **Later:** review the G3 disease cards (30) when they are ready.

## Artifacts, newest first

| Artifact | What it is |
|---|---|
| `ds-sim0.3.1-A-iv-v1` | Interviewed simulated training cases (Front A frozen) |
| `ds-sim0.3.1-A-n100-s1001` (+`-excl-v1`) | Front A training set, 501,100 cases |
| `s3-data-v1` + split `s3-v1` | S3 patients; dev 10,210 / test 9,990 (sealed) |
| `simcal-train-v1`, `simcal-s3-v1` | Simulator calibration files |
| `kb-v5` | KB without half B of `annot-split-v1` |
| `annot-split-v1` | Held-out annotation pairs |
| `calib-v1` | R1-train targets |
| `kb-v4`, `kb-v3`, `genes-v1` | Earlier KBs and gene profiles |
| `kb-v2` | VOID |

## Invariants to keep in mind
- Never touch `GenPhenAI/`.
- Commit before any run that writes a manifest, and don't edit tracked files
  while a long run is going.
- Scripted shell blocks use `set -euo pipefail` on their own line. Never
  pipe a step through `grep` when a later step depends on it. Never write
  numbers before reading them.
- In this Bash environment `set -e` has been seen not to stop a chain; chain critical steps with `&&` and check exit codes.
- Worktree agents push with `PYTHONPATH=<worktree>/src`.
- Sealed data is read only under a committed pre-registration.
- No AI mention in commits or PRs.
- **Graceful stop:** message the agents, then stop queue scripts before
  their runs (by exact PID). Interrupted runs must leave no manifest.
