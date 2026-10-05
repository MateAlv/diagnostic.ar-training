# diagnostic.ar-training

Training, re-ranking and evaluation for [diagnostic.ar](https://diagnosticar.infra.cluster.qb.fcen.uba.ar/).
It extends the GenPhenia v3.0 gene-prioritisation GNN with three patient
inputs it ignores today: **sex**, **age** and **negated symptoms** (for
example "no tengo fiebre recurrente"). This is part of the Trabajo Profesional
*Diagnóstico de Enfermedades Genéticas Poco Frecuentes mediante Deep Learning*
(FIUBA).

## What was built
- **A literature-enriched patient simulator** (`rare-disease-simulator` 0.5.4): 97 literature shards (build v2),
  onset and presentation ages from the literature, PMID masking, pinned sources and manifests. The AI extraction
  was checked: Codex cross-check 96.1% agreement; audit row error 2.0% [1.25, 3.17] and recall 93.3%.
- **An evaluation infrastructure**, an open problem the anteproyecto itself names: frozen publication-level splits
  (`r1-v1`: train/dev/test/vault) with held-out PMID masking; pre-registration; a code-enforced sealed-read guard
  and ledger; simulated-interview benchmarks (S3 v1, v2, v3b) with a knowledge split and source separation for age
  and sex; every claim as a paired-bootstrap Δ vs E0 with a CI and the harmed share.
- **Deployed in staging:** question selection **Q2b** and the "no"-answer re-ranker `rerank-v1.0.0`
  (release channel: `diagnostic.ar-model`). The GNN was also reimplemented in PyTorch with parity tests.

## What was measured
| Result | Δ MRR [95% CI] |
|---|---|
| Q2b over the baseline questioner (sealed, simulated; EXP-Q-001) | +0.0049 [+0.0027, +0.0069] |
| "No"-answer re-ranker (sealed, simulated; EXP-B-003) | +0.0044 [+0.0032, +0.0057] |
| Same re-ranker vs E0 on real patients, R1-test (EXP-B-003) | −0.0025 [−0.0070, +0.0013]: no regression |
| Sex and age, tested fairly (EXP-B-004) | no gain |
| Onset: simulated (EXP-B-005) / real patients (EXP-B-006, EXP-V-001) | +0.0023 / no gain; `rerank-v1.1.0` not released |

The simulator's realism was measured against a gate fixed in advance (ADR-0012); the gate was not passed (G2b dev
0.159 vs UP 0.231), which is why GNN retraining stopped. The retraining attempts (EXP-A-001, A-002f, A-003f) are
documented.

## Limits, with context
- E0 (GenPhenAI v3.0) was trained upstream on annotations that derive in part from the same published case reports
  R1 is built from, and could not be retrained or masked: E0 is favoured on R1.
- R1's excluded terms are publication negatives, not interview "no" answers, so R1 cannot measure the production
  input; efficacy on the interview path is simulated, with no real-user measurement.

Final decisions: [ADR-0016](docs/decisions/0016-final-deployment-and-close-out.md).

**Start here:** [`docs/INDEX.md`](docs/INDEX.md).

## Quickstart

```bash
make setup          # Python 3.12 venv + package
make sources        # fetch + sha256-verify every pinned input (data/sources.yaml)
make check          # lint, tests, lineage verification
.venv/bin/dxt --help
```

Simulator v0.4 inputs and its realism gate (see `docs/DATA_LINEAGE.md` §7):

```bash
dxt knowledge recount --id hpoa-recount-v1          # also: cardinal, report-model, shrinkage-prior, panel
dxt genes build --id genes-v2 --scheme v2 --hpoa-artifact hpoa-recount-v1
dxt sim realism --dataset <export.jsonl.gz | artifact:<id> | source:<name>> --label <name> [--baseline | --sim-version <v>]
dxt sim gate --candidate <label>                    # ADR-0012 G2 table vs UP and V03
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
| `src/diagnostic_ar_training/eval/` | Metrics, paired bootstrap, contamination checks, simulated-data realism (`realism.py`, ADR-0012 G2) |
| `src/diagnostic_ar_training/knowledge/` | Gene profiles, HPOA recount, cardinal features, reporting model (simulator v0.4 inputs, ADR-0011) |
| `data/realism/`, `results/realism/` | Literature panel; realism reports, the G2 gate table and the R1-dev ledger |
| `src/diagnostic_ar_training/rerank/` | Front B |
| `src/diagnostic_ar_training/gnn/` | Front A: v3.0 in PyTorch (`GinV3`), graph batching, zero-initialised extension (ADR-0009), ONNX export |
| `docs/` | Plan, log, protocol, lineage, decisions, experiments |

## Related repos

| Repo | Role |
|---|---|
| `rare-disease-simulator` | Synthetic patients for Front A |
| `diagnostic.ar-model` | Release channel for bundles consumed by production |
| `GenPhenAI/` (upstream) | **Read-only.** Never modified from here |
