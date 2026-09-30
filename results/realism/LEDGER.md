# R1-dev realism ledger

Every `dxt sim realism` run reads R1-dev as a check (ADR-0011, ADR-0012). At most 3 candidate simulator versions may be compared before one is frozen; baselines (UP, V03) do not count.

| Date (UTC) | Label | Dataset | Dataset sha256 | Commit | Role | Simulator version |
|---|---|---|---|---|---|---|
| 2026-09-30 14:35 | v0.3-analysis10 | path:analysis10.jsonl.gz | fd0185c2457d2fd0026b093ed641ebe1e8441ed189887ab85e9e686115f56248 | df4f1dcf66c2 | baseline | — |
| 2026-09-30 14:36 | up-graphens | source:graphens_sim_20251202@GraPhens@7d861ff | d4e8c416b49d27cad113e0a235ff1caecad9f49e95686c479c7afe80d9fddd8e | 93c618251d24 | baseline | — |
| 2026-09-30 14:37 | v0.3-baseline | artifact:ds-sim0.3.1-A-n100-s1001 | 97fa06bff5d8c6b1f8fab26548124302a97e15d8ad5f0943690a5774d93b1744 | 93c618251d24 | baseline | — |
| 2026-09-30 14:43 | realism-report-model-v2-dev | artifact:report-model-v2 | 1be9413b8b4b040b4f07c60ffe693879f848d869c8db906e9a858fb827b7f6b4 | 78dd66e05f9d | check | — |
| 2026-09-30 15:34 | v0.4-cand1 | artifact:ds-sim0.4.1-A-n100-s1001 | b18df39dddfb4986614d97fe454f46e81ce66cb38435ac78166bb39efbb05995 | 0edee50ab829 | candidate | 0.4.1-cand1 |
| 2026-09-30 18:11 | v0.3-full-baseline | artifact:ds-sim0.3.1-full-n100-s1001 | 840433d24d1e43cf14b5833b0dffcbc4ef0a8411210f89f167a6ef42e8dbdac6 | 0131f972359c | baseline | — |
| 2026-09-30 18:28 | v0.4-cand2 | artifact:ds-sim0.4.2-full-n100-s1001 | 2ab420355fe28a93b0bc19d9dd888c154514519b828c677542728a038c429afa | 81f8f0870c37 | candidate | 0.4.2-cand2 |
