noise 0.05: 2 runs

| strategy | hash | MRR initial | MRR +answers | MRR final | primary Δ vs E0-initial [95% CI] | harmed | helped | questioner effect | re-ranker effect [CI] | rr harmed | top-10 initial → final | yes/no per case |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Q0 | abdad4c63756 | 0.3185 | 0.3272 | 0.3334 | +0.0148 [+0.0117, +0.0176] | 0.166 | 0.353 | +0.0086 [+0.0058, +0.0114] | +0.0062 [+0.0050, +0.0074] | 0.049 | 0.451 → 0.460 | 1.24 / 7.46 |
| Q2b-lam0.6 | f4bbbc0d67fd | 0.3185 | 0.3331 | 0.3388 | +0.0203 [+0.0170, +0.0236] | 0.168 | 0.364 | +0.0146 [+0.0113, +0.0178] | +0.0057 [+0.0046, +0.0070] | 0.049 | 0.451 → 0.461 | 1.20 / 7.49 |

Selection (re-ranker-effect harmed <= 5%, primary CI lower bound > 0, ties within 0.001 -> simpler):
- feasible: ['Q0', 'Q2b-lam0.6']; best Δ +0.0203; within 0.001: ['Q2b-lam0.6']
- winner: Q2b-lam0.6 (f4bbbc0d67fd), primary Δ +0.0203

Paired difference in final MRR vs Q0 (same cases, 95% CI over genes):
- Q2b-lam0.6: +0.0055 [+0.0028, +0.0083]
- not feasible: []
