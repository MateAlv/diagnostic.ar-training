# Current state (handoff snapshot)

The fastest way back into the work after an interruption. It is overwritten
at each checkpoint; the history lives in `BITACORA.md`.

**Snapshot:** 2026-09-30, evening (v0.4 candidate 1 under the data-quality gate). Disk: about 40 GB free on TARS.

## Where each front stands

| Front | Status | Evidence |
|---|---|---|
| Shared | E0 measured on every cohort; R1 CIs resample publications | `EXP-000.md` |
| B on R1 | rr-v1 null; rr-v2 (learned on R1-train) +0.056 dev but harmed 10%, and its gain is R1's negation reporting pattern; sex/age/onset ≈ 0 | `EXP-B-001.md`, `EXP-B-002.md` |
| B on S3 | **The only method that passes the harm cap:** rr-v1[neg=0.5] +0.0045 [+0.0034, +0.0056], harmed 4% (knowledge-based, no simulator training). rr-v2 hurts (−0.030) | `EXP-S3-001.md` |
| A | **All three trained designs fail on real patients:** A-001 (full fine-tune), A-002f (negation, frozen), A-003f (sex/age, frozen). Each gains on S3, which is the same simulator. A-004f not run (nothing to combine) | `EXP-A-001.md`, `EXP-A-002f.md`, `EXP-A-003f.md`, `EXP-A-004f.md` |

## In progress: simulator v0.4 data-quality gate (ADR-0011, ADR-0012)
**Retraining is blocked until the ADR-0012 gate passes.**

| Piece | Status |
|---|---|
| Simulator v0.4 code | Merged (rare-disease-simulator PR #5, 266472c). Not tagged; freezing waits for the gate |
| Training artifacts | Merged (PR #22): `hpoa-recount-v1`, `genes-v2`, `report-model-v2`, `cardinal-v1`, `literature-panel-v1`, `dxt sim realism/gate`, G2 baselines for UP and V03 |
| Candidate 1 settings | Merged (PR #23, ADR-0011 amendment 1): μ₀ 0.30 (pairs with m ≥ 10), cardinal terms unforced, `simcal-v04-v2` |
| Candidate 1 data + G1/G2 | **Running** (agent, branch `phase3/sim-v04-cand1-data`). This is R1-dev read **1 of 3** |
| G4 literature panel v2 | **Running** (agent, branch `phase3/literature-panel-v2`): 60-gene evaluation split frozen first; Claude extraction, Codex 10% cross-check |
| G3 disease cards | Not started. Needs candidate data and panel v2; the 30 cards go to Mateo |

**G2 baselines** (`results/realism/gate-baselines.md`):

| Metric | UP (GraPhens sim) | V03 |
|---|---|---|
| panel-v1 MAE | 0.504 | 0.556 |
| R1-dev ρ | 0.231 | 0.086 |
| W1 terms per case | 3.717 | 1.382 |
| C2ST AUC | 0.840 | 0.778 |
| E0 gap to 0.512 | 0.307 | 0.344 |

**Next:**
1. Review candidate 1's G1/G2 results.
2. Recompute G2a on panel v2.
3. Build the G3 cards.
4. If it fails, write candidate 2 settings from R1-train-only diagnostics.
5. Once G1–G4 pass, freeze (G5), then pre-register A-002f-v2 / A-003f-v2.

## Latest analysis
**ANALYSIS-001 (dataset realism).** The simulator is internally
consistent but not realistic per disease. Over-masking guts some
profiles (UMOD keeps 3 of 33 rows), and the emission model mismatches how
real patients are reported. Front A's negatives are about *this*
simulator. See `docs/analyses/ANALYSIS-001-dataset-realism.md` §6 for the
proposed fixes.

## Open decisions for Mateo
1. **Phase-4 gate for rr-v1[neg=0.5]:** pre-register one sealed read of
   S3-test + an R1-test no-regression check (R1-test "present" view is
   identical by construction; its "+excluded" view carries the reporting
   caveat).
2. **Front A going forward:**
   - (a) stop and write up the negative results;
   - (b) A-005: train the new parameters on real R1-train patients;
   - (c) improve the simulator's realism first.
3. **Optional:** an S3 v2 that also holds out onset and inheritance, so
   sex/age can be evaluated fairly on S3.

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
