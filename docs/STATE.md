# Current state (handoff snapshot)

The fastest way back into the work after an interruption. It is overwritten
at each checkpoint; the history lives in `BITACORA.md`.

**Snapshot:** 2026-09-29, night. Disk: 43 GB free on TARS.

## Where each front stands

| Front | Status | Evidence |
|---|---|---|
| Shared | E0 measured on every cohort. R1 CIs resample publications | `EXP-000.md` |
| B on R1 | rr-v1: null. rr-v2 (learned on R1-train): +0.056 dev but no candidate (harmed 10%); the gain is R1's negation reporting pattern. Sex, age and onset ≈ 0 | `EXP-B-001.md`, `EXP-B-002.md` |
| B on S3 | **Clinically-signed negation helps**: rr-v1[neg=0.5] +0.0045 [+0.0034, +0.0056], harmed 4%. The R1-learned rr-v2 **hurts** (−0.030, harmed 28%). S3 v1 is fair for negation only; sex, age and onset are circular there | `EXP-S3-001.md` |
| A | GinV3 accepted. Training set `ds-sim0.3.1-A-n100-s1001` (+ exclusion `-excl-v1`). **EXP-A-001: fine-tuning on simulated positives HURTS R1 (−0.09 to −0.21 MRR, harmed 46–61%); no candidate.** Cause: distribution shift from an over-confident start, not unlearning half B. **Redesign decided (ADR-0010): v3.0 frozen; only new inputs' parameters train, on interviewed training cases.** Next: A-002f/A-003f/A-004f | `EXP-A-001.md` |

## Artifacts, newest first

| Artifact | What it is |
|---|---|
| `s3-data-v1` + split `s3-v1` | 20,200 S3 patients; dev 10,210 / test 9,990 (sealed) |
| `simcal-train-v1`, `simcal-s3-v1` | Simulator calibration files (from `calib-v1` only) |
| `kb-v5` | KB without half B of `annot-split-v1` (the systems' knowledge in S3) |
| `annot-split-v1` | 78,917 held-out annotation pairs (30%) |
| `calib-v1` | R1-train targets + noise vocabulary |
| `kb-v4` | All R1 publications masked |
| `kb-v3` | Held-out-masked KB for R1 evaluation |
| `genes-v1` | Gene profiles |
| `kb-v2` | **VOID** |

## Open items for Mateo
- None blocking.
- Optional: the GeneCards request (`docs/TODO.md`), and the remaining disk
  wins (BITACORA, disk cleanup).

## Next steps, in order
1. Register the training set (manifest + release) and run the contamination
   check: its signatures vs S3 and vs R1 (EVAL_PROTOCOL §9.7).
2. Front A training loop:
   - export-v2 dataloader → GinV3Extended;
   - two learning rates;
   - early stopping on sim-val;
   - curves (train, sim-val, R1-dev with and without inputs, S2);
   - manifests.
3. Pre-register and run **A-001** (fine-tune with positives only) → A-002
   (+negated) → A-003 (+covariates) → A-004 (all). Each at ≤ 8
   configurations, ≥ 3 seeds for the selected one.
4. Phase-4 gates, each with its own pre-registration:
   - rr-v1[neg=0.5] on S3-test + R1-test no-regression;
   - the best Front A candidate.
5. Optional: an S3 v2 split that also holds out onset and inheritance, to
   evaluate sex and age fairly.

## Invariants to keep in mind
- Never touch `GenPhenAI/`.
- Commit before any run that writes a manifest, and don't edit tracked files
  while a long run is going.
- Scripted shell blocks use `set -euo pipefail` on its own line. Never pipe
  a step's output through `grep` when the next step depends on its success.
- Sealed data (R1 test/vault, MCRD, DDD, S3-test) is read only under a
  committed pre-registration.
- No AI mention in commits or PRs.
