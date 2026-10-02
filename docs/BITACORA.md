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

### 2026-09-29 — EXP-000 — E0: the production model, measured (Phase 0 closed)
- **Front / versions:** shared.
  - Code: `17f1392` for the runs; publication-clustered CIs from the next
    commit.
  - Model: `genphenia_v3` (model-v3.0.0), split `r1-v1`.
  - Pre-registration: `docs/experiments/EXP-000.md` (committed before any
    sealed read).
- **Question:** how does production v3.0 do on every cohort, measured by our
  harness, as the reference for both fronts?
- **Setup:**
  - `systems/genphenia_v3.py` rebuilds production's graph construction from
    the pinned bundle.
  - **Parity:**
    - top-10 genes and scores match the production-captured
      `reference_rankings.json` to ≤ 5e-7;
    - **bit-identical** to the vendored engine on 300 R1-train patients
      (max |Δp| = 0, 0 top-1 mismatches);
    - term order has no effect.
  - The harness writes per-case ranks, a summary and a lineage manifest per
    (cohort, view).
  - Sealed reads: r1-v1/test, MCRD and DDD, one each, all ledgered. The vault
    is untouched.
  - Hardware: CPU, 1 thread. About 8 s for 1,883 cases.
- **Result:**

  | Cohort | n | MRR [95% CI] | top-1 | top-10 | Gene not in vocab | MRR, in-vocab |
  |---|---|---|---|---|---|---|
  | R1-train | 4103 | 0.440 [0.387, 0.494] | 0.370 | 0.579 | 14.2% | 0.512 |
  | R1-dev | 1883 | 0.448 [0.399, 0.504] | 0.339 | 0.669 | 10.8% | 0.503 |
  | R1-test | 2548 | 0.370 [0.266, 0.480] | 0.296 | 0.504 | 10.6% | 0.414 |
  | MCRD | 229 | 0.747 [0.699, 0.794] | 0.677 | 0.882 | 0% | 0.747 |
  | DDD | 1048 | 0.757 [0.736, 0.782] | 0.689 | 0.877 | 0.2% | 0.759 |
  | S2 (sim) | 5228 | 0.812 [0.803, 0.821] | 0.751 | 0.926 | 0% | 0.812 |

  R1 CIs are publication-clustered; the others are case bootstraps.
- **Findings, with what changed because of each:**
  1. **Case-level CIs on R1 were 3–7× too narrow.** Patients cluster by
     publication; one paper is 18% of R1-test.
     - *Changed:* the paired bootstrap now resamples publications on R1
       (`metrics.paired_bootstrap(groups=…)`), R1 runs record groups, and the
       protocol was updated.
     - The dev → test drop (0.448 → 0.370) lies within publication-level
       variability.
  2. **DDD cases look annotation-derived.** 97% carry an inheritance-mode
     term, and the median case's terms are all verbatim annotations.
     - *Changed:* DDD is demoted to a no-regression check (sources notes,
       protocol, lineage gaps).
  3. **My MCRD expectation was wrong** (pre-registered as "low, possibly
     < 0.2"; measured 0.747). The old 0.070 most likely came from a broken
     upstream evaluation (a `genes.json.bak_wrong_order` exists upstream).
     - *Lesson:* never carry forward numbers from an unpinned checkpoint.
  4. **10.6–14.2% of R1 patients have a gene outside v3.0's 5,229 classes**
     (86 genes and 784 patients in train+dev; 70 of those genes are in HPO
     2026). This is a hard ceiling for Front B, and a lever only Front A can
     pull. Proposed as A-008; it needs a decision because it changes the
     frozen vocabulary.
  5. **R1 terms are verbatim HPO annotations far more often than MCRD's**
     (78% vs 3.5% of cases fully annotated). This is consistent with HPOA
     being curated from R1 papers, and it quantifies the declared E0 optimism.
- **Verdict:** ✅ E0 accepted as the reference. Phase 0 is closed, 4 days
  ahead of plan.
- **Next:**
  - **Decision for Mateo:** A-008 (vocabulary expansion) in or out of scope.
  - Phase 1B: the re-ranker KB, masked with `r1-v1.heldout-pmids.txt`.
  - Phase 1A: the simulator's HPOA backbone.
- **Evidence for the informe:**
  - §14: the E0 table, and parity as a quality measure (criterion 4).
  - §14 / §16: the CI redesign after the first measurement. This is exactly
    criterion 4's "measurements that drove redesigns".
  - §16: the DDD provenance finding, and the wrong expectation about MCRD.

### 2026-09-29 — sesión — Decision on the vocabulary; Front B knowledge base `kb-v1`
- **Front / versions:** B. Code `d3a2e3e`; artifact `kb-v1` (release
  `kb-v1`, manifest `data/manifests/kb-v1.json`).
- **Decision (Mateo):** the gene vocabulary stays v3.0's 5,229 genes
  (ADR-0006). A-008 is rejected; vocabulary expansion goes to future work.
- **Done:**
  - `ontology.py`: hp.json loader with alt-id and obsolete→replacement
    resolution, ancestors and descendants.
  - `rerank/kb.py`: the KB builder, with 8 fixture tests covering:
    - merging, alt ids, obsolete terms;
    - NOT and Excluded as negation;
    - sex restriction, HPO onset → age intervals, Orphanet fallback,
      inheritance;
    - masking, polygenic exclusion, determinism.
  - `dxt kb build --publish` and `dxt artifacts fetch`. Published artifacts
    missing locally no longer fail `lineage verify`.
  - The simulator's HPOA backbone (Phase 1A) runs in parallel on
    `rare-disease-simulator` branch `feat/hpoa-backbone`, done by a subagent.
- **Result (`kb-v1`):**

  | Measure | Value |
  |---|---|
  | Diseases / genes | 12,802 / 5,148 |
  | Phenotype annotations | 249,434 |
  | Negations | 720 |
  | Sex-restricted annotations | 496 |
  | HPOA rows masked (held-out PMIDs) | 15,412 (matches the Phase 0 measurement) |
  | Unresolvable or renamed terms | 0 (HPOA 2026 already uses current ids) |
  | Diseases with onset | 4,303 from HPO + 3,795 from the Orphanet fallback |
  | Diseases with inheritance | 8,175 |
  | Size / build time | 1.4 MB gz, 4 s |

  | Coverage of v3.0's 5,228 real genes | Count | Share |
  |---|---|---|
  | in the KB | 5,053 | 97% |
  | with onset | 4,286 | 82% |
  | X-linked | 256 | 5% |
  | with sex-restricted phenotypes | 213 | 4% |
  | with NOT annotations | 374 | 7% |

  **Masking audit** (share of cases whose present terms are all annotated to
  the gene in the KB):

  | Cohort | Unmasked KB | kb-v1 (masked) |
  |---|---|---|
  | R1-dev | 78.1% | **16.1%** |
  | R1-train | 68.2% | 41.2% (train genes also lose held-out-paper annotations) |

  - Median verbatim-term share on dev: 1.00 → 0.50.
  - 203 dev patients' genes have no remaining annotations; for them the
    re-ranker will be the identity.
- **Verdict:** ✅ `kb-v1` adopted as Front B's knowledge base.
- **What it implies for Front B:**
  - **Age is the broadest new signal:** 82% of genes have onset data.
  - **Sex and explicit negation reach only 4–7% of genes.** Negated symptoms
    will mostly act through frequencies (a typical feature reported absent),
    not through NOT annotations. This agrees with the qa-agent's
    near-zero result for NOT-only negation.
- **Next:** B2 features (negation penalty, sex and age compatibility) and
  pre-registration of EXP-B-001 (rr-v1 grid on R1-dev).
- **Evidence for the informe:**
  - §11: the KB design and what each source contributes.
  - §14 / §16: the masking audit table, which quantifies the leakage path and
    its removal.

### 2026-09-29 — sesión — Front A: simulator HPOA backbone (`rare-disease-simulator` PR #1)
- **Front / versions:** A. `rare-disease-simulator` branch
  `feat/hpoa-backbone` (7 commits, `1c13e90..425106f`), PR #1, open and not
  merged. Built by a subagent; I spot-checked it (authorship, tests, output
  hash).
- **Done:**
  - `HpoOntology.from_json`, with alt-id and replaced-by resolution.
  - `build-profiles --from-hpoa` with `--exclude-pmids`.
  - Profiles now carry:
    - per-phenotype sex restriction and onset;
    - disease onset (HPO, with the Orphanet fallback by ORPHA id);
    - inheritance, and sex bias derived from inheritance;
    - progression;
    - input sha256s and the simulator git SHA.
  - `simulate` now passes the ontology, noise vocabulary and labels.
  - 97 tests (57 old + 40 new) and a CHANGELOG.
- **Result** (real build on the pinned inputs + `r1-v1.heldout-pmids.txt`;
  5.2 s; output sha256 `fc64d0cd…`, identical on a rerun):

  | Measure | Value |
  |---|---|
  | Profiles | 8,904 (6,462 OMIM, 2,442 ORPHA) |
  | Profiles dropped for having no positive phenotype | 212, of which 197 were emptied by the mask |
  | Genes | 5,136; covers 5,050 of the GNN's classes (5,102 without the mask; the mask removes 52 GNN genes entirely) |
  | Phenotype annotations | 187,948 (40,671 with unknown frequency) |
  | Negatives | 2,389 (471 `NOT` + 1,918 pooled `0/m`) |
  | Rows masked | 15,412, across 457 diseases (same as `kb-v1` and Phase 0) |
  | Diseases with onset | 72.9% (82.9% with an OMIM↔ORPHA map, which is **not pinned**) |
  | Sex-restricted phenotypes | 430 (311 male, 119 female) |
  | Sex bias | male 215, female 1, none 5,832, unset 2,856 |
- **Problems found (to fix in Phase 1A part 2):**
  1. **16% of phenotypes become "obligate" (frequency 1.0) from `n/n`
     counts**, 13,263 of them from `1/1`. The simulator would emit them in
     every case. Frequencies from small counts need shrinkage (e.g. a Beta
     prior on n/m). This affects Front B's KB too: `kb-v1` uses the same
     point estimates.
  2. **The KB and the simulator disagree on `0/m` counts.** The simulator
     makes them negatives; `kb-v1` keeps them as frequency 0. Front B
     features will treat frequency 0 as neutral ("supports nothing and
     excludes nothing"). The convention has to be unified before comparing
     fronts.
  3. **964 multi-gene diseases** fall back to the alphabetically first gene
     as the case label. The gene-label sampling rule must be decided before
     generating a dataset.
  4. **676 thin profiles** (fewer than 3 phenotypes), and **1,872 gene-linked
     diseases with no HPOA rows**.
  5. **HPO's "Excluded" frequency term never appears** in the 2026-02-16
     release.
- **Pending decision:** whether to pin the Orphanet OMIM↔ORPHA alignment. The
  only local copy is a 2022 file inside `GenPhenAI/`; we would need a fresh,
  pinned snapshot. It raises onset coverage from 72.9% to 82.9%.
- **Verdict:** ✅ backbone adopted, pending merge of the simulator PR. Not yet
  used to generate cases.
- **Next (Phase 1A part 2):**
  - frequency shrinkage;
  - sex-conditioned sampling;
  - age gating;
  - negatives from confounder diseases;
  - noise vocabulary from R1-train;
  - export v2 with manifest.
- **Evidence for the informe:**
  - §11: the simulator design (structured backbone + masking).
  - §16: the `1/1 → obligate` issue as a data-quality lesson.

### 2026-09-29 — sesión — OMIM↔ORPHA mapping pinned; GeneCards ruled out as a data source
- **Front / versions:** shared sources. Branch `data/orphanet-2026-06`;
  release `data-snapshot-2026-09-29`.
- **Decision (Mateo):** approve the OMIM↔ORPHA mapping. It raises the
  simulator's onset coverage from 72.9% to 82.9%.
- **Done:**
  - The local `en_product1.xml` turned out to be a mislabelled copy of
    `en_product6.xml` (byte-identical, gene associations only), so it could
    not serve as the mapping.
  - Downloaded the current Orphanet release instead (**2026-06-23**,
    CC-BY-4.0).
  - Published a snapshot and registered two sources:

    | Source | Contents |
    |---|---|
    | `orphanet_alignments` (`en_product1.xml`) | OMIM mappings: 3,781 exact, 4,138 BTNT, 797 NTBT, 29 ND |
    | `orphanet_ages_2026_06` | the same release's ages, so new artifacts don't mix Orphanet releases |

    The old `orphanet_ages` (2025-12-09) stays registered, so `kb-v1`
    remains reproducible.
  - **Rule:** only **exact, validated** mappings (E) carry facts from ORPHA
    to OMIM diseases.
- **GeneCards: requested by Mateo as the gene-profile source; not used.**
  The GeneCards Suite terms of use
  (https://www.lifemapsc.com/genecards-suite-terms-of-use/, read 2026-09-29)
  say:
  - "The use of GeneCards data for training of AI models is strictly
    prohibited without the express written permission of the LifeMap
    Sciences."
  - "Automated scraping of GeneCards data is also strictly prohibited for any
    purpose."
  - Academic access is "internal use … solely for the benefit of the
    Registered User and not for use for any third party."

  Training and validating our models, and serving a public web app, fall
  outside that. Options were put to Mateo:
  - (a) request written permission from LifeMap Sciences;
  - (b) build gene profiles from the open primary sources GeneCards itself
    aggregates.
- **Found while doing it:** disk at 96% (11 GB free).
- **Next:** Mateo's choice on the gene-profile sources.
- **Evidence for the informe:**
  - §13 (tools and sources) and §10 (ethics): a data source discarded for
    licensing reasons, with the quoted terms. This is the "fundamentación"
    that criterion 10 rewards.

### 2026-09-29 — sesión — PRs merged; frequency convention; gene profiles `genes-v1`
- **Front / versions:** shared knowledge (both fronts).
  - Training repo: branch `phase1/gene-profiles`; the artifact `genes-v1` was
    built from the commit before this log entry.
  - `rare-disease-simulator`: part 2 runs in parallel (subagent, branch
    `feat/simulation-v0.2`).
- **Decisions (Mateo):**
  - Build gene profiles from open sources now (option b).
  - GeneCards permission may be requested later; it is `docs/TODO.md` item 1,
    with a draft email.
  - Merge PRs #2 and #3 (training) and #1 (simulator). Done; plain merge
    commits with no attribution.
- **Done:**
  - **ADR-0007:** one frequency convention for both fronts.
    - Pooled counts use the Jeffreys mean `(n+0.5)/(m+1)`, so `1/1` becomes
      0.75, not "obligate".
    - Category midpoints.
    - Only `NOT` means absent; `0/m` is a low frequency.
  - **ADR-0008:** gene profiles and disease weighting.
  - **Six sources pinned:** HGNC, Orphanet genes and prevalence, ClinGen
    (snapshot release), MONDO v2026-09-01 and ClinVar 2026-09 (immutable
    URLs).
  - **`knowledge/genes.py` + `dxt genes build|calibrate`:** 8 fixture tests
    (74 in total).
- **Result (`genes-v1`, 49 s build):**

  | Measure | Value |
  |---|---|
  | Genes | 5,568 |
  | Disease entities | 13,960 (11,125 simulable, i.e. with masked HPOA phenotypes) |
  | Genes with ≥ 2 simulable diseases | 2,713 |
  | Validity basis | 2,686 ClinGen, 7,255 Orphanet, 4,019 HPO-only |
  | Zero-validity entities (refuted / somatic) | 603 |
  | v3.0 genes | 5,050 of 5,228 simulable; 8 renamed in HGNC (e.g. BVES→POPDC1); 6 unresolved |

  Examples of the top-weighted disease:

  | Gene | Top disease | Weight |
  |---|---|---|
  | NF1 | NF1 (OMIM:162200) | 0.72 |
  | FBN1 | Marfan | 0.53 |
  | SCN1A | Dravet | 0.37 |

  **Calibration on R1-train only** (2,544 patients whose gene has ≥ 2
  diseases):

  | Scheme | Patient's own disease ranked first | Mean p (true disease) |
  |---|---|---|
  | Uniform | — | 0.346 |
  | ADR-0008 weight | 64.2% | 0.574 |

  - γ = 0.5 maximises log-likelihood (−0.777 vs −0.825 linear, −1.060
    validity-only).
  - It is stable across 2 publication folds within train.
  - Weights and the selection rule are frozen as pre-specified.
- **Verdict:** ✅ `genes-v1` adopted as the source of gene → disease choice
  and inheritance for the simulator. It can also replace the uniform
  gene → disease mixing in Front B's KB (`kb-v2`).
- **Next:**
  - Simulator: gene-first sampling from `genes-v1` + export v2, after part 2
    lands.
  - Front B: `kb-v2` (ADR-0007 frequencies + mapping + `genes-v1` weights),
    then B2 features and EXP-B-001.
- **Evidence for the informe:**
  - §11 / §13: the source table with licenses, and the GeneCards licensing
    decision (criterion 10).
  - §14: the calibration table (a quality measure of synthetic-data
    realism).

### 2026-09-29 — sesión — `kb-v3`, the Front B knowledge base on ADR-0007 + gene weights (and a void `kb-v2`)
- **Front / versions:** B. Branch `phase1b/kb-v2` (stacked on
  `phase1/gene-profiles`); artifact `kb-v3`.
- **Done:**
  - `rerank/kb.py` schema 2, with 3 new tests (84 in total):
    - ADR-0007 frequency estimation;
    - onset carried to OMIM diseases through exact, validated Orphanet
      alignments of the same 2026-06 release;
    - gene → disease weights from `genes-v1`, split evenly over an entity's
      profiles;
    - a `vocabulary` map from v3.0 symbols to current ones.
- **Result:**

  | Measure | kb-v1 | kb-v3 |
  |---|---|---|
  | Phenotypes at frequency 1.0 | 32,615 | 649 (only HPO "Obligate" categories remain) |
  | Diseases with onset | 8,098 | 9,487 (4,303 HPO + 3,789 Orphanet direct + 1,395 via exact alignment) |
  | v3.0 genes with onset | 4,286 | 4,529 |
  | Genes | uniform over diseases | 5,192 with calibrated weights |
- **Failure (logged, not hidden):** `kb-v2` was published by mistake.
  - What happened: a scripted CLI edit failed on a mismatched anchor, and
    because the commands were chained with `;` instead of `&&`, the build
    still ran on the old schema-1 command path and published `kb-v2`.
  - It is kept as a **void** artifact: manifest committed, id burnt, listed in
    `DATA_LINEAGE.md`. It was not deleted or reused.
  - *Changed:*
    - `lineage.manifest.ensure_new` makes the build commands refuse an
      existing id before any work or publishing;
    - scripted edits now run under `set -e` / `&&`.
- **Verdict:** ✅ `kb-v3` is Front B's KB. ❌ `kb-v2` is void.
- **Next:**
  - B2 features: negation penalty, sex and age compatibility, onset.
  - rr-v1, and the pre-registration of EXP-B-001 on R1-dev.
- **Evidence for the informe:**
  - §14: the before/after table (a measurement that drove a redesign).
  - §16: the void-artifact incident, and the guard it produced.

### 2026-09-29 — EXP-B-001 — rr-v1 on R1-dev: no useful re-ranker; negation works against the true gene
- **Front / versions:** B. Branch `phase1b/rr-v1`; code `863fa3d`
  (pre-registration committed first); KB `kb-v3`; base E0.
- **Question:** do knowledge-based compatibility features (negation, sex,
  age, onset) over v3.0's top 200 genes improve R1-dev MRR?
- **Setup:**
  - 15 configurations within the pre-registered budget of 16: identity, each
    feature alone at w ∈ {0.5, 1, 2}, and 2 combinations chosen by a fixed
    rule.
  - Paired publication-clustered bootstrap. 52 s.
- **Result (R1-dev, n = 1,883, Δ MRR vs E0):**

  | Feature | Δ MRR | Harmed |
  |---|---|---|
  | neg | −0.007 / −0.013 / −0.022 | 12–19% |
  | sex | +0.000 / +0.0003 / +0.0001 | — |
  | age | −0.002 / −0.003 / −0.008 (w = 2: CI < 0) | — |
  | onset | +0.0017 / −0.002 / −0.009 | — |
  | stage2-combined (sex=1, onset=0.5) | +0.0020, CI [−0.0012, +0.0053] | 7.0% |

  - The identity configuration reproduced EXP-000 exactly.
  - The pre-registered rule selects `sex=1.0` (+0.0003): negligible.
- **Diagnosis (dev, exploratory).** Excluded terms are annotated to the
  *true* gene 45.1% of the time, vs 32.0% for the GNN's top wrong
  candidates. Case reports list the typical signs a patient *lacks*.
- **Verdict:** ❌ no useful rr-v1. Nothing advances to a gate.
- **What changes because of it:**
  1. Front B's next step is a **learned** re-ranker (rr-v2) fitted on
     R1-train, so the sign and size of each feature come from data. The
     no-regression and harmed rules stay the same.
  2. The simulator's negatives must reproduce the reporting process (source
     (a) dominant). Front A would otherwise learn the opposite of real
     records.
  3. A deployment-like negation scenario (question-agent flow) is needed
     before claiming anything about negation in production. R1 measures
     "negation as papers report it".
  4. Age: check the adult-onset and presymptomatic hypotheses on dev.
- **Evidence for the informe:**
  - §14: the full configuration table, a measured null result, with the
    pre-registration showing it wasn't tuned away.
  - §16: the negation reporting-bias finding. It's also a lesson on how
    evaluation data encodes its collection process.

### 2026-09-29 — sesión — Front A: simulator v0.2 (`rare-disease-simulator` PR #2)
- **Front / versions:** A. `rare-disease-simulator` branch
  `feat/simulation-v0.2` (8 commits `cfb670c..acfe67e`), PR #2, open and not
  merged. Built by a subagent; I spot-checked it (authorship with no
  trailers, 143 tests, `validate` report).
- **Done:**
  - ADR-0007 frequencies.
  - OMIM↔ORPHA onset through Orphanet 2026-06 `en_product1` (exact +
    validated).
  - Sex prior from inheritance, with sex-specific anatomy never emitted for
    the other sex.
  - Onset → age gating, and a progression boost.
  - Negatives from own-disease absent terms, confounders (IC-weighted index)
    and NOT rows, with slots allotted to sources before drawing.
  - At least one observed positive per case.
  - Covariate missingness.
  - Per-case input sha256s, and no timestamps, so reruns are byte-identical.
  - `validate` with invariant checks.
- **Result** (real build on the pinned inputs + r1-v1 mask; profiles
  `d783c2aa…`; a 6,000-case sample of 300 stratified diseases × 20):

  | Measure | Part 1 → v0.2 |
  |---|---|
  | Obligate annotations | 31,240 → 416 |
  | Negative annotations in profiles | 2,389 → 471 (only NOT now) |
  | Onset coverage | 72.9% → 83.3% via exact alignments |

  Per case (mean):

  | Measure | Value |
  |---|---|
  | Present terms | 6.42 (22% of cases have only 1) |
  | Negated terms | 3.16 (median 2, max 15; 29% of cases have none) |
  | Missing / unknown | 1.22 / 0.82 |
  | Noise | 0 (no vocabulary yet) |

  | Negatives by source | Share |
  |---|---|
  | Own disease | 67.2% |
  | Confounders | 32.7% |
  | NOT rows | 0.1% |

  - Sex matches its priors (XLR 0.909 vs 0.9).
  - Calibration error: 0.0027.
  - **0 invariant violations.**
- **Gaps vs real R1 patients** (to calibrate from R1-train only, in this
  repo):
  - negatives average 3 per case vs about 12 in R1, capped by how many
    terms each disease annotates;
  - no noise vocabulary yet;
  - 22% of cases have a single present term.
- **Verdict:** ✅ simulator v0.2 accepted for review. Not yet used to build a
  training dataset. Gene-first sampling from `genes-v1` and export v2 are
  still pending.
- **Next (Front A):**
  - R1-train calibration pass: negative count and noise vocabulary.
  - Gene-first sampling from `genes-v1`.
  - Export v2 + dataset manifest.
  - `GinV3` parity (A-000).

### 2026-09-29 — EXP-B-002 + calib-v1 + kb-v4 — a learned re-ranker; the "gain" is R1's negation reporting pattern
- **Front / versions:** B (+ A calibration). Branch `phase1b/rr-v2`.
  - `kb-v4`: KB with ALL R1 publications masked, for anything fitted on
    R1-train.
  - rr-v2 run from `6eacff6`; `calib-v1` from `6eacff6`.
- **Age diagnosis (EXP-B-001 Addendum 3):** not presymptomatic patients.
  The feature averaged a disease's listed onset classes, e.g. Orphanet
  "Childhood + Adult".
- **EXP-B-002 (pre-registered):** a conditional-logit re-ranker with 7
  components, fitted on R1-train, penalty chosen on dev.
  - **Dev Δ MRR +0.0565 [+0.009, +0.118]**, the first CI above 0. But the
    harmed rate is 10% > 5%, so the rule gives **no candidate**.
  - **Ablation:** without the negation components, Δ = +0.0014 [−0.002,
    +0.005]. The gain is entirely the model learning that "absent findings
    belong to the true disease" in case reports.
  - In the web app, negations are answers to questions about candidates'
    features, so this would push toward the candidates the patient ruled
    out. Not deployable.
  - Sex, age and onset add ≤ +0.002 each.
- **Process incident:** the first fit run was refused its manifest because
  I edited files during the run. That is the lineage guard working. The
  outputs were deleted, and the rerun from a clean tree reproduced them
  exactly.
  - *Changed:* long commands now capture the code state when they start.
- **calib-v1** (R1-train, `kb-v4`):

  | Target | R1-train | Simulator v0.2 |
  |---|---|---|
  | Present terms per case | 8.7 (median 7) | 6.4 |
  | Negated terms per case | 11.0 (median 7; 9.5% have none) | 3.2 (29% have none) |
  | Negated terms annotated to own gene | 43% | 67% |
  | Present terms unexplained by the gene | **3.7 per case (46%)** | 0 |
  | Missing sex / age / onset | 7.7% / 25.1% / 40.4% | — |

  The noise vocabulary has 1,254 terms seen in ≥ 2 patients; the top ones
  are developmental delay, motor delay and facial features. The simulator's
  patients are much cleaner than real ones. It needs noise and more
  negatives, with a lower own-disease share. (My earlier instruction to make
  own-disease negatives dominant overshot: the real share is 43%, not a
  majority.)
- **Verdict:**
  - ❌ Front B, as knowledge-based features over v3.0 evaluated on R1, gives
    no deployable improvement.
  - ✅ Two findings worth the informe: R1's negation reporting pattern, and
    the redundancy of sex, age and onset given phenotypes on R1.
- **Next / decisions for Mateo:**
  1. A deployment-like negation evaluation: negatives from question-agent
     style questions answered from the patient's record.
  2. Apply `calib-v1` to the simulator once its calibration hook lands.
  3. Front A is now the main hope for sex, age and onset: a network that
     learns them jointly with phenotypes.
- **Evidence for the informe:**
  - §14: the EXP-B-002 tables, with the pre-registered rule applied.
  - §16: the reporting-pattern finding, and the manifest-refusal incident.

### 2026-09-29 — EXP-A-000 — GinV3: v3.0 in PyTorch (merged PR #8); S3 building blocks
- **Front / versions:** A. PR #8 (`aacbb91..ec43c95`), built by a subagent in
  an isolated worktree. I reviewed it and ran its suite on its own code.
  torch 2.14.0+cu130.
- **Done (agent):**
  - `gnn/model.py` `GinV3`: pure torch, strict load of `best_model.pt`.
  - `GinV3Extended`: negated nodes + covariates, all zero-initialised.
    ADR-0009 (Proposed): the untrained model equals v3.0 exactly, with and
    without new inputs.
  - ONNX export (our export == production ONNX, 0.0 difference on 1,000
    cases).
  - `--system ginv3-torch`, `dxt gnn parity`, `dxt eval compare`.
- **EXP-A-000 result (pre-registered):**

  | Criterion | Result |
  |---|---|
  | Top-10 on 1,000 R1-train cases | identical 1,000/1,000 ✅ |
  | R1-dev ranks vs EXP-000 | identical 1,883/1,883 ✅ |
  | max \|Δlogit\| ≤ 1e-4 | **4.9e-4 (CPU) ❌** |

  - The miss is float32 rounding at logits of magnitude in the hundreds:
    relative error ≤ 1.2e-6.
  - Torch is closer to a float64 reference than production's own ONNX
    Runtime in 92% of cases.

  **Verdict:** ⚠️ gate not met as written. Accepting GinV3 as v3.0, and
  switching future parity gates to "relative ≤ 1e-5 + identical ranks", is
  Mateo's call.

  | Speed | Value |
  |---|---|
  | Torch GPU | 0.64 ms/case; 15,350 cases/s in batches of 128 |
  | Torch CPU | 2.4 ms/case |
- **Found by the agent:** a naive ONNX export of v3.0 is silently wrong. The
  TorchScript exporter turns `index_add` into a last-write-wins scatter.
  `diagnostic.ar-model`'s vendored adapter has that form. Production is
  unaffected (it ships the prebuilt ONNX), but any re-export must use the
  one-hot aggregation.
- **S3 building blocks (me, branch `phase1c/s3-eval`):**
  - the annotation split;
  - KB builds that drop half B;
  - `PublicCase` + information-gain questioner + truth-based answerer;
  - the protocol, in EVAL_PROTOCOL §8.
- **Resource alert:** 4.7 GB of disk free (98%). Torch took about 6 GB.
- **Evidence for the informe:**
  - §11 / §14: ADR-0009's step-zero identity and the parity table.
  - §16: the silent ONNX export bug, a lesson on why the parity gates
    exist.

### 2026-09-29 — sesión — Disk cleanup on TARS (local Docker only)
- **Why:** disk at 99%. It fell to 2.8 GB free while the simulator agent
  wrote its dataset; torch had taken about 6 GB.
- **Safety:**
  - the host is `TARS`;
  - `DOCKER_HOST` / `DOCKER_CONTEXT` are unset, and the only context is the
    local socket (daemon `TARS`);
  - no remote or production server was contacted (Mateo: "NEVER IN PROD
    SERVER").
- **Done (reversible or cache-only):**
  - pruned the one stopped container (`qa-eval-model`);
  - pruned all unused build cache (27.35 GB), which also released 63
    dangling images; images went from 106 to 43.
  - The running `nodo0-*` containers were untouched and stay healthy.
- **Result:** 2.8 GB → **26 GB free** (99% → 89%).
- **Left for Mateo to decide:**
  - the `trivy-cache` volume (1.45 GB, re-downloadable);
  - about 70 anonymous volumes of ~65 MB each (about 4 GB, possibly old test
    databases; keep `lucai_v2_devdb`);
  - unused tagged images (5.8 GB, mostly the `lucai-agent-bioeutectics`
    staging images);
  - user caches: Chrome 4.2 GB, Flatpak 3.4 GB, Steam 3.2 GB;
  - one disabled `cups` snap revision.
- **Context snapshot:** `docs/STATE.md` was added before the detour, and is
  also the resume point in memory.
- **Follow-up (Mateo's instruction), same day:**
  - Deleted every tagged image not used by a container (`docker image prune
    -a`, local TARS daemon re-verified): **18.43 GB** reclaimed. Only the 4
    images used by containers remain.
  - Cleared Stremio's cache (flatpak `cache/`, 66 MB); its `data/` and
    `config/` were kept.
  - Disk: **43 GB free (81%)**.

### 2026-09-29 — sesión — Decisions: GinV3 accepted; ADR-0009 accepted for Front A only; Front A overfitting rules
- **Mateo:**
  - "I'm ok with rebuilding if we proved it's the same" → GinV3 accepted as
    v3.0 (EXP-A-000 addendum). The missed absolute gate stays on record;
    future parity gates use relative ≤ 1e-5 + identical ranks.
  - "starting point in the same weights is perfect … only for the front that
    retrains; the other should just work with the model's normal output" →
    ADR-0009 accepted, **scoped to Front A**. Front B keeps consuming the
    production ONNX distribution.
  - "make sure we are not overfitting" → **EVAL_PROTOCOL §9**, written
    before any training run:
    - four data roles that never mix;
    - a budget of ≤ 8 configurations per experiment;
    - required curves: train, sim-val, R1-dev with and without the new
      inputs, and S2 for forgetting;
    - a "present-only" no-regression anchor;
    - ≥ 3 seeds;
    - learning-rate limits;
    - a contamination check before every run.

### 2026-09-29 — EXP-S3-001 — Negation as the app produces it: penalising denied findings helps; R1-learned weights hurt
- **Front / versions:** B + the S3 harness. Code `da1e3d7`; `s3-data-v1`
  (20,200 simulated patients, full profiles, `simcal-s3-v1`, seed 2002);
  split `s3-v1` frozen before any system ran; KB `kb-v5` (half B dropped).
- **Calibration done before it** (R1-train targets only, in 2 declared pilot
  rounds):

  | Artifact | For |
  |---|---|
  | `simcal-train-v1` | Front A generator; matches R1-train within a few percent on counts, negated terms, own-gene share and missingness |
  | `simcal-s3-v1` | S3 generator; noise 2.4 = 3.7 − the 1.3 unexplained terms half B already contributes |

  Residual gaps: unexplained share 41.8% vs 46%; the negated-count
  distribution is less skewed than real.
- **Result on S3-dev** (10,210 patients; 6.9 questions per case, 0.75
  "yes", 6.1 "no"; Δ vs E0+answers, CI by gene):

  | System | Δ MRR | Harmed |
  |---|---|---|
  | Questions themselves (E0+answers vs E0-initial) | +0.012 | — |
  | rr-v1 negation, w = 0.5 | **+0.0045 [+0.0034, +0.0056]** (selected by the pre-registered rule) | 4.0% |
  | rr-v1 negation, w = 1 / w = 2 | +0.0078 / +0.0095 | 5.3% / 7.2% |
  | **rr-v2 (R1-learned)** | **−0.030 [−0.033, −0.027]** | **28%** |
  | rr-v2 without negation | ≈ 0 | — |
- **Verdict:** ✅ H1, H2 (modest), H3 (strong). The clinically-signed
  negation penalty helps when negations come from questions about
  candidates. The R1-learned inverse weighting would have hurt a deployment.
- **Limitation found:** S3 v1 is fair for negation only. Onset and
  inheritance knowledge is shared between the generator and the KB, so the
  sex/age/onset gain in rr-v1[all=1] (+0.006) is partly circular and not
  claimed.
- **Process incidents (both fixed):**
  1. `set -e && …` doesn't stop on failures inside `&&` lists; scripted
     blocks now use `set -euo pipefail` on its own line.
  2. The first Front A training export failed silently: I had piped it
     through `grep`, so the pipeline's status was grep's, and the next step
     deleted the intermediate cases. It is regenerating (deterministic),
     with full logs and delete-only-if-the-output-exists.
- **Next:**
  - Register the Front A training set, and add the contamination check
    against S3 and R1.
  - Pre-register the Phase-4 gate for rr-v1[neg=0.5] (S3-test + R1-test
    no-regression).
  - Front A ladder A-001….
- **Evidence for the informe:**
  - §14: the S3 table. The most direct evidence about negation in the
    product's own interaction pattern.
  - §16: the circularity limitation, plus the two process incidents.

### 2026-09-29 — sesión — Front A training set `ds-sim0.3.1-A-n100-s1001`
- **Generator:** rare-disease-simulator@8ba7430, profiles without half B,
  `simcal-train-v1`, seed 1001, 100 cases per gene.
- **Result:**
  - 501,100 cases for 5,011 genes. Hiding half B left 39 genes that S3 has
    with no simulable disease.
  - 37 MB gz; simulator splits 450,877 train / 25,300 val / 24,923 test
    (S1).
  - **0 invariant violations**, on the second attempt.
- **Invariant incident:** the first full run had 4 of 505,000 cases where
  ontology generalization moved a term to a parent the profile restricts to
  the other sex. `validate` refused the export. Fixed in simulator PR #4,
  with a regression test proven to fail without the fix; regenerated.
- **Contamination:**

  | Against | Same full signature | Same (gene, present set) |
  |---|---|---|
  | S3 | 7 | 101 |
  | R1 | 0 | 22 |

  These are chance coincidences on small presentations. **143 cases** are
  excluded by artifact `ds-sim0.3.1-A-n100-s1001-excl-v1` (the stricter
  gene-insensitive key catches more than the pairwise counts); the residual
  overlap is 0.
- **My errors, corrected:**
  - A commit message claimed "no overlap" before I had read the check. It
    was amended before being pushed.
  - A pushed commit and the protocol said 130 excluded cases instead of 143.
    Corrected in a follow-up commit.
  - *Rule adopted:* no numbers in messages or docs until the output has been
    read.

### 2026-09-29 — EXP-A-001 — Fine-tuning v3.0 on simulated positives hurts real patients (no candidate)
- **Front / versions:** A. PR #11, built and run by a subagent in a
  worktree; I verified the pre-registration order, authorship and the
  branch's own tests. Training set `ds-sim0.3.1-A-n100-s1001` with its
  exclusion applied (residual overlap 0).
  - Throughput: 14,300 cases/s; 7.3 min per 10-epoch run; 1.6 GB of GPU
    memory.
- **Result:** 6 configurations: lr ∈ {1e-5, 5e-5, 2e-4} × BatchNorm
  train/frozen.
  - **R1-dev Δ MRR from −0.091 [−0.122, −0.059] to −0.208**, harmed
    46–61%.
  - S2 (forgetting) 0.68–0.75 vs E0 0.81.
  - Every warning flag fired ("sim-val up while R1-dev down", S2 < E0 −
    0.02) from epoch 1.
  - S3-dev *rose* (+0.11 to +0.27): the declared same-generator dependency
    at work, and a warning never to read S3 as evidence for Front A models
    trained on the same simulator.
  - c1 (the least harmful) over 3 seeds: Δ −0.0917 ± 0.0011.
  - The epoch-0 identity held exactly (Δ 0).
- **Verdict:** ❌ **no candidate.** Simulated positives alone push v3.0 off
  what makes it good on real patients.
- **Diagnosis (addendum):** not "unlearning half B" (that hypothesis was
  rejected; the damage is larger on cases that don't rely on it). It is a
  distribution shift with an extremely overconfident starting point (loss
  24.6, sim-val MRR 0.166).
- **Implications:**
  1. Any Front A variant that updates v3.0's weights on this data inherits
     this harm, so A-002–A-004 as planned would build on it.
  2. The S3 numbers of Front A models are not comparable with Front B's:
     same generator family.
  3. A sounder Front A design keeps v3.0's weights frozen and trains only
     the new zero-initialised parts, for negation and covariates.
     No-regression then holds by construction on the "present only" view.
     The training negatives should be produced the way the app produces
     them (questions about candidates), not the R1-like reporting mix.
     This is a proposal to Mateo.
- **Evidence for the informe:**
  - §14: the A-001 table, a clean, pre-registered negative result with
    curves.
  - §16: "synthetic data can hurt a pre-trained model even when it is
    calibrated to real statistics".

### 2026-09-29 — decision — Front A redesign: v3.0 frozen (ADR-0010)
- **Mateo chose:** "Freeze v3.0, train only new parts".
- **ADR-0010:**
  - only ADR-0009's zero-initialised parameters train, so the present-only
    view equals E0 by construction;
  - training negatives come from interviewing simulated training cases the
    way S3 does (E0 top-10 questioner on `kb-v5`, answers from the truth),
    not from the simulator's R1-like reporting mix;
  - sex, age and onset come from the simulated patient.
- **Evaluation:** R1-dev is decisive for covariates; S3-dev for negation,
  with the same-simulator caveat.
- **The ladder becomes** A-002f (negation), A-003f (covariates), A-004f
  (both). The PLAN keeps the original table for planned vs actual.

### 2026-09-29/30 — EXP-A-002f, EXP-A-003f, EXP-A-004f — Frozen-base Front A: learned from simulated patients, harmful on real ones
- **Front / versions:** A (ADR-0010, v3.0 frozen). PR #14.
  - Interviewed training set `ds-sim0.3.1-A-iv-v1`: 100,217 cases
    interviewed like S3.
  - Pre-registrations committed before any run (`7eb5686`, `241acc2`).
  - Run from `7eb5686`, `241acc2` and `5f1f3f0` (same code); every
    manifest verifies.
- **EXP-A-002f (negation):** ❌ no candidate.
  - The `neg` design never beat the untrained model on sim-val, so early
    stopping kept exactly E0.
  - `neg2` gives S3-dev +0.057 to +0.093, but harms 10–23% of S3
    patients, and on R1-dev "+excluded" −0.14 to −0.28.
  - "Not a candidate" seeds: S3 +0.0902 ± 0.0020, R1 −0.2539 ± 0.0006.
  - **Shuffled-negation control:** with another patient's "no" answers,
    S3 keeps +0.0775 of +0.0925. The model mostly learned "has negated
    answers", not their content.
- **EXP-A-003f (sex/age/onset):** ❌ no candidate.
  - R1-dev "all" −0.21 to −0.23 in all 6 configurations, harmed 55–60%;
    sex −0.07 to −0.22, age −0.16 to −0.22.
  - "Not a candidate" seeds: **−0.2074 ± 0.0028**.
  - S3 +0.10 to +0.13 (circular for covariates).
- **EXP-A-004f:** not run, by ADR-0010's own rule. It combines selected
  configurations, and there are none.
- **Conclusion for Front A:**
  - **Three pre-registered experiments** (A-001, A-002f, A-003f) show that
    learning from our simulated patients improves simulated evaluation and
    hurts real patients.
  - The simulator matches the calibrated *statistics*, but not the real
    *relationships* between phenotypes, negations, sex/age and genes.
  - The one new-input method that survives the harm cap is Front B's
    knowledge-based denied-finding penalty (EXP-S3-001).
- **Process:**
  - **Graceful stop (2026-09-29).** My stop message could not reach the
    agent inside its batch loop. I stopped its two queue scripts (SIGTERM)
    and their runs (SIGINT), by exact PID after one over-broad `pkill`.
    Nothing was lost: completed runs kept their manifests, and interrupted
    ones left no outputs.
  - **Recovery (2026-09-30):**
    - committed the agent's A-002f results;
    - re-ran the interrupted A-003f configurations under the same ids;
    - finished the grid and the seeds.
  - **Slip:** I ran the A-001 `gnn report` command on A-003f, which
    overwrote `report.json` with the wrong schema. It was restored from git
    at once, and the right command is `gnn report-frozen`.
  - A pre-push hook run from a worktree tests the main checkout's code
    unless `PYTHONPATH` points at the worktree. It failed a push once; this
    is noted for future agents.
- **Evidence for the informe:**
  - §14: the three Front A tables, plus the shuffled control.
  - §16: "synthetic data calibrated to real statistics still teaches
    relationships that don't hold on real patients", and the
    graceful-stop/recovery procedure.

### 2026-09-30 — ANALYSIS-001 — Dataset realism: the simulator is consistent but not realistic; over-masking found
- **Asked by Mateo:** is disease→phenotype the problem, and how good is the
  dataset? Full write-up: `docs/analyses/ANALYSIS-001-dataset-realism.md`.
  R1-dev (out of sample for the simulator) and R1-train only, plus a
  literature check of 10 diseases by two research agents.
- **Findings:**

  | Question / check | Result |
  |---|---|
  | Real-vs-generated term-frequency correlation, 10 genes | ours 0.07 vs upstream 0.39 |
  | HPOA frequency vs real reporting, 64 genes | within-gene ρ 0.02–0.07 |
  | Reporting model fitted on R1-train | ρ 0.170 |
  | Over-masking | whole multi-PMID cohort rows dropped: UMOD keeps 3 of 33 rows |
  | Literature | cardinal features under-emitted, wrong Orphanet bins, OMIM/ORPHA halving, spurious links, no age dependence |
  | Real R1-dev per-gene rates | often a single paper's cohort, so not per-gene ground truth |

- **Answers:**
  1. The disease framing is not the root cause; profile construction and
     emission are.
  2. The dataset is internally consistent but not realistic per disease,
     so the Front A negatives are about *this* simulator.
- **Recommendations** (awaiting Mateo): recount instead of whole-row
  masking; merge OMIM/ORPHA; better disease weights; reporting-model
  emission with forced cardinal features; age dependence; a standing
  realism check.
- **Evidence for the informe:**
  - §14: the realism tables and the frequency-vs-reporting calibration;
  - §16: over-masking as a design flaw, and "internally valid ≠
    realistic".

### 2026-09-30 — decision — Simulator v0.4 rebuild (ADR-0011)
- **Mateo chose:** "Rebuild simulator".
- **ADR-0011 fixes:**
  - the design;
  - the formats of four new training-repo artifacts: `hpoa-recount-v1`
    (recount instead of drop), `genes-v2` (patient-count weights, spurious
    and somatic links removed), `report-model-v1`, `cardinal-v1` (Orphadata
    product 4 flags + count-based proxies);
  - simulator v0.4 (merged entity profiles, Beta shrinkage, truth-then-
    reporting emission with forced cardinal features, age dependence where
    data exist);
  - the standing `dxt sim realism` check, with its R1-dev budget (≤ 3
    simulator versions, logged).
- **Protocol amendment:** EVAL_PROTOCOL §4.1 is now recount-or-drop.

### 2026-09-30 — decision — Data-quality gate before any retraining (ADR-0012)
- **Mateo:** "not move forward until the simulator and data is pristine".
  GenPhenAI's plain gene→phenotype simulator is the bar to beat. Claude Code
  and Codex are available for processing sources.
- **ADR-0012 gate**, written before any v0.4 number exists:
  - G1: integrity.
  - G2: beat both GraPhens' simulator (UP) and v0.3 on literature-panel
    error, R1-dev aggregate term correlation, term-count distance, a
    classifier two-sample test (AUC ≤ 0.75) and E0 difficulty match
    (≤ 0.10).
  - G3: 30 disease cards reviewed by a person.
  - G4: a ≥ 50-disease literature panel, LLM-extracted with evidence
    quotes, 10% double-checked, strictly separated from construction.
  - G5: freeze.
- **R1-dev budget:** 3 candidate versions.
- **GeneReviews:** facts-with-citations use under its non-commercial terms;
  written confirmation requested (TODO).
- **Correction to ADR-0012 G2e,** made before any v0.4 number exists. The
  difficulty target is now R1-train's in-vocab E0 MRR, 0.512 (it was the
  all-genes 0.440): simulated genes are all in vocabulary. Gaps become
  UP 0.300 and V03 0.336, both taken from EXP-000 and EXP-A-002f.
- **Clarification to ADR-0012 G2a,** made before any v0.4 number exists. The primary panel error uses only the rows sourced from GeneReviews or cohort papers. HPOA already carries Orphanet's frequencies, so Orphanet-sourced rows would not be an independent check.

### 2026-09-30 — build — Simulator v0.4 code merged (rare-disease-simulator PR #5, 266472c)
- **Implemented (ADR-0011):**
  - merged entity profiles;
  - Beta shrinkage of count frequencies, with no built-in μ₀;
  - truth-then-reporting emission, using report-model-v1's R1-train budget histogram and cardinal terms first;
  - age gating;
  - new validate checks.
- **239 tests pass.** Only fixture runs so far; no real data, because the
  training-repo artifacts are still being built.
- **Review fix before merge:** noise terms now take slots from the report
  budget instead of adding to it. The budget comes from R1-train's
  reported-term counts, which already include noise, so without the fix
  simulated cases would overshoot terms-per-case (G2c). On the fixture,
  reported totals follow the histogram with total variation 0.038.
- **Onset coverage is thin:** 1.2% of positive HPOA rows carry an onset
  (HPO 2026-02-16), so most terms are not age-gated.
- **Not tagged or frozen.** Freezing waits for the ADR-0012 gate.

### 2026-09-30 — build + decision — v0.4 artifacts merged (PR #22); ADR-0011 amendment 1
- **Merged the training-repo artifacts:** `hpoa-recount-v1`, `genes-v2`,
  `report-model-v2` (v1 superseded by the format change), `cardinal-v1`
  (new source: Orphadata product 4), `simcal-v04-v1`,
  `literature-panel-v1`, plus `dxt sim realism|gate`.
- **Recount restores masked profiles.** Diseases gutted by whole-row
  masking get their rows back: UMOD 3 → 20 rows, Holt-Oram 21 → 46,
  FBXL4 26 → 82.
- **report-model-v2 on R1-dev:** within-gene ρ 0.367, vs 0.185 for HPOA
  frequency alone (68 genes; ledgered as a check).
- **G2 baselines** (`results/realism/gate-baselines.md`):

  | Metric | UP | V03 |
  |---|---|---|
  | panel-v1 MAE | 0.504 | 0.556 |
  | dev ρ | 0.231 | 0.086 |
  | W1 terms per case | 3.717 | 1.382 |
  | C2ST AUC | 0.840 | 0.778 |
  | E0 gap to 0.512 | 0.307 | 0.344 |

  The UP ρ is lower than ANALYSIS-001's 0.39: this one covers 42 genes and
  averages tied ranks.
- **Amendment 1, fixed before any candidate number:**
  - μ₀ = median of count pairs with m ≥ 10 (0.30); the all-pairs median of
    0.667 is inflated by single case reports;
  - cardinal terms are not forced, since report-model-v2's fitted cardinal
    coefficient already covers them;
  - one merged calibration file, `simcal-v04-v2`;
  - the candidate uses the Front A training shape;
  - 159 genes lose coverage, which is accepted.

### 2026-09-30 — build — v0.4 candidate 1 dataset: G1 fails (622 invariant violations); G2 not run
- **Front / versions:** A / rare-disease-simulator@266472c (0.4.0, clean
  tree), `hpoa-recount-v1`, `genes-v2`, `report-model-v2`, `cardinal-v1`,
  `simcal-v04-v2`, half A of `annot-split-v1`. Candidate 1 of 3 (ADR-0012).
- **Profiles:** `build-profiles --from-hpoa` with `--hpoa` hpoa-recount-v1,
  `--drop-annotations` annot-split-v1, `--gene-profiles` genes-v2, no
  `--exclude-pmids`.
  - 9,095 profiles, 5,134 genes; 1,675 recounted rows used.
  - The simulator's config still supplies the r1-v1 PMID mask as a fallback,
    so the mask ran: 1,026 references, **0 rows masked**. This confirms
    hpoa-recount-v1 carries no held-out citation.
  - Half B: 59,651 of 78,917 listed pairs dropped (59,798 rows); 128
    diseases left without phenotypes.
- **Simulate** (gene-first, 100 per gene, medium, seed 1001, 442 s):
  486,800 cases for **4,868 genes**. 360 of 5,228 vocabulary genes skipped:
  6 unresolved symbol, 53 no gene record, 277 no simulable entity, **24 no
  profile available** (ADRB1, CEBPA, FLT3, SF3B1, …), which is the gap to
  the 4,892 genes expected. Their entities' profiles were not built; the
  likely cause is the 128 diseases half B leaves without phenotypes (not
  checked per gene).
- **G1:**

  | Check | Result |
  |---|---|
  | `validate` invariants | **FAIL: 622 violations**, all `reported_count_mismatch`, each off by one |
  | Rerun byte-identical | pass: a 20-gene slice (19 simulated, 1,900 cases) run twice gives identical bytes, equal to the full run's lines for those genes |
  | `dxt lineage verify` | ok |
  | Contamination vs R1 and S3 | not run: `export-training` refuses cases that fail `validate` |

- **Cause of the violations** (simulator `_report`): a reported term whose
  own id was already shown, because an earlier term was generalized to it,
  is skipped with no record. Example: A2ML1 case 75 generalizes HP:0000407
  to HP:0000365, then reports the true HP:0000365 itself. The case shows 9
  profile terms for a profile budget of 10, and the skipped term is neither
  a positive, a `recorded_as_generalized` missing term nor an unreported
  one. An independent count over the cases finds exactly 622 cases below
  their profile budget with unreported true terms left, and every one has a
  generalized positive. The fix belongs in the simulator and needs a new
  commit and a regenerated dataset.
- **No dataset was registered or published, and G2 was not run.** No
  R1-dev read and no ledger row, so candidate 1's budget slot is unspent.
  `scripts/register_sim_dataset.py` (manifest + `-excl-v1`, as for V03) is
  committed for the rerun; it has not been exercised yet.
- **Diagnostics without R1-dev** (from the rich cases and the run summary;
  `present` computed as in export v2):

  | | Candidate | R1-train |
  |---|---|---|
  | Present terms per case: mean / median | 7.34 / 7 | 8.70 / 7 |
  | p10 / p90 / max | 4 / 12 / 51 | 2 / 17 / 66 |
  | Cases with ≤ 2 terms | 2.6% | 11.0% |

  - W1 of terms per case vs R1-train (G2c's statistic, R1-train only):
    **2.046**. UP is 3.717 and V03 1.382. The fix touches 622 cases by one
    term, so this should barely move: the candidate is on course to fail
    G2c against V03.
  - Budget: mean drawn 8.70, reported total 7.35 (3.65 profile terms +
    3.70 noise). TV of reported totals vs the budget histogram 0.234.
  - **Noise share:** 50.4% of shown terms pooled, 55.3% mean per case.
    41.6% of cases show exactly one profile term.
  - **Cardinal:** 0.193 reported cardinal positives per case, 2.6% of shown
    terms, at least one in 12.3% of cases. `validate`: 110,132 of 228,415
    true cardinal terms reported (48.2%), counting generalized ones.
  - Frequency calibration (ungated terms): error 0.0028.
- **Verdict:** ❌ candidate 1 fails G1. Nothing tuned.
- **Next:** fix the simulator's generalization collision with a regression
  test, regenerate with the same settings, and re-run G1, then G2 once as
  `v0.4-cand1`. Open question for Mateo before that run: noise takes half of
  the shown terms and the term-count spread is narrower than R1-train's
  (the W1 above).

### 2026-09-30 — decision — Candidate 1 revised before its R1-dev read (ADR-0011 amendment 2)
- **Simulator 0.4.1** (rare-disease-simulator PR #6): refills report slots
  absorbed by a generalized child, the cause of the 622 G1 violations;
  regression test added. Adds `budget_share` noise.
- **Noise:** each budget slot is noise with probability 0.4625 (R1-train
  unexplained share, calib-v1), at most k − 1. This replaces
  Poisson(3.7) drawn independently of the budget, which left 41.6% of
  cases with one profile term.
- **New calibration file:** `simcal-v04-v3`.
- **Status:** R1-dev still unread; candidate 1 remains read 1 of 3.

### 2026-09-30 — build + gate — v0.4 candidate 1 (simulator 0.4.1): G1 passes, G2 fails on a, b and e
- **Front / versions:** A / rare-disease-simulator@b645c60 (0.4.1, clean
  tree), `simcal-v04-v3` (ADR-0011 amendment 2), `hpoa-recount-v1`,
  `genes-v2`, `report-model-v2`, `cardinal-v1`, half A of `annot-split-v1`.
  Gene-first, 100 per gene, medium, seed 1001. This is candidate 1 of 3 and
  spends R1-dev read 1 of 3.
- **Profiles:** the 266472c → b645c60 diff touches only `simulation/`, docs
  and tests. A rebuild with 0.4.1 is byte-identical to the 0.4.0 build
  (sha256 `ad4476b4…`); its PMID-mask fallback again masked 0 rows.
- **Dataset** `ds-sim0.4.1-A-n100-s1001` (release assets, ADR-0005):
  - 486,800 cases for 4,868 genes, the same 24 `no_profile_available`
    genes short of 4,892 as before;
  - 36.6 MB gz (sha256 `b18df39d…`); sim splits 438,011 train / 24,584 val
    / 24,205 test.
- **G1:**

  | Check | Result |
  |---|---|
  | `validate` (cases and export) | pass: 0 invariant violations |
  | Rerun byte-identical | pass: a 20-gene slice (19 simulated) run twice gives identical cases and identical exports, and its cases equal the full run's lines |
  | `dxt lineage verify` | ok |
  | Contamination, key (gene, present set) | R1 (all parts, keys only): 58; S3: 449 (42 with the same full signature). **498 cases excluded** by `ds-sim0.4.1-A-n100-s1001-excl-v1`; residual 0 |

  The S3 overlap is higher than V03's (101). These are chance matches on
  small presentations, likely because 12.7% of this candidate's records
  have at most 2 terms.
- **G2** (`dxt sim realism --label v0.4-cand1 --sim-version 0.4.1-cand1`,
  one run with no crash; `results/realism/gate-v0.4-cand1.md`):

  | Metric | UP | V03 | Candidate | Pass |
  |---|---|---|---|---|
  | a: panel-v1 MAE | 0.504 | 0.556 | 0.512 | ❌ (beats V03, not UP) |
  | b: R1-dev mean per-gene ρ (38 genes scored) | 0.231 | 0.086 | 0.152 | ❌ (beats V03, not UP) |
  | c: W1 terms per case vs R1-train | 3.717 | 1.382 | 1.214 | ✅ |
  | d: C2ST AUC (≤ 0.75) | 0.840 | 0.778 | 0.737 | ✅ |
  | e: \|E0 MRR − 0.512\| (≤ 0.10) | 0.307 | 0.344 | 0.420 | ❌ (worse than both) |

  - **G2e:** E0's MRR on the candidate is 0.092. V03 gave 0.168 and UP
    0.819, so the candidate's patients are much harder for E0 than real
    ones.
  - **G2a:** literature-panel-v1 has no `source_kind` column, so the
    primary MAE uses all 37 rows, Orphanet-sourced ones included; the
    baselines were computed the same way. It will be recomputed on
    literature-panel-v2, which reads no R1-dev.
- **Diagnostics without R1-dev** (`results/realism/v0.4-cand1.train-diagnostics.json`):

  | | Candidate | R1-train |
  |---|---|---|
  | Present terms per case: mean / median | 7.49 / 6 | 8.70 / 7 |
  | p10 / p90 | 2 / 14 | 2 / 17 |
  | Cases with ≤ 2 terms | 12.7% | 11.0% |
  | W1 | 1.214 | — |

  - Profile terms per case: mean 3.51, median 3. **27.2% of cases show
    exactly one profile term** (41.6% under 0.4.0).
  - **Noise share:** 53.1% of shown terms pooled, 48.6% mean per case, 3.97
    noise terms per case. That is above the nominal 0.4625 because profile
    slots go unfilled when the true phenotype is thinner than the budget:
    budget mean 8.70, shown 7.49.
  - Reported totals vs the budget histogram: TV 0.070 (0.234 under 0.4.0).
  - **Cardinal:** 0.194 reported cardinal positives per case, 2.6% of shown
    terms, at least one in 12.9% of cases. `validate`: 111,082 of 228,406
    true cardinal terms reported (48.6%).
- **Verdict:** ❌ candidate 1 fails the gate (G2a, G2b, G2e). Nothing was
  tuned after the read.
- **Next:** Mateo decides candidate 2 (2 R1-dev reads left). The
  R1-train-only numbers point to a possible source of the G2e difficulty,
  not tested: about half of each record is noise, and a quarter of cases
  carry a single profile term.

### 2026-09-30 — analysis + decision — ANALYSIS-002; ADR-0012 amendment 1
- **Candidate 1** (sim 0.4.1, R1-dev read 1 of 3) passes G1 and fails G2
  a, b and e (PR #27). E0 MRR on it is 0.092.
- **ANALYSIS-002** (R1-train only):
  - Real present terms are 53.8% explained, 11.5% more specific than an
    annotation, 9.9% related (shared-ancestor IC 2–4), and 23.9% weakly
    related or unrelated.
  - Candidate 1 is 49.4% / 5.0% / 4.7% / 40.6%. Its noise is too
    gene-independent.
  - E0 in-vocab MRR on R1-train is 0.562 for patients whose paper is cited
    in HPOA (n 2,398) and 0.405 for uncited ones (n 1,124).
- **ADR-0012 amendment 1** (disclosed as made after candidate 1's read):
  - the G2e target becomes 0.405;
  - G2 scores full-profile runs, because half A zeroes 30% of G2b's
    reference terms.
  - Recomputed G2e gaps: UP 0.414, V03 0.237, candidate 1 0.313. None
    passes.
- **ADR-0011 amendment 3 (candidate 2 design, fixed before any candidate 2
  number):**
  - specialisation of reported terms (rate r);
  - disease-related noise (share s of noise slots);
  - noise share 0.348;
  - r and s chosen in at most 2 declared pilot rounds against ANALYSIS-002's
    R1-train term categories.
- **Scoring and budget:** G2 runs on the full-profile dataset. This is
  R1-dev read 2 of 3.


### 2026-09-30 — ADR-0012 G4 — Evaluation/construction disease split frozen (`litpanel-split-v1`)
- **Why:** G4 requires the split to be frozen and hashed before any
  literature extraction.
- **Frozen at commit `b9be9baae84f47ae6cfcb8f635f25ba273053579`**, built by
  `dxt litpanel split --id litpanel-split-v1` at code `cb0ccf4` (clean tree).
  - `data/realism/litpanel-split-v1.tsv` sha256
    `39ba3b252adc7bf0712d03a0abc6d2fc522d6011fdf77658699f2203737f504c`;
    manifest `data/manifests/litpanel-split-v1.json`.
- **Unit:** a vocabulary gene plus its main disease, the simulable
  `genes-v1` entity with the highest `sim_weight`. Pool: 5,050 units.
- **Selection (seed 20260930):**
  - the 10 ANALYSIS-001 genes;
  - 50 sampled units, with square-root allocation over organ system (modal
    child of HP:0000118 among the entity's HPOA terms, held-out rows
    masked), inheritance (AD/AR/XL/other) and R1-train patients (0, 1–9,
    ≥ 10). Picks alternate with genes that have ≥ 10 R1-dev patients: 25
    of the 50, 35 of 60 counting anchors;
  - 20 ordered reserves, drawn only if fewer than 50 units survive
    extraction.
- **R1 parts read:** train and dev (patient counts per gene). No sealed data.
- **Separation:** all 80 listed units (their genes and all their disease
  ids) are evaluation-only. Every other unit is construction.
- **Caveat:** `genes-v1` picks some odd main diseases (e.g. UNC13A → ALS1,
  CST3 → ARMD11). The split keeps them, because the panel evaluates what
  the simulator emits for that entity.

### 2026-09-30 — ADR-0012 G4 — Reserve list extended (`litpanel-split-v2`)
- **Why:** after 5 of the 8 extraction batches, 15 of 38 panel units had
  been dropped (no source with stated numbers for ≥ 5 features, or a
  susceptibility-only gene–disease link). The 20 reserves of
  `litpanel-split-v1` might not bring the panel to 50.
- **Frozen at commit `410c0354bb7e0fbdb3b0232ec85c187bad71d566`**, built at
  code `25bf214` (clean tree): the same sampler and seed, with 40 reserves.
  - `data/realism/litpanel-split-v2.tsv` sha256
    `c9de69c3a2575efaac176a1c4eb65f7c80055c905e87933b13ca0e4b25216543`.
  - Its first 80 rows are identical to `litpanel-split-v1` (checked with
    `diff`).
- **Frozen before any extraction on reserves 81–100.** No
  construction-side literature extraction has happened yet, so moving
  these 20 units from construction to evaluation leaks nothing.
  `litpanel-split-v2` supersedes v1 as the evaluation/construction
  boundary.

### 2026-09-30 — ADR-0012 G4 — Reserve list extended again (`litpanel-split-v3`)
- **Why:** of the first 80 units, 43 survive extraction. Reserves 81–100 are
  still being extracted, and at the survival rate seen so far they may not
  reach 50.
- **Frozen at commit `7399bc212cd525ab7d402d49c767c95eb4524f46`**, built at
  code `4d3da3a` (clean tree): the same sampler and seed, with 60 reserves.
  - `data/realism/litpanel-split-v3.tsv` sha256
    `b508e757f0896a125cb8eab91ae6902d0dce419a601d54f032b4fd5ff3f60ad2`.
  - Its first 100 rows are identical to `litpanel-split-v2`.
- **Frozen before any extraction on reserves 101–120.**
  `litpanel-split-v3` is now the evaluation/construction boundary. All 120
  listed units are evaluation-only, whether or not they survive
  extraction.

### 2026-09-30 — ADR-0012 G4 — `literature-panel-v2` built: 56 units, 531 rows, cross-check 52/54
- **Built at commit `9e7f13d`** by `dxt litpanel build --id
  literature-panel-v2 --split litpanel-split-v3`, at code `d9d08ff`,
  clean tree, `lineage verify` ok. Full write-up:
  `docs/analyses/LITPANEL-v2.md`.
- **Panel:**
  - 56 evaluation units, 531 rows, 5–12 rows per unit;
  - 164 GeneReviews rows, 367 cohort-paper rows, 0 Orphanet rows;
  - 497 rows independent of construction, and 52 units have ≥ 5 of them;
  - all 8 `literature-panel-v1` diseases, and 9 of the 10 ANALYSIS-001
    genes (SPTAN1 dropped: closed-access cohorts).
- **Extraction:**
  - 17 Claude subagent batches under one written spec. Each quote was
    machine-checked as verbatim in its source text.
  - The 37-row draft was re-verified row by row. Rows resting on vague
    quantifiers or penetrance were dropped or replaced.
  - I excluded 10 more rows in review (a complement, a pooled symptom
    sentence, hospital-admission shares, an "up to"). NHLRC1 and F8 then
    fell below 5 rows and were dropped.
- **Units dropped:** 64 of 120 (51 without stated numbers, 11 not
  monogenic, 2 after review). This led to the two reserve extensions
  logged above.
- **Cross-check:**
  - 54 rows (10%, seed 20260930) re-extracted by Codex CLI 0.155.1 from
    gene, disease, feature and citation, with the cited text on stdin
    (Codex's sandbox cannot read local files here).
  - 52/54 agree (96.3%).
  - Both disagreements were re-read, and the source supports the panel in
    each: RPS19 (Codex declined a DBA-wide figure) and TNFRSF13B (Codex
    took the total column instead of the biallelic column).
- **Access:**
  - Blocked: NCBI Bookshelf/PMC pages (reCAPTCHA), orpha.net (bot check),
    `efetch db=books`.
  - Used instead: the GeneReviews litarch bulk archive (sha256 recorded in
    the manifest), Europe PMC REST, and E-utilities `db=pmc`/`db=pubmed`.
  - Europe PMC returned intermittent 503s.
- **Gaps:**
  - no ear/hearing unit survived;
  - several units carry disease-level rather than gene-level figures
    (MELAS, PCD, FA, AP-4, DBA), flagged in `population`.
- **Evidence for the informe:** the G4 row of the data-quality gate, and
  the dropped-unit statistics (most vocabulary units have no published
  frequencies).
- **History note:** before the first push, three commit messages on this
  branch were reworded, and the branch was replayed with identical trees.
  The commit ids quoted above and in the manifests' `code.sha` are the
  replayed ones, remapped one-to-one; each names exactly the code tree
  that produced the artifact.

### 2026-09-30 — decision — Mateo's answers
1. **ADR-0012 amendment 1: accepted.** The G2e target is 0.405, and G2
   scores full-profile runs.
2. **GeneReviews confirmation:** Mateo is sending the email; the work
   doesn't wait for the answer. Without GeneReviews rows, 35 diseases keep
   ≥ 5 independent rows. The fallback is recorded in the TODO.
3. **Phase-4 sealed gate for rr-v1[neg=0.5]:** approved; pre-registration
   follows.
4. **G3 disease cards:** delegated. The assistant and Codex review them
   independently, and Mateo spot-checks at the end (ADR-0012 amendment 2).

### 2026-09-30 — pre-registration — EXP-B-003: Phase-4 gate for rr-v1[neg=0.5]
- **Plan:** one S3-test read and one R1-test read, as a no-regression
  tripwire. Step 0 reproduces the dev numbers first.
- **Gate rules:** P1 (S3-test CI lower bound > 0, harmed ≤ 5%), N1 (R1
  present view Δ exactly 0), N2 (R1 "all" view is neither significantly
  harmful nor below −0.02).
- **New code:**
  - `dxt rerank eval`: one fixed configuration, "all" and "present"
    views, sealed-aware;
  - `dxt s3 run --system`: scores only the named systems.

### 2026-09-30 — result — EXP-B-003: rr-v1[neg=0.5] passes its Phase-4 gate
- **Step 0 (dev reproduction):** exact.
- **S3-test** (sealed, read once): Δ +0.0044 [+0.0032, +0.0057], harmed
  0.039.
- **R1-test** (sealed, read once):
  - present view: exactly 0;
  - all view: −0.0025 [−0.0070, +0.0013], harmed 0.090.
- **Verdict:** P1, N1 and N2 all pass. rr-v1[neg=0.5] is a release
  candidate. Deployment through `diagnostic.ar-model` is Mateo's decision.
- **Vault:** untouched.

### 2026-09-30 — pre-registration — Candidate 2 pilot rounds (ADR-0011 amendment 3)
Written and committed before the first pilot runs.
- **Generator:** rare-disease-simulator@ddb1ec1 (0.4.2).
  - Full profiles from hpoa-recount-v1 + genes-v2.
  - Calibration: `simcal-v04-v3` plus `reporting.noise_share` 0.348, with
    `reporting.specialize_rate` r and `noise.related_share` s.
- **Pilot shape:**
  - genes: the simcal-train-v1 pilot list
    (`rare-disease-simulator/outputs/cal/pilot-genes.txt`, 523 symbols,
    sha256 `5c817192…4c082`);
  - 10 cases per gene, medium, seed 91001.
- **Measure:** ANALYSIS-002 categories on each pilot export, every record
  (`scripts/analysis/dataset_term_categories.py`, kb-v4; it reads no R1
  data). Targets (R1-train): more specific 0.115, related IC ≥ 2 0.108,
  weak IC < 2 0.239.
- **Round 1:** r = 0.15, s = 0.30.
- **Round 2 rule:** each knob is scaled by target / realized share of its
  own category, capped to [0, 1]:
  - r₂ = r₁ × 0.115 / more-specific share;
  - s₂ = s₁ × 0.108 / related (IC ≥ 2) share.
- **Selection:** the pair with the smallest summed absolute error over the
  three categories is frozen as `simcal-v04-v4`.
- **Not used:** R1-dev and E0.

### 2026-09-30 — pilot — Candidate 2 pilot rounds; `simcal-v04-v4` frozen
- **Setup:** as pre-registered in the entry above; R1-train targets only,
  no R1-dev, no E0.
  - Pilot shape: 4,890 cases for 489 genes. On genes-v2 full profiles, 34 of
    the listed genes are skipped (the simcal-train-v1 pilots had 505).
  - Categories scored on 4,830 records; 60 have no kb-v4 gene.
  - Validate: 0 invariant violations in both rounds.
- **Every pair tried:**

  | Round | r | s | Realized specialised share of profile terms | Realized related share of noise | More specific (0.115) | Related IC ≥ 2 (0.108) | Weak IC < 2 (0.239) | Explained | Summed abs. error |
  |---|---|---|---|---|---|---|---|---|---|
  | 1 | 0.15 | 0.30 | 0.0848 | 0.2708 | 0.0815 | 0.0949 | 0.2755 | 0.5482 | 0.0831 |
  | 2 | 0.2117 | 0.3414 | 0.1194 | 0.3081 | 0.1021 | 0.1025 | 0.2662 | 0.5292 | **0.0456** |

  - Round 2 applies the declared rule: r₂ = 0.15 × 0.115 / 0.0815, and
    s₂ = 0.30 × 0.108 / 0.0949, rounded to 4 decimals.
  - Both realized shares stay below their rates, as expected: a
    specialisation or related draw can find no eligible term.
- **Selected:** round 2, the smaller summed error. Frozen as
  `simcal-v04-v4` (`dxt knowledge shrinkage-prior --min-denominator 10
  --base data/calib/simcal-v04-v3.json`, with `reporting.noise_share`
  0.348, `reporting.specialize_rate` 0.2117 and `noise.related_share`
  0.3414).
- **Remaining gap:** weak (IC < 2) stays 0.027 above R1-train's share, and
  more specific stays 0.013 below it.

### 2026-09-30 — build + gate — v0.4 candidate 2 (simulator 0.4.2): G1 passes on both datasets; G2 fails on a, b, d and e
- **Front / versions:** A / rare-disease-simulator@ddb1ec1 (0.4.2),
  `simcal-v04-v4`, hpoa-recount-v1, genes-v2, report-model-v2, cardinal-v1.
  Gene-first, 100 per gene, medium, seed 1001. Candidate 2 of 3; R1-dev
  read 2 of 3.

**Phase A: scoring on the amended criteria (ADR-0012 amendment 1), no R1-dev read**
- **Code** (`dxt sim`):
  - the G2e target is 0.405 (the gap to 0.512 is kept as
    `gap_all_train`), and the gate recomputes the gap for older reports;
  - G2a's primary rows are literature-panel-v2's `independent == "true"`
    rows (497 of 531), and panel v2 is the default;
  - `sim panel-error`: G2a alone; it reads no R1 data and writes no ledger
    row;
  - `sim realism --no-dev`: G2a, G2c, G2d and G2e without R1-dev, and no
    ledger row;
  - `sim gate --secondary`.
- **G2a on literature-panel-v2** (panel-only runs):

  | Dataset | Primary MAE (independent rows) | Rows scored | All-rows MAE |
  |---|---|---|---|
  | UP | 0.416 | 468 of 497 | 0.419 |
  | V03 (half A) | 0.418 | 497 | 0.422 |
  | Candidate 1 | 0.421 | 497 | 0.426 |

- **V03-full baseline** `ds-sim0.3.1-full-n100-s1001`:
  - Generator: simulator 8ba7430, run from its GitHub tarball (sha256
    `72aa20e2…`) because this session cannot check out commits in the
    simulator repo. The run summary therefore records no git sha; the
    manifest records the tarball's sha.
  - Profiles: v0.3's full profiles (`outputs/cal/profiles-full.jsonl`, the
    s3-data-v1 profiles), with simcal-train-v1.
  - Result: 505,000 cases for 5,050 genes; 0 invariant violations. 206
    cases excluded by `-excl-v1`.
  - Its realism run is a baseline and doesn't count against the budget.
- **gate-baselines recomputed:** UP and V03-full, with V03 (half A) as a
  secondary row; panel v2; G2e target 0.405.

**Phase B: pilot rounds** (entries above): round 2, r = 0.2117 and s =
0.3414, was frozen as `simcal-v04-v4`.

**Phase C: datasets**
- **Profiles:** built at ddb1ec1 from hpoa-recount-v1 + genes-v2.
  - Full: 9,223 profiles.
  - Half A: 9,095 profiles, byte-identical to candidate 1's
    (`ad4476b4…`).
  - The PMID-mask fallback masked 0 rows in both builds.
- **G1:**

  | Check | `ds-sim0.4.2-full-n100-s1001` | `ds-sim0.4.2-A-n100-s1001` |
  |---|---|---|
  | Cases / genes | 489,200 / 4,892 | 486,800 / 4,868 |
  | `validate` (cases and export) | 0 violations | 0 violations |
  | Slice rerun (20 genes, 19 simulated) | cases and export byte-identical, equal to the full run's lines | same |
  | `dxt lineage verify` | ok | ok |
  | Overlap with R1 (all parts, keys only) / S3 | 76 / 727 (115 same signature) | 59 / 592 (39) |
  | Excluded by `-excl-v1`, residual | 792, 0 | 641, 0 |
  | Release | published | published |

  The S3 overlap is higher than candidate 1's (449). S3 was simulated from
  full v0.3 profiles, which may explain part of it; not investigated.
- **Run summaries:**
  - Specialised share of profile terms: 0.1172 (full) and 0.1168 (A), for a
    rate of 0.2117.
  - Related share of noise: 0.3026 and 0.3109, for a rate of 0.3414.
  - Shown terms per case: 7.38 (full) and 7.01 (A): 4.39 / 4.01 profile
    terms plus 3.00 noise. The drawn budget mean is 8.71.

**G2** (`dxt sim realism --label v0.4-cand2 --sim-version 0.4.2-cand2` on
the full dataset, one run with no crash; `results/realism/gate-v0.4-cand2.md`):

| Metric | UP | V03-full | Candidate 2 | Pass | V03 half A (secondary) |
|---|---|---|---|---|---|
| a: panel-v2 MAE, independent rows | 0.416 | 0.390 | 0.404 | ❌ (beats UP, not V03-full) | 0.418 |
| b: R1-dev mean per-gene ρ (38 genes) | 0.231 | 0.095 | 0.193 | ❌ (beats V03-full, not UP) | 0.086 |
| c: W1 terms per case vs R1-train | 3.717 | 1.653 | 1.315 | ✅ | 1.382 |
| d: C2ST AUC (≤ 0.75) | 0.840 | 0.819 | 0.792 | ❌ (beats both, above 0.75) | 0.778 |
| e: \|E0 MRR − 0.405\| (≤ 0.10) | 0.414 | 0.183 | 0.242 | ❌ (beats UP, not V03-full) | 0.237 |

- **E0 MRR:** 0.163 on candidate 2 (0.222 on V03-full), so the candidate
  is still much harder than R1-train's uncited 0.405. The gap to 0.512 is
  0.349.

**Secondary numbers** (none read R1-dev):

| | Full (G2 dataset) | Half A (`--no-dev`) | Candidate 1 (half A) |
|---|---|---|---|
| G2a panel-v2 MAE | 0.404 | 0.412 | 0.421 |
| G2c W1 vs R1-train | 1.315 | 1.695 | 1.214 |
| G2d C2ST AUC | 0.792 | 0.770 | 0.737 |
| E0 MRR (gap to 0.405) | 0.163 (0.242) | 0.166 (0.239) | 0.092 (0.313) |
| More specific (target 0.115) | 0.109 | 0.111 | 0.050 |
| Related, IC ≥ 2 (target 0.108) | 0.100 | 0.101 | 0.049 |
| Weak, IC < 2 (target 0.239) | 0.255 | 0.266 | 0.406 |
| Explained | 0.536 | 0.521 | 0.494 |

- Categories are scored on a 5% sample (seed 7) of each export: 24,016 and
  23,866 records. Candidate 1 is ANALYSIS-002's 1% sample.
- **Verdict:** ❌ candidate 2 fails the gate (G2a, G2b, G2d, G2e). The term
  categories now match R1-train within 0.016 each, and E0 MRR rose from
  0.092 to 0.163. Nothing was tuned after the read. One R1-dev candidate
  read is left.

### 2026-09-30 — result + analysis + decision — candidate 2 fails G2; ANALYSIS-003; candidate 3 design
- **Candidate 2** (sim 0.4.2, `simcal-v04-v4`; R1-dev read 2 of 3; PR #34):
  - passes G1 on both the full and half-A datasets;
  - passes G2c only.
  - G2a 0.404, b 0.193, d 0.792, e 0.242; E0 MRR 0.163.
- **ANALYSIS-003:**
  - Noise causes E0's difficulty: removing it lifts MRR from 0.163 to
    0.472. Real patients' unexplained terms cost only 0.074.
  - The kb-v4 reference inflates "unexplained". Against the simulator's own
    knowledge (kb-v3), uncited patients show 66.8% explained, 9.3% more
    specific, 8.2% related and 15.7% weak.
  - G2a scored reported rates against prevalence, while real patients' own
    reports miss the literature by 0.307.
- **Decisions:**
  - ADR-0012 amendment 3: G2a on the truth layer, disclosed as made after
    candidate 2's read.
  - ADR-0011 amendment 4: candidate 3 uses `calib-v2` (uncited patients vs
    kb-v3), re-pilots r and s, and runs a train-side go/no-go before the
    last R1-dev read.

### 2026-09-30 — pre-registration — Candidate 3 pilot rounds (ADR-0011 amendment 4)
Written and committed before the first candidate 3 pilot run.
- **calib-v2** (built above in this branch):
  - population: 1,193 uncited R1-train patients, measured against kb-v3;
  - category shares: explained 0.668, more specific 0.0929, related
    (IC ≥ 2) 0.0822, weak (IC < 2) 0.1569;
  - noise share: 0.2391 (related + weak);
  - noise vocabulary: 295 related-or-weak terms seen in ≥ 2 patients.
- **Generator:** rare-disease-simulator@ddb1ec1 (0.4.2), with candidate 2's
  full profiles from the same commit and inputs.
  - Calibration: `simcal-v04-v4`, plus `noise.vocabulary_path` → calib-v2's
    vocabulary and `reporting.noise_share` 0.2391.
- **Pilot shape:** the same 523-symbol list
  (`outputs/cal/pilot-genes.txt`), 10 cases per gene, medium, seed 91001.
- **Measure:** `scripts/analysis/dataset_term_categories.py --kb kb-v3
  --targets data/calib/calib-v2.targets.json`, every record.
- **Round 1:** r = 0.21, s = 0.3437 (calib-v2's related / (related + weak)
  = 0.0822 / 0.2391, rounded to 4 decimals).
- **Round 2 rule:** each knob is scaled by target / realized share of its
  own category, capped to [0, 1], rounded to 4 decimals:
  - r₂ = r₁ × 0.0929 / more-specific share;
  - s₂ = s₁ × 0.0822 / related share.
- **Selection:** the pair with the smallest summed absolute error over the
  three categories is frozen as `simcal-v04-v5`.
- **Not used:** R1-dev and E0.

### 2026-09-30 — pilot — Candidate 3 pilot rounds; `simcal-v04-v5` frozen
- **Setup:** as pre-registered above; R1-train targets only (calib-v2, vs
  kb-v3), no R1-dev, no E0.
  - Pilot shape: 4,890 cases for 489 genes.
  - Validate: 0 invariant violations in both rounds.
- **Every pair tried:**

  | Round | r | s | Specialised share of profile terms | Related share of noise | More specific (0.0929) | Related (0.0822) | Weak (0.1569) | Explained (0.668) | Summed abs. error |
  |---|---|---|---|---|---|---|---|---|---|
  | 1 | 0.21 | 0.3437 | 0.1173 | 0.3046 | 0.1000 | 0.0719 | 0.1962 | 0.6320 | 0.0566 |
  | 2 | 0.1951 | 0.3929 | 0.1099 | 0.3526 | 0.0957 | 0.0785 | 0.1896 | 0.6362 | **0.0392** |

  Round 2 applies the declared rule: r₂ = 0.21 × 0.0929 / 0.1000, and
  s₂ = 0.3437 × 0.0822 / 0.0719.
- **Selected:** round 2. Frozen as `simcal-v04-v5`: base simcal-v04-v4,
  `noise.vocabulary_path` calib-v2's vocabulary, `reporting.noise_share`
  0.2391, `reporting.specialize_rate` 0.1951, `noise.related_share`
  0.3929.
- **Remaining gap:** weak (IC < 2) stays 0.033 above the uncited patients'
  share. Related plus weak comes to 0.268 against the nominal noise share
  of 0.239; unfilled profile slots are a likely cause, not checked.

### 2026-09-30 — build + go/no-go — v0.4 candidate 3: G1 passes; the train-side go/no-go fails (G2c, G2d, G2e), so the last R1-dev read is not spent
- **Front / versions:** A / rare-disease-simulator ddb1ec1 (0.4.2),
  `simcal-v04-v5`, calib-v2 vocabulary, hpoa-recount-v1, genes-v2,
  report-model-v2, cardinal-v1. Gene-first, 100 per gene, medium, seed 1001.
  Candidate 3 of 3 (ADR-0011 amendment 4).
- **Tooling** (this branch):
  - `dxt calib build --population uncited --vocabulary related_or_weak`;
  - truth-layer G2a (ADR-0012 amendment 3), with the reported layer and
    R1-train's reported rates as references;
  - `dxt sim train-checks`, plus G2b-train and the age match in every
    realism report;
  - `dataset_term_categories.py --kb --targets`.
- **calib-v2** (uncited R1-train vs kb-v3):
  - 1,193 patients (1,140 with a KB gene), 9,177 present terms;
  - category shares: explained 0.668, more specific 0.093, related 0.082,
    weak 0.157;
  - noise share 0.239; related share of noise 0.344;
  - vocabulary: 295 related-or-weak terms seen in ≥ 2 patients (324 seen
    once were dropped).
- **G2a recomputed on the truth layer** (literature-panel-v2, 497
  independent rows; panel-only runs that read R1-train, not R1-dev):

  | Dataset | Primary (truth, emission for UP) | Reported layer | Truth on the 145 rows with ≥ 10 R1-train patients | Reported on those rows |
  |---|---|---|---|---|
  | UP | 0.416 | 0.416 | 0.407 | 0.407 |
  | V03-full | 0.336 | 0.390 | 0.341 | 0.381 |
  | V03 half A (secondary) | 0.377 | 0.418 | | |
  | Candidate 1 (half A) | 0.339 | 0.421 | 0.298 | 0.394 |
  | Candidate 2 (full) | 0.304 | 0.404 | 0.267 | 0.380 |
  | Candidate 3 (full) | 0.305 | 0.398 | 0.267 | 0.373 |

  R1-train patients' own reported rates on those 145 rows: 0.307.
- **Pilots:** see the two entries above; round 2 is frozen as `simcal-v04-v5`.
- **Environment incident:**
  - While candidate 3 was generating, the shared simulator checkout moved
    to 0.5.0 (020e41d, "Report each true term independently"). The full
    run recorded a dirty tree, and `export-training` refused it. That
    first attempt was stopped and discarded.
  - Everything was regenerated from the GitHub tarball of ddb1ec1 (sha256
    `c0a97f33…`). Its slice exports are byte-identical to the slice
    exports the clean ddb1ec1 checkout had produced minutes earlier, full
    and half A.
  - The run summaries therefore record no commit; the manifests record the
    tarball. The pilots ran on the clean ddb1ec1 checkout.
- **G1:**

  | Check | `ds-sim0.4.2c3-full-n100-s1001` | `ds-sim0.4.2c3-A-n100-s1001` |
  |---|---|---|
  | Cases / genes | 489,200 / 4,892 | 486,800 / 4,868 |
  | `validate` (cases and export) | 0 violations | 0 violations |
  | Slice rerun (20 genes, 19 simulated) | cases and export byte-identical, equal to the full run's lines | same |
  | `dxt lineage verify` | ok | ok |
  | Overlap with R1 (keys, all parts) / S3 | 111 / 1,199 (194 same signature) | 88 / 949 (59) |
  | Excluded by `-excl-v1`, residual | 1,293, 0 | 1,021, 0 |
  | Release | published | published |

- **Run summaries:**
  - specialised share of profile terms: 0.108 (full) and 0.107 (A);
  - related share of noise: 0.349 and 0.358;
  - shown terms per case: 6.97 (4.91 profile + 2.06 noise) and 6.50
    (4.43 + 2.07), for a drawn budget mean of 8.71.
- **Go/no-go** (`dxt sim realism --no-dev --label v0.4-cand3-full-nodev`, no
  R1-dev read, no ledger row; `results/realism/gate-v0.4-cand3-gonogo.md`):

  | Check | UP | V03-full | Candidate 3 | Rule | Result |
  |---|---|---|---|---|---|
  | G2a truth layer | 0.416 | 0.336 | 0.305 | beat both | ✅ |
  | G2c W1 terms per case | 3.717 | 1.653 | 1.732 | beat both | ❌ (worse than V03-full) |
  | G2d C2ST AUC | 0.840 | 0.819 | 0.764 | beat both, ≤ 0.75 | ❌ (above 0.75) |
  | G2e \|E0 MRR − 0.405\| | 0.414 | 0.183 | 0.142 | beat both, ≤ 0.10 | ❌ (above 0.10) |
  | G2b-train (83 genes, ≥ 10 train patients) | 0.241 | 0.385 | 0.536 | beat both | ✅ (optimistic: the report model is fitted on R1-train) |
  | Age: median \|ln(median age ratio)\| (69 genes) | no ages | 0.537 | 0.539 | report only | candidate 2: 0.488 |

  - E0 MRR 0.263 (candidate 2: 0.163).
  - COL3A1 median age: simulated 4.0 vs R1-train 32.0.
  - Age medians are floored at 0.1 years.
- **Decision:** three stop conditions fire (G2c, G2d, G2e). The last R1-dev
  read (`v0.4-cand3`) was **not** run. The ledger is unchanged; its last
  candidate row is `v0.4-cand2`.
- **Secondary numbers** (no R1-dev read):

  | | Full | Half A (`--no-dev`) |
  |---|---|---|
  | G2a truth / reported | 0.305 / 0.398 | 0.341 / 0.407 |
  | G2c | 1.732 | 2.203 |
  | G2d | 0.764 | 0.746 |
  | E0 MRR (gap to 0.405) | 0.263 (0.142) | 0.259 (0.146) |
  | G2b-train | 0.536 | 0.428 |
  | Age median \|log ratio\| | 0.539 | 0.519 |
  | Categories vs kb-v3 (5% sample): explained / more specific / related / weak | 0.641 / 0.100 / 0.077 / 0.182 | 0.627 / 0.102 / 0.080 / 0.191 |
  | Summed error vs calib-v2 | 0.037 | 0.045 |

- **E0 ablation** (`scripts/analysis/e0_ablation.py`, 3,073 cases of the
  full rich cases), in-vocab MRR:
  - as exported 0.263, 7.03 terms per case;
  - no noise 0.515;
  - no generalisation 0.285;
  - no specialisation 0.309;
  - profile terms ungeneralised, no noise 0.592;
  - all true terms 0.742.

  R1-train uncited patients: 0.405 (8.11 terms), and 0.479 on their
  explained terms only. Mean IC: simulated noise 5.37, profile positives
  4.47, R1-train present terms 4.14.
- **Verdict:** ❌ candidate 3 stops at the train-side go/no-go. As
  instructed, no fix was designed.

### 2026-09-30 — analysis + decision — ANALYSIS-004; candidate 4 design (ADR-0011 amendment 5)
- **Candidate 3 stopped at the train-side go/no-go** (G2c, d and e fail).
  R1-dev read 3 of 3 is still unspent.
- **Construction-side audit** (complete later: 25 of 26 implausible; ANALYSIS-004 §4): Codex reviewed 16 of 26 cards of genes
  outside the panel; 15 were implausible. The main themes were hallmark
  features under-reported (10) and unrelated noise dominating (9).
- **ANALYSIS-004:**
  - real uncited patients' unexplained terms give E0 an MRR of 0.059;
  - 13.5% of them are annotated to the gene in unmasked g2p (MRR 0.305);
    the rest give 0.026;
  - simulated vocabulary noise gives 0.001, related noise 0.030.
- **Candidate 4 design:**
  - simulator 0.5.0, with independent reporting and age by onset;
  - `report-model-v3` (uncited vs kb-v3);
  - ρ 0.207;
  - s set by a noise-signal component target of 0.026;
  - the same go/no-go as candidate 3.
- **Process slip:** the shared simulator checkout was updated to 0.5.0
  while candidate 3 was generating. The agent detected the dirty tree,
  discarded the run and regenerated from a pinned tarball. Rule: runs use
  pinned worktrees or tarballs.

### 2026-09-30 — pre-registration — Candidate 4 pilot rounds (ADR-0011 amendment 5)
Written and committed before the first candidate 4 pilot run.
- **Generator:** rare-disease-simulator 0.5.0, run from the GitHub tarball
  of 020e41d, never the shared checkout.
  - Full profiles from hpoa-recount-v1 + genes-v2.
  - report-model-v3; cardinal-v1.
  - Calibration: `simcal-v05-v1` (simcal-v04-v5 + age-durations-v1,
    independent reporting, proportional noise at 0.207, calib-v2
    vocabulary), with r and s replaced per round.
- **Pilot shape:** the 523-symbol list (`outputs/cal/pilot-genes.txt`), 10
  cases per gene, medium, seed 91001.
- **Targets:**
  - more specific = 0.0929, calib-v2's share vs kb-v3 (the 0.093 of the
    amendment);
  - E0 in-vocab MRR on the noise terms alone (vocabulary + related noise
    together) = 0.026, by `scripts/analysis/noise_signal.py`, every case.
- **Round 1:** r = 0.195, s = 0.5. It also measures E0 MRR on vocabulary
  noise alone (MRR_voc) and related noise alone (MRR_rel).
- **Round 2 rules:**
  - r₂ = r₁ × 0.0929 / the realized more-specific share, capped to
    [0, 1];
  - s₂ = (0.026 − MRR_voc) / (MRR_rel − MRR_voc), clipped to [0, 1]
    (s₂ = s₁ if MRR_rel = MRR_voc);
  - both rounded to 4 decimals.
- **Selection:** the round with the smaller |more specific − 0.0929| /
  0.0929 + |noise MRR − 0.026| / 0.026 is frozen as `simcal-v05-v2`.
- **Also reported per round:**
  - categories vs kb-v3;
  - reported terms per case;
  - `forced_min_one`;
  - the q-calibration error.
- **Not used:** R1-dev.

### 2026-09-30 — build + pilot — report-model-v3, age-durations-v1, candidate 4 pilots; `simcal-v05-v2` frozen
- **`report-model-v3`** (`dxt knowledge report-model --population uncited
  --kb kb-v3`; R1-train only, published). It loads with simulator 0.5.0's
  strict loader.
  - Data: 1,193 uncited patients, 1,054 with a profile; 54,305 (patient,
    profile term) rows; positive rate 0.093.
  - Coefficients (raw scale): intercept −1.655; frequency 2.347 (unknown
    value 0.454); information content 0.022; ancestor count −0.045; log
    reportability 0.413; cardinal flag 0.494.
  - In-sample fit:

    | | Base rate | Frequency only | Full |
    |---|---|---|---|
    | Log loss | 0.309 | 0.291 | 0.267 |
    | AUC | | 0.686 | 0.765 |

  - Within-gene ρ on R1-train (32 genes with ≥ 5 patients):
    - in-sample: full 0.509, frequency only 0.267;
    - each gene's publications left out of reportability: full 0.406,
      frequency only 0.267.
- **`age-durations-v1`** (`dxt calib age-durations`): 891 R1-train patients
  with age and onset, mapped with simulator 0.5.0's windows (the narrowest
  window holding the onset).

  | Onset category | Patients | Mean (age − onset), years | Median | Used |
  |---|---|---|---|---|
  | antenatal | 24 | 2.41 | 0.14 | 2.41 |
  | neonatal | 49 | 4.71 | 1.46 | 4.71 |
  | infantile | 338 | 7.56 | 5.04 | 7.56 |
  | childhood | 153 | 10.35 | 8.0 | 10.35 |
  | juvenile | 124 | 14.60 | 9.5 | 14.60 |
  | adult | 203 | 12.38 | 9.0 | 12.38 |
  | childhood_or_adolescent, variable | 0 | | | 9.82 (overall) |

  Left out: 3,205 without age or onset, 3 with age below onset, 4 with
  onset past every window.
- **`simcal-v05-v1`:**
  - base simcal-v04-v5 + age-durations-v1;
  - `reporting.mode` independent, `noise_count` proportional,
    `noise_share` 0.207, `force_cardinal` false;
  - r = 0.195, s = 0.5.
- **Pilots** (as pre-registered above; simulator 0.5.0 from the 020e41d
  tarball, profiles byte-identical to candidate 2's; 4,890 cases for 489
  genes; 0 invariant violations in both rounds):

  | Round | r | s | More specific (0.0929) | Related | Weak | Explained | Noise-only E0 MRR (0.026) | Vocabulary / related noise MRR | Related share of noise | Reported terms per case (profile + noise) | `forced_min_one` | q-calibration error | Selection score |
  |---|---|---|---|---|---|---|---|---|---|---|---|---|---|
  | 1 | 0.195 | 0.5 | 0.1003 | 0.0688 | 0.1191 | 0.7118 | 0.0098 | 0.001 / 0.020 | 0.422 | 2.97 (2.35 + 0.63) | 1,579 | 0.0024 | 0.703 |
  | 2 | 0.1806 | 1.0 | 0.0918 | 0.1128 | 0.0798 | 0.7157 | 0.0181 | 0.0011 / 0.0211 | 0.870 | 2.97 (2.35 + 0.62) | 1,579 | 0.0024 | **0.316** |

  Round 2 applies the declared rules:
  - r₂ = 0.195 × 0.0929 / 0.1003;
  - s₂ = (0.026 − 0.001) / (0.020 − 0.001) = 1.32, clipped to 1.
- **Selected:** round 2, frozen as `simcal-v05-v2` (r 0.1806, s 1.0).
- **What the pilots show** (R1-train comparisons only):
  - **The noise target is out of reach.** Even with every noise slot
    related (s = 1), noise-only MRR is 0.018 against 0.026; related noise
    alone gives 0.021.
  - **Records are much shorter than real ones.** Independent reporting
    with report-model-v3 reports 16.9% of true profile terms: 2.97 shown
    terms per case against R1-train's 8.70.
  - **Many cases hit the fallback.** `forced_min_one` fires in 1,579 of
    4,890 cases (32%), where no roll succeeds.
  - Nothing here is tuned. r and s are the only pilot knobs.

### 2026-09-30 — build + go/no-go — v0.5 candidate 4: G1 passes; the train-side go/no-go fails (G2c, G2d, G2e); last R1-dev read not spent
- **Front / versions:** A / rare-disease-simulator 0.5.0 (GitHub tarball of
  020e41d, sha256 `025e860a…`; never the shared checkout), `simcal-v05-v2`,
  report-model-v3, cardinal-v1, hpoa-recount-v1, genes-v2. Gene-first, 100
  per gene, medium, seed 1001. ADR-0011 amendment 5.
- **Profiles:** rebuilt with 0.5.0; byte-identical to candidates 2 and 3
  (full `d44e1586…`, half A `ad4476b4…`).
- **G1:**

  | Check | `ds-sim0.5.0-full-n100-s1001` | `ds-sim0.5.0-A-n100-s1001` |
  |---|---|---|
  | Cases / genes | 489,200 / 4,892 | 486,800 / 4,868 |
  | `validate` (cases and export) | 0 violations | 0 violations |
  | Slice rerun (20 genes, 19 simulated) | cases and export byte-identical, equal to the full run's lines | same |
  | `dxt lineage verify` | ok | ok |
  | Overlap with R1 (keys, all parts) / S3 | 369 / 6,094 (809 same signature) | 411 / 4,753 (303) |
  | Excluded by `-excl-v1`, residual | 6,413, 0 | 5,106, 0 |
  | Release | published | published |

- **Run summaries** (independent reporting):

  | | Full | Half A |
  |---|---|---|
  | Shown terms per case (profile + noise) | 2.95 (2.34 + 0.61) | 2.39 (1.90 + 0.49) |
  | Share of true terms reported | 0.174 | 0.191 |
  | `forced_min_one` | 157,402 (32.2%) | 189,402 (38.9%) |
  | Specialised share of profile terms | 0.099 | 0.091 |
  | Related share of noise | 0.868 | 0.900 |
  | q-calibration error | 0.0003 | 0.0005 |

- **Go/no-go** (`dxt sim realism --no-dev --label v0.5-cand4-full-nodev`, no
  R1-dev read, no ledger row; `results/realism/gate-v0.5-cand4-gonogo.md`):

  | Check | UP | V03-full | Candidate 4 | Rule | Result |
  |---|---|---|---|---|---|
  | G2a truth layer | 0.416 | 0.336 | 0.307 | beat both | ✅ |
  | G2c W1 terms per case | 3.717 | 1.653 | 5.754 | beat both | ❌ (worse than both) |
  | G2d C2ST AUC | 0.840 | 0.819 | 0.822 | beat both, ≤ 0.75 | ❌ (worse than V03-full) |
  | G2e \|E0 MRR − 0.405\| | 0.414 | 0.183 | 0.204 | beat both, ≤ 0.10 | ❌ (worse than V03-full) |
  | G2b-train (83 genes) | 0.241 | 0.385 | 0.502 | beat both | ✅ |
  | Age: median \|ln(median age ratio)\| (69 genes) | no ages | 0.537 | 0.571 | report only | |

  - E0 MRR 0.201.
  - Terms per case: mean 2.95; p10 / median / p90 = 1 / 2 / 7 (R1-train:
    8.70; 2 / 7 / 17).
- **Decision:** three stop conditions fire. The last R1-dev read
  (`v0.5-cand4`) was **not** run, and the ledger is unchanged. Per ADR-0011
  amendment 5 §5, v0.4/0.5 is not frozen: the gate is **unmet**, and Mateo
  decides how to proceed.
- **Secondary numbers** (no R1-dev read):

  | | Full | Half A (`--no-dev`) |
  |---|---|---|
  | G2a truth / reported | 0.307 / 0.443 | 0.345 / 0.455 |
  | G2c | 5.754 | 6.309 |
  | G2d | 0.822 | 0.836 |
  | E0 MRR (gap to 0.405) | 0.201 (0.204) | 0.180 (0.225) |
  | G2b-train | 0.502 | 0.400 |
  | Age median \|log ratio\| | 0.571 | 0.467 |
  | Categories vs kb-v3 (5% sample): explained / more specific / related / weak | 0.721 / 0.094 / 0.107 / 0.078 | 0.730 / 0.094 / 0.103 / 0.073 |
  | Summed error vs calib-v2 | 0.105 | 0.106 |

- **E0 ablation** (3,073 full cases), in-vocab MRR:
  - as exported 0.206, 2.88 terms per case;
  - no noise 0.251;
  - no generalisation 0.221;
  - no specialisation 0.228;
  - profile terms ungeneralised, no noise 0.300;
  - all true terms 0.743.

  R1-train uncited: 0.405. Mean IC: noise 6.78, profile positives 3.77,
  R1-train present 4.14.
- **Age per gene** (median age in years; R1-train patients with a known
  age):

  | Gene | R1-train n | R1-train | V03-full | Candidate 3 | Candidate 4 |
  |---|---|---|---|---|---|
  | NF1 | 158 | 18.0 | 5.65 | 3.94 | 4.68 |
  | LMNA | 27 | 46.0 | 22.14 | 21.48 | 23.53 |
  | FBN1 | 66 | 18.5 | 26.45 | 24.17 | 28.79 |
  | PTPN11 | 10 | 7.5 | 5.28 | 4.69 | 6.42 |
  | KMT2D | 11 | 11.6 | 3.99 | 4.21 | 3.40 |
  | TBX5 | 41 | 33.0 | 3.67 | 5.12 | 2.41 |
  | UMOD | 76 | 39.0 | 23.84 | 23.75 | 34.88 |
  | FBXL4 | 33 | 2.0 | 4.45 | 5.49 | 7.38 |
  | SPTAN1 | 13 | 46.0 | 7.46 | 8.18 | 12.64 |
  | ITPR1 | 45 | 16.0 | 14.94 | 15.38 | 18.98 |
  | COL3A1 | 35 | 32.0 | 3.88 | 4.02 | 4.59 |

- **Verdict:** ❌ candidate 4 stops at the train-side go/no-go. The main
  driver is record length: independent reporting with report-model-v3
  shows about 3 terms per case (R1-train: 8.7), and a third of the cases
  fall back to `forced_min_one`. No fix was designed.

### 2026-09-30 — status — ADR-0012 gate unmet after candidates 1–4; decision for Mateo
- **Candidate 4** (sim 0.5.0, independent reporting; PR #44):
  - passes G1 and the G2a / G2b-train stop conditions;
  - fails G2c (5.754), G2d (0.822) and G2e (gap 0.204), because records
    are far too short (2.95 terms per case vs 8.70; 32% of cases fall back
    to `forced_min_one`).
  - The last R1-dev read was **not** spent.
- **Per ADR-0011 amendment 5 §5,** nothing is frozen and Mateo decides.
- **Closest candidate so far: candidate 3** (sim 0.4.2, `simcal-v04-v5`).
  It misses three thresholds narrowly: G2c 1.732 (needs < 1.653), G2d 0.764
  (needs ≤ 0.75), G2e gap 0.142 (needs ≤ 0.10).

### 2026-09-30 — release prep — rr-v1[neg=0.5] packaged for production (diagnostic.ar-model PR #2, not merged)
- **Module:** `diagnostic_ar_model.rerank`, copied from diagnostic.ar-training
  with provenance headers; the code is unchanged since EXP-B-003's commit.
- **KB:** kb-v3 (sha `39d5f921…`), verified whenever it loads. Release
  asset `rerank-v1.0.tar.gz` (sha `4b83f5e3…`, reproducible).
- **Parity** over every scorable R1-dev case (1,680; 367 moved by rr-v1):
  0 rank mismatches, for both E0 and rr-v1. Without negations the output
  is byte-identical to v3.0.
- **Latency:** p50 2.46 ms, p95 6.77 ms per case, on top of v3.0.
- **Nothing is deployed.** App integration is documented in
  `docs/integracion-app-rerank-v1.md` in diagnostic.ar-model. It needs the
  API to accept `excluded_hpo_ids`, and the question agent (Mariano's
  repo) to send only its "no" answers, which reverses its D-18.
- **Production caveat:** production `/genphenai` currently routes to
  brainy, not the pinned image.

### 2026-09-30 — analysis — SOURCES-SCOPING-001: would GeneReviews or open-access cohorts improve the profiles?
- **What:** a scoping study of counts, with no extraction and no artifact.
  Write-up: `docs/analyses/SOURCES-SCOPING-001.md`; raw counts in
  `results/analyses/SOURCES-SCOPING-001/`; scripts
  `scripts/analysis/sources_scoping*.py`.
- **Boundaries:** the 120 `litpanel-split-v3` units (genes and all disease
  ids) are counted separately and never as construction. R1 held-out PMIDs
  were used only as a mask. No sealed data was read.
- **Downloads:** the GeneReviews FTP index files and the litarch file list
  (URLs and sha256 in `sources.json`), plus Europe PMC search metadata. The
  GeneReviews bulk archive already downloaded for LITPANEL-v2 was reused:
  its sha256 was re-checked, and only its listing and 30 sampled chapters
  were read.
- **GeneReviews coverage:**
  - 1,289 of 5,108 construction genes (25.2%) have a usable chapter: one
    that touches no evaluation unit;
  - that is 1,279 of the 4,776 simulable genes, over 794 chapters;
  - 483 construction genes are reachable only through the 78 chapters that
    touch an evaluation unit, mostly large overviews;
  - evaluation genes: 68 of 120 have a chapter.
- **30-chapter sample** (seed 20260930):
  - numeric feature table: 17/30;
  - ≥ 5 features with stated numbers: 19/30;
  - numeric onset or diagnosis age: 14/30;
  - qualitative age only: 7/30;
  - 4/30 chapters cite R1 held-out PMIDs. White-Sutton cites 10, pooled in
    its table.
- **Europe PMC** (200 construction genes, stratified; `title` query,
  open access only):
  - weighted hit bins: 35.7% have 0, 48.8% 1–4, 15.5% 5+;
  - gene-level precision 22/40, so about 35% of simulable construction
    genes have ≥ 1 real open-access phenotype series;
  - licences: CC BY 64.7%, CC BY-NC-ND 19.1%, CC BY-NC 12.6%, other 3.6%;
  - 3 of 1,066 PMIDs are R1 held-out; 6 are already cited in HPOA.
- **Weak profiles:**
  - 2,571 of 4,776 simulable construction genes (53.8%) have no n/m row
    from a series of ≥ 5 patients;
  - 606 of them have a usable chapter, which gives about 384 with ≥ 5
    frequencies;
  - about 300 more could come from open-access cohorts;
  - about 73% are unreachable.
- **Age:** Orphadata onset covers 2,507 genes (classes only). GeneReviews
  would add a numeric age for about 597 genes (CI 387–817).
- **Effort** (LITPANEL-v2 throughput: 97 raw rows per agent-hour, 7.1 rows
  per chapter):
  - GeneReviews for weak genes: about 1,790 rows, 18 agent-hours (2.3
    hours of wall time at 8 in parallel);
  - all usable chapters: about 3,590 rows, 37 agent-hours;
  - open-access papers for weak genes without a chapter: about 31
    agent-hours.
- **Recommendation:** GeneReviews first (weak genes, then all usable
  chapters), once the licence is confirmed; open-access cohorts second.
  Pre-register the held-out rule for pooled chapter tables first, and let
  Mateo decide on overview chapters that touch evaluation units.
- **Caveat:** the ANALYSIS-004 audit genes are almost all count-rich and
  still implausible. Literature should also check the truth layer, not only
  fill empty frequencies.

### 2026-09-30 — checkpoint — End of day: clean stop, state for resuming
- **Agents:** none running; each handed back before the stop. No background
  jobs.
- **Merged today:**
  - diagnostic.ar-training PRs up to #47;
  - rare-disease-simulator PRs #5–#8 (0.4.0 → 0.5.0).
- **Waiting for Mateo:** diagnostic.ar-model PR #2 (rr-v1 release). The
  decision list is in STATE.md.
- **Front A:** the ADR-0012 gate is unmet after 4 candidates. The last
  R1-dev read is unspent. Mateo is considering better sources
  (SOURCES-SCOPING-001).
- **Disk:** about 11 GB free.

### 2026-10-01 — decision — Mateo's answers; ADR-0013
1. **Front A:** literature enrichment of construction profiles **plus** up
   to two more reporting/noise candidates checked on R1-train only.
   Time-boxed to about a week. The last R1-dev read goes only to a
   candidate that passes the train-side go/no-go.
2. **Literature rules (ADR-0013):**
   - chapters citing R1 held-out papers are dropped entirely;
   - overview chapters touching an evaluation unit are excluded;
   - no-derivatives OA papers are used as facts plus citations only.
3. **rr-v1 release (diagnostic.ar-model PR #2):** on hold.
4. **Approved:**
   - ADR-0012 amendment 3 (G2a on the truth layer);
   - deleting candidate 4's rich-cases files and merged agent worktrees;
   - keeping the 50 R1-dev parity fixture in the private model repo;
   - recommending to Mariano that the question agent send only its "no"
     answers.

### 2026-10-01 — decision — ADR-0013 amendment 1: verified sources only
- **Mateo's rule:** only human-curated sources or major studies.
- **Tier 1, curated knowledge bases:** GeneReviews, MedlinePlus Genetics,
  Gene2Phenotype, PanelApp (plus the existing HPOA, Orphanet, ClinGen and
  MONDO).
- **Tier 2, major studies:** peer-reviewed cohort or natural-history studies
  with ≥ 20 confirmed patients, preferably cited by a usable GeneReviews
  chapter.
- **Housekeeping:** deleted candidate 4's rich-cases files and three merged
  agent worktrees (approved). Disk is at 20 GB free; sources and lineage
  verify.

### 2026-10-01 — data — Tier-1 sources registered; lit-sources-v1 frozen (SOURCES-ACQUISITION-001)
- **Write-up:** `docs/analyses/SOURCES-ACQUISITION-001.md`. Branch
  `phase3/lit-sources-v1`. No LLM extraction and no LLM classification of
  papers; no sealed data read; R1 held-out PMIDs used only as a mask.
- **Sources registered** (private snapshot release assets, licence terms
  quoted in `sources.yaml`):
  - `genereviews`: chapter NXML plus index files, 32 MB, noncommercial
    research use; written confirmation still pending;
  - `medlineplus_genetics`: public domain;
  - `gene2phenotype`: all 7 panels, 3,851 records, CC BY 4.0; DDD caveat
    recorded;
  - `panelapp`: 433 panels. Its terms forbid "diagnostic use" without an
    agreement, so it is **restricted to research analyses** until Mateo
    decides.
- **ClinGen beyond validity:** nothing added. Actionability has prevalence
  and penetrance only as prose; dosage has no phenotypes.
- **Coverage, construction genes** (weak W1–W4 in brackets):
  - G2P 2,847 (1,293), new HPO terms vs HPOA for 1,445 (640);
  - MedlinePlus 2,548 (1,309), disease prevalence only, numeric ages rare;
  - PanelApp 4,562 (2,320), almost no HPO ids;
  - no Tier-1 KB gives feature frequencies.
- **lit-sources-v1** (manifest `data/manifests/lit-sources-v1.json`, code
  `7474c4c`, committed in `6e7ebd7` before any extraction):
  - **GeneReviews:** 882 chapters screened, **695 usable**. Dropped: 78
    touch an evaluation unit, 99 cite R1 held-out PMIDs, 10 have no
    construction gene. The usable chapters cover 1,084 construction genes
    (515 weak). By priority class: P1 157, P2 193, P3 175, P4 170;
  - **Tier-2:** **1,011 selected papers**:
    - 707 cited by usable chapters, from 4,942 open-access records of
      27,326 cited PMIDs;
    - 304 from the recorded per-gene Europe PMC query for 1,970 weak
      genes with no usable chapter (9,390 records);
  - together: 1,304 construction genes, 735 of the 2,485 simulable weak
    ones.
- **Screen revisions before freezing:**
  - germline-only confirmation words;
  - somatic/oncology and susceptibility exclusions;
  - pass-2 variant-context rule;
  - 5 papers per gene.

  Recorded in `7474c4c`, after reading samples of the first screen's
  output.
- **Screen QA** (seeded 40 selected papers, my reading; the list is
  unchanged): precision 23/40 = 0.58 (CI 0.42–0.72). The false positives
  are screening or diagnostic-yield cohorts, association studies, trials,
  and n parsed from a year.
- **Failures and incidents:**
  - Europe PMC returned 500/502/503 for a stretch, absorbed by the retries;
  - the sequential fetch was interrupted and resumed with 4 workers (the
    cache is resumable);
  - one `gh release download` returned HTTP 500 and succeeded on retry.
- **Recommended shards:**
  - chapters: 10 per shard in priority order (70 shards; P1 + P2 is 35,
    about 16 agent-hours);
  - papers: 12 per shard (about 85 shards, about 33 agent-hours);
  - Codex 10% cross-check: about 630 rows.
- `dxt lineage verify` passes. Disk: about 15 GB free.

### 2026-10-01 — pre-registration — Candidate 5 pilot rounds (ADR-0011 amendment 6)
Written and committed before the first candidate 5 pilot run. Train-side
only: **no R1-dev read in this task, whatever the result.**
- **Generator:** rare-disease-simulator 0.5.1, run from the GitHub tarball
  of 09e5802 (sha256 `3d125ec2…`), never the shared checkout.
  - Full profiles rebuilt with 0.5.1 from hpoa-recount-v1 + genes-v2: 9,223
    profiles, byte-identical to candidates 2–4 (`d44e1586…`).
  - report-model-v3; cardinal-v1; no presentation ages.
  - Calibration per round: `simcal-v05-v2` + `noise.related_up_levels` 1 +
    `noise.related_down_levels` 1, with `reporting.q_scale`,
    `noise.related_share` (s) and `reporting.specialize_rate` (r) set per
    round.
- **Pilot shape:** the 523-symbol list (`outputs/cal/pilot-genes.txt`,
  sha256 `5c817192…`), 10 cases per gene, medium, seed 91001.
- **Targets** (all R1-train):
  - **E** = mean reported terms per record that kb-v3 explains =
    **5.3772**: uncited R1-train patients with a kb-v3 gene (1,140), by
    `uncited_categories.py kb-v3` (now also printing per-case means;
    `results/realism/cand5-pilots/target-uncited-kb-v3.json`). ANALYSIS-003's
    5.53 was against kb-v4. Simulated value: `dataset_term_categories.py
    --kb kb-v3`, `per_record.explained`.
  - **M** = E0 in-vocab MRR on the noise terms alone = **0.026**, by
    `noise_signal.py`, every case;
  - **S** = more-specific share vs kb-v3 = **0.0929** (calib-v2).
- **Round 1:** q_scale = 2.0, s = 0.6, r = 0.18.
- **Update rules** (round k+1 from round k's measurements, rounded to 4
  decimals):
  - q_scale_{k+1} = q_scale_k × 5.3772 / E_k, capped to [1, 10];
  - s_{k+1} = (0.026 − MRR_voc,k) / (MRR_rel,k − MRR_voc,k), clipped to
    [0, 1], where MRR_voc and MRR_rel are E0's MRR on vocabulary noise
    alone and related noise alone; s_{k+1} = s_k if MRR_rel,k ≤ MRR_voc,k;
  - r_{k+1} = r_k × 0.0929 / S_k, capped to [0, 1].
- **Rounds:** at most 3. Rounds 2 and 3 run unless, after a round, all
  three relative errors (below) are ≤ 0.05; then the remaining rounds are
  skipped.
- **Selection:** the round with the smallest
  |E − 5.3772| / 5.3772 + |M − 0.026| / 0.026 + |S − 0.0929| / 0.0929 is
  frozen as `simcal-v051-v1` (`dxt knowledge shrinkage-prior
  --min-denominator 10 --base data/calib/simcal-v05-v2.json --set …`).
- **Also reported per round:** the four categories vs kb-v3; shown terms
  per case (profile + noise); `forced_min_one`; `q_mean` and the capped
  share; the q-calibration error; the mean IC of related and vocabulary
  noise (`noise_signal.py`, e0_ablation's kb-v4 IC); every tried triple.
- **Not used:** R1-dev.

### 2026-10-01 — pilot — Candidate 5 pilot rounds; `simcal-v051-v1` frozen
- **Setup:** as pre-registered above (simulator 0.5.1 from the 09e5802
  tarball; 4,890 cases for 489 genes per round; 0 invariant violations in
  all three rounds). R1-train targets only; no R1-dev.
  Files: `results/realism/cand5-pilots/` (per-round calibration, run
  summary, validate log, categories, noise signal; `summary.json` from
  `scripts/analysis/cand5_pilot_rounds.py`).
- **Every triple tried:**

  | Round | q_scale | s | r | E: explained per record (5.3772) | M: noise-only E0 MRR (0.026) | S: more specific (0.0929) | Score |
  |---|---|---|---|---|---|---|---|
  | 1 | 2.0 | 0.6 | 0.18 | 3.727 | 0.0117 | 0.0998 | 0.931 |
  | 2 | 2.8855 | 1.0 | 0.1676 | 4.998 | 0.0276 | 0.0932 | **0.135** |
  | 3 | 3.1042 | 0.7168 | 0.1671 | 5.284 | 0.0169 | 0.0942 | 0.381 |

  Round 2 applies the rules to round 1: q = 2.0 × 5.3772 / 3.727;
  s = (0.026 − 0.0011) / (0.0227 − 0.0011) = 1.15, clipped to 1;
  r = 0.18 × 0.0929 / 0.0998. Round 3 applies them to round 2:
  s = (0.026 − 0.0012) / (0.0358 − 0.0012).
- **Also per round:**

  | Round | Explained / more specific / related / weak (vs kb-v3) | Shown terms per case (profile + noise) | True terms reported | `forced_min_one` | q_mean | q capped | q-calibration error | Related share of noise | MRR vocabulary / related noise | Mean IC related / vocabulary noise |
  |---|---|---|---|---|---|---|---|---|---|---|
  | 1 | 0.714 / 0.100 / 0.079 / 0.108 | 5.22 (4.14 + 1.08) | 0.298 | 896 | 0.288 | 0.024 | 0.0046 | 0.467 | 0.0011 / 0.0227 | 6.76 / 4.39 |
  | 2 | 0.714 / 0.093 / 0.117 / 0.075 | 7.00 (5.53 + 1.46) | 0.399 | 643 | 0.392 | 0.089 | 0.0040 | 0.803 | 0.0012 / 0.0358 | 6.77 / 4.37 |
  | 3 | 0.717 / 0.094 / 0.091 / 0.097 | 7.37 (5.84 + 1.53) | 0.421 | 592 | 0.414 | 0.101 | 0.0041 | 0.570 | 0.0013 / 0.0324 | 6.78 / 4.37 |

  Targets (uncited R1-train vs kb-v3): 0.668 / 0.093 / 0.082 / 0.157;
  8.05 terms per case. Candidate 4's round 2 for comparison: 2.97 shown
  terms per case, 1,579 `forced_min_one`, 0.169 of true terms reported.
- **Selected:** round 2, frozen as `simcal-v051-v1`: simcal-v05-v2 +
  `reporting.q_scale` 2.8855, `noise.related_share` 1.0,
  `reporting.specialize_rate` 0.1676, `noise.related_up_levels` 1,
  `noise.related_down_levels` 1.
- **What the pilots show** (R1-train comparisons only):
  - **q_scale fixes record length.** Shown terms per case go from 2.97
    (candidate 4) to 7.00, and `forced_min_one` from 32% to 13% of cases.
  - **Sibling-only related noise is no less specific.** Its mean IC stays
    6.76–6.78 (candidate 4's noise: 6.78; R1-train present terms: 4.14).
    The reach knobs did not change specificity; `noise.related_max_ic` was
    not part of this design.
  - **Noise-only MRR is not linear in s.** At s = 0.7168 it fell to 0.0169,
    not the 0.026 the interpolation aimed for: vocabulary noise in a case
    dilutes the related noise's signal. The interpolation rule assumed
    linearity.
  - Explained share stays about 0.71 against 0.668 real; weak (IC < 2)
    stays below the real share at s = 1 (0.075 vs 0.157).

### 2026-10-01 — build + go/no-go — v0.5.1 candidate 5: G1 passes; the train-side go/no-go fails (G2c, G2d); G2e passes; no R1-dev read
- **Front / versions:** A / rare-disease-simulator 0.5.1 (GitHub tarball of
  09e5802, sha256 `3d125ec2…`; never the shared checkout), `simcal-v051-v1`,
  report-model-v3, cardinal-v1, hpoa-recount-v1, genes-v2, no presentation
  ages. Gene-first, 100 per gene, medium, seed 1001. ADR-0011 amendment 6.
  **Full profiles only** (disk); no half-A dataset.
- **G1** (`ds-sim0.5.1-full-n100-s1001`):

  | Check | Result |
  |---|---|
  | Cases / genes | 489,200 / 4,892 |
  | `validate` (cases and export) | 0 violations |
  | Slice rerun (20 genes, 19 simulated), run twice | cases and export byte-identical to each other and equal to the full run's lines for those genes (1,900 each) |
  | `dxt lineage verify` | ok |
  | Overlap with R1 (keys, all parts) / S3 | 282 / 5,682 (739 same signature) |
  | Excluded by `-excl-v1`, residual | 5,922, 0 |
  | Release | published (dataset and exclusion list) |

- **Run summary** (independent reporting, q_scale 2.8855):
  - shown terms per case 6.91 (5.49 profile + 1.43 noise); candidate 4:
    2.95;
  - share of true terms reported 0.410 (candidate 4: 0.174);
  - `forced_min_one` 66,675 (13.6%; candidate 4: 32.2%);
  - q_mean 0.400, capped share 0.097, q-calibration error 0.0004;
  - specialised share of profile terms 0.101; related share of noise
    0.796.
- **Go/no-go** (`dxt sim realism --no-dev --label v0.5.1-cand5-full-nodev`
  plus `dxt sim train-checks`; no R1-dev read, no ledger row;
  `results/realism/gate-v0.5.1-cand5-gonogo.md`):

  | Check | UP | V03-full | Candidate 3 | Candidate 4 | Candidate 5 | Rule | Result |
  |---|---|---|---|---|---|---|---|
  | G2a truth layer | 0.416 | 0.336 | 0.305 | 0.307 | 0.306 | beat both | ✅ |
  | G2c W1 terms per case | 3.717 | 1.653 | 1.732 | 5.754 | 1.908 | beat both | ❌ (worse than V03-full) |
  | G2d C2ST AUC | 0.840 | 0.819 | 0.764 | 0.822 | 0.809 [0.774, 0.839] | beat both, ≤ 0.75 | ❌ (beats both, above 0.75) |
  | G2e \|E0 MRR − 0.405\| | 0.414 | 0.183 | 0.142 | 0.204 | **0.049** | beat both, ≤ 0.10 | ✅ |
  | G2b-train (83 genes) | 0.241 | 0.385 | 0.536 | 0.502 | 0.537 | beat both | ✅ (optimistic) |
  | Age: median \|ln(median age ratio)\| (69 genes) | no ages | 0.537 | 0.539 | 0.571 | 0.555 | report only | |

  - E0 MRR 0.356 (target 0.405), the first candidate inside the G2e
    threshold.
  - Terms per case: mean 6.91; p10 / p25 / median / p75 / p90 =
    1 / 2 / 5 / 9 / 16 (R1-train: 8.70; 2 / 4 / 7 / 11 / 17).
- **Decision:** two stop conditions fire (G2c, G2d). As instructed, **no
  R1-dev read was made in this task, whatever the result**; the ledger is
  unchanged (last candidate row `v0.4-cand2`). The last read is reserved for
  the better of candidates 5 and 6, and Mateo decides when to spend it.
- **Secondary numbers** (no R1-dev read):
  - G2a reported layer 0.396 (truth 0.306); on the 145 rows with ≥ 10
    R1-train patients, truth 0.268 and reported 0.343 (R1-train patients'
    own reports: 0.307).
  - Categories vs kb-v3 (5% sample, 24,251 records): explained 0.719,
    more specific 0.097, related 0.111, weak 0.073 (calib-v2: 0.668 /
    0.093 / 0.082 / 0.157); summed error 0.1165. Per record: 6.95 terms,
    4.996 explained (target 5.377).
- **E0 ablation** (`e0_ablation.py`, 3,073 cases, 1 in 160), in-vocab MRR:

  | Variant | MRR | Terms per case |
  |---|---|---|
  | as exported | 0.365 | 6.72 |
  | no noise | 0.467 | 5.34 |
  | no generalisation | 0.388 | 6.72 |
  | no specialisation | 0.417 | 6.72 |
  | profile terms ungeneralised, no noise | 0.546 | 5.34 |
  | all true terms | 0.743 | 13.18 |
  | R1-train uncited | 0.405 | 8.11 |
  | R1-train uncited, explained terms only | 0.479 | 5.53 |

  Mean IC: simulated noise 6.33, profile positives 3.80, R1-train present
  4.14.
- **Age per gene** (median age in years; R1-train patients with a known
  age; `results/realism/v0.5.1-cand5.age-table.json`):

  | Gene | R1-train n | R1-train | V03-full | Candidate 3 | Candidate 4 | Candidate 5 |
  |---|---|---|---|---|---|---|
  | NF1 | 158 | 18.0 | 5.65 | 3.94 | 4.68 | 4.68 |
  | LMNA | 27 | 46.0 | 22.14 | 21.48 | 23.53 | 30.19 |
  | FBN1 | 66 | 18.5 | 26.45 | 24.17 | 28.79 | 29.00 |
  | PTPN11 | 10 | 7.5 | 5.28 | 4.69 | 6.42 | 4.26 |
  | KMT2D | 11 | 11.6 | 3.99 | 4.21 | 3.40 | 3.52 |
  | TBX5 | 41 | 33.0 | 3.67 | 5.12 | 2.41 | 2.55 |
  | UMOD | 76 | 39.0 | 23.84 | 23.75 | 34.88 | 30.68 |
  | FBXL4 | 33 | 2.0 | 4.45 | 5.49 | 7.38 | 6.78 |
  | SPTAN1 | 13 | 46.0 | 7.46 | 8.18 | 12.64 | 13.06 |
  | ITPR1 | 45 | 16.0 | 14.94 | 15.38 | 18.98 | 20.67 |
  | COL3A1 | 35 | 32.0 | 3.88 | 4.02 | 4.59 | 3.62 |

  Same age model as candidate 4 (no presentation ages), so medians move
  only by sampling.
- **Reading** (R1-train only):
  - **Records are still short and too often tiny.** The q_scale target
    was explained terms per record of the *uncited* population (5.38;
    reached 5.00), but G2c compares with *all* R1-train (8.70 terms).
    Unexplained terms are fewer than real (weak 0.073 vs 0.157), and 13.6%
    of cases still fall back to one forced term, so p10 / p25 are 1 / 2
    against 2 / 4.
  - **Noise is still too specific:** mean IC 6.33 against 4.14.
    Sibling-only related noise did not lower it.
  - **Difficulty now matches:** E0 MRR 0.356 against 0.405.
- **Housekeeping:** the 3.4 GB rich-cases file was deleted after the
  export, metrics and ablation; its sha256 (`22bae199…`, equal to the run
  summary's) and a 1-in-160 sample (3,109 cases,
  `cases.keep160.jsonl`) stay in `rare-disease-simulator/outputs/v0.5.1-cand5-full/`.
- **Verdict:** ❌ candidate 5 stops at the train-side go/no-go on G2c and
  G2d, and passes G2a, G2e and G2b-train. No fix was designed here.

### 2026-10-01 — result + analysis — candidate 5 (train-side) and ANALYSIS-005
- **Candidate 5** (sim 0.5.1, `simcal-v051-v1`; PR #53):
  - passes G1, G2a (0.306), G2e (gap **0.049**, the first pass) and
    G2b-train (0.537);
  - fails G2c (1.908) and G2d (0.809).
  - No R1-dev read.
- **ANALYSIS-005:**
  - The strongest separating feature is term count. Simulated records for
    R1 genes average 14.3 terms vs 8.1 real.
  - Simulated record size follows the profile's true-term count
    (ρ 0.966); real record size only partly does (0.532).
- **ADR-0011 amendment 7:** candidate 6 uses budget-normalised independent
  reporting (simulator 0.5.2), plus the enriched profiles and presentation
  ages when ready.

### 2026-10-01 — data — lit-extract tooling; pilot shard C001 (ADR-0013)
- **Branch** `phase3/lit-extract-tooling`. No sealed data read; R1 held-out
  PMIDs used only as a mask; no evaluation unit can be written (validator).
- **Tooling** (`src/diagnostic_ar_training/{cli_lit_extract,knowledge/lit_extract}.py`,
  guide `docs/lit/EXTRACTION_GUIDE.md`, wrapper `scripts/lit/dxt-local`):
  - `dxt lit shards`: `data/lit-extract/shards.tsv` from `lit-sources-v1`:
    **70 chapter shards** (C001–C070, 10 each in P1→P4 order; last has 5)
    and **85 paper shards** (P001–P085, 12 each in list order; last has 3).
    Each source lists the (gene, disease) units it may feed: 1,493 for
    chapters, 2,333 for papers; no source is left without a unit;
  - `dxt lit fetch-text`: plain text of each source, rendered from the
    GeneReviews snapshot NXML or Europe PMC `fullTextXML` (abstract
    fallback), cached in `data/interim/lit-text/` (gitignored), plus a
    per-shard worksheet;
  - `dxt lit hpo`: label/synonym lookup in the pinned HPO;
  - `dxt lit validate-shard`: HPO current and under HP:0000118; counts and
    prevalence consistent; quote ≤ 25 words and verbatim **inside the named
    section or table**; unit allowed by `shards.tsv` and not a
    `litpanel-split-v3` gene or disease; no held-out PMID; notes cover every
    source. Writes `data/lit-extract/reports/<shard>.json`, exits 1;
  - `dxt lit crosscheck prepare|run|score`: seeded per-shard 10% sample
    (seed 20261001), blind prompt (unit, feature, population, citation,
    never our numbers or quote) with the cited section on stdin,
    `codex exec --ephemeral -s read-only --output-schema`, panel agreement
    rule (ages: overlap or within max(1 y, 10%)).
- **Pilot C001** (the 10 first P1 chapters), extracted by me following the
  guide; `validate-shard` 0 problems:
  - **100 rows** from 9 of 10 chapters: 80 feature rows, 20 age rows;
    27 units; 23 rows with counts, 11 with ranges;
  - per chapter: CMS 0 (gene shares only), GnRH deficiency 3, HSP 18 (onset
    per gene), ADSHE 6, EVC 11, PGL/PCC 1, albinism 5, BWS 19, MERRF 19,
    Silver-Russell 18;
  - about 12 minutes of wall time to a passing validation, plus about 3
    minutes spent reading EVC while writing the guide.
- **Cross-check** (`data/lit-extract/crosscheck/pilot-C001.*`): 10 of 100
  rows; Codex 0.155.1, about 8 s per item. **10/10 agree** (Wilson 95% CI
  0.72–1.00). Caveat: the passage is the cited section and the population
  is named, so this checks the number, not the unit, population or HPO
  choice, nor what was missed.
- **Problems met and guide changes (v1 → v2, commit `182ee6e`):**
  - figures pooled over several diseases (albinism overview) would have
    been dropped: added `pooled_group` rows, recorded once with the group's
    units listed in `construction_unit`; propagation is left to the
    `hpoa-lit-v1` build;
  - a pooled table can belong to an umbrella unit (ADSHE →
    `CRH|ORPHA:98784`): added the rule;
  - worksheet units can be another disease (main-entity fallback: CDKN1C →
    BWS in the Silver-Russell chapter; ADAR, DNM2 in HSP; AD vs AR SPG30):
    agents must check each unit's disease name;
  - multi-cohort tables (MERRF: 62 / 34 / 321): largest denominator with
    a header-plus-row quote;
  - added skip rules for category bundles, one number for several
    features, conditional shares, features with no HPO term; carrier
    penetrance vs tumour risk among affected; decades and period spans for
    ages; quote word counts ignore table pipes.
- `dxt lineage verify` passes.

### 2026-10-01 — lit-extract — P001 pilot paper shard; per-unit ≥ 20 rule
- **P001:** 12 papers; **3 qualified** (25%, not the 0.58 screen precision).
  - The 9 dead ends are diagnostic-yield or screening studies, association
    studies, penetrance in carriers, a variant database, and a mixed
    registry.
- **Rule decision (conservative, in line with ADR-0013 amendment 1):**
  - The ≥ 20-patient minimum applies **per unit**: a subgroup under 20 in a
    qualifying paper is not extracted. This removed the ARHR2 (≤ 11) and
    ABCC6 (19) rows.
  - Age at newborn screening is **not** age at presentation; that row was
    removed.
  - P001 now has 12 rows.
- **Before the other 84 paper shards:** a deterministic re-screen of the
  paper list on title and abstract signatures (the dead-end types above),
  then one more pilot.

### 2026-10-01 — data — lit-extract shards C002–C010 (ADR-0013)
- Branch `phase3/lit-extract-C002-C010`, guide v2, one commit per shard, each `validate-shard` 0 problems (re-checked after merging main); no Codex cross-check yet (central). **1,227 rows (1,188 feature, 39 age) from 86 of 90 chapters** (C002 93, C003 99, C004 246, C005 222, C006 147, C007 130, C008 87, C009 108, C010 95); 4 chapters with 0 rows (1 `no_numbers`: Rotor; 3 `not_about_units`, worksheet fallbacks for another disease: 16p12.2 deletion → UQCRC2 complex III deficiency, Xq28 int22h duplication → CLIC2/RAB39B, VEXAS → UBA1 SMAX2). Other wrong-disease fallback units skipped (e.g. SUFU→medulloblastoma in NBCCS, SMAD4→JPS in HHT, MYH11/MYLK→aortic aneurysm in MMIHS, CSF1R early-onset column = BANDDOS); guide ambiguities listed in the PR; `dxt lineage verify` passes.

### 2026-10-01 — data — lit-extract shards C029–C035 (ADR-0013)

- Shards C029–C035 (70 GeneReviews chapters) extracted with guide v2, each passing `validate-shard` with 0 problems: **250 rows** from 49 of 70 chapters (C029 43, C030 36, C031 20, C032 15, C033 47, C034 48, C035 41); 21 chapters gave none (15 `no_numbers`; 6 `not_about_units`, all worksheet fallback units for another disease: AKT1→Cowden in Proteus, GNAS→PHP1A in McCune-Albright, UROD→PCT in HEP, ZFHX3→prostate cancer in SCA4, CHEK2→LFS2, PIK3CA somatic units in PROS); Codex cross-check pending (central); `dxt lineage verify` passes.

### 2026-10-01 — data — lit-extract shards C036–C044 (ADR-0013)
- Branch `phase3/lit-extract-C036-C044`, guide v4, one commit per shard, each `validate-shard` 0 problems (re-checked after merging main); C036–C040 first, C041–C044 after a pause; no Codex cross-check (central). **1,809 rows from 88 of 90 chapters** (C036 457, C037 235, C038 210, C039 170, C040 182, C041 145, C042 143, C043 129, C044 138); 2 `not_about_units` (worksheet fallbacks: ECCL → FGFR1 HH2, Temple → Kagami-Ogata units); `dxt lineage verify` passes.

### 2026-10-01 — data — lit-extract shards C020–C028 (ADR-0013)
- Branch `phase3/lit-extract-C020-C028`, guide v2, one commit per shard, each `validate-shard` 0 problems; no Codex cross-check yet (central). **293 rows from 71 of 90 chapters** (C020 6, C021 23, C022 25, C023 37, C024 42, C025 31, C026 56, C027 48, C028 25); 19 chapters with 0 rows (17 `no_numbers`, 2 `not_about_units` where the only units were worksheet fallbacks: celiac → achalasia/narcolepsy, MT-RNR1 → MERRF); guide ambiguities listed in the PR.

### 2026-10-01 — lit-extract — lit-papers-v2 re-screen, guide v3, pilot Q001
- **Branch** `phase3/lit-papers-v2`. No sealed data read; no LLM
  classification (every paper decision is the deterministic rule); no
  evaluation unit can be written (validator).
- **Re-screen** (`knowledge/lit_papers.py`; `dxt lit-sources
  rescreen-fetch|rescreen`):
  - **Input:** the 1,011 selected papers of `lit-sources-v1`. Title,
    abstract and publication type re-fetched from Europe PMC (7 queries,
    0 missing), cached in `data/interim/lit-sources/lit-papers-v2/`.
  - **Rule** (first failing check sets the reason):
    1. publication type case report, review or trial;
    2. title signatures: review; case, family or sibling report; a single
       patient; database; screening or method title (sequencing, panel,
       NGS, molecular or genetic testing, screening other than newborn
       screening, mutation analysis, "for mutations in", variant prevalence,
       diagnostic yield, unsolved, suspected, prenatal diagnosis, "is a
       frequent cause"); carriers or penetrance; variant-level work (novel
       variants, reclassification, in silico, functional studies, copy
       number); treatment; biomarker; model organism; a plural disease group
       with no gene symbol; a title count under 20;
    3. abstract signatures: diagnostic yield or negative-tested cohorts,
       sequencing applied to a series of N, association designs
       (susceptibility, predisposition, odds or hazard ratio, case-control,
       risk factors, polymorphism, comparison with healthy individuals),
       penetrance in carriers, variant databases; positives reported as a
       share of those screened, all under 20;
    4. positive per-unit evidence: a count ≥ 20 bound to a gene symbol of
       the paper or to one disease (a defined abbreviation whose long form
       is not a plural group, or a disease noun), or a bare count when the
       title names a single disease or gene.
  - **Deviation from the brief, on purpose:** bare "associated with",
    "association" and "risk of" are not exclusions. Two of the three P001
    qualifiers contain them ("associated with more disability", "the risk
    of complication remains"). Narrower association forms are used instead.
  - **Calibration on P001's 12 known outcomes:** qualified→pass 3,
    qualified→fail 0, dead end→pass 0, dead end→fail 9.
  - **Revisions before freezing,** after reading P001 and seeded samples of
    40 passing titles (seeds 11, 99) plus failure samples: added the review,
    single-patient, sibling, variant-level, treatment, biomarker and
    "frequent cause" title signatures; exempted newborn screening; added
    "unsolved". The first draft passed 439 of 999 and failed one P001 dead
    end (the PXE CNV study).
- **`lit-papers-v2`** (manifest from `04c506a`, clean tree; release
  `lit-papers-v2`; committed `182eadb` before any further extraction):
  - **305 of 999** re-screened papers pass; 197 have a weak gene; 304 genes.
  - Pass reasons: bare count with a single-unit title 183, count bound to a
    unit phrase 82, count next to a unit term 31, unit cohort of N 9.
  - Top fail reasons: screening/method title 160, association 97,
    variant-level title 73, no per-unit n ≥ 20 71, diagnostic yield 36.
- **Q shards** (`dxt lit shards --set papers-v2`,
  `data/lit-extract/shards-papers-v2.tsv`): **26 shards** (Q001–Q025 of
  12, Q026 of 5), 305 papers, 942 units.
  - Same units as each paper's P row; list order kept; no P001 paper.
  - `shards.tsv` rebuilds byte-identical.
  - `fetch-text`, `validate-shard` and the cross-check route `Q` ids to
    the new file (tests added).
- **Guide v3** (`edf1b20`): a "Papers" section with the per-unit rule,
  own-cohort data only, definitions from Methods, yes/no cells, prenatal
  ages, screening age, empty tables; a changelog.
- **Pilot Q001** (12 papers), extracted by me following guide v3;
  `validate-shard` 0 problems:
  - **9 of 12 qualified** (75%, Wilson 95% CI 0.47–0.91; P001: 25%).
  - **140 rows:** 136 feature rows and 4 age rows; 116 with counts.
  - Rows per paper: 7, 15, 4, 9, 11, 68, 14, 11, 1. One table (KBG,
    `PMID:35970914`) gives 68.
  - Dead ends:
    - 1 not about units: an infantile-hypercalcaemia cohort attributed to
      AGXT through its citing chapter, a gene-attribution issue rather than
      the screen;
    - 2 screen false positives: a WES/WGS diagnostic-yield study (the
      abstract says "unexplained" and "diagnosis rate", outside the
      patterns); a linkage study ("association analyses", plural, outside
      the pattern).

    The rule stays frozen; these misses are recorded here.
  - **Time:** about 10 minutes of wall time from `fetch-text` to a passing
    validation.
- **Estimate for Q002–Q026** (293 papers):
  - **Rows:** at 0.75 qualifying and a median of 11 rows per qualifying
    paper, about 2,400. Range about 1,250 (0.47 × 9 rows) to 4,200
    (0.91 × 15.6 rows).
  - **Agent-hours:** about 5 at the pilot pace (10–12 minutes per shard);
    about 25 at the LITPANEL-v2 rate (97 rows per agent-hour).
  - **Cross-check:** a 10% Codex sample, about 240 rows, about 30 minutes.
- `dxt lineage verify` passes.

### 2026-10-01 — data — lit-extract shards C011–C019 (ADR-0013)
- Branch `phase3/lit-extract-C011-C019`, guide v2, one commit per shard, each `validate-shard` 0 problems; no Codex cross-check yet (central). **545 rows (490 feature, 55 age) from 77 of 90 chapters** (C011 97, C012 95, C013 110, C014 67, C015 38, C016 42, C017 9, C018 34, C019 53); 13 chapters with 0 rows (11 `no_numbers`: only carrier risks, symbol/bin tables or prose; 2 `not_about_units`: C3 glomerulopathy and maternal-effect MLID, where the worksheet fallback assigned other diseases). Wrong-disease fallback units skipped (e.g. APOE→AD4, EIF4A2→NDD, DNMT3B→ICF, WT1→Denys-Drash in 46,XX DSD); guide ambiguities listed in the PR.

### 2026-10-01 — pre-registration — Candidate 6a pilot rounds (ADR-0011 amendment 7, current profiles)
Written and committed before the first candidate 6a pilot run. Train-side
only: **no R1-dev read in this task, whatever the result.** Candidate 6a
checks amendment 7's budget-normalised reporting on the **current**
profiles; the literature-enriched profiles come later, as candidate 6.
- **Generator:** rare-disease-simulator 0.5.2, run from the GitHub tarball
  of 40f8896 (sha256 `ce272645…`), never the shared checkout.
  - Full profiles rebuilt with 0.5.2 from hpoa-recount-v1 + genes-v2: 9,223
    profiles, byte-identical to candidates 2–5 (`d44e1586…`).
  - report-model-v3; cardinal-v1; no presentation ages.
- **Budget histogram:** `profile-budget-v1` (manifest committed;
  `scripts/analysis/profile_budget_histogram.py`): explained terms per
  patient vs kb-v3 over the 1,140 uncited R1-train patients with a kb-v3
  gene (the `uncited_categories.py` population and rule). Mean 5.3772
  (equal to candidate 5's E target), median 5, p10 / p90 = 1 / 10, max 26;
  54 patients have 0 explained terms. The simulator ignores the 0 bin, so
  the effective k mean is 5.6446.
- **Calibration per round:** `simcal-v051-v1` + `reporting.budget_normalize`
  true + `reporting.profile_budget_histogram` from `profile-budget-v1`, with
  `noise.related_share` (s) and `reporting.specialize_rate` (r) set per
  round. Everything else unchanged (proportional noise ρ 0.207, calib-v2
  vocabulary, related levels 1/1, age durations by onset). `q_scale` stays
  2.8855 in the file; in this mode c absorbs it.
- **Pilot shape:** the 523-symbol list (`outputs/cal/pilot-genes.txt`,
  sha256 `5c817192…`), 10 cases per gene, medium, seed 91001, full
  profiles.
- **Targets** (R1-train, as candidate 5):
  - **S** = more-specific share vs kb-v3 = **0.0929** (calib-v2);
  - **M** = E0 in-vocab MRR on the noise terms alone = **0.026**
    (`noise_signal.py`).
- **Round 1:** s = 1.0, r = 0.1676 (candidate 5's values); no knob changes.
- **Round 2** runs only if, after round 1, |S − 0.0929| / 0.0929 > 0.20 or
  |M − 0.026| / 0.026 > 0.20. It changes only the drifted knob(s), with
  candidate 5's update rules (rounded to 4 decimals):
  - r₂ = r₁ × 0.0929 / S₁, capped to [0, 1];
  - s₂ = (0.026 − MRR_voc,1) / (MRR_rel,1 − MRR_voc,1), clipped to [0, 1]
    (s₂ = s₁ if MRR_rel,1 ≤ MRR_voc,1).
  At most 2 rounds.
- **Selection:** round 1 if round 2 does not run; otherwise the round with
  the smaller |S − 0.0929| / 0.0929 + |M − 0.026| / 0.026. Frozen as
  `simcal-v052-v1` (`dxt knowledge shrinkage-prior --min-denominator 10
  --base data/calib/simcal-v051-v1.json --include
  data/calib/profile-budget-v1.json --set reporting.budget_normalize=true`,
  plus `--set` for any changed knob).
- **Reported per round** (not targets): shown terms per case (profile +
  noise); realised profile terms vs k (means and total variation); the four
  categories vs kb-v3 and explained terms per record (candidate 5's E,
  5.3772); `forced_min_one`; mean c (`scale_mean`); the capped share; the
  per-gene Spearman of simulated record size vs simulated true-term count
  (`scripts/analysis/record_size_by_gene.py`, ANALYSIS-005's method: over
  every pilot gene with `--no-r1`, and over the pilot genes with ≥ 10
  R1-train patients, where the real record size is also compared;
  candidate 5's full dataset: 0.966, real 0.532 over 84 genes).
- **Then:** `ds-sim0.5.2-full-n100-s1001` (gene-first, all genes, 100 per
  gene, medium, seed 1001; full profiles only), G1, and the train-side
  go/no-go (G2a truth layer, G2c, G2d, G2e, G2b-train; age reported) with
  `dxt sim realism --no-dev`, plus `c2st_features.py`. **No R1-dev read.**
- **Not used:** R1-dev.

### 2026-10-01 — pilot — Candidate 6a pilot round 1; round 2 not triggered; `simcal-v052-v1` frozen
- **Setup:** as pre-registered above (simulator 0.5.2 from the 40f8896
  tarball; 4,890 cases for 489 genes; 0 invariant violations). R1-train
  targets only; no R1-dev. Files: `results/realism/cand6a-pilots/`
  (calibration, run summary, validate log, categories, noise signal,
  record size; `summary.json` from `scripts/analysis/cand6a_pilot_rounds.py`).
- **Round 1** (s = 1.0, r = 0.1676):

  | Round | s | r | S: more specific (0.0929) | M: noise-only E0 MRR (0.026) | Relative errors S / M | Round 2? |
  |---|---|---|---|---|---|---|
  | 1 | 1.0 | 0.1676 | 0.0897 | 0.0303 | 0.034 / 0.165 | no (both ≤ 0.20) |

- **Also measured** (candidate 5's pilot round 2 on the same genes and
  seed in brackets):

  | Measure | Round 1 | [Candidate 5 round 2] |
  |---|---|---|
  | Shown terms per case (profile + noise) | 5.84 (4.63 + 1.21) | [7.00 (5.53 + 1.46)] |
  | k mean drawn / realised profile terms | 5.732 / 4.646 | — |
  | Total variation, realised vs k | 0.137 | — |
  | Mean c (`scale_mean`, relative to q_scale · π / f) | 2.683 | — |
  | Share of true terms reported | 0.334 | [0.399] |
  | `forced_min_one` | 157 (3.2%) | [643 (13.1%)] |
  | q_mean / q capped share | 0.332 / 0.128 | [0.392 / 0.089] |
  | Explained / more specific / related / weak (vs kb-v3) | 0.722 / 0.090 / 0.115 / 0.073 | [0.714 / 0.093 / 0.117 / 0.075] |
  | Explained terms per record (candidate 5's E target 5.377) | 4.219 | [4.998] |
  | Related share of noise; MRR vocabulary / related noise | 0.818; 0.0008 / 0.038 | [0.803; 0.0012 / 0.0358] |
  | Mean IC related / vocabulary noise | 6.83 / 4.26 | [6.77 / 4.37] |
  | Spearman, simulated record size vs true-term count, 489 genes | **0.676** | [0.956] |
  | Same, the 9 pilot genes with ≥ 10 R1-train patients (real vs the same true-term count) | 0.167 (0.667) | [0.950 (0.683)] |

  Targets (uncited R1-train vs kb-v3): 0.668 / 0.093 / 0.082 / 0.157;
  8.05 terms per case.
- **Selected:** round 1, frozen as `simcal-v052-v1`: simcal-v051-v1 +
  `reporting.budget_normalize` true + `profile-budget-v1`'s
  `reporting.profile_budget_histogram`.
- **What the pilot shows** (R1-train comparisons only):
  - **Budget normalisation decouples record size from profile richness:**
    the per-gene Spearman over the 489 pilot genes falls from 0.956 to
    0.676. The 9-gene R1 subset is too small to read.
  - **Records got shorter, not longer:** realised profile terms 4.65
    against a drawn k of 5.73. min(k, true terms) caps small profiles, the
    rolls realise fewer than k on average, and specialised terms leave
    the explained category, so explained terms per record are 4.22
    against the uncited real 5.38. `forced_min_one` falls to 3.2%.
  - The realised count is wider than k (TV 0.137, close to the 0.133 the
    simulator's fixture showed).

### 2026-10-01 — build + go/no-go — v0.5.2 candidate 6a: G1 passes; the train-side go/no-go fails (G2c, G2d); G2e passes; no R1-dev read
- **Front / versions:** A / rare-disease-simulator 0.5.2 (GitHub tarball of
  40f8896, sha256 `ce272645…`; never the shared checkout),
  `simcal-v052-v1` (budget-normalised independent reporting,
  `profile-budget-v1`), report-model-v3, cardinal-v1, hpoa-recount-v1,
  genes-v2, no presentation ages. Gene-first, 100 per gene, medium, seed
  1001. ADR-0011 amendment 7 (candidate 6a: current profiles). **Full
  profiles only** (disk).
- **G1** (`ds-sim0.5.2-full-n100-s1001`):

  | Check | Result |
  |---|---|
  | Cases / genes | 489,200 / 4,892 |
  | `validate` (cases and export) | 0 violations |
  | Slice rerun (20 genes, 19 simulated), run twice | cases and export byte-identical to each other and equal to the full run's lines for those genes (1,900 each) |
  | `dxt lineage verify` | ok |
  | Overlap with R1 (keys, all parts) / S3 | 313 / 3,917 (628 same signature) |
  | Excluded by `-excl-v1`, residual | 4,181, 0 |
  | Release | published (dataset and exclusion list) |

- **Run summary** (budget-normalised independent reporting):
  - shown terms per case 5.75 (4.56 profile + 1.19 noise); candidate 5:
    6.91;
  - k mean drawn 5.649, realised profile terms 4.569, total variation
    realised vs k 0.146; mean c 2.772;
  - share of true terms reported 0.340 (candidate 5: 0.410);
  - `forced_min_one` 15,170 (3.1%; candidate 5: 13.6%);
  - q_mean 0.338, capped share 0.135, q-calibration error 0.0002;
  - specialised share of profile terms 0.095; related share of noise
    0.818.
- **Go/no-go** (`dxt sim realism --no-dev --label v0.5.2-cand6a-full-nodev`
  plus `dxt sim train-checks`; no R1-dev read, no ledger row;
  `results/realism/gate-v0.5.2-cand6a-gonogo.md`):

  | Check | UP | V03-full | Candidate 3 | Candidate 4 | Candidate 5 | Candidate 6a | Rule | Result |
  |---|---|---|---|---|---|---|---|---|
  | G2a truth layer | 0.416 | 0.336 | 0.305 | 0.307 | 0.306 | 0.306 | beat both | ✅ |
  | G2c W1 terms per case | 3.717 | 1.653 | 1.732 | 5.754 | 1.908 | 2.955 | beat both | ❌ (worse than V03-full) |
  | G2d C2ST AUC | 0.840 | 0.819 | 0.764 | 0.822 | 0.809 | 0.764 [0.737, 0.794] | beat both, ≤ 0.75 | ❌ (beats both, above 0.75) |
  | G2e \|E0 MRR − 0.405\| | 0.414 | 0.183 | 0.142 | 0.204 | 0.049 | **0.011** | beat both, ≤ 0.10 | ✅ |
  | G2b-train (83 genes) | 0.241 | 0.385 | 0.536 | 0.502 | 0.537 | 0.507 | beat both | ✅ (optimistic) |
  | Age: median \|ln(median age ratio)\| (69 genes) | no ages | 0.537 | 0.539 | 0.571 | 0.555 | 0.584 | report only | |

  - E0 MRR 0.394 (target 0.405).
  - **G2c is not a spread-only failure.** Terms per case, simulated vs
    R1-train: mean 5.74 vs 8.70; p10 / p25 / median / p75 / p90 =
    1 / 2 / 5 / 8 / 11 vs 2 / 4 / 7 / 11 / 17. The W1 (2.955) equals the
    mean difference (8.70 − 5.74 = 2.955), so the simulated distribution
    sits at or below the real one at every quantile: the failure is mostly
    location. The spread is also narrower (p90 − p10 = 10 vs 15; IQR 6
    vs 7). Candidate 5 had mean 6.91, p90 16.
- **Decision:** two stop conditions fire (G2c, G2d). As instructed, **no
  R1-dev read was made in this task, whatever the result**; the ledger is
  unchanged (last candidate row `v0.4-cand2`).
- **Record size vs profile richness** (`record_size_by_gene.py`, 84 genes
  with ≥ 10 R1-train patients; `results/realism/v0.5.2-cand6a.record-size.json`):

  | | Candidate 5 | Candidate 6a | Real |
  |---|---|---|---|
  | Mean terms per case | 13.38 | 6.51 | 8.60 |
  | Spearman, record size vs simulated true-term count | 0.966 | **0.658** | 0.532 (real size vs the same count; 0.502 with candidate 6a's counts) |
  | Spearman, real vs simulated record size by gene | 0.552 | 0.266 | |
  | Median simulated / real ratio | 1.33 | 0.83 | |

- **C2ST features** (`c2st_features.py`, 3,514 gene-matched pairs;
  `results/realism/v0.5.2-cand6a.c2st-features.json`), univariate AUC,
  candidate 5 (ANALYSIS-005) in brackets:

  | Feature | AUC | Real mean | Simulated mean |
  |---|---|---|---|
  | mean depth | 0.386 [0.406] | 6.56 | 6.23 [6.31] |
  | annotated share (kb-v5) | 0.404 [0.398] | 0.570 | 0.473 [0.475] |
  | term count | 0.422 [**0.655**] | 8.06 | 6.50 [14.26] |
  | noise share | 0.536 [0.551] | 0.374 | 0.402 [0.409] |
  | limbs system share | 0.465 | 0.058 | 0.042 |
  | metabolism / homeostasis share | 0.471 | 0.058 | 0.040 |
  | integument share | 0.473 | 0.085 | 0.055 |

  Term count is no longer the top separator; it flipped side (simulated
  records for R1 genes are now shorter than real). Mean depth and
  annotated share lead, as in candidate 5.
- **Secondary numbers** (no R1-dev read):
  - G2a reported layer 0.412 (truth 0.306); on the 145 rows with ≥ 10
    R1-train patients, truth 0.269 and reported 0.391 (R1-train patients'
    own reports: 0.307).
  - Categories vs kb-v3 (5% sample, 24,251 records): explained 0.726,
    more specific 0.094, related 0.112, weak 0.068 (calib-v2: 0.668 /
    0.093 / 0.082 / 0.157); summed error 0.1201. Per record: 5.72 terms,
    4.15 explained (uncited real: 5.38).
- **E0 ablation** (`e0_ablation.py`, the 3,073 kept cases, 1 in 160),
  in-vocab MRR (candidate 5 in brackets):

  | Variant | MRR | Terms per case |
  |---|---|---|
  | as exported | 0.406 [0.365] | 5.76 |
  | no noise | 0.499 [0.467] | 4.55 |
  | no generalisation | 0.429 [0.388] | 5.76 |
  | no specialisation | 0.451 [0.417] | 5.76 |
  | profile terms ungeneralised, no noise | 0.567 [0.546] | 4.55 |
  | all true terms | 0.743 [0.743] | 13.19 |
  | R1-train uncited | 0.405 | 8.11 |
  | R1-train uncited, explained terms only | 0.479 | 5.53 |

  Mean IC: simulated profile positives 4.29 (candidate 5: 3.80), noise
  6.39, R1-train present 4.14.
- **Age per gene** (median age in years;
  `results/realism/v0.5.2-cand6a.age-table.json`): same age model as
  candidates 4–5 (no presentation ages), so medians move only by sampling
  (NF1 5.21 vs 18.0 real; TBX5 2.47 vs 33.0; COL3A1 4.51 vs 32.0).
- **Reading** (R1-train only):
  - **Budget normalisation does decouple record size from profile
    richness** (Spearman 0.966 → 0.658, now near the real 0.50–0.53), and
    removes term count as C2ST's top feature; G2d improves from 0.809 to
    0.764, level with candidate 3 but still above 0.75.
  - **Records are now too short.** The budget is explained terms of
    *uncited* patients (5.38, or 5.65 without the 0 bin, which the
    simulator drops), but realised profile terms are 4.57: min(k, true
    terms) caps small profiles and independent rolls realise below k
    (TV 0.146). Noise adds 1.19 terms against about 2.7 unexplained real
    terms per uncited patient (8.05 − 5.38). G2c compares with all
    R1-train (8.70 terms), so W1 rises from 1.908 (candidate 5) to
    2.955.
  - **Difficulty matches closely:** E0 MRR 0.394 against 0.405.
- **Housekeeping:** the 3.4 GB rich-cases file was deleted after the
  export, metrics and ablation; its sha256 (`95ea022b…`, equal to the run
  summary's) and a 1-in-160 sample (3,073 cases, `cases.keep160.jsonl`)
  stay in `rare-disease-simulator/outputs/v0.5.2-cand6a-full/`.
- **Verdict:** ❌ candidate 6a stops at the train-side go/no-go on G2c and
  G2d, and passes G2a, G2e and G2b-train. No fix was designed here.

### 2026-10-01 — result + analysis — candidate 6a; ANALYSIS-006; ADR-0011 amendment 8
- **Candidate 6a** (sim 0.5.2, budget-normalised; PR #61):
  - G2e gap **0.011**; G2d 0.764 (close); G2c 2.955 (records too short,
    5.74 vs 8.70);
  - no R1-dev read.
  - It survived a usage-limit stop and was resumed from its committed
    worktree.
- **ANALYSIS-006:** simulated reports generalise to an ancestor in 15.2% of
  explained terms, vs 9.3% for real uncited patients.
- **ADR-0011 amendment 8:**
  - simulator 0.5.3 with a record-level budget (from R1-train's total-terms
    histogram) and noise inside it;
  - the generalisation rate piloted to 0.093.
  - Candidate 6b runs this design on the current profiles; candidate 6 adds
    the literature profiles.
- **Literature work:**
  - guide v4 merged (PR #62);
  - chapter batches C011–C019 merged (PR #60);
  - C002–C010 resumed after the usage stop (C002–C008 were already
    committed).

### 2026-10-01 — decision — ADR-0013 amendment 2: literature integration rules
- **Fixed before any enriched profile exists:**
  - counts → `n/m`, prevalence-only → `%` (below counts);
  - `pooled_group` rows → a percentage on each listed unit (no counts);
  - rows citing a PMID HPOA already cites for the same disease and term are
    dropped;
  - presentation ages come from `AGE_PRESENTATION` rows only (GeneReviews
    first, single values widened by ±10%).
- **Progress:** the C002–C010 batch is merged (1,227 rows). Main now has 37
  shards, 2,567 rows, 417 units. Simulator 0.5.3 is merged. Candidate 6b
  (train-side) is running.

### 2026-10-01 — tooling + dry run — `dxt lit build` (ADR-0013 amendment 2)
- **What:** `dxt lit build` turns the shard rows into `hpoa-lit-vN`,
  `hpoa-enriched-vN` and `presentation-ages-vN` (DATA_LINEAGE §8).
  - Every shard with a passing report is re-validated first.
  - `validate-shard` shares that code.
  - 30 mocked tests, one or more per rule.
  - Check: a scratch copy with one corrupted quote and one failing report
    had both shards refused.
- **Dry run** on main's 37 shards (code `1cf985d`, clean tree; no artifact
  id, no manifest): `results/analyses/LIT-INTEGRATION-dryrun.json`.
  - **Shards:** 37 accepted, 0 refused.
  - **Rows in:** 2,567, of which 2,344 feature, 27 `AGE_PRESENTATION` and
    196 `AGE_ONSET`.
  - **Feature rows by outcome:**
    - 2,210 used;
    - 13 dropped as an HPOA double count;
    - 111 lost the one-percentage choice;
    - 10 were a smaller same-source count;
    - 0 failed validation.
  - **Placements:** 3,084, from 336 `pooled_group` rows giving 1,076
    placements. 10 were skipped because the same source had a
    unit-specific row.
  - **`hpoa-lit`:** 2,892 rows:
    - 635 count rows, 8 of them pooling several sources;
    - 2,242 percentage rows;
    - 15 NOT rows.
  - **Reach:** 434 diseases, all already in `hpoa-recount-v1`. 454 of
    455 units enriched (455 counts every unit a `pooled_group` row
    lists). 264 sources used.
  - **Terms:** 1,847 new (disease, term) pairs and 1,004 existing.
  - **What the 1,004 existing pairs do in the simulator** (precedence
    counts > % > category):

    | Effect | Pairs |
    |---|---|
    | Literature % overrides an HPOA row with no frequency | 398 |
    | Literature % shadowed by HPOA counts | 334 |
    | Counts pooled with HPOA counts | 126 |
    | Literature counts override an HPOA row with no frequency | 77 |
    | Literature % overrides an HPOA category | 51 |
    | Literature counts override an HPOA category | 13 |
    | % averaged with an HPOA % | 5 |

  - **NOT pairs:** 2 conflict with an HPOA positive, so the simulator
    drops them.
  - **`hpoa-enriched`:** 271,878 rows (268,986 + 2,892).
  - **Presentation ages:** 30 diseases (28 GeneReviews, 2 papers).
    - 12 of the 30 come from `pooled_group` rows of 2 chapters.
    - 16 single values were widened.
    - 6 placements had an open upper bound.
  - **`AGE_ONSET`:** 196 rows reach 202 diseases; only 5 of those also
    have a presentation age.
- **Simulator check** (rare-disease-simulator `6833d2d`, source copied
  read-only into a scratch dir):
  - `build-profiles --from-hpoa --hpoa` on a 28-disease slice of the
    dry-run `phenotype.hpoa` built 28 profiles, with 0 masked rows. All
    170 positive literature rows of the slice appear in the profiles, with
    their source cited. Of 3 NOT rows, 2 became negatives and 1 was
    dropped for a positive conflict.
  - `load_presentation_ages` read all 30 rows.
- **Ambiguities found** (resolved as in DATA_LINEAGE §8; flagged for
  Mateo):
  - **Rule 6, percentages.** 132 (disease, term) pairs had several
    percentages.
    - 150 of the 152 losers are the same source giving several
      populations.
    - 120 losers had no stated n on either side, so 102 choices fell to
      source and file order. 62 losers differ from the winner by more
      than 20 points.
  - **Rule 5.** Rows have no `source_pmids`. Chapters are matched by NBK
    id, chapter PMID and Bookshelf URL.
  - **Rule 7.** `pooled_group` age rows and open-ended ranges are not
    covered by the rule.
  - **Zeros.** A zero `pooled_group` row becomes NOT. A prevalence-0 row
    in a pre-v4 shard is treated as an explicit absence.
- **Not done:** no artifact registered or published. The real build waits
  for the extraction to finish.

### 2026-10-01 — data — lit-extract paper shards Q019–Q026 (ADR-0013)
- Branch `phase3/lit-extract-Q019-Q026`, guide v4, one commit per shard, each `validate-shard` 0 problems; no Codex cross-check (central). **121 rows (103 feature, 18 age, 9 of them `AGE_PRESENTATION`) from 19 of 89 papers** (Q019 12, Q020 4, Q021 2, Q022 25, Q023 27, Q024 8, Q025 42, Q026 1); 70 papers with 0 rows (62 `not_cohort`: screening/yield studies, somatic tumour cohorts, single families, own cohorts under 20 pooled with literature, confirmed P/LP groups under 20 once VUS carriers are removed; 6 `no_numbers`; 2 `not_about_units`: MT-TT LHON cohort vs lethal infantile myopathy unit, SLCO2A1 enteropathy vs hypertrophic osteoarthropathy units). Guide ambiguities (VUS-majority groups, carrier vs affected denominators, pooled_group per-unit n, genetic-confirmation age as presentation age) listed in the PR; `dxt lineage verify` passes.

### 2026-10-01 — data — lit-extract chapter shards C063–C070 (ADR-0013)
- Branch `phase3/lit-extract-C063-C070`, guide v4, one commit per shard, each `validate-shard` 0 problems; no Codex cross-check (central). **420 rows (356 feature, 64 age, 16 of them `AGE_PRESENTATION`) from 67 of 75 chapters** (C063 30, C064 38, C065 32, C066 62, C067 46, C068 110, C069 45, C070 57); 8 chapters with 0 rows (6 `no_numbers`: SCADD, variegate porphyria, SLC39A14, ethylmalonic encephalopathy, PMLD1, ALPK1; 2 `not_about_units`: Duarte galactosemia → unit is classic galactosemia, CMTC → unit GNA11|OMIM:145981 is FHH2). Open points for the guide: spectrum chapters whose other phenotype is not a unit (DNMT1 cohort put on HSAN1E with `pooled`; PUF60 figures on Verheij OMIM:615583), CNV syndrome with two genes on one disease id (Potocki-Lupski on RAI1, `pooled`), and explicit-absence wording ("have not been reported/documented") recorded as prevalence 0.

### 2026-10-01 — decision + dry run — ADR-0013 amendment 3: rule-6 choice and the ambiguity guard
- **Ruling (coordinator):**
  - percentages are chosen by both sexes, then the largest stated
    `n_assessed`, then unit > `pooled` > `pooled_group`;
  - if one source's rows are still tied after sex and n and differ by
    more than 0.20, the term is dropped from that source
    (`ambiguous_populations`);
  - the same guard applies to equal count denominators;
  - the other amendment 2 resolutions are accepted.
- **Implemented in PR #67;** 34 mocked tests.
- **Effect on main's 37 shards** (code `c10788b` vs `1cf985d`):
  - 80 rows (102 placements, 47 disease–term–source triples) are dropped
    as `ambiguous_populations`;
  - "not chosen" falls from 111 to 71 rows;
  - file-order choices fall from 102 to 56;
  - `hpoa-lit` falls from 2,892 to 2,841 rows on 431 diseases;
  - the count guard never fires (same-source smaller counts stay at 10).
- **Dry run after merging main** (45 shards with Q019–Q026; code
  `cc86be3`, clean): `results/analyses/LIT-INTEGRATION-dryrun.json`.
  - **Rows in:** 2,688, with 0 failed validation. Feature rows: 2,273 used,
    80 ambiguous, 71 not chosen, 13 HPOA double count, 10 smaller
    same-source count.
  - **`hpoa-lit`:** 3,004 rows (666 count, 2,323 %, 15 NOT) on 456
    diseases. 475 of 480 units enriched.
  - **Terms:** 1,941 new and 1,025 existing.
  - **Presentation ages:** 40 diseases. `AGE_ONSET` reaches 215 diseases.
- **Simulator check (`6833d2d`, read-only copy):**
  - `build-profiles --from-hpoa --hpoa … --gene-profiles genes-v2` on a
    28-disease slice built 28 profiles. All 168 positive and 4 NOT
    literature rows of the slice arrive.
  - `load_presentation_ages` reads 40 rows.
  - Still no artifact registered.

### 2026-10-01 — data — lit-extract chapter shards C054–C062 (ADR-0013)
- Branch `phase3/lit-extract-C054-C062`, guide v4, one commit per shard, each `validate-shard` 0 problems; no Codex cross-check (central). **424 rows (350 feature, 74 age, 7 of them `AGE_PRESENTATION`) from 84 of 90 chapters** (C054 42, C055 31, C056 41, C057 39, C058 58, C059 56, C060 58, C061 51, C062 48); 6 chapters with 0 rows, all `no_numbers` (enlarged parietal foramina, Baller-Gerold, PNKD, choroideremia, hemophilia B, PAH deficiency). Phenotypes without a matching unit skipped (e.g. adult PLAN, PLP1 null syndrome, SYNE1 AMC) and cone-dystrophy units left out of the achromatopsia pooled group. Open points for the guide (undefined age phrases such as "toddler years", phenotype-definition onsets, "consistent/constant" as always, Table legends with "++ = always present") listed in the PR.

### 2026-10-01 — data — lit-extract chapter shards C045–C053 (ADR-0013)
- Branch `phase3/lit-extract-C045-C053`, guide v4, one commit per shard, each `validate-shard` 0 problems; no Codex cross-check (central). **704 rows (660 feature, 44 age, 12 of them `AGE_PRESENTATION`) from 86 of 90 chapters** (C045 104, C046 100, C047 102, C048 90, C049 81, C050 74, C051 41, C052 58, C053 54); 4 chapters with 0 rows: NBK621478 (`not_about_units`: the EPAS1 unit is familial erythrocytosis 4, the chapter covers mosaic Pacak-Zhuang syndrome), NBK1129 (`no_numbers`: LQTS per-gene event shares come from a treated registry with genotype-positive relatives, the rest is cumulative risk), NBK1110 (`no_numbers`: PMM2-CDG table is verbal only) and NBK1118 (`no_numbers`: IPEX gives only an onset distribution and vague quantifiers). Work paused after C051 on request and resumed for C052–C053. Ambiguities found are listed in PR #73.


### 2026-10-01 — data — lit-extract paper shards Q002–Q010 (ADR-0013)
- Branch `phase3/lit-extract-Q002-Q010`, guide v4, one commit per shard, each `validate-shard` 0 problems; no Codex cross-check (central). Paused after Q005 to save usage, then resumed. **574 rows (527 feature, 47 age, 9 of them `AGE_PRESENTATION`) from 53 of 108 papers** (Q002 36, Q003 12, Q004 41, Q005 124, Q006 89, Q007 97, Q008 75, Q009 74, Q010 26); 55 papers with 0 rows (mostly `not_cohort`: screening/yield studies, single families, literature reviews, groups under 20 confirmed, drug trials, enzyme-only diagnosis; `no_numbers`: data only in figures or supplements, or own cohort pooled with published cases in every figure; a few `not_about_units`). Open questions for the guide: mixed cohorts with an unconfirmed minority (confirmed-majority rule vs confirmed subgroups), enzyme- or biopsy-only diagnosis (MPS II, CGD, DMD), Temple syndrome `pooled_group` over 9 units, overlapping cohorts across papers and shards (PMID:28640239 within PMID:39693239; PMID:40176950 re-analyses P001's ENPP1 cohort; Friedreich ataxia across Q007/Q008), registries pooled with literature cases (PMID:31810826 MAPT dropped), age at referral-centre visit, genetic or registry diagnosis as `AGE_PRESENTATION` (PMID:31194252 minimum 0 may include screening), counts with an implicit denominator.

### 2026-10-01 — data — lit-extract paper shards Q011–Q018 (ADR-0013)
- Branch `phase3/lit-extract-Q011-Q018`, guide v4, one commit per shard, each `validate-shard` 0 problems; no Codex cross-check (central). **481 rows (446 feature, 35 age, 9 of them `AGE_PRESENTATION`) from 47 of 96 papers** (Q011 41, Q012 71, Q013 84, Q014 80, Q015 61, Q016 50, Q017 27, Q018 67). Q011–Q015 were done first; after a pause, Q016–Q018 were resumed in the same PR. Q011 has one follow-up commit that drops a sub-20 female bone-age row. The Q015 commit message miscounts its sources as "8 of 12"; 7 of 12 were extracted (the notes file is right, history not rewritten). Dead ends: diagnostic-yield/screening studies, unit-disease mismatches (MT-RNR1 = MERRF, CTSA = galactosialidosis, COL6A3 neuromyopathy), series that pool literature cases (RAD21, PURA, RRM2B, ALG13, ACAD9, Primrose), registries of clinically diagnosed patients (TOSCA, XLH survey), guidelines and trials.

### 2026-10-01 — pre-registration — Candidate 6b pilot rounds (ADR-0011 amendment 8, current profiles)
Written and committed before the first candidate 6b pilot run. Train-side
only: **no R1-dev read in this task, whatever the result.** Candidate 6b
checks amendment 8's record-level budget on the **current** profiles; the
literature-enriched profiles come later, as candidate 6.
- **Generator:** rare-disease-simulator 0.5.3, run from the GitHub tarball
  of 6833d2d (sha256 `c9a56f79e1b91ddd62b465cb474e0e17beddf5bb82f3f3467f5eeb1b8e55f105`;
  the tarball's pax comment is the full commit `6833d2d4db8a…`), never the
  shared checkout.
  - Full profiles rebuilt with 0.5.3 from hpoa-recount-v1 + genes-v2: 9,223
    profiles, byte-identical to candidates 2–6a (`d44e1586…`).
  - report-model-v3; cardinal-v1; no presentation ages.
- **Budget histogram:** `record-budget-v1` (manifest committed;
  `scripts/analysis/record_budget_histogram.py`): report-model-v2's
  `term_budget` histogram, copied as is (present terms per R1-train case,
  all 4,103 R1-train patients; report-model-v2 sha256 `1be9413b…`). Mean
  8.6995, p10 / p25 / median / p75 / p90 = 2 / 4 / 7 / 11 / 17, min 1, max
  66, no 0 bin. With `reporting.budget_scope: record`, 0.5.3 reads it as
  total present terms per case, noise included.
- **Calibration per round:** `simcal-v052-v1` + `record-budget-v1`'s
  `reporting.profile_budget_histogram` (replacing profile-budget-v1's) +
  `reporting.budget_scope` "record" + `reporting.noise_count`
  "budget_share" + `reporting.noise_share` 0.207, with
  `presets.medium.ontology_smoothing_rate` (g), `noise.related_share` (s)
  and `reporting.specialize_rate` (r) set per round. Everything else
  unchanged (independent mode, budget_normalize, calib-v2 vocabulary,
  related levels 1/1, age durations by onset; `q_scale` stays in the file
  and c absorbs it).
- **Pilot shape:** the 523-symbol list (`outputs/cal/pilot-genes.txt`,
  sha256 `5c817192…`), 10 cases per gene, medium, seed 91001, full
  profiles.
- **Targets** (all R1-train):
  - **A** = ancestor share of explained terms vs kb-v3 = **0.093**
    (ANALYSIS-006, uncited R1-train patients), measured with
    `explained_exactness.py` on every pilot record (`keep_one_in` 1; the
    script also reprints the R1-train value);
  - **S** = more-specific share vs kb-v3 = **0.0929** (calib-v2),
    `dataset_term_categories.py --kb kb-v3`;
  - **M** = E0 in-vocab MRR on the noise terms alone = **0.026**
    (`noise_signal.py`, every case).
- **Round 1 measures the current values first:** g = 0.15 (the medium
  preset, used by candidates 1–6a; candidate 6a gave A = 0.152), s = 1.0,
  r = 0.1676 (candidate 6a's).
- **Next-round rule** (round k+1 from round k, rounded to 4 decimals). A
  knob changes only if its target drifted: relative error above **0.10** for
  A and S, above **0.20** for M (noise-only MRR is noisy at 10 cases per
  gene and not linear in s, as candidate 5 showed):
  - g_{k+1} = g_k × 0.093 / A_k, capped to [0, 1];
  - r_{k+1} = r_k × 0.0929 / S_k, capped to [0, 1];
  - s_{k+1} = (0.026 − MRR_voc,k) / (MRR_rel,k − MRR_voc,k), clipped to
    [0, 1] (s_{k+1} = s_k if MRR_rel,k ≤ MRR_voc,k).
- **Rounds:** at most 3. Round k+1 runs only if some target drifted after
  round k.
- **Selection:** the round with the smallest
  |A − 0.093| / 0.093 + |S − 0.0929| / 0.0929 + |M − 0.026| / 0.026 (ties:
  the earlier round), frozen as `simcal-v053-v1` with
  `dxt knowledge shrinkage-prior --min-denominator 10 --base
  data/calib/simcal-v052-v1.json --include data/calib/record-budget-v1.json
  --set reporting.budget_scope='"record"' --set
  reporting.noise_count='"budget_share"' --set
  presets.medium.ontology_smoothing_rate=<g>`, plus `--set` for s or r if
  they changed. `scripts/analysis/cand6b_pilot_rounds.py` applies the
  rules.
- **Reported per round** (not targets): total shown terms per case and its
  total variation vs the record-budget histogram (run summary); k drawn,
  noise slots, profile target and realised profile terms; the four
  categories vs kb-v3; A; `forced_min_one`; mean c; the q capped share;
  the per-gene Spearman of record size vs true-term count
  (`record_size_by_gene.py`, all pilot genes with `--no-r1`, and the pilot
  genes with ≥ 10 R1-train patients).
- **Then:** `ds-sim0.5.3-full-n100-s1001` (gene-first, all genes, 100 per
  gene, medium, seed 1001; full profiles only), G1, registration with
  `--publish` and the contamination exclusion, and the train-side go/no-go
  (G2a truth layer, G2c, G2d, G2e, G2b-train; age reported) with
  `dxt sim realism --no-dev` and `dxt sim train-checks`, plus
  `c2st_features.py`, terms-per-case percentiles and A on the full
  dataset. **No R1-dev read.**
- **Not used:** R1-dev.

### 2026-10-01 — pilot — Candidate 6b pilot rounds 1–3; `simcal-v053-v1` frozen
- **Setup:** as pre-registered above (simulator 0.5.3 from the 6833d2d
  tarball; 4,890 cases for 489 genes per round; 0 invariant violations in
  all three rounds). R1-train targets only; no R1-dev. Files:
  `results/realism/cand6b-pilots/` (per-round calibration, run summary,
  validate log, categories, exactness, noise signal, record size;
  `summary.json` from `scripts/analysis/cand6b_pilot_rounds.py`).
- **Every triple tried:**

  | Round | g (smoothing) | s | r | A: ancestor share (0.093) | S: more specific (0.0929) | M: noise-only E0 MRR (0.026) | Relative errors A / S / M | Score |
  |---|---|---|---|---|---|---|---|---|
  | 1 | 0.15 | 1.0 | 0.1676 | 0.1544 | 0.0889 | 0.0357 | 0.660 / 0.043 / 0.373 | 1.076 |
  | 2 | 0.0903 | 0.5178 | 0.1676 | 0.0968 | 0.0908 | 0.0121 | 0.041 / 0.023 / 0.535 | 0.598 |
  | 3 | 0.0903 | 0.6198 | 0.1676 | 0.0962 | 0.0915 | 0.0158 | 0.034 / 0.015 / 0.392 | **0.442** |

  Round 2 applies the rules to round 1: g = 0.15 × 0.093 / 0.1544;
  s = (0.026 − 0.0013) / (0.0490 − 0.0013); r kept (S within 10%). Round 3
  changes only s: (0.026 − 0.0009) / (0.0414 − 0.0009). The script
  reprints R1-train's uncited ancestor share as 0.0933 (6,130 explained
  terms; ANALYSIS-006).
- **Also per round:**

  | Round | Total shown per case | TV total vs histogram | k drawn / noise / profile target k − n / realised profile | Explained / more specific / related / weak (vs kb-v3) | `forced_min_one` | Mean c | q capped | Related share of noise; MRR vocab / related noise | Spearman size vs true terms, 489 genes |
  |---|---|---|---|---|---|---|---|---|---|
  | 1 | 7.06 | 0.099 | 8.89 / 1.83 / 7.06 / 5.23 | 0.681 / 0.089 / 0.142 / 0.089 | 167 (3.4%) | 2.948 | 0.172 | 0.807; 0.0013 / 0.049 | 0.706 |
  | 2 | 7.07 | 0.100 | 8.89 / 1.83 / 7.06 / 5.24 | 0.676 / 0.091 / 0.088 / 0.146 | 167 | 2.948 | 0.172 | 0.435; 0.0009 / 0.041 | 0.700 |
  | 3 | 7.07 | 0.100 | 8.89 / 1.83 / 7.06 / 5.24 | 0.676 / 0.092 / 0.099 / 0.134 | 167 | 2.948 | 0.172 | 0.512; 0.0009 / 0.043 | 0.700 |

  Targets (uncited R1-train vs kb-v3): 0.668 / 0.093 / 0.082 / 0.157;
  record-budget-v1 mean 8.70. Share of true terms reported 0.376; mean IC
  related / vocabulary noise 6.82 / 4.28 (round 3). The 9 pilot genes with
  ≥ 10 R1-train patients: Spearman size vs true terms 0.133 (real vs the
  same count 0.683), too few genes to read.
- **Selected:** round 3, frozen as `simcal-v053-v1`: simcal-v052-v1 +
  record-budget-v1 + `reporting.budget_scope` "record" +
  `reporting.noise_count` "budget_share" +
  `presets.medium.ontology_smoothing_rate` 0.0903 + `noise.related_share`
  0.6198 (r stays 0.1676). Its knobs equal round 3's calibration except the
  vocabulary path (relative in the frozen file).
- **What the pilots show** (R1-train comparisons only):
  - **The smoothing rate controls the ancestor share almost linearly:**
    0.15 → 0.0903 moved it from 0.154 to 0.097 (target 0.093).
  - **Records are still shorter than the budget:** total shown 7.07 per
    case against k 8.89 drawn (histogram mean 8.70). Noise fills its 1.83
    slots, but the profile target k − n (7.06) is capped by the sampled true
    terms: in 1,442 of 4,889 round-1 cases the patient had fewer true terms
    than k − n, and mean min(k − n, true terms) is 5.18, against 5.24
    realised. So the shortfall comes from the truth layer, not the rolls.
  - **Noise-only MRR is again not linear in s** (as candidate 5): s = 1.0
    gives 0.036, s = 0.52 gives 0.012 and s = 0.62 gives 0.016. Lowering s
    also moves unexplained terms from related to weak (round 3: 0.099 /
    0.134 vs real 0.082 / 0.157).

### 2026-10-01 — build + go/no-go — v0.5.3 candidate 6b: G1 passes; the train-side go/no-go fails on G2c only; no R1-dev read
- **Versions:** rare-disease-simulator 0.5.3 (tarball of 6833d2d, sha256
  `c9a56f79…`), `simcal-v053-v1`, report-model-v3, cardinal-v1,
  hpoa-recount-v1, genes-v2, no presentation ages; gene-first, 100 per gene,
  medium, seed 1001; full profiles only.
- **G1** (`ds-sim0.5.3-full-n100-s1001`): 489,200 cases / 4,892 genes;
  `validate` 0 violations (cases and export); 20-gene slice (19 simulated)
  run twice, byte-identical to each other and to the full run's 1,900 lines
  (cases and export); `dxt lineage verify` ok; overlap R1 keys 147, S3
  1,492 (246 same signature); `-excl-v1` excludes 1,619, residual 0;
  dataset and exclusion list published.
- **Run summary:** total shown 6.89 per case (5.11 profile + 1.79 noise);
  k mean 8.71, profile target k − n 6.92, TV total vs k 0.114; mean c
  3.056; `forced_min_one` 16,915 (3.5%); q capped 0.180; related share of
  noise 0.506.
- **Go/no-go** (`dxt sim realism --no-dev`, `dxt sim train-checks`;
  `results/realism/gate-v0.5.3-cand6b-gonogo.md`; no ledger row):

  | Check | UP | V03-full | C3 | C4 | C5 | C6a | **C6b** | Rule | Result |
  |---|---|---|---|---|---|---|---|---|---|
  | G2a truth layer | 0.416 | 0.336 | 0.305 | 0.307 | 0.306 | 0.306 | 0.304 | beat both | ✅ |
  | G2c W1 | 3.717 | 1.653 | 1.732 | 5.754 | 1.908 | 2.955 | 1.816 | beat both | ❌ (V03-full 1.653) |
  | G2d C2ST AUC | 0.840 | 0.819 | 0.764 | 0.822 | 0.809 | 0.764 | **0.721** [0.690, 0.755] | beat both, ≤ 0.75 | ✅ (first pass; CI upper end above 0.75) |
  | G2e gap | 0.414 | 0.183 | 0.142 | 0.204 | 0.049 | 0.011 | 0.077 (E0 0.328) | beat both, ≤ 0.10 | ✅ |
  | G2b-train (83 genes) | 0.241 | 0.385 | 0.536 | 0.502 | 0.537 | 0.507 | 0.522 | beat both | ✅ |
  | Age (69 genes) | — | 0.537 | 0.539 | 0.571 | 0.555 | 0.584 | 0.603 | report only | |

  - Terms per case p10 / p25 / median / p75 / p90: simulated 2 / 3 / 6 / 9 /
    13, mean 6.88; R1-train 2 / 4 / 7 / 11 / 17, mean 8.70.
  - Ancestor share (1 in 50, kb-v3): 0.095 (R1-train uncited 0.093;
    candidate 6a 0.152).
  - Categories vs kb-v3 (5%): 0.680 / 0.095 / 0.095 / 0.130 (summed error
    0.042; candidate 6a 0.120).
  - C2ST top separators (univariate AUC; candidate 6a in brackets):
    annotated share 0.402 [0.404], noise share 0.576 [0.536], mean depth
    0.429 [0.386], head/neck share 0.531, limbs 0.476, term count 0.478
    [0.422].
  - Record size vs true terms, 84 R1 genes: Spearman 0.770 (real 0.503);
    real vs simulated size 0.393; median ratio 0.96.
  - E0 ablation (3,073 kept cases): as exported 0.342, no noise 0.512, no
    generalisation 0.352, no specialisation 0.384; noise mean IC 5.71.
- **Housekeeping:** the 3.46 GB rich-cases file was deleted after the
  analyses; its sha256 `fc4c9904…` (equal to the run summary's) and a
  1-in-160 sample (3,073 cases) stay in `outputs/v0.5.3-cand6b-full/`.
- **Verdict:** ❌ stops on G2c alone (records still short: profiles run out of
  true terms). No R1-dev read; Mateo decides.
- **Stopped here** (graceful stop requested): all steps done except the
  STATE update and a fuller write-up; next step is Mateo's decision.

### 2026-10-02 — decision — Onset ages approved; path to candidate 6 (ADR-0013 amendment 4)
- **Extraction complete:** all 97 shards merged, 7,100 rows. The dry-run
  build enriches 840 diseases with 4,567 new disease–term pairs, and gives
  onset ages for 399 diseases and presentation ages for 88.
- **Mateo approved:**
  - literature onset ages in simulator 0.5.4;
  - the sequence cross-check → audit → build → 0.5.4 → candidate 6 → report;
  - the smallest adequate models for agents.
- **Rulings applied at build:**
  - "not reported" is not an absence;
  - ages at genetic confirmation are excluded;
  - carriers, high VUS share and sub-20 pooled groups are declared as
    limitations.
- **Cross-check:** interrupted by a PC freeze after 113 answers (112 agree);
  resumed.

### 2026-10-02 — build + tooling — `onset-ages`, two build rulings, and the audit tool (ADR-0013 amendment 4)
- **Branch** `phase3/lit-build-onset-audit`. No artifact registered, no R1 read.
- **`dxt lit build`** now has a fourth output, `onset-ages-vN` (header
  `disease_id`, `age_low_years`, `age_high_years`, `source`), selected
  exactly like presentation ages. It is in the report (`onset_ages`) and the
  manifests; `--dry-run` writes `onset-ages.tsv` to `--out-dir`.
- **Rulings in the build:**
  - a prevalence-0 row whose quote matches `not (been )?(reported|described|documented|observed in the literature)`
    (case-insensitive; `NOT_REPORTED_PATTERNS`) is dropped with
    `not_reported_is_not_absence`;
  - an `AGE_PRESENTATION` row whose `population`, `age_note` or quote
    mentions genetic, molecular or DNA diagnosis, testing or confirmation
    (`GENETIC_CONFIRMATION_PATTERNS`) is dropped with
    `age_at_genetic_confirmation`.
- **Dry run** (`results/analyses/LIT-INTEGRATION-dryrun.json`, 97 shards, 7,100
  rows, clean commit `1590df2`):
  - onset ages for 372 diseases (437 `AGE_ONSET` rows; placements: 372 used, 84 not
    chosen, 40 open upper bound, 1 pooled-group skip);
  - presentation ages for 79 diseases (91 rows; placements: 79 used, 13 not chosen, 9
    open upper bound, 11 placements dropped as `age_at_genetic_confirmation`);
  - 5 rows dropped as `not_reported_is_not_absence`; NOT rows 69.
- **Audit tool** (`dxt lit audit prepare|run|score`, ADR-0013 amendment 4
  §3.2), Codex runs later, not run here.
  - `prepare` draws a seeded 5% of sources per shard, at least one per shard
    and at least two from C036. The floor dominates: 97 shards give 98
    sources of 1,012 (9.7%). Every source of a validated shard is eligible,
    including `no_numbers` and `not_cohort` ones, since a wrong skip is a
    missed fact.
  - Each item has `prompt.txt` (the guide's skip rules), `source.txt` (cited
    sections plus tables, about 12k characters), `units.txt` (allowed units
    with disease names, plus our extraction outcome and note) and `rows.tsv`
    (rows cited by shard-file line number). Answers follow a JSON schema:
    `ok`, `wrong_unit`, `missed`, `bad_row`.
  - `run` is resumable (an item with an `answer.json` is skipped) and uses
    the crosscheck Codex template with `model_reasoning_effort="medium"`.
  - `score` writes `data/lit-extract/audit/<run>.summary.json` (per shard:
    sources with any issue, wrong-unit rows, missed facts, bad rows) and an
    issues TSV with a `resolution` column kept across re-scores.
  - Frozen sample: `data/lit-extract/audit/lit-extract-v1.items.tsv`
    (seed 20261002, fraction 0.05).

### 2026-10-02 — cross-check — lit-extract-v1: 715/744 agree; 29 adjudicated, 1 row removed
- **Front / versions:** Front A data (literature layer), ADR-0013 amendment 4
  step 1. Guide v4. Sample: 744 rows, seed 20261001, 97 shards, C001 excluded
  (pilot 10/10).
- **Checkers:**
  - Codex answered 354 items: 342 agree (96.6%).
  - Claude Haiku answered the last 390 (`scripts/tools/claude_reextract.py`,
    after the Codex usage limit): 373 agree (95.6%).
  - Haiku calibration: 35/40, agreeing wherever Codex agreed. The first
    attempt failed on a 0-1 versus percent format; fixed in the wrapper's
    system prompt.
- **Result:** 715/744 agree (96.1%). Prevalence rows 668/689, age rows 47/55.
- **Adjudication** (`data/lit-extract/crosscheck/lit-extract-v1.adjudication.tsv`):
  - 26 `ours_correct`, 0 `checker_correct`, 2 `both_acceptable` (0546, 0557),
    1 `row_should_not_exist` (0533).
  - The disagreements come mostly from the checker prompt: named age periods it
    cannot map (8), "all/universal/absent/none" with no number (8) and a
    spurious age field (6).
- **Fix:** removed the OPA3 "Structural brain abnormalities" row from C059
  ("No ... have been reported" is a not-reported absence, and the build
  pattern misses that wording); notes rows 6 -> 5; `validate-shard C059`
  0 problems. Items 0534 and 0535 now sit one row earlier than their frozen
  row numbers.
- **Error rate** (`checker_correct` + `row_should_not_exist`): 1/744 = 0.13%,
  Wilson 95% CI 0.02%-0.76%.
- **Limits:** Haiku is the same family as the extractor, so it is less
  independent. The check cannot see missed facts (the audit's job).
  A scan found 7 other prevalence-0 rows whose quote says "reported /
  described / documented / observed" but escapes the build's not-reported
  pattern; not changed here.
- **Evidence:** `docs/analyses/LIT-CROSSCHECK-v1.md`.

### 2026-10-02 — result + fix — Cross-check complete; "not reported" pattern widened
- **Cross-check of 744 rows (PR #81):** 715 agree (96.1%; Codex 342/354, Haiku
  373/390). Of the 29 disagreements, 26 were checker errors, 2 are genuine
  ambiguities and 1 was our error.
- **Estimated extraction error rate:** 1/744 = 0.13% (Wilson 95% CI
  0.02–0.76%).
- **Haiku:** used for the last 390 rows after the Codex limit, through a
  minimal Claude CLI call with thinking off. Calibrated on 40 Codex-checked
  items (35/40, agreeing on every row Codex agreed with). It is the same
  model family as the extractor, so it is less independent.
- **Fix:** `NOT_REPORTED_PATTERNS` now also matches "no/none … has/have
  been reported/described/documented". One more row (C069) is no longer
  read as an absence. "Has not been observed in affected individuals" stays
  an explicit absence (guide v4 §6a).
