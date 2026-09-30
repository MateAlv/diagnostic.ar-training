| Dataset | Role | G2a: literature panel MAE (primary rows) (lower) | G2b: R1-dev mean per-gene rho (higher) | G2c: W1 terms/case vs R1-train (lower) | G2d: C2ST AUC vs R1-train (lower) | G2e: |E0 MRR - 0.512| (lower) | All |
|---|---|---|---|---|---|---|---|
| up-graphens | baseline | 0.504 | 0.231 | 3.717 | 0.840 | 0.307 | — |
| v0.3-baseline | baseline | 0.556 | 0.086 | 1.382 | 0.778 | 0.344 | — |
| v0.4-cand1 | candidate | 0.512 fail | 0.152 fail | 1.214 pass | 0.737 pass | 0.420 fail | FAIL |

G2d also requires AUC <= 0.75; G2e also requires a gap <= 0.1 (ADR-0012).
