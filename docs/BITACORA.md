# Bitácora — Reentrenamiento de GenPhenAI (sexo, edad, síntomas negados)

A chronological log of everything done on the two fronts (see `PLAN.md`).
Each entry records what was tried, the numbers against E0, and whether it
worked. It is raw evidence for the informe; the team writes the informe prose.

Entry template:

```
### YYYY-MM-DD — <EXP-id or "sesión"> — <title>
- Front / versions: A|B / sim vX, ds-…, <repo@sha>
- Question:
- Setup: config hash, seed, hardware, wall time
- Result: (table vs E0: MRR, top-1/10, harmed %, 95% CI)
- Verdict: ✅ adopted / ❌ discarded / ⚠️ inconclusive — why
- Next:
- Evidence for the informe: (section → figure/table)
```

---

## Planned vs actual

| Item | Anteproyecto | Actual | Deviation / reason |
|---|---|---|---|
| Retraining framework | Keras 3 + JAX (GraPhens trainer) | PyTorch (ADR-0001, confirmed 2026-09-28) | The upstream Keras trainer only builds GCN v2.0. Production is PyTorch GIN v3.0, and warm-starting it requires PyTorch |
| Compute | Clementina XXI | Local RTX 4070 Ti (12 GB) | Clementina not used for now (decision 2026-09-28) |
| Validation scheme | Classic train/val/test partition; MCRD at the end | Publication-grouped R1 split into train/dev/test/vault, test and vault sealed; MCRD/DDD eval-only (ADR-0003) | 40 days of iteration on both fronts would overfit a single test set |
| Artifact versioning | Not specified | Manifests in git + GitHub release assets (ADR-0005) | The DVC remote was unmounted and the disk is nearly full |
| Retraining (Jun–Jul) | Retrain with new data | Not started as of 2026-09-28 | The simulator's MVP stopped at fixtures (last commit 2026-06-27) |
| Features (Aug–Sep) | Age, sex, location, absent symptoms | Age, sex and absent symptoms planned; location dropped | No data source links location to genes |
| Final benchmark | MCRD | MCRD (R2) plus phenopacket-store (R1) | MCRD has no sex, age or excluded features; R1 has all three |
| Approach | Retrain only | Two fronts: retrain (A) and re-ranker on top (B) | Reduces risk and gives an early deliverable |

---

## Baselines known before this work (not reproduced by us yet)

| Source | Model | Data | MRR | Top-1 | Top-10 |
|---|---|---|---|---|---|
| Checkpoint metadata (`GENPHENAI_RN_ARQUITECTURA_ENTRENAMIENTO.md:195-213`) | v3.0 | its simulated validation split | 0.781 | 0.711 | 0.911 |
| qa-agente-claude `docs/EVALUACION.md` | v3.0 | phenopacket-store 0.1.27, 501 patients | 0.508 | 0.431 | — |
| `GraPhens/validation_arena/validation_mcrd_new_training_dataset.csv` | unknown checkpoint (2025-06) | MCRD, 225 rows | 0.070 | 0.036 | 0.133 |
| `GraPhens/validation_arena/validation_bitgenia.csv` | unknown checkpoint | Bitgenia, 128 rankable rows | 0.128 | 0.055 | 0.320 |
| qa-agente-claude | v3.0 + Bayesian re-rank, symmetric | phenopacket-store | Δ −0.047 [−0.065; −0.029] | | |
| qa-agente-claude | v3.0 + asymmetric re-rank, k=0.3 | phenopacket-store held out | Δ −0.001 [−0.009; +0.007] | | |
| qa-agente-claude | v3.0 + one negated finding only | phenopacket-store | Δ −0.006 [−0.011; −0.001] | | |

What they tell us:

- There is a large gap between simulated and real performance.
- Nothing that re-weights by HPOA frequencies has improved results on real
  patients so far.
- No existing experiment uses sex or age.

---

## Log

### 2026-09-28 — sesión — Survey, guardrails and plan
- **Front / versions:** both. Upstream state is GraPhens@7d861ff and
  `diagnostic.ar-model` model-v3.0.0 (`654736f`). `rare-disease-simulator`
  is at `a40d414` (not pushed).
- **Done:**
  - Read the anteproyecto, the rúbrica, and every repo in the workspace plus
    the question agents.
  - Wrote `PLAN.md`.
  - Locked `GenPhenAI/` in all 5 repos (GraPhens, diagnostic.ar,
    diagnostic.ar-api, diagnosticar-GenPhenAI-repo, diagnosticar_tools):
    - push URLs set to `DISABLED--…`;
    - a `pre-push` hook that exits 1;
    - `.claude/settings.json` deny rules plus the PreToolUse hook
      `.claude/hooks/guard_genphenai.py` (14 hook test cases pass).
- **Findings:**
  - No real-case measurement of the production v3.0 is reproducible from
    our repos.
  - The upstream Keras trainer cannot build v3.0.
  - Dense NPZ datasets do not fit on disk (16 GB free).
  - The web collects sex and date of birth but never sends them.
  - Negated terms are dropped on the client and hard-coded `false` in the
    extractors.
- **Next:**
  - Mateo to answer the open decisions in `PLAN.md` §14.
  - Then Phase 0: harness plus EXP-000 (E0).
- **Evidence for the informe:**
  - §16: the risk "the upstream trainer does not support the production
    architecture".
  - §12: the planned-vs-actual table above.

### 2026-09-28 — sesión — Decisions, new repo, lineage and anti-overfitting groundwork
- **Front / versions:** shared. `diagnostic.ar-training` initial commit;
  `rare-disease-simulator@a40d414`, now pushed.
- **Decisions (Mateo):**
  - PyTorch (ADR-0001).
  - A new private repo `MateAlv/diagnostic.ar-training` (ADR-0002), holding
    the plan and the log.
  - 40 days, until 2026-11-07.
  - No Clementina for now.
  - Push the simulator's pending commit.
  - Strict anti-overfitting and pristine lineage.
- **Done:**
  - Created the repo. Moved `PLAN.md` and `BITACORA.md` here and revised the
    plan (phases with dates, lineage, protocol).
  - **Source registry.** `data/sources.yaml` has 9 sources, each with an
    immutable URL, sha256 and role (knowledge / cohort / eval / baseline):
    HPO v2026-02-16 ×4, Orphanet ages 2025-12-09, phenopacket-store 0.1.27,
    MCRD, DDD, and the genphenia-v3.0 bundle. All were verified from local
    copies.
  - **Lineage code**, with tests:
    - role enforcement (`eval` sources can't feed training, KBs or the
      simulator);
    - manifests that refuse a dirty tree and never overwrite;
    - the sealed-split ledger;
    - `dxt lineage verify`.
  - **Split `r1-v1`**, frozen before any model output on the cohort was seen:

    | Part | Patients | Publications | Genes |
    |---|---|---|---|
    | train | 4,103 | 706 | 409 |
    | dev | 1,883 | 324 | 235 |
    | test (sealed) | 2,548 | 350 | 242 |
    | vault (sealed, opens once) | 1,771 | 352 | 241 |

    - Content sha256 `b007aa17741c2309a2fce9e36aaa77608d3d2b1311630e96c77be9d39e462ccf`.
    - Dropped 69 multi-gene and 3 empty packets.
  - **Held-out PMID list** (1,026 PMIDs, sha256 `3d99720c…`) exported for the
    simulator and KBs.
  - **Harness groundwork:**
    - metrics: pessimistic ranks, top-k, MRR;
    - paired bootstrap;
    - harmed/helped rates;
    - contamination checks.
  - `EVAL_PROTOCOL.md`, `DATA_LINEAGE.md`, 5 ADRs, the experiment template,
    CI (ruff + pytest), and 39 passing tests.
  - **Workspace guard hook hardened** after two false positives: the bare
    word "GenPhenAI" in a message was read as a path, and heredoc bodies were
    parsed as commands. It now has 26 test cases.
- **Findings:**

  | Check | Result | Consequence |
  |---|---|---|
  | HPOA rows citing R1 held-out publications | 15,412 of 282,723 (5.45%), across 457 diseases | They must be masked from the KB and the simulator |
  | R1-train PMIDs cited by HPOA | 10,995 rows | Allowed |
  | MCRD vs R1 | 0 exact (gene, present) overlaps; 44 genes shared | — |
  | DDD vs R1 | 0 exact overlaps; 140 genes shared | — |
- **Follow-ups the same day:**
  - Published the `data-snapshot-2026-09-28` release with the Orphanet ages
    file.
  - Checked that fetching from URL works for both the private release (via
    `gh`) and the raw GitHub URL (MCRD). Both were sha256-verified.
  - **GitHub Actions did not run.** The job was refused because of account
    billing / spending limit; it was not a code failure. Mitigation:
    `scripts/hooks/pre-push` runs `make check` (lint, tests, lineage verify)
    before every push, installed by `make setup` / `make hooks`. CI will
    resume if billing is fixed.
- **Verdict:** ✅ the foundation is in place. Every future number can be
  traced to pinned bytes, a SHA and params.
- **Next (Phase 0 remainder):**
  1. Add the v3.0 ONNX adapter to the harness (`rank(case)`) and measure
     latency and unknown-term rates.
  2. Pre-register `EXP-000` and run E0 on R1-dev and S2, then its sealed reads.
  3. Publish the `data-snapshot-2026-09-28` release (Orphanet ages) and check
     that URL-based fetches work.
  4. Start Phase 1A (simulator HPOA backbone) and Phase 1B (re-ranker KB) in
     parallel.
- **Evidence for the informe:**
  - §12 / §14: the validation scheme (ADR-0003) and the split stats table.
  - §16: the risk "leakage between HPO annotations and the evaluation
    cohort", with the measured 5.45%.
  - §13: the choice of artifact storage (ADR-0005).
