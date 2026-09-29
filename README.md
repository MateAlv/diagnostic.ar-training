# diagnostic.ar-training

Training, re-ranking and evaluation for [diagnostic.ar](https://diagnosticar.infra.cluster.qb.fcen.uba.ar/).
It extends the GenPhenia v3.0 gene-prioritisation GNN with three patient
inputs it ignores today: **sex**, **age** and **negated symptoms** (for
example "no tengo fiebre recurrente"). This is part of the Trabajo Profesional
*Diagnóstico de Enfermedades Genéticas Poco Frecuentes mediante Deep Learning*
(FIUBA).

The work has two fronts:
- **A:** finish `rare-disease-simulator`, then retrain the GNN with the new
  inputs.
- **B:** a re-ranker on top of the GNN's gene distribution.

Both are measured by one harness against the production model (E0), under a
strict anti-overfitting protocol.

**Start here:** [`docs/INDEX.md`](docs/INDEX.md).

## Quickstart

```bash
make setup          # Python 3.12 venv + package
make sources        # fetch + sha256-verify every pinned input (data/sources.yaml)
make check          # lint, tests, lineage verification
.venv/bin/dxt --help
```

## Layout

| Path | What |
|---|---|
| `data/sources.yaml` | Every external input: immutable URL, sha256, role |
| `data/splits/` | Frozen, publication-grouped cohort splits (`r1-v1`) and held-out PMID lists |
| `data/manifests/` | Lineage manifest per derived artifact |
| `src/diagnostic_ar_training/lineage/` | Source registry and roles, manifests, sealed-split ledger |
| `src/diagnostic_ar_training/cohorts/` | `Case` schema, phenopacket parser, benchmark loaders |
| `src/diagnostic_ar_training/splits.py` | Split computation, freezing, sealed access |
| `src/diagnostic_ar_training/eval/` | Metrics, paired bootstrap, contamination checks |
| `src/diagnostic_ar_training/rerank/` | Front B |
| `src/diagnostic_ar_training/gnn/` | Front A: v3.0 in PyTorch (`GinV3`), graph batching, zero-initialised extension (ADR-0009), ONNX export |
| `docs/` | Plan, log, protocol, lineage, decisions, experiments |

## Related repos

| Repo | Role |
|---|---|
| `rare-disease-simulator` | Synthetic patients for Front A |
| `diagnostic.ar-model` | Release channel for bundles consumed by production |
| `GenPhenAI/` (upstream) | **Read-only.** Never modified from here |
