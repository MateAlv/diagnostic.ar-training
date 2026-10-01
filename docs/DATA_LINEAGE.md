# Data lineage

Every number we report must trace back, with no gaps, to:
- pinned external bytes;
- a code SHA;
- a set of parameters.

This document says how that works and what we still cannot trace.

## 1. The graph

```mermaid
flowchart LR
  subgraph sources [data/sources.yaml: immutable URL + sha256 + role]
    HPO[HPO 2026-02-16<br/>hp.json, phenotype.hpoa,<br/>genes_to_*] 
    ORPHA[Orphanet ages<br/>2025-12-09]
    PPS[phenopacket-store 0.1.27<br/>role: cohort]
    BENCH[MCRD, DDD<br/>role: eval]
    V3[genphenia-v3.0 bundle<br/>role: baseline]
  end
  PPS --> SPLIT[data/splits/r1-v1.json<br/>train/dev/test/vault]
  SPLIT --> HELD[held-out PMIDs]
  HPO --> MASK[masked HPOA]
  HELD --> MASK
  MASK --> KB[Front B KB<br/>manifest]
  ORPHA --> KB
  MASK --> PROF[simulator profiles]
  ORPHA --> PROF
  PROF --> DS[ds-sim… dataset<br/>manifest + release asset]
  SPLIT -- train only --> DS
  DS --> CKPT[Front A checkpoints<br/>manifest]
  V3 --> CKPT
  SPLIT -- train only --> RR[rr-vN weights<br/>manifest]
  KB --> RR
  V3 --> RR
  CKPT --> RES[results/EXP-…]
  RR --> RES
  V3 --> RES
  SPLIT -- dev / sealed test, vault --> RES
  BENCH -- sealed --> RES
  RES --> LOG[BITACORA.md + TEST_LEDGER.md]
```

## 2. Rules

1. **Nothing enters without a pin.** Every external file is listed in
   `data/sources.yaml` with an immutable URL and its sha256. For a source
   whose upstream URL is mutable (Orphadata), we publish a snapshot as a
   release asset of this repo and pin that.
2. **Raw bytes are never edited.** `data/raw/` is populated only by
   `dxt sources fetch`, which verifies the sha256 whatever the origin (a local
   copy or the URL). GitHub release URLs are downloaded with `gh`, so private
   release assets (the Orphanet snapshot, the v3.0 bundle) work too. Code gets paths only through `registry.open_source(name,
   purpose)`, which also checks the role **[code]**.
3. **Roles limit flow [code].**
   - `knowledge` may feed anything.
   - `eval` may only be evaluated on.
   - `baseline` may be evaluated on or warm-started from, but never trained on
     as data.
   - `cohort` is reachable only through a frozen split, whose parts have their
     own purposes (`EVAL_PROTOCOL.md` §1).
4. **Every derived artifact has a manifest.** Datasets, KBs, embeddings,
   checkpoints and re-ranker weights each get
   `data/manifests/<artifact-id>.json`, recording:
   - the kind;
   - the creation time;
   - the code (repo, SHA, dirty flag);
   - the inputs (`id` + sha256: sources, splits, other artifacts, the
     held-out PMID list);
   - the params and their hash;
   - every output file with sha256 and size.

   `build_manifest` refuses a dirty working tree **[code]**.
5. **Artifact ids are immutable [code].** A changed artifact gets a new id
   (e.g. `ds-sim0.2.0-hpo20260216-n200-s42` → `…-s43`, or `sim0.2.1`).
   `write_manifest` refuses to overwrite.
6. **Storage.**
   - Manifests, splits, configs and results tables are committed to git.
   - Large binaries (datasets, checkpoints, KBs) are uploaded as **GitHub
     release assets** of this repo, one release per artifact id; the URL goes
     in the manifest notes (ADR-0005).
   - Local copies can be deleted and re-fetched; their hashes are re-checked.
7. **Cross-repo inputs are pinned by SHA.** Simulator output used here records
   the `rare-disease-simulator` commit and its config hash. Code copied from
   upstream or teammates carries a header naming the source repo, path and
   commit.
8. **Verify before logging.** Before an experiment is recorded, run
   `dxt lineage verify`. It re-hashes sources, re-checks split hashes, and
   re-hashes every manifest's outputs that are present locally.

## 3. Adding a source

1. Get an immutable URL: a release asset, a commit-pinned raw URL, or our own
   snapshot release.
2. Compute its sha256.
3. Choose its role, and justify it in the `notes` field.
4. Add the entry to `data/sources.yaml`, with `local_candidates` if a verified
   copy exists on this machine.
5. Run `dxt sources fetch <name>` and `dxt sources verify`.
6. Log it in `BITACORA.md`. If it is a patient source, it must get a frozen
   split before anyone looks at model outputs on it.

## 4. HPO versions in play

| Release | Where | Used for |
|---|---|---|
| 2026-02-16 | `hpo_*` sources | Annotations, KB, simulator profiles, graph ontology for new models |
| 2025-11-24 | inside the v3.0 bundle (`hp.json`) | v3.0's own graphs (parity) |
| 2025-03-17 | v3.0 embeddings (BioBERT-NLI memmap) | Node features; missing terms are zero vectors |
| 2025-11-24 | phenopacket-store 0.1.27 metadata | The cohort's annotations |
| 2026-01-08 | diagnostic.ar-api gateway `hp.obo` | Production extraction (outside this repo) |

Every evaluation reports the share of case terms that are unknown to the
model's ontology or zero-embedded.

## 5. Known gaps (declared, not fixable)

- **v3.0 training data is unavailable.** Here is what we know about it:
  - it was simulated from `genes_to_phenotype` (HPO ~2025-11);
  - it had 5,000 patients per gene, with `include_reverse_edges=False`;
  - it was built on the original author's machine.

  We cannot mask R1 publications out of it, so E0 on R1 is optimistic
  (`EVAL_PROTOCOL.md` §4.5).
- **The original sources of MCRD and DDD** are not documented in GraPhens;
  they must be cited in the informe once found. GraPhens also fine-tuned an
  experimental model on DDD (`validation_arena/finetune_ddd_model.py`). There
  is no evidence that v3.0 did.
- **DDD looks annotation-derived.** 97.1% of its cases carry an
  inheritance-mode term, and the median case's terms are all verbatim
  annotations of the gene (EXP-000 Addendum 1). It overstates real-patient
  performance of any model trained on HPO annotations.
- **R1 terms are often verbatim HPO annotations** (78% of dev cases are fully
  annotated, vs 3.5% for MCRD). This quantifies the E0-optimism caveat above.
- **ClinVar and ClinGen evidence** (gene profiles, ADR-0008) cites
  publications that may include R1 papers. These sources contribute no
  phenotype terms; they only shift a disease's weight within its gene. Not
  masked; declared.
- **Bitgenia cases** (`GraPhens/validation_arena/Casos_Bitgenia*.json`) are
  not registered. Their origin and consent status are unknown, so they are
  not used (G10).

## 6. Record of lineage events

| Date | Event | Details |
|---|---|---|
| 2026-09-30 | Source added | `orphanet_phenotypes`: Orphadata product 4 (2026-06-23), release `data-snapshot-2026-09-30-product4` |
| 2026-09-30 | Simulator v0.4 artifacts built and published | `hpoa-recount-v1`, `cardinal-v1`, `report-model-v1` (superseded by `report-model-v2`, same fit in the simulator's format), `genes-v2`, `simcal-v04-v1`, `literature-panel-v1` (§7) |
| 2026-09-30 | Realism baselines | `dxt sim realism` on UP (`graphens_sim_20251202`) and V03 (`ds-sim0.3.1-A-n100-s1001`), plus a smoke run on the ANALYSIS-001 10-gene sample; ledgered as baselines |
| 2026-09-28 | Sources registered | 9 sources; all verified from local copies (`dxt sources fetch --no-download`) |
| 2026-09-28 | Split `r1-v1` frozen | content sha256 `b007aa17741c2309a2fce9e36aaa77608d3d2b1311630e96c77be9d39e462ccf`, before any model was run on the cohort |
| 2026-09-29 | Sources added | Orphanet 2026-06-23 alignments + ages (release `data-snapshot-2026-09-29`); HGNC, Orphanet genes + prevalence, ClinGen (release `data-snapshot-2026-09-29-genes`); MONDO v2026-09-01 and ClinVar 2026-09 by immutable URL |
| 2026-09-29 | Artifact `kb-v3` built and published | Front B KB, schema 2: ADR-0007 frequencies (phenotypes at frequency 1.0: 32,615 in kb-v1 → 649), Orphanet 2026-06 onset + exact alignments (onset for 9,487 diseases; v3.0 genes with onset 4,286 → 4,529), gene → disease weights from `genes-v1` |
| 2026-09-29 | **Artifact `kb-v2`: VOID. Do not use** | Built by mistake: a failed CLI edit left the schema-1 command path, so it used the 2025-12 Orphanet ages with no alignments and no gene weights (built from `cbd34fa`, before the CLI was fixed). Its id is kept burnt, not deleted or reused. The intended KB is `kb-v3`. Build commands now refuse existing ids before doing any work (`ensure_new`) |
| 2026-09-29 | Artifact `genes-v1` built and published | Gene profiles (ADR-0008): 5,568 genes, 13,960 disease entities (11,125 simulable); 5,050 of v3.0's 5,228 genes are simulable. Weights calibrated on R1-train only |
| 2026-09-29 | Artifact `kb-v1` built and published | Front B KB from commit `d3a2e3e`, release `kb-v1`: 12,802 diseases, 5,148 genes, 249,434 phenotype annotations; 15,412 held-out-PMID rows masked. Masking audit: R1-dev cases fully covered by KB annotations fell from 78.1% (unmasked) to 16.1% |
| 2026-09-29 | Source added | `graphens_sim_20251202` (S2, role eval) from GraPhens@7d861ff; MCRD and DDD marked `sealed` |
| 2026-09-29 | E0 measured (EXP-000) | Production parity: bit-identical to the vendored engine on 300 cases. Sealed reads of r1-v1/test, MCRD and DDD ledgered |
| 2026-09-28 | Leakage measured | 15,412 of 282,723 HPOA rows (5.45%, 457 diseases) cite R1 held-out PMIDs; MCRD/DDD have 0 exact (gene, present) overlaps with R1 |

## 7. Simulator v0.4 artifacts (ADR-0011, ADR-0012)

All are fitted or counted on R1-train only. Each has a manifest in
`data/manifests/` and, when large, a release of the same tag.

| Artifact | What | File the simulator reads |
|---|---|---|
| `hpoa-recount-v1` | `phenotype.hpoa` with rows citing held-out PMIDs recounted as `n/m` over R1-train phenopackets (`reference R1-TRAIN:r1-v1`), dropped when `m < 3` | `phenotype.hpoa` (`build-profiles --hpoa`); also `feature-onsets.tsv` (per-feature onset quartiles, ≥ 3 patients) and `data/hpoa-recount/hpoa-recount-v1.stats.json` (kept/recounted/dropped per disease) |
| `cardinal-v1` | Hallmark features: Orphadata product 4 diagnostic criteria and pathognomonic signs (new source `orphanet_phenotypes`), plus count proxies (`m ≥ 10`, `n/m ≥ 0.8`) | `data/cardinal/cardinal-v1.tsv` (`disease_id, hpo_id, kind, source`) |
| `report-model-v1` | Reporting model, first layout (superseded, kept for lineage) | — |
| `report-model-v2` | The same fit, in the simulator's `report-model` v1 format | `report-model.json` (release `report-model-v2`) |
| `genes-v2` | Gene profiles with R1-train patient counts in the weight and zero weight for somatic-only and unsupported links; profiles from `hpoa-recount-v1` | `genes.json.gz` (release `genes-v2`) |
| `simcal-v04-v1` | `frequency.shrinkage_mean`: median pooled count-based frequency of `hpoa-recount-v1` | `data/calib/simcal-v04-v1.json` |
| `literature-panel-v1` | Literature prevalence of 37 features of 8 diseases, with citations | `data/realism/literature-panel-v1.tsv` (read by `dxt sim realism`) |

**Realism reports** (`dxt sim realism`, `dxt sim report-model-check`) go to
`results/realism/`, each with a manifest `realism-<label>`. Every run reads
R1-dev and appends a row to `results/realism/LEDGER.md`; baselines (UP,
V03) and checks do not count against the 3-candidate budget, and the
command refuses a fourth candidate version. `dxt sim gate` writes the G2
comparison table (`gate-<name>.json`, `.md`).

## 8. Literature-enriched profiles (ADR-0013 amendment 2)

`dxt lit build --version N` turns `data/lit-extract/rows/*.tsv` into three
artifacts. It reads every C/P shard of `shards.tsv` and every Q shard of
`shards-papers-v2.tsv` that has a passing report, re-validates each one in
memory, and refuses any shard that fails. Code:
`knowledge/lit_build.py`; tests: `tests/test_lit_build.py`, one or more per
rule.

| Artifact | What | File the simulator reads |
|---|---|---|
| `hpoa-lit-vN` | Feature rows as HPOA phenotype rows (aspect P, evidence `PCS`, biocuration `diagnostic.ar-training:lit-extract`, reference = `source_id`) | `phenotype.hpoa`, plus `data/lit-build/hpoa-lit-vN.report.json` |
| `hpoa-enriched-vN` | `hpoa-recount-v1` with `hpoa-lit-vN` appended; a `#derived` header line records both sha256 | `phenotype.hpoa` (`build-profiles --hpoa`) |
| `presentation-ages-vN` | One age range per disease from `AGE_PRESENTATION` rows | `presentation-ages.tsv` (`simulate --presentation-ages`, sim ≥ 0.5.1) |

`--dry-run --out-dir … --report …` writes the files and the report with no
artifact id and no manifest. The dry run on main's 37 shards is
`results/analyses/LIT-INTEGRATION-dryrun.json`.

**Where amendment 2 is silent**, the build does the following, as ruled
in ADR-0013 amendment 3. Each choice is counted in the report.
- **Rule 5 citations.** Rows carry a `source_id`, not a PMID list. A paper
  is cited by its PMID. A chapter is cited by its NBK id, its own PMID (from
  the GeneReviews index `GRtitle_shortname_NBKid.txt`), a Bookshelf URL
  `…/books/NBK…/`, or `br.fcgi?book=gene&part=<shortname>`; HPOA writes the
  last two forms. Terms are compared after resolving alternative ids.
- **Rule 2 skip.** A "unit-specific row" is any non-`pooled_group` row from
  the same source, for the same term, on the same disease id.
- **Zeros.**
  - A `pooled_group` row with prevalence 0 becomes NOT on every listed
    disease. A `0%` row would be a positive annotation.
  - Every validated prevalence-0 row without both counts is read as an
    explicit absence (guide v4 §6a). That includes rows with only
    `n_assessed`. Shards extracted before v4 are not told apart.
- **Rule 6, counts** (amendment 3). From one source, only the count row
  with the largest denominator is kept ("distinct sources only"). If two
  rows share that denominator and their n/m differ by more than 0.20, the
  term is dropped from that source (`ambiguous_populations`). The pooled
  row lists every source in `reference`, `;`-separated.
- **Rule 6, percentages** (amendment 3).
  - Preference order: both sexes, then the largest stated `n_assessed`
    (0 when not stated), then unit before `pooled` before `pooled_group`,
    then source id and file order.
  - The guard: when one source's rows are still tied after sex and n, and
    their prevalences differ by more than 0.20, the term is dropped from
    that source (`ambiguous_populations`).
  - A percentage is still written beside literature counts. The simulator
    ignores it, by its precedence.
- **Sex.** The `sex` column is `MALE`/`FEMALE`, as HPOA writes it. A pooled
  row keeps it only when every pooled row agrees, as the simulator does.
- **Rule 7.**
  - A missing low end is 0 ("before X", or a range that starts prenatally).
  - A missing high end gives no range, so the row is not used.
  - A `pooled_group` age row applies to each listed disease that has no
    other `AGE_PRESENTATION` row from the same source.
  - After population size, a row for both sexes beats a sex-restricted
    row.
- **Onset column** stays empty: no feature row carries a feature onset age.
