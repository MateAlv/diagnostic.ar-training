# Current state (handoff snapshot)

The fastest way back into the work after an interruption. It is overwritten
at each checkpoint; the history lives in `BITACORA.md`.

**Snapshot:** 2026-10-01, paused (graceful stop, usage). Previously 2026-09-30, end of day: Stopped cleanly for the night:
- no agents running, no background jobs;
- every PR from today merged except diagnostic.ar-model PR #2, which waits
  for Mateo.

**Deadline:** 2026-11-07 (38 days left).

## TL;DR (2026-10-01, paused at about 81% session usage)
**R1-dev realism reads: 2 of 3 used.** The last read waits for a candidate
that passes every train-side stop condition, and Mateo is told first.

**Simulator** (rare-disease-simulator main 6833d2d = 0.5.3):

| Candidate | Passes | Fails |
|---|---|---|
| 5 | G2e gap 0.049 | G2c 1.908, G2d 0.809 |
| 6a | G2e gap 0.011 | G2c 2.955 (records too short), G2d 0.764 |

- **Candidate 6b** (0.5.3 record budget + generalisation pilot; PR #71,
  open) **finished**:
  - **passes** G2a 0.304, **G2d 0.721** (the first G2d pass), G2e gap 0.077
    and G2b-train 0.522;
  - **fails only G2c**, 1.816 vs the 1.653 needed. Records average 6.88
    terms vs 8.70, because truth can't fill the budget for sparse profiles.
  - No R1-dev read.
  - Candidate 6 (the same design on the literature-enriched profiles)
    could close G2c, since richer profiles give more true terms.

**Literature (ADR-0013 and amendments 1–2):**
- Merged: 53 shard files, 3108 rows. That covers all P1/P2 chapters
  (C001–C035), C063–C070, P001 and Q001, plus Q019–Q026.
- **Open PRs waiting to merge** (resolve BITACORA by keeping both sides;
  check that only shard files changed):
  - #71: candidate 6b;
  - #72: Q002–Q005, 213 rows; next shard Q006;
  - #73: C045–C051, 592 rows; next shard C052.
- Stopped gracefully mid-batch (each agent commits per shard; resume via
  their branches or PRs). At writing, Q011–Q018, C036–C044 and C054–C062
  had not yet reported where they stopped.

  | Batch | Branch |
  |---|---|
  | Q002–Q010 | `phase3/lit-extract-Q002-Q010` |
  | Q011–Q018 | `phase3/lit-extract-Q011-Q018` |
  | C036–C044 | `phase3/lit-extract-C036-C044` |
  | C045–C053 | `phase3/lit-extract-C045-C053` |
  | C054–C062 | `phase3/lit-extract-C054-C062` |

- **Integration tooling** (`dxt lit build`): PR #67, **merged** with
  amendment 3. It is being
  updated with my rule-6 ruling as ADR-0013 amendment 3:
  - prefer both sexes, then the largest n;
  - drop a term if same-source percentages differ by more than 0.20 with
    no n to decide.

  The dry run on 37 shards gave 2,892 HPOA rows over 434 diseases, 1,847
  new disease–term pairs, and **presentation ages for only 30 diseases**.

**Pending rulings, to decide in one batch:**
- **"has not been reported/described"**: do **not** treat it as an
  explicit absence, so it never becomes a NOT row.
- **Age at genetic confirmation**: exclude it from presentation ages.
- **Family-cohort carriers** (some unaffected): need a rule.
- **High VUS share**: need a rule.
- **`pooled_group` with sub-20 member units**: need a rule.
- **Spectrum chapters with a single unit**, and **two genes on one disease
  id**: fine as `pooled`.
- **Proposal for Mateo:** use the literature `AGE_ONSET` rows (about 200
  diseases) to improve onset, because presentation ages cover only about 30
  diseases.

**Next steps, in order, economising usage:**
1. Collect the stopped agents' final states. Merge their PRs (resolve the
   BITACORA conflicts by keeping both sides; check that only shard files
   changed).
2. Finish the remaining shards later, in smaller batches.
3. Merge PR #67 after amendment 3. Write the pending rulings as amendment 4,
   then run the final `dxt lit build --version 1 --publish`.
4. Codex cross-check (10%) plus a recall and unit audit (about 5% of
   sources).
5. Candidate 6b result → candidate 6 (enriched profiles + 0.5.3 design) →
   train-side go/no-go. Then **ask Mateo** before the last R1-dev read.
6. If it passes: the G3 cards (assistant + Codex), then G5 freeze. Only
   then can Front A retraining be pre-registered.

## Decisions still open
- **Deploying rr-v1** (on hold): when the time comes, merge PR #2 and
  create the release. Production routes to brainy, not the pinned image.
- **"Con tus respuestas"** showing the re-ranked list: a product call.
- **The GeneReviews email:** Mateo is sending it; not blocking.

## Where each front stands
| Front | Status | Evidence |
|---|---|---|
| Shared | E0 measured on every cohort; R1 CIs resample publications | `EXP-000.md` |
| B on R1 | rr-v1 null on R1-dev. rr-v2 (learned on R1-train) gains on dev, but only through R1's negation reporting pattern | `EXP-B-001.md`, `EXP-B-002.md` |
| **B on S3, sealed** | **rr-v1[neg=0.5] passed (EXP-B-003):** S3-test +0.0044 [+0.0032, +0.0057], harmed 3.9%; R1-test −0.0025 [−0.0070, +0.0013], exactly 0 without negations. Production package: diagnostic.ar-model PR #2 (parity 0 mismatches over 1,680 dev cases; p95 +6.8 ms) | `EXP-S3-001.md`, `EXP-B-003.md` |
| A (retraining) | A-001, A-002f and A-003f all failed on real patients using simulator v0.3 data. **Retraining is blocked** until the ADR-0012 data gate passes | `EXP-A-00*.md` |

## Simulator data-quality gate (ADR-0012), history
**Gate:**
- G1: integrity.
- G2: beat UP (GraPhens' simulator) and V03 (our v0.3, full profiles) on
  - a: literature panel, truth layer;
  - b: R1-dev per-gene ρ;
  - c: terms per case, W1;
  - d: C2ST AUC ≤ 0.75;
  - e: E0 difficulty gap to 0.405 ≤ 0.10.
- G3: 30 disease cards, reviewed by the assistant and Codex; Mateo
  spot-checks.
- G4: literature panel (done).
- G5: freeze.

**Amendments:** 1 (accepted), 2 (G3 reviewers), 3 (G2a truth layer; needs
Mateo's OK).

| Candidate | Simulator / calibration | G1 | a | b (dev) | c | d | e gap | Outcome |
|---|---|---|---|---|---|---|---|---|
| UP (baseline) | GraPhens | — | 0.416 | 0.231 | 3.717 | 0.840 | 0.414 | — |
| V03-full (baseline) | v0.3 | — | 0.336 | 0.095 | 1.653 | 0.819 | 0.183 | — |
| 1 | 0.4.1 / simcal-v04-v3 | pass | 0.339 | 0.152 | 1.214 | 0.737 | 0.313 | read 1; fail |
| 2 | 0.4.2 / simcal-v04-v4 | pass | 0.304 | 0.193 | 1.315 | 0.792 | 0.242 | read 2; fail |
| 3 | 0.4.2 / simcal-v04-v5 (calib-v2) | pass | 0.305 | not read (train 0.536) | 1.732 | 0.764 | 0.142 | stopped before read 3 |
| 4 | 0.5.0 / simcal-v05-v2 | pass | 0.307 | not read (train 0.502) | 5.754 | 0.822 | 0.204 | stopped before read 3 |
| 5 | 0.5.1 / simcal-v051-v1 | pass | 0.306 | not read (train 0.537) | 1.908 | 0.809 | 0.049 | train-side only; fails c, d |
| 6a | 0.5.2 / simcal-v052-v1 (budget-normalised) | pass | 0.306 | not read (train 0.507) | 2.955 | 0.764 | 0.011 | train-side only; fails c, d |

Candidate 1's a and e are recomputed on today's definitions (truth layer;
target 0.405).

**What we learned** (all R1-train only):
- **ANALYSIS-002:** real noise is structured. Also, E0 scores 0.562 on
  patients whose paper HPOA cites and 0.405 on uncited ones, which led to
  the G2e target of 0.405.
- **ANALYSIS-003:**
  - noise causes E0's difficulty;
  - the kb-v4 reference inflated "unexplained" (the right reference is
    uncited patients vs kb-v3, giving about 24% noise);
  - G2a should score the truth layer (real patients' own reports miss the
    literature by 0.307).
- **ANALYSIS-004:**
  - real unexplained terms carry gene signal (E0 MRR 0.059), while
    simulated vocabulary noise carries none (0.001);
  - 13.5% of real unexplained terms are annotated to the gene in unmasked
    g2p;
  - construction-side audit (Codex, 26 genes outside the panel): **25 of 26
    implausible**. The top problems are unrelated noise (14), hallmark
    features under-reported (14) and missing features in the truth
    layer (11).
- **Candidate 4:** independent reporting with q = π/f reports only 17–19%
  of true terms (2.95 terms per case; 32% forced_min_one). Age calibration
  barely moved medians (COL3A1 4.6 vs 32 years real; TBX5 2.4 vs 33), so
  the problem is the onset categories, not the durations.
- **SOURCES-SCOPING-001:**
  - GeneReviews has a usable chapter for 1,289 construction genes (25%);
  - an estimated 35% of genes have at least one OA cohort series;
  - 2,571 of 4,776 simulable construction genes have weak profiles;
  - literature should also be used to *check* existing profiles (22 of the
    26 audit genes were count-rich yet implausible).

## Front B release: what exists
- **diagnostic.ar-model worktree** at
  `/home/mate/FIUBA/trabajo-profesional/diagnostic.ar-model-rerank-v1.0.0`,
  branch `release/rerank-v1.0.0`.
  - The tarball `dist/rerank-v1.0.tar.gz` (sha `4b83f5e3…`) is not yet a
    GitHub release.
  - The KB is kb-v3 (sha `39d5f921…`).
- **App integration list:** `docs/integracion-app-rerank-v1.md` in that PR.
  The API needs to accept `excluded_hpo_ids`, and the question agent needs
  to send its "no" answers.
- **The main diagnostic.ar-model checkout has changes that are not ours**
  (`.dvc/config` modified; untracked `dist/`, `models/`, `.claude/`). They
  were left untouched.

## Artifacts, newest first (see `data/manifests/`)
| Artifact | What it is |
|---|---|
| `ds-sim0.5.0-{full,A}-n100-s1001` (+`-excl-v1`) | Candidate 4 datasets (gate unmet) |
| `simcal-v05-v1/v2`, `report-model-v3` | Candidate 4 calibration; report model fit on uncited patients vs kb-v3 |
| `ds-sim0.4.2c3-{full,A}-n100-s1001` (+excl) | Candidate 3 datasets (closest; gate unmet) |
| `calib-v2`, `simcal-v04-v5` | Uncited-vs-kb-v3 targets and noise vocabulary (295 terms); candidate 3 calibration |
| `ds-sim0.4.2-{full,A}-n100-s1001`, `simcal-v04-v4` | Candidate 2 |
| `ds-sim0.4.1-A-n100-s1001`, `simcal-v04-v3` | Candidate 1 |
| `ds-sim0.3.1-full-n100-s1001` | V03-full baseline |
| `literature-panel-v2`, `litpanel-split-v1..v3` | G4 evaluation panel (56 diseases, 531 rows). **The 120 split units are evaluation-only** |
| `hpoa-recount-v1`, `genes-v2`, `report-model-v2`, `cardinal-v1`, `simcal-v04-v2` | Simulator v0.4 inputs |
| `ds-sim0.3.1-A-*`, `s3-data-v1` + `s3-v1`, `kb-v5`, `annot-split-v1`, `calib-v1`, `kb-v4`, `kb-v3`, `genes-v1` | Earlier; kb-v2 is VOID |

## Repos, outputs, disk
- **diagnostic.ar-training** main is at `fe81790` (PRs #1–#47 merged).
  Agent worktrees of merged branches remain under `.claude/worktrees/`;
  they are safe to remove.
- **rare-disease-simulator** main is at `020e41d` (0.5.0; PRs #1–#8
  merged). Not tagged: nothing is frozen.
- **Simulator outputs.** Candidate 4's rich-cases files (about 3 GB each)
  are in `rare-disease-simulator/outputs/v0.5.0-cand4-{full,A}`. Their
  exports are registered, so the rich files can go if disk is needed.
- **Disk: only about 11 GB free on `/` (96%).** Free space before the next
  big run.

## Tooling added today
| Tool | What it does |
|---|---|
| `dxt sim realism [--no-dev]`, `dxt sim gate [--secondary]`, `dxt sim panel-error`, `dxt sim train-checks` | Gate metrics; every R1-dev read is ledgered in `results/realism/LEDGER.md` |
| `dxt calib build --population uncited`, `dxt calib age-durations`, `dxt knowledge report-model --population uncited`, `dxt knowledge shrinkage-prior --min-denominator/--base/--set/--include` | Calibration builders |
| `dxt rerank eval`, `dxt s3 run --system` | Fixed-configuration and sealed-aware evaluation |
| `scripts/realism_cards.py [--construction N]`, `scripts/g3/review_codex.sh` | G3 cards; Codex reviewer B (prompt and schema in `scripts/g3/`) |
| `scripts/analysis/*.py` | ANALYSIS-002..004 and SOURCES-SCOPING-001 scripts |

## Invariants to keep in mind
- Never touch `GenPhenAI/`.
- Commit before any run that writes a manifest, and don't edit tracked files
  while a long run is going.
- Scripted shell blocks use `set -euo pipefail` on their own line. In this
  Bash environment `set -e` has been seen not to stop a chain, so chain
  critical steps with `&&` and check exit codes.
- Never pipe a step through `grep` when a later step depends on it. Never
  write numbers before reading them.
- **Never update a shared checkout** (e.g. rare-disease-simulator main)
  while an agent is generating from it. Runs use a pinned worktree or
  tarball.
- `pkill -f` can match your own shell. Kill by exact PID.
- Worktree agents push with `PYTHONPATH=<worktree>/src`.
- Sealed data is read only under a committed pre-registration. The R1-dev
  realism budget is 3 candidate reads; 2 are used.
- **Train-side go/no-go before any R1-dev realism read:** G2a, c, d, e and
  G2b-train.
- No AI mention in commits or PRs.
- **Usage limits stop every agent.** Keep agent worktrees until their PR is merged *and* they won't be resumed. Agents commit after each unit of work; resume them with SendMessage.
- **Graceful stop:** message the agents, then stop queue scripts before
  their runs (by exact PID). Interrupted runs must leave no manifest.
