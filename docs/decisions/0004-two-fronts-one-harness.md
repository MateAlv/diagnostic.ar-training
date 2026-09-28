# ADR-0004: Two fronts (retrain, re-rank) judged by one harness

- **Status:** Accepted, 2026-09-28.

## Context
Sex, age and negated symptoms can enter either inside the network (a new
input, retraining) or after it (re-scoring the network's gene distribution
with knowledge-based compatibility). The first is more expressive but slower
and riskier. The second is cheap and interpretable, and it is exactly the
identity when the new inputs are absent.

## Decision
- Pursue both:
  - Front A: simulator + GNN retrain;
  - Front B: re-ranker on v3.0.
- Every system implements `rank(case) -> full gene distribution` and is scored
  by the same metrics, on the same frozen cases, against the same E0.
- A+B combined is evaluated too.

## Alternatives dropped
- **Retrain only**, as in the anteproyecto. With no early deliverable, a
  failure of the simulator would leave nothing to show.
- **Re-rank only.** It doesn't meet the proposal's retraining objective.

## Consequences
- The shared harness and splits come first (Phase 0).
- The informe can compare "learned inside the network" against "added on
  top".
