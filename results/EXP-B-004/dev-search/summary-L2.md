L2: 6 configurations logged (budget 6)

| arm | hash | Δ MRR | 95% CI | harmed | helped | R1-dev Δ | R1-dev CI | R1 pass |
|---|---|---|---|---|---|---|---|---|
| L2:propagated:k0.5:w0.5:kb-v6 | 8ecd5b320f33 | +0.0063 | [+0.0051, +0.0075] | 0.049 | 0.233 | -0.0020 | [-0.0097, +0.0044] | 1 |
| L2:propagated:k0.5:w0.5:kb-v8 | 8d48a53224aa | +0.0064 | [+0.0052, +0.0076] | 0.047 | 0.236 | -0.0094 | [-0.0241, +0.0007] | 1 |
| L2:propagated:k0.5:w0.5:kb-v7 | af6da5cdbf19 | +0.0064 | [+0.0052, +0.0076] | 0.048 | 0.235 | -0.0095 | [-0.0241, +0.0007] | 1 |
| L2:gated:tau0.4:k0.5:w0.5:kb-v6 | 8e8b70d00a1c | +0.0065 | [+0.0052, +0.0078] | 0.045 | 0.237 | +0.0028 | [+0.0006, +0.0050] | 1 |
| L2:gated:tau0.4:k0.5:w0.5:kb-v8 | 262466604de5 | +0.0066 | [+0.0053, +0.0079] | 0.044 | 0.242 | +0.0008 | [-0.0039, +0.0048] | 1 |
| L2:gated:tau0.4:k0.5:w0.5:kb-v7 | 2767e4ab88ca | +0.0066 | [+0.0053, +0.0079] | 0.045 | 0.243 | +0.0007 | [-0.0039, +0.0047] | 1 |

Frontier (best Δ at each harm limit, over this lever's arms):
- harmed <= 0.050: L2:gated:tau0.4:k0.5:w0.5:kb-v8 Δ +0.0066 [+0.0053, +0.0079] harmed 0.044, CI lower bound > 0: True, R1-dev pass: True
- harmed <= 0.075: L2:gated:tau0.4:k0.5:w0.5:kb-v8 Δ +0.0066 [+0.0053, +0.0079] harmed 0.044, CI lower bound > 0: True, R1-dev pass: True
- harmed <= 0.100: L2:gated:tau0.4:k0.5:w0.5:kb-v8 Δ +0.0066 [+0.0053, +0.0079] harmed 0.044, CI lower bound > 0: True, R1-dev pass: True

Selection rule (harmed <= 5%, CI lower bound > 0, R1-dev no-harm, ties within 0.001 -> simpler):
- winner: L2:propagated:k0.5:w0.5:kb-v6 8ecd5b320f33
- feasible arms within 0.001 of the best Δ, passed over for the simpler winner: ['L2:propagated:k0.5:w0.5:kb-v8', 'L2:propagated:k0.5:w0.5:kb-v7', 'L2:gated:tau0.4:k0.5:w0.5:kb-v6', 'L2:gated:tau0.4:k0.5:w0.5:kb-v8', 'L2:gated:tau0.4:k0.5:w0.5:kb-v7']
