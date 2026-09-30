# Plan — Reentrenamiento de GenPhenAI con sexo, edad y síntomas negados

The master plan for the "Optimización del modelo" axis of the Trabajo
Profesional (*Diagnóstico de Enfermedades Genéticas Poco Frecuentes mediante
Deep Learning*). It was written on 2026-09-28 after reading every repo in the
workspace, and revised the same day with Mateo's decisions (§14).

Keep it current: when a decision changes, edit this file, add an ADR in
`docs/decisions/`, and log the change in `docs/BITACORA.md`.

**Where to find what:**

| Question | Document |
|---|---|
| Rules | `CLAUDE.md` (repo root) and §10 below |
| How data may flow | `docs/DATA_LINEAGE.md` |
| How we avoid overfitting | `docs/EVAL_PROTOCOL.md` |
| What was run | `docs/BITACORA.md` |
| Every sealed-split read | `docs/TEST_LEDGER.md` |

---

## 0. TL;DR

**Goal.** Add three patient-level inputs to the gene prioritisation that
production serves today:
- **sexo**: male / female / unknown;
- **edad**: current age, plus age of onset when it is known;
- **síntomas negados**: e.g. "no tengo fiebre recurrente".

Today the model sees only the list of present HPO terms. The web collects sex
and date of birth but never sends them, and it throws away negated
phenotypes on the client.

**Two fronts, one shared evaluation, all in `diagnostic.ar-training`:**

| | Front A: "the network learns it" | Front B: "a module on top of the network" |
|---|---|---|
| Idea | Finish `rare-disease-simulator` so it produces patients with sex, age and negated terms. Retrain the GNN (PyTorch, warm-started from v3.0) with those inputs, plus the real R1-train patients | Keep the GNN. Re-score its full gene distribution with sex/age compatibility and negated-symptom evidence from HPO annotations. Learned weights come from R1-train |
| Cost / risk | High: simulator, dataset, retrain, ONNX. High payoff if it works | Low: CPU, fast iterations, interpretable. Ships first |
| Output | A `model-v4.x` bundle (new ONNX inputs), released through `diagnostic.ar-model` | Re-ranker `rr-vN`, released through `diagnostic.ar-model`; the ONNX stays unchanged |

Both fronts are judged by the **same harness, the same frozen splits and the
same metrics**. The reference is **E0**: production GenPhenia v3.0 as we
measure it. The anti-overfitting rules in `docs/EVAL_PROTOCOL.md` bind both.

**Window:** 40 days, from 2026-09-28 to **2026-11-07**. **Compute:** local
only (RTX 4070 Ti 12 GB, about 14 GB of free disk). Clementina XXI is not
used for now.

---

## 1. Why, and what the jury evaluates

**Anteproyecto commitments:**
- retrain with extra clinical variables: age, sex, location and absent
  symptoms (location is out of scope, §14);
- beat the model without the new features;
- MCRD as the final quantitative benchmark;
- a train/validation/test split.

**Rúbrica.** The file is
`/home/mate/diagnostic.ar/informe/Rúbrica del Informe Final (grupal).xlsx`.
The criteria this work feeds:

| Criterion | Weight | What this work must leave behind |
|---|---|---|
| 3★ Solution and architecture | 12 | Architecture views and justified decisions (`docs/decisions/`) |
| 4 Quality and metrics | 8 | **Measurements repeated over time that drove redesigns.** This is what `BITACORA.md` records |
| 6★ Methodology | 10 | Planned vs actual, with deviations explained (e.g. Keras+JAX → PyTorch) |
| 7 Automation | 7 | Versioned code, data and models; CI; reproducible runs from a SHA + manifest |
| 9 Risks and lessons | 6 | What failed and why, with numbers |
| 12 Innovation | 5 | Comparison against the state of the art (PhenoBrain, SHEPHERD etc. ignore sex, age and negation) |

**Authorship rule.** The informe must be written by the students. Using
IAG/IAA for its redaction is an ethics fault. Our documents are **evidence
and notes**; the team writes the informe prose (G9).

---

## 2. What exists today (verified 2026-09-28)

| Thing | Where | State |
|---|---|---|
| **Production model**: GenPhenia v3.0 | `diagnostic.ar-model` tag `model-v3.0.0`; registered here as source `genphenia_v3` | See notes below |
| Inference engine | `diagnostic.ar-model/vendor/genphenia_inference_engine/`; byte-identical copy in `diagnostic.ar-api/services/genphenai/inference_engine/` | `predict(hpo_ids)` takes present HPO ids only. The files import `inference_engine.*`, which doesn't match the directory name |
| v3.0 metrics | `GenPhenAI/GENPHENAI_RN_ARQUITECTURA_ENTRENAMIENTO.md:195-213` | Validation on its own simulated data: MRR 0.781, top-1 0.711, top-10 0.911 |
| **E0 (EXP-000, 2026-09-29)** | `docs/experiments/EXP-000.md`, `results/EXP-000/` | R1 MRR: dev 0.448 [0.399, 0.504], test 0.370 [0.266, 0.480] (publication-clustered CIs). MCRD 0.747. DDD 0.757 (annotation-derived, so inflated). S2 0.812. **10.6–14.2% of R1 patients have a gene outside v3.0's vocabulary.** Median latency 1–1.6 ms |
| GNN on real phenopackets (earlier) | `qa-agente-claude/docs/EVALUACION.md` | v3.0 alone: top-1 43.1%, MRR 0.508 on 501 patients (one per gene). In 23% of cases the true gene is outside the top 50 |
| Older real-case numbers | `GenPhenAI/GraPhens/validation_arena/*.csv` (checkpoint unknown, 2025-06) | MCRD MRR 0.070; Bitgenia MRR 0.128 |
| Upstream trainer | `GenPhenAI/GraPhens/training/` (Keras 3 + JAX) | Builds only v2.0 (4×GCN); cannot build v3.0 GIN. No trained Keras GNN exists. The 26M-sample training LMDB is not available |
| Upstream simulator | `GraPhens/src/simulation/phenotype_simulation/` | Uniform choice over annotated terms and ancestors; no frequencies, sex, age or negatives |
| **Our simulator** | `rare-disease-simulator` (MateAlv; 57 tests passing; up to date with origin since 2026-09-28) | See notes below |
| Re-ranker prototype | `/home/mate/diagnostic.ar/qa-agente-claude` (Mariano's repo, branch `feat/agente-v2`, uncommitted changes) | Bayesian re-rank of the GNN top 50 using HPOA frequencies and NOT. No age or sex. Results on real patients: symmetric −0.047 MRR; asymmetric k=0.3 −0.001; one negated finding −0.006 |
| **Real cohort with all three features** | `phenopacket-store` 0.1.27, registered here as `phenopacket_store` | 10,377 patients (10,305 usable): 9,030 have excluded features, ~9.5k known sex, 7.9k age, 5.8k disease onset. **Frozen split r1-v1** (§5.2) |
| Other benchmarks | Registered here as `mcrd` (229) and `ddd` (1,048) | Present phenotypes only; eval-only. No exact overlap with R1 |
| HPO data | Registered here (v2026-02-16) | `phenotype.hpoa`, `hp.json`, `genes_to_disease.txt`, `genes_to_phenotype.txt`. **5.45% of HPOA rows (15,412, across 457 diseases) cite R1 held-out publications and must be masked** |
| Web contract | `diagnostic.ar-api` origin/main `services/genphenai/app/main.py` | See notes below |

**Production model details:**
- PyTorch GIN: 3 layers, input 768 → hidden 512 → 5,229 genes. Class 0 is the
  placeholder `"-"`.
- Node features are BioBERT-NLI embeddings. Nodes are the observed terms plus
  all their ancestors; edges run child → parent.
- It is served as ONNX with inputs `x`, `edge_index` and `batch`.

**Our simulator's state:**
- The schemas include sex, age and negatives, and `parse_hpoa` already reads
  them.
- Missing:
  - profiles built from HPOA (only fixtures work today);
  - an `hp.json` loader;
  - a noise vocabulary;
  - the `validate` command;
  - an export that carries sex, age and negatives.
- It has generated 0 cases so far.

**Web contract:**
- The request is `RankRequest{hpo_ids, top_k}`.
- The API already computes the full 5,229-gene distribution, which is where a
  re-ranker plugs in.
- The frontend filters out negated terms and never sends `sexo` or
  `fechaNacimiento`.
- Both extractors hard-code `negated: False`.

**HPO releases in play:**

| Release | Used for |
|---|---|
| 2025-11-24 | The model's ontology |
| 2025-03-17 | The embeddings |
| 2026-02-16 | Our annotations |
| 2026-01-08 | The API's `hp.obo` |

Terms missing from the embedding table silently become zero vectors (G5).

---

## 3. Findings that shape the plan

1. **Retrain in PyTorch, not Keras+JAX** (ADR-0001). The upstream Keras
   trainer cannot build the production GIN, and no Keras GNN checkpoint
   exists. PyTorch gives us three things:
   - we can load `best_model.pt` exactly;
   - we can warm-start with zero-initialised new inputs, so at step 0 the
     model equals v3.0;
   - we can export to the ONNX runtime production already uses.
2. **Measure before improving.** v3.0 has never been evaluated on real data
   with a pinned, reproducible script. The simulated-vs-real gap is large.
   Every claim needs E0 measured on the same frozen cases.
3. **Negation alone is weak with HPOA-only knowledge.** HPOA has only about
   711 NOT rows, and the qa-agent measured about zero effect. The simulator
   must therefore produce clinically plausible negatives, and R1-train
   supplies real ones (3,713 train patients have excluded features).
4. **Sex and age are new, unused signal.** It comes from four places:
   - HPOA sex rows (448 M / 190 F) and onset (3,043 rows);
   - X-linked inheritance terms;
   - Orphanet ages;
   - real phenopackets.
5. **The upstream data format doesn't fit on disk.** Dense padded NPZ takes
   about 0.67 MB per sample, so 52k samples need about 35 GB. We store HPO
   indices and look up embeddings in the model.
6. **Simulated training leaks into real evaluation unless masked.** 5.45% of
   HPOA rows cite R1 held-out publications. Every KB and every simulator
   profile must drop them (`dxt` exports the held-out PMID list; see
   `docs/EVAL_PROTOCOL.md` §4).
7. **E0 is optimistic on R1, and we cannot fix that.** v3.0 was trained on
   `genes_to_phenotype` of about 2025-11, which includes annotations from
   those publications. Our masked models start at a disadvantage, so any win
   is conservative. Record this whenever E0 is compared.

---

## 4. Where the work lives

```
trabajo-profesional/                    ← workspace (not a repo): CLAUDE.md + .claude guard only
├── GenPhenAI/                           ⛔ READ-ONLY upstream. Push disabled in all 5 repos.
├── diagnostic.ar-training/              ✅ THIS REPO (MateAlv, private): plan, lineage, eval, both fronts
├── rare-disease-simulator/              ✅ Front A data generator (MateAlv)
├── diagnostic.ar-model/                 ✅ release channel: bundles, inference engine, model-vX.Y.Z tags
└── spanish-symptoms-recognizer/         (other axis; not touched here)
```

**`diagnostic.ar-training`** (ADR-0002):

```
data/sources.yaml          every external input: immutable URL + sha256 + role
data/splits/               frozen cohort splits (committed; hash-checked)
data/manifests/            lineage manifest per derived artifact (committed)
data/raw/                  fetched sources (gitignored; `dxt sources fetch`)
src/diagnostic_ar_training/
├── lineage/               registry (roles), manifests, sealed-split ledger, git state
├── cohorts/               Case schema, phenopacket parser, benchmark loaders
├── splits.py              publication-grouped split, sealing, held-out PMIDs
├── eval/                  metrics, paired bootstrap, contamination checks
├── rerank/                Front B
└── gnn/                   Front A
docs/                      INDEX, PLAN, BITACORA, DATA_LINEAGE, EVAL_PROTOCOL, TEST_LEDGER,
                           decisions/ (ADRs), experiments/ (one pre-registered file per EXP)
```

The other repos:
- **`rare-disease-simulator`** owns disease profiles (HPOA → `DiseaseProfile`),
  patient simulation and the compact export. It consumes the pinned HPO files
  and the held-out PMID list from this repo.
- **`diagnostic.ar-model`** stays the **release channel**. A candidate that
  passes its gate here is packaged there as `model-vX.Y.Z`, together with the
  vendored engine, then pinned by `diagnostic.ar-api` in `model.lock`.

Reuse rules:
- **GenPhenAI/** is only read. Code we need is copied here with a provenance
  header (source repo, path, commit, e.g. `GraPhens@7d861ff`).
- **`qa-agente-claude`** (Mariano) is reused by copying with provenance; it is
  never edited (G4).

---

## 5. Shared foundation (both fronts depend on it)

### 5.1 Data pins: one source of truth
- **Registry.** Everything is in `data/sources.yaml`, checked by
  `dxt sources verify`:
  - HPO v2026-02-16;
  - Orphanet ages 2025-12-09 (snapshot as a release asset, because
    Orphadata's URL is mutable);
  - phenopacket-store 0.1.27;
  - MCRD and DDD (GraPhens@7d861ff);
  - the v3.0 bundle.
- **Roles are enforced in code** (`lineage.registry.require_role`):
  - `eval` sources can never feed training, KBs or the simulator;
  - `cohort` sources are reached only through a frozen split.
- **Ontology for graphs.** For v3.0 parity, keep the model's `hp.json`
  (2025-11-24). For new terms, compute `gsarti/biobert-nli` embeddings with the
  same recipe (`name: definition`) and register them as a derived artifact
  with a manifest. Report the rate of unknown or zero-vector terms per cohort.
- **Gene vocabulary.** Frozen to v3.0's `genes.json` (5,229, same order), so the
  classifier warm-starts row for row. Genes outside it are counted and
  reported, never silently dropped.

### 5.2 Cohorts and the frozen split `r1-v1`
- **R1 = phenopacket-store 0.1.27.** It is split by publication (the connected
  components of shared PMIDs) with a salted hash, into:

  | Part | Patients | Publications | Use |
  |---|---|---|---|
  | **train** | 4,103 | 706 | may be used for training, KBs and the simulator |
  | **dev** | 1,883 | 324 | tuning and model selection only |
  | **test** | 2,548 | 350 | **sealed**: pre-registered gate reads only, each one ledgered |
  | **vault** | 1,771 | 352 | **sealed, opens once** for the final report |

  - Frozen in `data/splits/r1-v1.json`, content sha256 `b007aa17…`.
  - 72 packets were dropped: 69 were not single-gene and 3 had no present
    terms.
- **R2 = MCRD and R3 = DDD.** Eval-only and sealed in code, with the same
  ledger discipline as test. DDD is annotation-derived (EXP-000 Addendum 1),
  so it serves only as a no-regression check.
- **CIs on R1 resample publications** (EXP-000 Addendum 2).
- **S1 = our simulator's held-out split.** S2 = upstream-style simulated
  patients. Both are sanity checks, never headline numbers.

### 5.3 Evaluation harness (`diagnostic_ar_training.eval`)
- **One interface.** Every system implements
  `rank(case) -> full 5,229-gene distribution`. That covers E0 (the v3.0 ONNX),
  every re-ranker and every retrained model.
- **Metrics** (`eval/metrics.py`):
  - top-1/3/5/10/20/50 and MRR, with pessimistic tie ranks;
  - **paired bootstrap 95% CI** of Δ against E0 on the same cases;
  - the **harmed and helped rates**.
- **Ablation views on R1.** The same cases are run as:
  - present only;
  - + excluded;
  - + sex;
  - + age;
  - all.

  This attributes each gain.
- **Contamination checks** (`eval/contamination.py`) run between every
  training artifact and every eval cohort:
  - signature overlap;
  - present-set overlap;
  - PMID overlap.
- **Output.** Each run writes `results/<exp-id>/metrics.json`, a manifest, and
  a `BITACORA.md` entry.

### 5.4 E0 (EXP-000)
Run v3.0 (ONNX, the exact production bundle) on R1-dev, S2, and then (under
EXP-000's pre-registration) once on R1-test, R2 and R3. Also record latency
and the unknown-term rates. Every later number is a Δ against E0 from the same
code path.

---

## 6. Front A: finish the simulator, then retrain the GNN

### A1. Simulator v0.2: an HPOA structured backbone for every gene
This changes the simulator's original MVP scope (8 diseases with LLM
extraction). The GNN has 5,229 gene classes, so the simulator must cover them
all. The LLM enrichment stays as an optional later extension.

**Building profiles:**
- `build-profiles --from-hpoa`: turn `parse_hpoa` output into a
  `DiseaseProfile` for every OMIM/ORPHA disease with a gene in
  `genes_to_disease.txt`. Mapping:

  | HPOA field | Profile field |
  |---|---|
  | frequency | probability range |
  | aspect C onset | `age_of_onset` distribution |
  | per-annotation onset | per-phenotype onset |
  | `NOT` | `negative_phenotypes` |
  | `sex` column | phenotype sex restriction (new schema field) |
  | aspect I | inheritance |

  When HPOA has no onset, fall back to Orphanet ages.
- **Masking:** `--exclude-pmids data/splits/r1-v1.heldout-pmids.txt` drops
  every HPOA row citing a held-out publication, and the drop count goes in the
  dataset card.

**Pipeline fixes:**
- Add an `HpoOntology.from_json` loader.
- The `simulate` CLI must pass the ontology, noise vocabulary and labels
  through; today it drops them (`cli.py:293`).
- Sample the frequency per patient within its range.
- Require at least one observed positive per case.

**Sex:**
- By inheritance: XLR mostly male, XLD with male lethality mostly female,
  otherwise 50/50. HPOA sex rows override.
- Sex-restricted terms (HPOA sex rows, genital subtrees) are never emitted for
  the other sex.

**Age:**
- Sample onset, then a current age ≥ onset.
- A phenotype is emitted only if its onset ≤ current age.
- Progressive terms grow more likely with disease duration.
- Congenital terms are always eligible.

**Negatives.** Each case gets 0–k "asked and absent" terms, drawn from three
sources:
- (a) annotated terms of the true disease the patient lacks, weighted by
  frequency;
- (b) discriminative terms of confounder diseases (top-N by HPO overlap),
  keeping only terms not annotated at any level to the true disease;
- (c) NOT rows.

Invariant: a negated term is never an ancestor or descendant of a present term
in the same case.

**Noise, missingness, validation:**
- The noise vocabulary comes from nonspecific terms' frequency in
  **R1-train only**.
- **Covariate missingness:** sex, age and negatives are each absent in a
  configurable share of cases.
- The **`validate` command** reports:
  - phenotype counts;
  - observed vs expected frequency;
  - negative, missing and noise rates;
  - sex and age histograms against the priors;
  - the same statistics against **R1-train**, never dev, test or vault.

  It fails on invariant violations.
- Tests for each item.

### A2. Export v2: compact and feature-carrying
- Case record:
  `{case_id, gene, present[], excluded[], sex, age_years, onset_years, difficulty, seed}`.
  HPO ids are stored as integer indices, in JSONL or Parquet. A few hundred MB
  at most.
- The old `graphens.json` stays as it is, for backward compatibility and S2.
- The dataset id is `ds-<simver>-hpo<release>-n<per-gene>-s<seed>`. Each
  dataset has a lineage manifest in `data/manifests/` (inputs = source hashes
  + simulator SHA + held-out PMID list hash; outputs = file hashes). The files
  themselves are published as a release asset on this repo (ADR-0005).
- Sim train/val/test is split by case seed. Sim-val is used only for early
  stopping.

### A3. PyTorch training stack (`diagnostic_ar_training.gnn`)
- **`GinV3`:** a re-implementation that loads `best_model.pt`. **Parity gate:**
  identical logits (to 1e-5) against the production ONNX on 1,000 R1-train
  cases.
- **Dataloader:**
  - builds each graph on the fly from indices: observed terms + ancestors,
    edges child → parent;
  - looks node features up from the embedding memmap;
  - batches graphs PyG-style (concatenate + `batch` vector), no dense padding.
- **Extended variants.** All are initialised from v3.0 with zero-init new
  parameters, so their step-0 output is v3.0:
  - **A-neg (node channel):** negated terms enter as nodes flagged
    `[observed, ancestor, negated]`. They are *not* expanded to ancestors, and
    they connect only through ancestors already in the node set.
  - **A-neg2:** a second pooled graph, using `[h_pos, h_neg]`.
  - **A-cov:** `[sex one-hot(3), log1p(age), age_known, onset…]` → MLP →
    concatenated after pooling, or FiLM.
- **Training:**
  - AdamW, lr 5e-4, weight decay 5e-4, ReduceLROnPlateau;
  - AMP;
  - **feature dropout**, so the model tolerates absent inputs;
  - early stopping on sim-val;
  - **model selection on R1-dev only**.
  - Every run writes a manifest (dataset id, code SHA, config hash, seed).
  - Keep best + last checkpoints only.
- **Export:** ONNX with the new optional inputs; a new engine adapter version
  `"4.0"` in `diagnostic.ar-model`.

### A4. Experiment ladder: each step changes one thing

> **Revised 2026-09-29 (ADR-0010).** A-001 showed that updating v3.0's
> weights on simulated data harms real patients. From A-002 on, v3.0 is
> frozen and only the new inputs' parameters train (A-002f/A-003f/A-004f),
> on interviewed training cases. The table below is the original plan, kept
> for the planned-vs-actual record.


| Exp | Change | Question |
|---|---|---|
| A-000 | v3.0 through our PyTorch re-implementation | Parity with production (must equal E0) |
| A-001 | Fine-tune on `ds-sim0.2` (masked), **positives only** | Does our simulator alone help or hurt? This separates the data effect from the feature effect |
| A-002 | + negated (A-neg vs A-neg2) | Negation effect |
| A-003 | + sex/age covariates (A-cov) | Covariate effect |
| A-004 | All features | Combined effect |
| A-005 | + R1-train real patients mixed into training | Value of real data vs simulated |
| A-006 | Simulator ablations: remove negative source a/b/c, age gating, etc. | Which simulator mechanisms matter |
| A-007 | Train from scratch vs warm start (if local compute allows) | Is the warm start limiting? |
| ~~A-008~~ | ~~Expand the gene vocabulary~~: **rejected** (ADR-0006); the vocabulary stays v3.0's 5,229 genes | Future work |

**Release gate for `model-v4.0.0`** (evaluated once on R1-test, R2 and R3; see
`EVAL_PROTOCOL.md` §6):
- R1-test MRR Δ > 0 with CI > 0 on the "all features" view;
- no regression on "present only": Δ CI lower bound ≥ −0.01 on R1-test, R2 and
  R3;
- latency ≤ 2× v3.0.

---

## 7. Front B: a re-ranking module on top of the GNN

**Input:** v3.0's full distribution plus `{excluded[], sex, age_years,
onset_years?}`. **Output:** a re-scored full distribution. It uses the same
`rank(case)` interface as every other system.

### B1. Knowledge base
Copied and adapted from qa-agente-claude `kb/`, with provenance. For each
**gene**, aggregated over its diseases from `genes_to_disease`:
- phenotype frequencies (noisy-OR over descendants);
- the NOT set;
- the onset distribution (HPOA aspect C + Orphanet);
- inheritance;
- sex-restricted terms.

Built from sources with role `knowledge`, **with R1 held-out PMIDs masked**.
The KB gets its own manifest.

### B2. Features per (case, gene)

| Feature | Definition |
|---|---|
| `log_p_gnn` | log v3.0 probability (with temperature) |
| `neg_penalty` | Σ over excluded terms of log(1 − k·P(term\|gene)). Asymmetric: a term the gene doesn't annotate is neutral; a NOT-annotated term gives a small bonus |
| `sex_compat` | log P(sex\|gene), from inheritance and from sex-restricted *present* terms |
| `age_compat` | log P(age ≥ onset\|gene). An adult-onset-only gene in a 2-year-old is penalised; early onset in an adult is not |
| `onset_compat` | Likelihood of the reported onset under the gene's onset distribution |
| Missingness | Each feature is 0 when its input is absent, so the re-ranker is exactly the identity with no new inputs |

### B3. Versions

| Version | What | Fit on | Selected on |
|---|---|---|---|
| rr-v1 (rules) | `log_p_gnn + w·features`, 4 weights | none (grid search) | R1-dev |
| rr-v2 (learned, linear) | Listwise softmax / logistic regression over the top 200 genes | **R1-train** + sim S1-train | R1-dev |
| rr-v3 (optional) | LightGBM LambdaRank | R1-train + sim | R1-dev |

Re-rank at least the top 200; in 23% of real cases the true gene is outside
the top 50.

**Release gate:** the same R1-test / R2 / R3 rule as Front A, plus a
**harmed rate ≤ 5%**, plus the identity when there are no new inputs (tested).

### B4. The question agent
qa-agente-claude should eventually call this re-ranker or share its KB. That
is a coordination item with Mariano, outside this plan.

---

## 8. Integration path to the web (after a front passes its gate)

All new fields are **optional**; old clients get the same answers.

1. **`diagnostic.ar-model`:**
   - package the candidate (bundle + re-ranker KB) as `model-vX.Y.Z`;
   - CHANGELOG with Δ vs E0 and the ledger reference;
   - update the engine in `vendor/`.
2. **`diagnostic.ar-api` `services/genphenai`:**
   - `RankRequest` + `excluded_hpo_ids[]`, `sex`, `age_years`, `onset_years`;
   - update `model.lock`, the checkpoint SHA in `test_rank_genes.py`, and
     `reference_rankings.json`;
   - return `model_version` and `reranker_version`.
3. **Extractor negation.** The NLP axis must fix the hard-coded
   `negated: False` first (there is a NegEx helper in
   `services/phenotyper/negation.py`).
4. **Frontend:**
   - send negated terms as `excluded_hpo_ids`;
   - send `sexo` and an age derived from `fechaNacimiento`;
   - show which inputs were used.

---

## 9. Tracking and documentation

| Artifact | Scheme | Where |
|---|---|---|
| Sources | name + version + sha256 + role | `data/sources.yaml` |
| Splits | `r1-vN`, frozen, content hash | `data/splits/` |
| Simulator | SemVer tags `sim-vX.Y.Z` + CHANGELOG | `rare-disease-simulator` |
| Datasets, KBs, checkpoints | immutable artifact id + manifest; files as release assets | `data/manifests/` + GitHub releases (ADR-0005) |
| Experiments | `EXP-000`, `EXP-A-nnn`, `EXP-B-nnn`; pre-registered in `docs/experiments/<id>.md` before any sealed read | this repo |
| Sealed reads | one ledger row per read | `docs/TEST_LEDGER.md` |
| Model releases | `model-vX.Y.Z` tag + CHANGELOG with Δ vs E0 | `diagnostic.ar-model` |
| Chronology | dated entries: question, setup, result, verdict, next, informe evidence | `docs/BITACORA.md` |
| Decisions | ADRs | `docs/decisions/` |

**Also log what didn't work**, with numbers. Criteria 4 and 9 reward exactly
that.

---

## 10. Guardrails

**G1: GenPhenAI/ is read-only, forever.**
- Nothing is committed, pushed, edited, generated or installed-editable inside
  `GenPhenAI/`.
- This is enforced four ways:
  - the push URLs are set to `DISABLED--…`;
  - a `pre-push` hook exits 1;
  - `.claude/settings.json` has deny rules;
  - `.claude/hooks/guard_genphenai.py` blocks edits, mutating git, redirects,
    rm/mv/cp and `pip install -e` there. It has 22 test cases, in
    `.claude/hooks/test_guard_genphenai.py`.

**G2: our work lives in our repos.** Copied code carries a provenance header.

**G3: production only through a gate.**
- No change to `model.lock`, the deployed bundle or the API contract without
  a gate pass.
- New API fields are optional.
- Releases go through tag → release → lock.

**G4: teammates' repos are read-only** unless agreed: `qa-agente-claude`,
`diagnosticar-question-agent`, `spanish-symptoms-recognizer`.

**G5: pins.**
- One HPO release per experiment.
- The gene vocabulary is frozen.
- Everything is seeded.
- Manifests record the code SHA, config hash and inputs.

**G6: evaluation hygiene.** This is the whole of `docs/EVAL_PROTOCOL.md`, and
much of it is **enforced in code**:
- role checks;
- dev can't feed training;
- sealed parts need a pre-registered experiment, a clean tree and a ledger
  row;
- the vault opens once;
- split files are hash-checked.

**G7: feature-absent safety.** A candidate must reproduce E0 when sex, age and
negatives are absent: exactly for Front B, within the non-regression margin
for Front A. This is tested.

**G8: resources.**
- About 14 GB of disk: no dense datasets; best + last checkpoints only.
- Large files go out as release assets, not into git.
- Local GPU only for now.

**G9: informe authorship.** We produce evidence, never informe prose.

**G10: clinical safety.**
- The output is decision support, not a diagnosis.
- A negated symptom never *raises* a gene that annotates it.
- Sex and age act as compatibility evidence, never as hard exclusion, except
  anatomically impossible findings.
- No real patient data in our repos; the phenopackets, MCRD and DDD are
  public.

**G11: git.**
- One branch per task, and PRs.
- No AI co-author trailers.
- Never rewrite others' history.

**G12: log everything.** A result that is not in `BITACORA.md` did not happen.

**G13: data lineage is pristine.**
- Every artifact is traceable to pinned sources, a code SHA and params
  (`docs/DATA_LINEAGE.md`).
- Raw files are never edited.
- Derived files are never hand-edited.
- Artifact ids are never reused.
- `dxt lineage verify` must pass before any experiment is logged.

---

## 11. Phases (40 days: 2026-09-28 → 2026-11-07)

| Phase | Dates | Content | Exit criterion |
|---|---|---|---|
| **0. Foundation** | 09-28 → 09-29 ✅ | Repo, lineage, registry, split r1-v1, protocol, CI; the v3.0 adapter (production parity); the harness; the held-out PMID export; EXP-000 run | ✅ E0 table in `EXP-000.md` / `BITACORA.md` |
| **1B. Re-ranker v1** | 09-29 → 10-08 | ✅ KB `kb-v1` (masked, published, 09-29). Next: B2 features, rr-v1 grid on R1-dev, per-feature ablation | EXP-B-001: Δ vs E0 on dev; decide whether B has signal |
| **1A. Simulator v0.2** | 10-01 → 10-14 | A1 + A2 + `validate` + tests; tag `sim-v0.2.0`; masked dataset + manifest | `validate` report + dataset card |
| **2A. GNN stack** | 10-09 → 10-16 | `GinV3` + parity (A-000), dataloader, training loop, ONNX export | A-000 == E0 |
| **2B. Re-ranker v2** | 10-09 → 10-18 | Learned re-ranker on R1-train + sim; selection on dev | EXP-B-00x |
| **3A. Retraining ladder** | 09-29 → 09-30 ✅ | A-001 (full fine-tune), A-002f, A-003f (frozen, ADR-0010): all fail on real patients; A-004f not run | Tables in `EXP-A-*.md` |
| **4. Gates + vault** | 10-30 → 11-03 | One pre-registered test read per front's best candidate (and A+B combined); the release decision; the **vault** opened once for the final numbers of the chosen system vs E0 | Release + CHANGELOG + ledger |
| **5. Integration + evidence** | 11-03 → 11-07 | Optional API fields, frontend inputs (with the web and NLP axes); informe evidence pack | Staging demo; evidence index |

---

## 12. Risks (watch list; the ones that materialise go into the log and the informe)

| Risk | Mitigation |
|---|---|
| The simulator is far from real patients, so retraining degrades real performance | A-001 isolates the data effect; `validate` compares against R1-train; R1-train is mixed in (A-005); warm start + low lr |
| **Overfitting to dev through many iterations** | Dev → test drop is reported for every gated candidate; hyperparameter budget and every config tried are logged; test reads are budgeted; the vault stays untouched until the end (EVAL_PROTOCOL §5–6) |
| Leakage inflates R1 | PMID masking in the KB and simulator; publication-grouped split; contamination checks; E0-optimism noted (§3.7) |
| Negation carries little information | Confounder-based negatives; real R1-train negatives; report honestly if the effect is about zero |
| Sex/age signal is sparse | Aggregate HPOA + Orphanet + inheritance; report per-subset as well as overall |
| Local compute / disk | Index-based datasets; warm start; smaller ladders; A-007 is optional |
| No gain at all | Still a valid, measured result. Front B's identity guarantee means nothing ships that hurts |
| The 40-day window | Front B first; Front A's ladder is ordered by expected value |

---

## 13. How this maps to the informe sections (evidence only)

| Section | Evidence this work produces |
|---|---|
| 11 Solución implementada | Architecture of both fronts, the ADRs |
| 12 Metodología | Phase table in planned vs actual form, the experiment ladder, the lineage and eval protocol |
| 13 Herramientas | PyTorch, ONNX Runtime, Pydantic/Typer, GitHub releases as artifact store, and the alternatives dropped (Keras+JAX, dense NPZ, DVC) |
| 14 Experimentación | E0 vs every experiment, CIs, ablations, dev→test drops, harmed rate |
| 15 Cronograma | Real dates from `BITACORA.md` vs the anteproyecto months |
| 16 Riesgos y lecciones | Materialised risks with numbers |
| 18 Trabajos futuros | Location, disease-level labels, LLM-enriched profiles, prospective validation with ALAPA |

---

## 14. Decisions and scope

**Resolved (2026-09-28, Mateo):**
1. PyTorch for Front A (ADR-0001).
2. A new private repo, `MateAlv/diagnostic.ar-training`, for training,
   re-ranking and evaluation (ADR-0002). `diagnostic.ar-model` stays the
   release channel.
3. The plan and the log live in this repo.
4. 40 days, no corner-cutting: until 2026-11-07.
5. No Clementina XXI for now; local GPU only.
6. The simulator's unpushed commit `a40d414` was pushed on 2026-09-28.
7. Strict anti-overfitting and pristine lineage (ADR-0003, ADR-0004,
   `EVAL_PROTOCOL.md`, `DATA_LINEAGE.md`).

**Out of scope:**
- Geographic location (no data source links it to genes).
- The NLP negation fix (the NLP axis owns it).
- The question-agent redesign.
