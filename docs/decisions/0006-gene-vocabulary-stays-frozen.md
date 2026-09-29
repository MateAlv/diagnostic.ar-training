# ADR-0006: The gene vocabulary stays v3.0's 5,229 genes

- **Status:** Accepted, 2026-09-29 (Mateo).
- **Rejects:** the proposed experiment A-008.

## Context
EXP-000 found that 10.6–14.2% of R1 patients have a causal gene outside
v3.0's 5,229 output classes (Addendum 3). HPO 2026-02-16 has 145 genes the
model cannot output. Adding warm-started classifier rows (A-008) could
recover part of that loss.

## Decision
The model's gene list stays exactly v3.0's `genes.json`, same order, for both
fronts.

## Why
The project's question is the value of sex, age and negated symptoms. A
vocabulary change would move every metric for reasons unrelated to those
inputs, and it would confound the comparison with E0.

## Consequences
- **Out-of-vocabulary patients stay in every evaluation as misses**
  (`gene_not_in_vocab`), identical for every system. They lower absolute
  numbers but not paired Δs.
- **"In-vocabulary" metrics are reported alongside** every result.
- **Vocabulary expansion is recorded as future work** (informe §18), with
  EXP-000's measurement of what it would address.
