# diagnostic.ar-training: agent guide

This repo adds sex, age and negated symptoms to diagnostic.ar's gene
prioritisation (GenPhenia v3.0 GNN), on two fronts:
- **A:** simulator + GNN retrain;
- **B:** a re-ranker on top of the GNN.

Read `docs/INDEX.md` first. It maps every document, and `docs/PLAN.md` is the
master plan.

## Non-negotiables

1. **Never modify anything under `../GenPhenAI/`.** It is upstream work;
   pushes are disabled there and a hook blocks writes. Copy what you need into
   this repo with a provenance header (source repo, path, commit).
2. **Data lineage** (`docs/DATA_LINEAGE.md`):
   - Inputs come only from `data/sources.yaml`, via
     `lineage.registry.open_source(name, purpose)`.
   - Every derived artifact gets a manifest (`lineage.manifest`), built from
     a clean, committed tree.
   - Artifact ids are never reused.
   - Never edit `data/raw/`, `data/splits/*.json` or `docs/TEST_LEDGER.md` by
     hand.
3. **Anti-overfitting** (`docs/EVAL_PROTOCOL.md`):
   - Patients of a cohort come only from `splits.load_part`.
   - R1-dev never feeds training.
   - R1-test and R1-vault are sealed: they need a pre-registered
     `docs/experiments/<EXP-id>.md`, a clean tree and a reason, and each read
     is ledgered. The vault opens once.
   - MCRD and DDD are eval-only.
   - Mask `data/splits/r1-v1.heldout-pmids.txt` from every KB and simulator
     profile.
   - Statistics the simulator or a re-ranker estimates from patients come
     from R1-train only.
   - Log every dev configuration tried, not only the winner.
4. **Every claim is a Δ vs E0** (production v3.0) on the same cases, with a
   paired-bootstrap 95% CI and the harmed rate.
5. **Log every run in `docs/BITACORA.md`,** failures included.
   `dxt lineage verify` must pass first.
6. **Informe authorship.** The Trabajo Profesional informe must be written by
   the students. Produce evidence (tables, figures, decision records), never
   informe prose.
7. **Production changes only through a gate.** Releases go through
   `diagnostic.ar-model`; new API fields are optional.
8. **Git.**
   - One branch per task; PRs into `main`.
   - Never add AI co-author trailers.
9. **Resources.** About 14 GB of disk free. No dense-feature datasets. Large
   files are GitHub release assets (ADR-0005), not git. Local GPU only
   (RTX 4070 Ti, 12 GB).

## Commands

```bash
make setup | make sources | make check   # setup also installs the pre-push hook (make hooks)
.venv/bin/dxt sources list|fetch|verify
.venv/bin/dxt split freeze|show|heldout-pmids r1-v1
.venv/bin/dxt lineage verify
.venv/bin/dxt knowledge recount|cardinal|report-model|shrinkage-prior|panel   # simulator v0.4 inputs (ADR-0011)
.venv/bin/dxt sim realism|gate|report-model-check   # realism gate (ADR-0012); each R1-dev read is ledgered in results/realism/LEDGER.md
```

## Where things are

- **Code:** `src/diagnostic_ar_training/`
  - `lineage/`
  - `cohorts/`
  - `splits.py`
  - `eval/`
  - `rerank/` (Front B)
  - `gnn/` (Front A: `GinV3` in PyTorch, graph batching, zero-init extension, ONNX export)
- **Tests:** `tests/`. They are mocked, with no raw data needed, except
  `test_committed_splits.py`, which hash-checks the committed splits, and
  the production-parity tests (`test_genphenia_v3.py`, `test_gnn_model.py`),
  which skip without the `genphenia_v3` bundle, onnxruntime or torch.
- **Decisions:** `docs/decisions/`.
- **Experiments:** `docs/experiments/` (copy `TEMPLATE.md`).
- **Current phase and next steps:** the last entry of `docs/BITACORA.md`.
