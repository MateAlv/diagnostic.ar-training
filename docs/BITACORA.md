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
