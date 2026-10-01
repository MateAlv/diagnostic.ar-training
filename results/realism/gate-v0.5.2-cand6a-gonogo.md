| Dataset | Role | G2a: literature panel MAE (truth layer, primary rows) (lower) | G2b: R1-dev mean per-gene rho (higher) | G2c: W1 terms/case vs R1-train (lower) | G2d: C2ST AUC vs R1-train (lower) | G2e: |E0 MRR - 0.405| (lower) | All |
|---|---|---|---|---|---|---|---|
| up-graphens | baseline | 0.416 | 0.231 | 3.717 | 0.840 | 0.414 | — |
| v0.3-full-baseline | baseline | 0.336 | 0.095 | 1.653 | 0.819 | 0.183 | — |
| v0.4-cand3-full-nodev | secondary | 0.305 | n/a | 1.732 | 0.764 | 0.142 | — |
| v0.5-cand4-full-nodev | secondary | 0.307 | n/a | 5.754 | 0.822 | 0.204 | — |
| v0.5.1-cand5-full-nodev | secondary | 0.306 | n/a | 1.908 | 0.809 | 0.049 | — |
| v0.5.2-cand6a-full-nodev | candidate | 0.306 pass | n/a n/a | 2.955 fail | 0.764 fail | 0.011 pass | FAIL |

G2d also requires AUC <= 0.75; G2e also requires a gap <= 0.1 (ADR-0012).
G2e's target is E0's MRR on R1-train patients whose publication HPOA does not cite (0.405, ADR-0012 amendment 1).
Secondary rows are shown for reference; candidates are not judged against them.
G2a panel: literature-panel-v2.tsv.
