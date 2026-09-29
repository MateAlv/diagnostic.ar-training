# Documentation index

| If you need… | Read |
|---|---|
| **Where things stand right now; open decisions; next steps** | [STATE.md](STATE.md) |
| The goal, the two fronts, phases and dates, guardrails | [PLAN.md](PLAN.md) |
| What was done, when, with which numbers, and what worked or didn't | [BITACORA.md](BITACORA.md) (newest entry at the bottom) |
| How data may flow; sources, manifests, known gaps | [DATA_LINEAGE.md](DATA_LINEAGE.md) |
| Splits, sealing, pre-registration, gates, reporting | [EVAL_PROTOCOL.md](EVAL_PROTOCOL.md) |
| Every read of a sealed split | [TEST_LEDGER.md](TEST_LEDGER.md) |
| Actions only Mateo or the team can take (licenses, billing) | [TODO.md](TODO.md) |
| Why things are the way they are | [decisions/](decisions/README.md) |
| An experiment's hypothesis, gate, configs tried, results | `experiments/<EXP-id>.md` ([template](experiments/TEMPLATE.md)) |
| Agent rules (Claude, Codex, …) | [../CLAUDE.md](../CLAUDE.md) (`AGENTS.md` is a symlink to it) |

## Glossary

| Term | Meaning |
|---|---|
| **E0** | Production GenPhenia v3.0 (`model-v3.0.0`) measured by our harness; the reference for every claim |
| **R1** | phenopacket-store 0.1.27, split `r1-v1` into train / dev / test / vault by publication |
| **R2, R3** | MCRD (229) and DDD (1,048); eval-only external benchmarks |
| **S1, S2** | Our simulator's held-out cases; upstream-style simulated patients |
| **Front A** | Simulator + GNN retraining with sex, age and negated inputs |
| **Front B** | Re-ranker over v3.0's gene distribution using the same inputs |
| **Views** | The same cases evaluated as: present only / + excluded / + sex / + age / all |
| **Harmed rate** | Share of cases whose true gene ranks worse than under E0 |
| **Held-out PMIDs** | Publications of R1 dev/test/vault; masked from every KB and simulator profile |
| **Sealed** | Readable only through a pre-registered experiment, from a clean tree, with a ledger row |

## Related locations

| Location | What |
|---|---|
| `/home/mate/FIUBA/trabajo-profesional/CLAUDE.md` | Workspace guardrails (GenPhenAI lock) |
| `/home/mate/FIUBA/trabajo-profesional/.claude/` | Guard hook and its tests |
| `/home/mate/diagnostic.ar/informe/` | Informe draft, rúbrica, reglamento (written by the team) |
| `/home/mate/diagnostic.ar/qa-agente-claude/docs/EVALUACION.md` | Prior re-ranking evaluation (Mariano's repo; read-only) |
