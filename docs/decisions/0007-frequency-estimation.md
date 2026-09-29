# ADR-0007: How phenotype frequencies are read from HPOA (shared by both fronts)

- **Status:** Accepted, 2026-09-29.
- **Binds:** `diagnostic.ar-training` (KB `kb-v2` onward) and
  `rare-disease-simulator` (Phase 1A part 2 onward).

## Context
HPOA states a phenotype's frequency in three notations:
- an HPO frequency category;
- a count `n/m`;
- a percentage.

Point estimates from small counts are extreme. 16% of the simulator's
phenotype annotations became "obligate" (frequency 1.0) from `n/n` counts,
13,263 of them from `1/1`, so every simulated patient would show them. The two
repos also disagreed on `0/m`: the simulator made it a negation, `kb-v1` kept
it as frequency 0.

## Decision
1. **Counts** pool across duplicate rows of the same (disease, term): sum the
   n's and the m's. The estimate is the Jeffreys posterior mean
   `(n + 0.5) / (m + 1)`, so `1/1 → 0.75`, `10/10 → 0.95`, `0/3 → 0.125`.
2. **Categories** use the midpoint of the HPO-defined range (Obligate 1.0,
   Very frequent 0.895, Frequent 0.545, Occasional 0.17, Very rare 0.025).
3. **Percentages** are points; the cohort size is unknown.
4. **Precedence** when a (disease, term) has several notations: pooled counts,
   then the mean of percentages, then the mean of category midpoints.
5. **Empty** means unknown frequency (`None`), never "always".
6. **Only the `NOT` qualifier (or the Excluded category) is a negation.** A
   `0/m` count is a low frequency, not an absence. Absence claims need
   explicit evidence (the simulator's "unmentioned is not negative" rule).

## Alternatives dropped
- **Raw point estimates.** They produce the `1/1 → obligate` artefact.
- **Laplace `(n+1)/(m+2)`.** Pulls small counts too hard toward 0.5.
- **`0/m` as negation.** Turns "not seen in 3 patients" into "excluded".

## Consequences
- `kb-v1` stays as built; `kb-v2` adopts this convention.
- The simulator's 1,918 `0/m` negatives become low-frequency positives.
- The shared test vectors for this ADR are the examples in items 1 and 4.
