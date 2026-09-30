| Dataset | Role | G2a: literature panel MAE (primary rows) (lower) | G2b: R1-dev mean per-gene rho (higher) | G2c: W1 terms/case vs R1-train (lower) | G2d: C2ST AUC vs R1-train (lower) | G2e: |E0 MRR - 0.405| (lower) | All |
|---|---|---|---|---|---|---|---|
| up-graphens | baseline | 0.416 | 0.231 | 3.717 | 0.840 | 0.414 | — |
| v0.3-full-baseline | baseline | 0.390 | 0.095 | 1.653 | 0.819 | 0.183 | — |
| v0.3-baseline | secondary | 0.418 | 0.086 | 1.382 | 0.778 | 0.237 | — |
| v0.4-cand2 | candidate | 0.404 fail | 0.193 fail | 1.315 pass | 0.792 fail | 0.242 fail | FAIL |

G2d also requires AUC <= 0.75; G2e also requires a gap <= 0.1 (ADR-0012).
G2e's target is E0's MRR on R1-train patients whose publication HPOA does not cite (0.405, ADR-0012 amendment 1).
Secondary rows are shown for reference; candidates are not judged against them.
G2a panel: literature-panel-v2.tsv.
