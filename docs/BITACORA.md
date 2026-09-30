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
