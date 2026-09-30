# R1-dev realism ledger

Every `dxt sim realism` run reads R1-dev as a check (ADR-0011, ADR-0012). At most 3 candidate simulator versions may be compared before one is frozen; baselines (UP, V03) do not count.

| Date (UTC) | Label | Dataset | Dataset sha256 | Commit | Role | Simulator version |
|---|---|---|---|---|---|---|
| 2026-09-30 14:35 | v0.3-analysis10 | path:analysis10.jsonl.gz | fd0185c2457d2fd0026b093ed641ebe1e8441ed189887ab85e9e686115f56248 | df4f1dcf66c2 | baseline | — |
| 2026-09-30 14:36 | up-graphens | source:graphens_sim_20251202@GraPhens@7d861ff | d4e8c416b49d27cad113e0a235ff1caecad9f49e95686c479c7afe80d9fddd8e | 93c618251d24 | baseline | — |
| 2026-09-30 14:37 | v0.3-baseline | artifact:ds-sim0.3.1-A-n100-s1001 | 97fa06bff5d8c6b1f8fab26548124302a97e15d8ad5f0943690a5774d93b1744 | 93c618251d24 | baseline | — |
| 2026-09-30 14:43 | realism-report-model-v2-dev | artifact:report-model-v2 | 1be9413b8b4b040b4f07c60ffe693879f848d869c8db906e9a858fb827b7f6b4 | 78dd66e05f9d | check | — |
