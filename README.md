# diagnostic.ar-training

Training, re-ranking and evaluation for [diagnostic.ar](https://diagnosticar.infra.cluster.qb.fcen.uba.ar/).
It extends the GenPhenia v3.0 gene-prioritisation GNN with three patient
inputs it ignores today: **sex**, **age** and **negated symptoms** (for
example "no tengo fiebre recurrente"). This is part of the Trabajo Profesional
*Diagnóstico de Enfermedades Genéticas Poco Frecuentes mediante Deep Learning*
(FIUBA).

## What was built
- **Question agent with Q2b selection** (`diagnosticar-question-agent`, `feat/agente-v2`): enriches each case with
  follow-up questions and adds the confirmed and ruled-out findings of each round, which gives the model and the doctor's
  summary a more precise phenotype. On the sealed simulated test (S3-v2-test, n = 9,565) Q2b added 1.04 confirmed
  ("yes") and 7.87 ruled-out ("no") findings per case, 8.90 questions per case
  (`results/EXP-B-004/sealed/s3-v2-test__Q2b-lam0.6__cfg-8ecd5b320f33__noise0.report.json`). Deployed in staging.
- **"No"-answer re-ranker `rerank-v1.0.0`** (release channel: `diagnostic.ar-model`): uses the ruled-out findings to
  reorder the GNN's genes. Deployed in staging.
- **Onset age** in the final output the doctor sees: a more precise clinical summary (age selector in Precisar,
  MateAlv/diagnostic.ar PR #87; a web PR for the final output is in progress).
- **A literature-enriched patient simulator** (`rare-disease-simulator` 0.5.4): 97 literature shards (build v2),
  onset and presentation ages from the literature, PMID masking, pinned sources and manifests. The AI extraction
  was checked: Codex cross-check 96.1% agreement (715 of 744 rows); audit row error 2.0% [1.25, 3.17] and recall 93.3%.
- **An evaluation infrastructure**, an open problem the anteproyecto itself names: frozen publication-level splits
  (`r1-v1`: train/dev/test/vault) with held-out PMID masking; pre-registration; a code-enforced sealed-read guard
  and ledger; simulated-interview benchmarks (S3 v1, v2, v3b) with a knowledge split and source separation for age
  and sex; every claim as a paired-bootstrap Δ vs E0 with a CI and the harmed share.
- **A PyTorch reimplementation of the GNN** with parity tests against production.

## What was measured
| Result | Δ MRR [95% CI] | Split, n |
|---|---|---|
| Q2b over the baseline questioner Q0 (EXP-Q-001) | +0.0049 [+0.0027, +0.0069] | S3-v2-test (sealed, simulated), 9,565 |
| "No"-answer re-ranker vs E0+answers (EXP-B-003) | +0.0044 [+0.0032, +0.0057] | S3-test (sealed, simulated), 9,990 |
| Same re-ranker vs E0, pre-registered no-regression gate (EXP-B-003) | −0.0025 [−0.0070, +0.0013]; gate passed | R1-test (sealed, real), 2,548 |
| Onset in the re-ranker, F + onset 0.25 vs F (EXP-B-005) | +0.0023 [+0.0013, +0.0034] | S3-v3b-test (sealed, simulated), 6,745 |
| Onset candidate vs rr-v1, pre-registered no-regression gate (EXP-B-006) | −0.0003 [−0.0019, +0.0008]; gate passed | R1-test (sealed, real), 2,548 |
| R1 vault, MRR (EXP-V-001, descriptive) | E0 0.4136; `rerank-v1.0.0` 0.4114 (−0.0022 [−0.0046, +0.0002]); `rerank-v1.1.0` 0.4106 (−0.0031 [−0.0055, −0.0005]) | R1 vault (real), 1,771 |
| Sex and age in the re-ranker vs F (EXP-B-004, descriptive) | sex 0.5 +0.0003 [+0.0000, +0.0007]; age_mean 0.5 +0.0007 [−0.0001, +0.0014] | S3-v2-test (sealed, simulated), 9,565 |

`rerank-v1.1.0` (onset) is built in `diagnostic.ar-model` and not tagged (ADR-0016).

The simulator's realism was measured against a gate fixed in advance (ADR-0012): G2b on R1-dev 0.159 (UP 0.231,
V03-full 0.095), with 3 of 3 R1-dev reads used; GNN retraining stopped at that gate. The retraining attempts
(EXP-A-001, A-002f, A-003f) are documented, each with its R1-dev Δ vs E0 and CI in
`docs/evidence/EVIDENCE_INDEX.md` section 3.

## Context for the real-patient numbers
- E0 (GenPhenAI v3.0) was trained upstream on annotations that derive in part from the same published case reports
  R1 is built from, and could not be retrained or masked: E0 is favoured on R1.
- R1's excluded terms are publication negatives, not interview "no" answers, so R1 does not measure the production
  input; the interview path is measured on simulated interviews (S3), and there is no real-user measurement.

## Data limitations
We lack the data to test or simulate, correctly, whether these changes improve or reduce performance on real patients. This is why the re-ranker is in staging and not in production, and why the GNN retraining and `rerank-v1.1.0` were not deployed.
- **Interview negations:** no real-patient dataset with interview yes/no answers exists. R1 has only negatives written in publications, a different input from the agent's "no" answers. The effect on real patients is estimated in simulation only (S3; EXP-B-003 +0.0044 [+0.0032, +0.0057], n = 9,990). `rerank-v1.0.0` stays in staging until real sessions (interview answers plus confirmed diagnoses) can be collected and evaluated.
- **Training data:** no synthetic data was realistic enough to retrain the GNN on. The simulator's realism gate (ADR-0012) was measured: G2b 0.159 on R1-dev vs UP 0.231 and V03-full 0.095. Real patients are few and reserved for evaluation (R1 splits). Retraining with age, sex and negations could not be validated.
- **Literature data:** literature onset ages cover part of the entities (S3 v2: 1,027 cases, 5.25%, with literature onset; S3 v3: 120 eligible genes), so the onset effect is simulated on that subset. Real-patient reads: EXP-B-006 vs rr-v1 -0.0003 [-0.0019, +0.0008] (n = 2,548); EXP-V-001 MRR v1.1 0.4106, v1.0 0.4114, E0 0.4136 (n = 1,771). `rerank-v1.1.0` was not released.
- **E0 on R1:** E0's training annotations derive in part from the same publications as R1, so E0 is favoured there and real-patient comparisons against it are conservative.
- **Future work:** collect consented real sessions on the platform to evaluate the points above.

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
