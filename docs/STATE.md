# Current state (handoff snapshot)

The fastest way back into the work after an interruption. It is overwritten
at each checkpoint; the history lives in `BITACORA.md`.

**Snapshot:** 2026-09-30, night (simulator gate unmet; waiting for Mateo; Front B release candidate ready). Disk: about 40 GB free on TARS.

## Where each front stands

| Front | Status | Evidence |
|---|---|---|
| Shared | E0 measured on every cohort; R1 CIs resample publications | `EXP-000.md` |
| B on R1 | rr-v1 null; rr-v2 (learned on R1-train) +0.056 dev but harmed 10%, and its gain is R1's negation reporting pattern; sex/age/onset ≈ 0 | `EXP-B-001.md`, `EXP-B-002.md` |
| B on S3 | **rr-v1[neg=0.5] passed its sealed Phase-4 gate (EXP-B-003):** S3-test +0.0044 [+0.0032, +0.0057], harmed 3.9%; R1-test no regression (−0.0025 [−0.0070, +0.0013]). It is a release candidate; deploying is Mateo's call | `EXP-S3-001.md`, `EXP-B-003.md` |
| A | **All three trained designs fail on real patients:** A-001 (full fine-tune), A-002f (negation, frozen), A-003f (sex/age, frozen). Each gains on S3, which is the same simulator. A-004f not run (nothing to combine) | `EXP-A-001.md`, `EXP-A-002f.md`, `EXP-A-003f.md`, `EXP-A-004f.md` |

## In progress: simulator v0.4 data-quality gate (ADR-0011, ADR-0012)
**Retraining is blocked until the ADR-0012 gate passes.**

**R1-dev realism reads used: 2 of 3.** The next is the last; candidate 3 did not use it.

| Piece | Status |
|---|---|
| Candidate 1 (sim 0.4.1) | G1 pass; G2 fails on a, b, e |
| Candidate 2 (sim 0.4.2, `simcal-v04-v4`) | G1 pass; G2c passes; a 0.404, b 0.193, d 0.792, e 0.242 fail (PR #34) |
| ANALYSIS-003 | Noise causes E0's difficulty (0.163 → 0.472 without it). The kb-v4 reference inflated "unexplained": against kb-v3, new patients have about 24% noise, not 35%. G2a now scores the truth layer (ADR-0012 amendment 3) |
| Candidate 3 | G1 pass; **stopped at the train-side go/no-go** (G2c 1.732, d 0.764, e gap 0.142). The last R1-dev read was not spent (PR #39) |
| ANALYSIS-004 | Real "noise" carries gene signal: E0 MRR 0.059 on it, vs 0.001 for simulated vocabulary noise. 13.5% of it is annotated in unmasked g2p |
| Simulator 0.5.0 | Merged (PR #8): independent per-term reporting, proportional noise, age by onset |
| Candidate 4 | G1 pass; **stopped at the go/no-go** (G2c 5.754, d 0.822, e gap 0.204; records too short, 2.95 terms per case). PR #44 |
| **Gate** | **Unmet after four candidates. Mateo decides** (ADR-0011 amendment 5 §5). The last R1-dev read is still unspent |
| G3 cards | Tool merged (`scripts/realism_cards.py`). Review: the assistant plus Codex independently; Mateo spot-checks afterwards (ADR-0012 amendment 2) |
| G4 panel | Done (literature-panel-v2) |

## Latest analysis
**ANALYSIS-001 (dataset realism).** The simulator is internally
consistent but not realistic per disease. Over-masking guts some
profiles (UMOD keeps 3 of 33 rows), and the emission model mismatches how
real patients are reported. Front A's negatives are about *this*
simulator. See `docs/analyses/ANALYSIS-001-dataset-realism.md` §6 for the
proposed fixes.

## Open decisions for Mateo
1. **Deploy rr-v1[neg=0.5]?** It passed EXP-B-003. A release goes through
   `diagnostic.ar-model`, with the negation input as an optional API
   field.
2. **ADR-0012 amendment 3** (G2a on the truth layer), made after
   candidate 2's read: accept or revert. Amendment 1 is already accepted.
3. **Spot-check the G3 cards and the two reviewers' verdicts** once they
   exist.
4. **GeneReviews email:** Mateo is sending it; not blocking.

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
- **Never update a shared checkout (e.g. rare-disease-simulator main) while an agent is generating from it.** Runs use a pinned worktree or tarball.
- Worktree agents push with `PYTHONPATH=<worktree>/src`.
- Sealed data is read only under a committed pre-registration.
- No AI mention in commits or PRs.
- **Graceful stop:** message the agents, then stop queue scripts before
  their runs (by exact PID). Interrupted runs must leave no manifest.
