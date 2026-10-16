# HANDOFF: deploy v4 (F3) through diagnostic.ar-model

For the session that deploys the final model of Phase 4 ([ADR-0020](decisions/0020-v4-validated-and-next.md)
decision 4) through `diagnostic.ar-model` and the API, staging first. It follows the structure of
[HANDOFF-ft-v1.1-prod.md](HANDOFF-ft-v1.1-prod.md), which this document supersedes: `ft-v1.1` is not to be
integrated. Date: 2026-10-15. Nothing in `diagnostic.ar-model` has been changed, and no GitHub release or tag
was made.

## What F3 is
Two artifacts replace production's E0 (`model-v3.0.0`):

1. **The network `genphenia-v4.0`**: `R5x-f4-ef2f309462` (`last.pt`, sha256 `22edfd7e…`), E0's architecture (GIN,
   hidden 512, 3 layers, attention pooling, edges child → parent, no covariates, no node features) trained on
   `sim4` and fine-tuned with 4,369 real phenopacket-store patients (`p3-v1` train folds 0–3). It reads the present
   HPO terms only, through E0's exact input contract: same graph, embeddings, gene order and ONNX signature
   (`x` [N, 768] float32, `edge_index` [2, E] int64 → logits [1, 5229]).
2. **The layer `v4-layer`** (numpy) on the network's 5,229 logits `z`:

       s = z + r,   r_g = mean over the 3 members m of (−Σ_k θ_mk f_k(patient, g)),   θ ≥ 0, f ≥ 0
       s_g −= max(s) − min(s) + 1   for every gene the patient's recorded sex cannot have
       probs = softmax(s)

   - **The add-on `p3-addon-v1-all`** (on `p3-addon-kb-v1`, E0's own knowledge), `ft-v1.1`'s residual refit on the
     network's out-of-fold scores. It can only lower a gene. Mean θ of the 3 members:

     | Feature | Reads | Mean θ |
     |---|---|---|
     | `sex_mismatch` | sex: gene limited to the other sex (101 male-, 42 female-limited genes) | 2.850 |
     | `onset_strict_late` | onset, else age: the gene's strict earliest onset is later | 0.051 |
     | `onset_strict_gap` | log1p of those years | 0.020 |
     | `onset_lenient_gap` | log1p of the years to the lenient earliest onset | 0.063 |
     | `xlr_female` | female sex: the gene's diseases are all X-linked recessive (128 genes) | 3.754 |

     `neg_obligate` and `neg_embed` have θ = 0 in every member. They are not shipped: production needs no HPO
     embeddings nor obligate phenotypes, and **excluded terms change nothing**.
   - **The hard sex rule `sex-kb-v3`** ([P4-SEX](analyses/P4-SEX.md)): 101 genes a woman cannot have and 36 a man
     cannot have, from E0's knowledge plus HGNC locations, with differences of sex development excluded. Blocked
     genes go below every other gene, in their own order. Age is not a hard rule ([P4-AGE](analyses/P4-AGE.md)).
   - **No new input** (unknown sex, no age, no onset) gives r = 0 and no blocked gene: the output is
     softmax(network logits), bit for bit.

**Evidence.** Capped MRR (cap 10), Δ vs E0 with a publication-cluster bootstrap 95% CI:

| Reading | System | Patients | Δ vs E0 [95% CI] | Helped / harmed vs E0 |
|---|---|---|---|---|
| Vault, read once ([EXP-V-002](experiments/EXP-V-002.md)) | network + add-on | 2,678 uncited | +0.0649 [+0.0473, +0.0833] | 1,110 / 541 |
| Second CONFIRM read ([P4-CONFIRM](analyses/P4-CONFIRM.md)) | **F3** | 406 uncited | +0.0717 [+0.0332, +0.1200] | 161 / 108 |
| Same read | **F3** | 933, all | +0.0678 [+0.0421, +0.0967] | 316 / 171 |

- On the vault, uncited patients' gene is first 16.0% of the time (E0 11.7%) and in the top 10 34.5% (29.5%).
- **Sex rule** (F3 vs network + add-on): 130 helped, 0 harmed on folds 0–3; 31 helped, 0 harmed on fold 4. No
  fold-4 patient's true gene is on the list. Patients whose top 50 shows a gene impossible for their sex: network
  20, F3 0.
- **Add-on** (fold 4, network + add-on vs network): 101 helped, 5 harmed.
- **Limits** ([ADR-0020](decisions/0020-v4-validated-and-next.md)): the gain comes from genes with real training
  patients; mapping every term to its parent keeps 35% of it on the vault; the newest publications
  (`p2-fresh-v1`) show no gain. The harmed counts vs E0 are those of a different network, not of a re-ranker.

## Artifacts

| File | Bytes | sha256 |
|---|---|---|
| `genphenia-v4.0.tar.gz` (release asset, not in git) | 90,840,335 | `62b2c5e8eb4609d1003a81c3632ea82cf2b1173f4ffc646a02ecb66d38d95cc3` |
| its `artifacts/graphens_best_model/model.onnx` | 18,119,152 | `fafbecbed8585073b2afe9b6a481ee3182f21ff733f6e96745945d75bc7daf29` |
| its `checkpoints/best_model.pt` | 18,120,309 | `bff1a05b982bf2be5711c76ec3850d66d3c629921b25aa43c956d45146d621e2` |
| `dist/v4-layer/v4_layer.py` (numpy and the standard library only) | 8,603 | `2ca18111c9586c182156d98242299faa054da67f239affe922645e16562090b3` |
| `dist/v4-layer/v4-layer-bundle.json.gz` (`v4-layer-bundle/1`) | 22,571 | `3bdeeaedff851dc81983425f489d66bcff2b124a20df2283332d6c16bd69e21e` |
| `dist/v4-layer/staging-fixture.json` (tests only) | 51,205 | `99d83c92838f8059a3335eb08701f7762f6838ee6143c573a45b60c012b5734c` |

- **Where the tarball is:** `dist/genphenia-v4.0/` of the worktree that built it (ignored by git), and a copy with
  its `.sha256` in `data/interim/release/genphenia-v4.0/`. `dist/genphenia-v4.0/MANIFEST.json` and the `.sha256`
  are committed.
- **The bundle is E0's `genphenia-v3.0` with two files replaced,** `model.onnx` and `checkpoints/best_model.pt`.
  Every other file is E0's, byte for byte (spec.json, genes.json, DAG, embeddings, hp.json).
  - **`best_model.pt` is the v4 network in E0's checkpoint layout:** `model_state_dict` holds the GinV3 (PyG-named)
    state dict with E0's keys, shapes and dtypes in E0's order, plus `model_version: "4.0"` and the source run
    (`R5x-f4-ef2f309462`, `last.pt` sha256). It loads with `torch.load(weights_only=True)`. E0's optimizer,
    scheduler and validation entries are left out, which is why the tarball is smaller than E0's.
  - **The engine's own model, loaded from this `best_model.pt`, is the v4 network.** It is built and loaded as the
    engine's export does (`build_adapter_model`, `_load_raw_state_dict`, `convert_checkpoint_state_dict`; no
    missing or unexpected key), and it gives the shipped ONNX's ranks (Parity, below).
  - **The engine reports version "3.0", and that cannot change without an engine change.** The vendored engine
    reads spec.json's `model_version` as the architecture selector (`build_adapter_model`), and
    `normalize_model_version` rejects "4.0" ("Expected one of: 2.0, 2.5, 3.0"), so a bundle saying "4.0" would not
    load. spec.json keeps "3.0" (GenPhenAI v3.0's architecture), and the engine's `/healthz` and `predict` report
    it. Identify the model by the tarball's sha256, or by `best_model.pt`'s `model_version` ("4.0") and sha256.
    To report "4.0", the engine (diagnostic.ar-model and its copy in the API) must map "4.0" to the v3.0
    adapter: a code change, not made here.
  - **Keep the shipped `model.onnx`.** The engine uses it as is (a fresh registry always takes the prebuilt file).
    The engine can no longer rebuild a missing `model.onnx`, for E0 or for v4 (checked on scratch copies, torch
    2.14):
    - torch's default exporter needs `onnxscript`; with it, `torch.export` fails on the adapter's
      data-dependent `_is_single_graph`;
    - the legacy exporter drops the unused `batch` input, so the engine's own parity check fails. The file it
      wrote before failing is wrong: `index_add_` exports as a scatter without summation. Against the shipped
      ONNX it differs by up to 1,539 logits for v4 (true-gene rank identical for 3,646 / 4,369) and 280 for E0
      (2,549 / 4,369).

    So a missing `model.onnx` fails or gives a wrong model, never E0. Ship and verify the file by its sha256.
- **Reproducible packing:** diagnostic.ar-model's `scripts/package_bundle.sh` repacks E0's own files into E0's
  tarball (`2201b7f2…`) and these files into `62b2c5e8…` (two independent builds gave the same sha256). Unpacked
  into `models/base/genphenia-v4.0`, it gives the same sha256 there.
- **Build 1 is withdrawn.** A first tarball (`2ce8e9d0…`, lineage id `genphenia-v4.0`) kept E0's `best_model.pt`.
  It was never published. Its copy is in `data/interim/release/genphenia-v4.0/superseded-b1/`. Its `model.onnx`
  is byte-identical to this one, so the layer package built against it stands unchanged.
- **The layer bundle** holds E0's gene list in output order, each member's θ on the 5 kept features, the per-gene
  arrays they read, the two sex lists, and provenance: `p3-addon-v1-all` (`31299383…`), `p3-addon-kb-v1`
  (`089ccf87…`), `sex-kb-v3` (`7317a6bd…`), the network's `last.pt` and `model.onnx` hashes.
- **Lineage:** `data/manifests/genphenia-v4.0-b2.json` (built from `423ade0`) and `v4-layer-package.json` (built
  from `3becf05` on the same `model.onnx`).
  Parity reports: `results/P4/release/genphenia-v4.0-parity.json` and `v4-layer-parity.json`. Commands:
  `dxt v4 release-network` and `dxt v4 release-layer` (`v4/release.py`).

## Parity
Every patient of `p3-v1` train folds 0–3 (`patients.load_addon`): 5,053 patients, 4,369 with a gene in E0's
vocabulary. No sealed data was read.

| Check | Result |
|---|---|
| GinV4 → GinV3 weights (same keys and tensors), CPU, 200 patients | logits bit-identical (Δ = 0) |
| ONNX (`systems.genphenia_v3` on the bundle) vs torch `last.pt` (GPU, the research path) | max \|Δ logit\| 1.3e-3 (relative 2.7e-6); true gene's rank identical for 4,369 / 4,369 |
| diagnostic.ar-model's vendored engine on the packed tarball vs torch | max \|Δp\| 2.4e-5; rank identical 4,369 / 4,369; top-10 order identical 5,053 / 5,053; engine = `systems.genphenia_v3` exactly |
| The engine's own torch model loaded from the tarball's `best_model.pt` (CPU) | max \|Δ logit\| 1.1e-3 vs the shipped ONNX, 1.2e-3 vs torch `last.pt`; rank identical to torch 4,369 / 4,369 |
| The engine rebuilding a deleted `model.onnx` from `best_model.pt` | fails (see above), for E0 as well |
| Packaged layer vs research F3 (`v4.addon.Addon`, then `v4.sexrule.SexRule`), same logits | scores bit-identical for 5,053 / 5,053; ranks identical 4,369 / 4,369, on scores and on probabilities |
| θ = 0 features dropped vs the full add-on with embeddings | bit-identical for 5,053 / 5,053 |
| No input ⇒ softmax(logits) | bit-identical for 5,053 / 5,053 |
| End to end: ONNX logits + package vs research F3 on torch logits | ranks identical 4,369 / 4,369 |

No rank changed, so there were no tie flips to report. The layer changes the output of 4,822 of the 5,053 patients
(most have a recorded sex or age).

## Steps, in order
1. **Done 2026-10-15:** `model-v4.0.0` is published as a pre-release in MateAlv/diagnostic.ar-model (PR #12, tag on
   `78b37f2`), with assets `genphenia-v4.0.tar.gz` and `v4-layer.tar.gz` and the layer in `models/v4/v4-layer/`.
   **Release the network in diagnostic.ar-model**, as `model-v3.0.0` was, after Mateo's go:
   - unpack the tarball into `models/base/genphenia-v4.0` (DVC);
   - `scripts/package_bundle.sh models/base/genphenia-v4.0 dist/` must print `62b2c5e8…`;
   - a `model-v4.0.0` entry in `CHANGELOG.md` with the evidence above, and the release asset.
2. **Pin it in the API** (`diagnostic.ar-api`): the `model-v4.0.0` tag and the tarball's sha256 instead of
   `model-v3.0.0`. The vendored engine is unchanged; the network needs no code change.
3. **Vendor the layer:** copy `v4_layer.py`, `v4-layer-bundle.json.gz` and `staging-fixture.json` (also listed in
   `dist/v4-layer/SHA256SUMS`), e.g. to `models/v4-layer/`. Pin the bundle's sha256 in the config:
   `v4_layer.load(path, sha256=...)` refuses a modified file, and the service must not start if it fails.
4. **Call it between the network and the softmax:**

   ```python
   layer = v4_layer.V4Layer(v4_layer.load(bundle_path, sha256=PINNED))  # once, at startup
   assert layer.genes == tuple(engine.genes)                            # E0's output order

   graph = engine.preprocessor.preprocess(hpo_ids)                      # the known present terms
   logits = engine.runtime.predict_logits(graph)[0]                     # what engine.predict softmaxes
   probs = layer.apply(logits, case_inputs)                             # float64, sums to 1
   ```

   - `engine.predict` returns probabilities only, and the layer needs the logits. log-probabilities would also
     work, but a probability that underflows to 0 loses its order: use the logits.
   - Results, specialties and confidence must all come from the returned distribution. Rank it as the engine does
     (descending probability).
   - `layer.scores(logits, case_inputs)` gives the pre-softmax scores, if they are needed.
5. **API inputs.** All optional; `case_inputs` is a dict:

   | Key | Type | Unknown | Effect |
   |---|---|---|---|
   | `sex` | `"male"` or `"female"` (any case) | anything else, or absent | the add-on lowers genes limited to the other sex and, for a female, X-linked-recessive-only genes; the hard rule moves the impossible genes (101 for a woman, 36 for a man) to the bottom |
   | `age_years` | current age, float | `None` | used when the onset is unknown: lowers genes whose earliest onset is later (small weights) |
   | `onset_years` | age at onset, float | `None` | as the age, and takes precedence |
   | `excluded` | HPO ids | `[]` | **none** in F3 (θ = 0); accept the field, but promise no effect |

   - A negative age or onset counts as 0; a non-finite one counts as unknown.
   - Present terms go to the network as today; the layer does not read them.
6. **Port the tests:**
   - **Fixture** (`staging-fixture.json`, 32 cases). Each case has `hpo_ids` (known present terms), `inputs`, and the
     expected top 10 of the network alone (`network_top`) and of F3 (`f3_top`), as [gene, probability]:
     - 9 whose sex rule blocks a gene of the network's top 10, 10 whose top 10 the add-on changes, 10 others;
     - 3 `no-inputs` cases, where `f3_top` equals `network_top`.

     Run the network on `hpo_ids`, then the layer on `inputs`. The same genes must come in the same order, with
     each probability within 2e-6 of the fixture, for both lists. The patients are from folds 0–3, which the
     network was fine-tuned on: this is a parity fixture, not an evaluation.
   - **Identity:** with no sex, age or onset, `layer.apply(logits, inputs)` equals the engine's own softmax of the
     same logits bit for bit, whatever `excluded` holds.
   - **Reference implementation:** `tests/test_v4_release.py` in this repo (only lowers, sex block, θ = 0 features
     dropped, the committed package against its `SHA256SUMS` and fixture).
7. **Staging first,** behind a flag, with the checklist below. **Production** after Mateo's OK.

## Staging checklist
- [ ] `/healthz` reports the `model-v4.0.0` tarball's sha256 and the layer bundle's sha256. A wrong sha256 stops
      startup. The engine's own `model_version` still says "3.0", the architecture (above).
- [ ] **No inputs ⇒ softmax of the new network.** A request with no sex, age or onset (with or without excluded
      terms) returns exactly the plain `genphenia-v4.0` engine output: scores and order, end to end. The old
      "E0 unchanged" checks no longer apply: the network itself changed.
- [ ] **Fixture parity** on all 32 cases (step 6), through the deployed endpoint.
- [ ] **Sex rule:** for the 9 `sex-rule` cases, F3's top 10 shows no gene of the other sex's list, while the
      network's top 10 (`network_top`, no inputs) shows one.
- [ ] `rerank-v1.0.0` and `ft-v1.1` are off for v4 (below).
- [ ] Latency: the network is E0's size; the layer is a few numpy operations over 5,229 genes. Measure the
      endpoint's p95.

## Rollback
- **Immediate, no redeploy:** a flag (e.g. `V4_LAYER_ENABLED=false`) that skips the layer gives the plain v4
  network. Sending no sex, age or onset has the same effect.
- **Back to E0:** pin `model-v3.0.0` again (tarball `2201b7f2868afaf00439f76a6197bcf1d94eccc5ea171173719ca48c517a61c8`)
  and turn the layer off with it. The layer's add-on was fitted on v4's scores: never apply it to E0's logits.

## What NOT to stack
- **`rerank-v1.0.0`** (staging only, [ADR-0016](decisions/0016-final-deployment-and-close-out.md)): not on v4. It
  lowers the network on publication negatives: −0.0030 [−0.0065, −0.0001] on folds 0–3 (ADR-0020).
- **`ft-v1.1`** (`dist/ft-v1.1-confirmed/`): superseded. Its θ was fitted on E0's logits, and the add-on inside
  `v4-layer` is its refit on v4. Never run both.
- **No hard age rule:** every variant that could block a true gene harmed at least 4 development patients
  ([P4-AGE](analyses/P4-AGE.md)).

## Limits
- **Interview answers are not measured.** The evidence is from published patients: sex, age and onset as recorded
  in phenopackets.
- **The recorded sex is trusted.** Genes of differences of sex development are never on the list, but a wrong sex
  entry would block the true gene of a sex-limited condition.
- **Excluded terms change nothing in F3**, although the API may accept them.
- **Present terms the DAG does not know are left out** by the API, as for E0. A case with none is unscorable (422).
- **The probabilities are not chances of being right.** Like E0's, the network's top-1 probability overstates how
  often that gene is right, more so for genes from publications E0 never cited. The validation measured the order of
  the list, not these numbers. Folds 0–3, out of fold (`results/P3/addon/calibration.json`, cross-fitted networks):
  - top gene at 80–95%: right 54% of the time (uncited 38%);
  - top gene at ≥ 99%: right 94% of the time (uncited 83%);
  - E0 overstates more: ECE 0.226 against the network's 0.184 (uncited 0.309 against 0.277). ECE is the mean gap
    between the shown probability and how often it is right.
  - The web app already presents it as a score, not a probability (deploy session, 2026-10-16). It shows "bajo"
    below 0.01 and otherwise three decimals, under "Puntaje del modelo: ordena la lista, no es una probabilidad"
    (`frontend/src/lib/genes-api.ts`); the report says the same (`results-report.ts`). With v4 the reference case
    shows 0.999; any change to that presentation is Mateo's call.

## Restrictions
- Do not rebuild or edit the bundles or the knowledge. Use the published files with their sha256.
- Commits and PRs carry no AI co-author or AI mentions.
- API changes are additive: every new field is optional.
