# Current state (handoff snapshot)

The fastest way back into the work after an interruption. It is overwritten
at each checkpoint; the history lives in `BITACORA.md`.

**Snapshot:** 2026-09-29, taken before a disk-cleanup detour (disk at 99%,
4.3 GB free).

## Where each front stands

| Front | Status | Last evidence |
|---|---|---|
| Shared | E0 measured on every cohort (EXP-000). R1 CIs resample publications | `docs/experiments/EXP-000.md` |
| B (re-ranker) | rr-v1 (EXP-B-001): null. rr-v2 learned on R1-train (EXP-B-002): dev +0.056 but **no candidate** (harmed 10%), and the whole gain is R1's negation reporting pattern, not deployable. Sex, age and onset add ≤ 0.002 | `EXP-B-001.md`, `EXP-B-002.md` |
| A (retrain) | GinV3 = v3.0 in PyTorch; ranks identical, absolute logit gate missed from float32 rounding (EXP-A-000 ⚠️). Zero-init extension ready (ADR-0009, Proposed). **No training run yet** | `EXP-A-000.md`, ADR-0009 |
| A (simulator) | v0.2 merged. Gene-first sampling + export v2 + calibration hook + `true_present` + `--drop-annotations`: **a subagent is working on it** (simulator branch `feat/gene-first-export-v2`) | simulator repo PRs |
| S3 (simulated question-agent evaluation) | Design in EVAL_PROTOCOL §8. `annot-split-v1` (30% held out) and `kb-v5` (half A) built. Questioner and answerer coded and tested. **Waiting on the simulator's export v2** to generate S3 cases | branch `phase1c/s3-eval` (pushed; no PR yet) |

## Artifacts, newest first

| Artifact | What it is |
|---|---|
| `kb-v5` | KB without half B of `annot-split-v1`, held-out R1 masked (for S3 systems and the questioner) |
| `annot-split-v1` | 78,917 held-out (disease, term) pairs |
| `calib-v1` | R1-train targets: present 8.7, negated 11.0, unexplained 3.7 per case; noise vocabulary of 1,254 terms |
| `kb-v4` | All R1 publications masked (for anything fitted on R1-train) |
| `kb-v3` | ADR-0007 frequencies + genes-v1 weights (held-out masked) |
| `kb-v2` | **VOID**, never use |
| `genes-v1` | Gene profiles (ADR-0008) |
| `kb-v1` | First KB |

Everything is listed in `data/manifests/`; `dxt artifacts fetch <id>`
restores any published artifact.

## Open decisions for Mateo
1. Accept GinV3 as v3.0 despite the missed absolute logit gate, and switch
   future parity gates to "relative ≤ 1e-5 + identical ranks" (EXP-A-000).
2. Approve ADR-0009 (Proposed).
3. Disk space: about 10 GB more needed for datasets and checkpoints.
4. Optional: the GeneCards permission request (`docs/TODO.md`).

## Next steps, in order
1. The simulator agent reports → review → merge its PR.
2. Adjust the simulator knobs for S3 and training from `calib-v1`: the noise
   count, jointly with the 30% holdout, so the unexplained share ≈ 46%;
   negative count and source mix (own ≈ 43%); missingness.
3. Generate S3 (full profiles, disjoint seeds), freeze its dev/test split,
   pre-register EXP-S3-000 (E0 with and without questions; rr variants),
   run it on S3-dev.
4. Front A training data: profiles without half B, disjoint seeds,
   `calib-v1` → `ds-sim…` + manifest.
5. Front A ladder A-001… (fine-tune GinV3), evaluated on R1-dev and S3-dev.

## Invariants to keep in mind
- Never touch `GenPhenAI/`. The guard hook enforces it.
- Commit before any run that writes a manifest, and don't edit tracked files
  while a long run is going.
- Sealed data (R1 test/vault, MCRD, DDD, S3-test) is only read under a
  committed pre-registration.
- No AI mention in commits or PRs.
