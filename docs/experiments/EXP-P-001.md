# EXP-P-001: safe-v1 (knowledge-only sex, onset and negation rules) on the Phase 2 confirmation set

- **Front:** Phase 2, Track 1 ([PHASE2.md](../PHASE2.md), [ADR-0017](../decisions/0017-phase-2-real-patient-restart.md))
- **Registered:** 2026-10-08, by the main session for Mateo
- **Status:** registered; sealed read pending Mateo's go

## Hypothesis
On real patients from publications E0 may have seen (`p2-v1` test), `safe-v1` ranks the causal gene higher than E0
on average: Δ MRR > 0.

## Systems compared
| System | Artifact ids / code | Notes |
|---|---|---|
| E0 | `genphenia_v3` (model-v3.0.0), present terms | always included; production today |
| `safe-v1` | `safe-kb-v1`, bundle sha256 `28646c4a10d47e6994840a31462ffc0e4afb74efaab9b39e544fdb61824eb899`; knowledge built at `2984ed4` | E0 on present terms, then the rules below |

`safe-v1` rules (`safe/bundle.py`, `safe-v1-bundle/1`):
1. **Negation:** a gene's probability is multiplied by 0.1 when every annotated disease of the gene has an obligate
   phenotype (HP:0040280, "100%", or n/n with n ≥ 5) whose ancestors-or-self include one of the patient's excluded
   terms.
2. **Onset:** a gene's probability is multiplied by 0.01 when its strict earliest onset is later than the patient's
   onset, or the current age when onset is unknown. Negative ages count as 0, and so does Infantile onset. "Strict"
   means every OMIM disease of the gene has onset data in HPO or Orphanet 2026-06.
3. **Sex:** genes whose every disease is limited to the other sex go below every other gene, keeping their order.
   There are 75 male-limited and 17 female-limited genes, after the 2026-10-08 curation removed 49 of 141
   (`data/curation/safe-v1-overrides.csv`).

Knowledge: HPO 2026-02-16 with the held-out mask (every `r1-v1` dev, test and vault PMID), plus Orphanet ages
2026-06, HGNC 2026-09-25 and HPO genes_to_disease.

## Data
- **Fitting:** none. The rules are knowledge-only.
- **Selection:** R1 train and dev, the free parts, as logged in [P2-PROBES-v1](../analyses/P2-PROBES-v1.md) and BITACORA
  2026-10-07 and 2026-10-08:
  - 33 probe configurations;
  - the hard-block `safe-v1` on `safe-kb-v1a`;
  - the onset hard block vs ×0.1 vs ×0.01;
  - `safe-kb-v1`.
- **Sealed read (this experiment):** `p2-v1` test, 3,587 patients in 567 publication groups, none of them post-E0.
  This is its first read and Phase 2 confirmation read 1 of 3.
  - Sex known: 3,324. Age: 2,556. Onset: 1,870. Excluded terms: 2,876.
  - Command: `DXT_SEALED_READ=EXP-P-001 .venv/bin/dxt safe confirm --exp EXP-P-001 --split p2-v1 --part test --kb
    safe-kb-v1 --reason "EXP-P-001 confirmation read"`
  - Then: `.venv/bin/python scripts/analysis/exp_p_gate.py EXP-P-001 p2-v1-test-safe-kb-v1`

## Primary metric and gate (written before results)
- **Primary:** Δ MRR, `safe-v1` − E0, over all 3,587 patients, with misses counted as 0. The bootstrap is paired and
  resamples publication groups (2,000 resamples, seed 0).
- **Gate:**
  - **(a) The CI lower bound is above 0 at level 1 − 0.05/3 (98.33%).** That is the Bonferroni bound for Phase 2's
    budget of 3 confirmation reads; Holm can only relax it for later reads. Computed with
    `scripts/analysis/exp_p_gate.py`, using the same draws as the 95% CI.
  - **(b) Harmed ≤ 5%.** Harmed means the true gene ranks lower than under E0.
  - Pass = (a) and (b).
- **Production criterion,** for Mateo's decision and not part of the gate: pass, plus harmed ≤ 0.5%.

## Also reported (descriptive)
- the 95% CI;
- helped and harmed shares;
- top-1 and top-10 entries and exits;
- each rule alone (`safe-v1[sex]`, `[onset]`, `[negation]`);
- the subsets: in-vocabulary, sex known, age known, onset known, excluded known;
- the present-only identity check: the present view must equal E0 bit for bit;
- the dev → test drop.

## Expectations (from dev)
- **Dev, `safe-kb-v1`:** Δ +0.00246, 95% CI [+0.00090, +0.00416], 98.33% CI [+0.00072, +0.00464]; harmed 0.11% (2 of
  1,883); helped 13.0%.
- **Train, where the patients' own papers are not masked:** −0.00005 [−0.00133, +0.00095], harmed 31, all from the
  negation rule.
- **Expected on test:** Δ between +0.0005 and +0.003, with harmed below 0.5%. If the train pattern carries over
  through publications whose obligate rows conflict with their patients, the lower bound may fall below 0. That
  outcome is reported as it comes.

## Results
(Filled in after the read.)

## Verdict
(Filled in after the read.)
