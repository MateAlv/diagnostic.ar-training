# HANDOFF: integrate `ft-v1.1` into diagnostic.ar-model

> **Superseded** by [HANDOFF-v4-prod.md](HANDOFF-v4-prod.md) ([ADR-0020](decisions/0020-v4-validated-and-next.md)): F3 replaces
> the integration of `ft-v1.1`. Kept for the record.

For whoever integrates Phase 2's production-ready model ([ADR-0018](decisions/0018-ft-v11-production-ready.md)) into
`diagnostic.ar-model` and the API. It follows the structure of that repo's `docs/HANDOFF-deploy-rerank-v1.md`. Date:
2026-10-09. Nothing in `diagnostic.ar-model` has been changed.

## Which package
Two packages are built. Both use the same `ft_prod.py`, the same format and the same θ.

| Package | Knowledge | Status |
|---|---|---|
| **`dist/ft-v1.1-confirmed/`** | `ft-kb-all-v2` (every `r1-v1` paper masked) | **Recommended production default.** It is exactly the artifact that passed both sealed reads |
| `dist/ft-v1.1-prod/` | `ft-kb-prod-v1` (nothing masked) | Built, **not recommended**. On dev it adds negation harms; see [below](#not-recommended-ft-v11-prod-unmasked-knowledge) |

## What the model is
GenPhenAI v3.0 (E0, `model-v3.0.0`), unchanged, plus a residual on its 5,229 gene logits:

    probs = softmax(z + r),   r_g = −Σ_k θ_k f_k(patient, g),   θ_k ≥ 0

- **Five features**, each 0 when its input is unknown:
  - the gene is limited to the other sex;
  - the gene's strict earliest onset is later than the patient's onset (or age), as a flag and as log1p(years);
  - a female patient and an X-linked-recessive-only gene;
  - the excluded terms contradict an obligate phenotype of every disease of the gene.
- **The residual can only lower a gene.** With no new input it is 0, and the output is E0's.
- **θ** was fitted on 4,103 real patients (`r1-v1` train, EXP-P-003). The export holds the mean of the 3 seeds:
  2.132, 2.472, 2.206, 2.786, 2.982.
  - The two other features of the trained model, `onset_lenient_gap` and `neg_embed`, have θ = 0 in every seed. They
    are dropped, so production needs no HPO embeddings.
- **Architecture:** [`fig_f_ft_v11_architecture.png`](evidence/figures/fig_f_ft_v11_architecture.png). The figure shows
  `ft-kb-all-v2`, the knowledge of the confirmed package.

**Evidence** (ADR-0018). Sealed real patients, `ft-v1.1-c1-lin-all-ens` on `ft-kb-all-v2`, Δ MRR vs E0 with a
paired-bootstrap 95% CI:

| Read | Patients | Δ MRR [95% CI] | Harmed |
|---|---|---|---|
| [EXP-P-005](experiments/EXP-P-005.md), `p2-v1` test | 3,587 | +0.00138 [+0.00070, +0.00232] | 6 (0.17%) |
| [EXP-P-006](experiments/EXP-P-006.md), final check, post-E0 | 1,072 | +0.00054 [+0.00005, +0.00129] | 3 (0.28%) |

**Known limitation of the confirmed package: the masking artefact.** Masking removes some inheritance rows, so four
genes count as X-linked-recessive-only although they are not: OFD1, F8, SLC9A6 and THOC2. Female patients with these
genes are lowered. All 6 EXP-P-005 harms (0.17%) were females with OFD1 or SLC9A6. This is included in the confirmed
numbers above.

## Files to copy
From `dist/ft-v1.1-confirmed/` in this repo (also listed in `SHA256SUMS` there):

| File | Bytes | sha256 |
|---|---|---|
| `ft_prod.py` (numpy and the standard library only) | 8,312 | `054893684cfda65d7ddbc835f5c1baa45bb159690e98ca14bf192e2ebaaea63d` |
| `ft-v1.1-confirmed-bundle.json.gz` (`ft-v1.1-prod-bundle/1`) | 43,684 | `6bb6bb40d85a815c3bf8fb467cbfa9c32d34164ced280eb96d4f4228ddeee6c4` |
| `parity-fixture.json.gz` (tests only) | 4,361,103 | `440580df3c8e039965e3fb2b7e8f756de691e30111769a1fba47e4002ad37b0d` |

- **The bundle** holds:
  - E0's gene list in output order;
  - the per-gene arrays;
  - the obligate phenotypes with their ancestor closures;
  - θ and provenance.
- **Provenance:**
  - knowledge `ft-kb-all-v2`, sha256 `18cf37f1…`;
  - θ from `ft-v1.1-c1-lin-all-ens`, sha256 `89e3ea09…` (ADR-0018's pinned bundle);
  - lineage in `data/manifests/ft-kb-all-v2.json`, `ft-v1.1-c1-lin-all-ens.json` and
    `ft-v1.1-confirmed-package.json`.
- **The bundle format name** `ft-v1.1-prod-bundle/1` is shared by both packages; it names the format, not the
  knowledge.

## Steps, in order

1. **Vendor the files.** Copy the three files into `diagnostic.ar-model`, e.g. `models/ft/ft-v1.1-confirmed/`.
   - Add a config that pins the bundle's sha256 and `model-v3.0.0`.
   - `ft_prod.load(path, sha256=...)` refuses a modified file: the service must not start if it fails.
2. **Call it next to the inference engine.** After v3.0 runs on the present terms, and before the top-k:

   ```python
   model = ft_prod.FtProd(ft_prod.load(bundle_path, sha256=PINNED))  # once, at startup
   assert model.genes == tuple(engine.genes)                         # E0's output order
   probs = model.apply(logits, case_inputs)          # from v3.0's logits, or
   probs = model.apply_probs(v3_probs, case_inputs)  # from v3.0's probabilities
   ```

   - `log(E0 probabilities)` can replace the logits in `apply`, because softmax ignores a constant added to every
     gene.
   - `apply_probs` returns its input array itself when no gene changes.
   - `results`, `specialties` and `confidence` must all come from the returned distribution.
3. **API inputs** (all optional; `case_inputs` is a dict):

   | Key | Type | Unknown |
   |---|---|---|
   | `sex` | `"male"` or `"female"` | anything else, or absent |
   | `age_years` | current age, float | `None` |
   | `onset_years` | age at onset, float; used instead of the age when given | `None` |
   | `excluded` | HPO ids, release 2026-02-16 | `[]` |

   - A negative age or onset counts as 0; a non-finite one counts as unknown.
   - An unknown HPO id changes nothing.
   - Present terms go to v3.0 as today; the residual does not read them.
4. **Port the tests.**
   - **Parity:**
     - For each fixture case, decode `e0_logits_f32_b64` (little-endian float32, base64) and call
       `apply(logits, inputs)`.
     - The result must match `expected_probs` at `indices` within 1e-9, and give the same `rank_expected` for
       `gene_index`.
     - `ft_prod.softmax64(logits)` must match `e0_probs` within 1e-15 (exact on the same machine).
     - The fixture has 200 `r1-v1` dev cases (seed 0) and 7 synthetic edge cases: no inputs, unknown sex, negative
       age, negative onset, only excluded terms, only an unknown excluded id, and every input.
   - **With the vendored engine** (as `test_rerank_parity.py`): run v3.0 on each case's `present` terms and check
     its probabilities against `e0_probs`.
   - **Identity** (as `test_rerank_identity.py`): with no new input, `apply` equals softmax of the logits bit for bit,
     and `apply_probs` returns the same object.
   - **Reference implementations:** `tests/test_ft_prod.py` in this repo, which also checks monotonicity (no gene
     rises above what renormalisation alone gives) and determinism.
5. **Staging first.** Deploy behind a flag, with the checklist below.
6. **Production** after Mateo's OK. Shadow mode first is suggested: compute both orders, log both, show E0's.

## Checklist
- [ ] `/healthz` reports `ft-v1.1-confirmed` and the bundle's sha256. A wrong sha256 stops startup.
- [ ] **Identity:** a request with no sex, age, onset or excluded terms returns exactly E0's output: scores and order,
      end to end.
- [ ] Each of these patients sees the gene move down when it is in E0's top 10:
  - a female patient with an X-linked-recessive-only gene;
  - a patient with a gene limited to the other sex;
  - a patient whose onset is earlier than the gene's earliest onset.
- [ ] Latency: one residual is a few numpy operations over 5,229 genes. Measure the endpoint's p95.

## Rollback
- **Immediate, no redeploy:** a flag (e.g. `FT_V11_ENABLED=false`) that skips the call and returns v3.0's
  distribution. Sending no new inputs has the same effect.
- **With redeploy:** remove the pinned bundle from the model config.

## Limits
- **Absent findings in the app come from the question agent,** not from publications as in R1. The negation feature
  can only lower a gene, which bounds the difference, but it is not measured on interview answers.
- **The effect on interview answers is not measured** for any input.
- **The masking artefact** (above): OFD1, F8, SLC9A6 and THOC2 are treated as X-linked-recessive-only.
- **The obligate-phenotype rule can be wrong about real patients.** It counts a frequency of n/n with n ≥ 5 in
  phenotype.hpoa as obligate, and some such rows count only the patients who had the finding. The confirmed knowledge
  hides the rows from R1 papers, so this showed up only with the unmasked knowledge (below).

## Not recommended: `ft-v1.1-prod` (unmasked knowledge)
`ft-kb-prod-v1` is the same build with nothing masked: `dxt ft kb --mask-scope none`, same sources, code and 49
sex-curation overrides. The bundle `ft-v1.1-prod` reuses θ without refitting. The files are in `dist/ft-v1.1-prod/`:

| File | Bytes | sha256 |
|---|---|---|
| `ft-v1.1-prod-bundle.json.gz` | 45,793 | `db73e80fa931126b5b81ff04df38f0e871ef41ecb7a434d7e489c6ef327e1f10` |
| `parity-fixture.json.gz` | 4,363,620 | `b6fc76152cd87de5f57f43426f35562b941832919fcce766ad5fec84bfe3e3c9` |

The `ft_prod.py` there is the same file.

**Knowledge diff** against `ft-kb-all-v2` (`data/ft/ft-v1.1-prod/package-report.json`):

| Field | Genes changed |
|---|---|
| Sex limitation | 0 |
| X-linked-recessive-only | 7: OFD1, F8, SLC9A6, THOC2 lose it (the artefact is gone); CSTF2, DOCK11, MCTS1 gain it |
| Strict earliest onset | 288: 287 gain one, 1 earlier |
| Lenient onset (not used) | 133 |
| Negatable | 62: 57 gain, 5 lose |

**Dev sanity run** (descriptive, not a claim), `r1-v1` dev, 1,883 patients. The unmasked knowledge includes the dev
papers, so a dev patient can be scored with knowledge curated from their own publication:

| System | Knowledge | Δ MRR vs E0 [95% CI] | Helped | Harmed |
|---|---|---|---|---|
| `ft-v1.1-prod` | `ft-kb-prod-v1` | +0.00168 [−0.00128, +0.00419] | 289 | 11 (0.58%) |
| `ft-v1.1-confirmed` | `ft-kb-all-v2` | +0.00289 [+0.00136, +0.00461] | 291 | 2 (0.11%) |

**Cause** (`data/ft/ft-v1.1-prod/dev-harmed.json`): all 11 harms come from the obligate-phenotype feature.
- **8 are FBXO11 patients of PMID:30057029.** That paper's own rows give "strabismus 8/8" and similar, which makes
  FBXO11 negatable through the n/n ≥ 5 rule. These patients have the finding excluded.
- **1 is KDM6B:** "mild intellectual disability 14/14" from another R1 paper, and the patient has intellectual
  disability excluded.
- **2 are ASS1,** harmed under both knowledges.

The unmasked knowledge removes the X-linked artefact (the 7 female OFD1 dev patients stay at rank 1 under both), but
it adds 57 negatable genes through such rows. It was never confirmed on sealed patients.

## Parity of both exports
On all 1,883 dev patients plus the edge cases:

| Package | Max \|Δp\| vs `FtV1`, from logits | From probabilities | From log-probabilities |
|---|---|---|---|
| `ft-v1.1-confirmed` | 7.6e-19 | 6.7e-16 | 2.2e-16 |
| `ft-v1.1-prod` | 7.6e-19 | 2.1e-15 | 2.1e-15 |

- **Tolerance:** 1e-9.
- **Dropped features:** dropping the two zero-θ features changes no output (|Δp| = 0).
- **Ensemble:** the mean θ equals the seed ensemble, |Δr| ≤ 8.9e-16.
- **Fixtures:** both use the same 200 dev cases. The synthetic edge cases use another anchor patient in each,
  because the excluded terms are chosen from each knowledge's negatable genes.

## Restrictions
- Do not rebuild or edit the bundle or the knowledge. Use the published files with their sha256.
- Commits and PRs carry no AI co-author or AI mentions.
- API changes are additive: every new field is optional.
