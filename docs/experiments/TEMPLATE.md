# EXP-X-000: <title>

Copy to `docs/experiments/<EXP-id>.md` and fill in **before** running. The
file must exist before any sealed read (`EVAL_PROTOCOL.md` §3). After a
sealed read, only add dated addenda at the bottom.

- **Front:** A | B | shared
- **Registered:** YYYY-MM-DD, by <name>
- **Status:** planned | running | done

## Hypothesis
One sentence, falsifiable.

## Systems compared
| System | Artifact ids / code | Notes |
|---|---|---|
| E0 | genphenia_v3 (model-v3.0.0) | always included |
| candidate | … | … |

## Data
- Training inputs, with their manifest ids and masking.
- Selection: R1-dev (and S1-val for early stopping).
- Evaluation: R1-dev; sealed reads planned (test / vault / R2 / R3), or none.

## Primary metric and gate
- Primary: R1 MRR, "all features" view, Δ vs E0 with a paired-bootstrap 95% CI.
- Gate (written before results): …

## Dev search
- Budget: N configurations.
- Grid: …
- Tried: (fill in as you go; every configuration, not only the winner).

## Results
(filled after running; link to `results/<EXP-id>/metrics.json`)

## Verdict
✅ adopted / ❌ discarded / ⚠️ inconclusive, and why.

## Addenda
