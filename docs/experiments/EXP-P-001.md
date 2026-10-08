# EXP-P-001: safe-v1 (knowledge-only sex, onset and negation rules) on the Phase 2 confirmation set

- **Front:** Phase 2, Track 1 ([PHASE2.md](../PHASE2.md), [ADR-0017](../decisions/0017-phase-2-real-patient-restart.md))
- **Registered:** 2026-10-08, by the main session for Mateo
- **Status:** done. The sealed read ran on 2026-10-08 (ledger `655048562d34`) after Mateo's go.

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
   means every OMIM disease of the gene has HPO onset data. Orphanet ages (2026-06) add bounds for ORPHA diseases;
   ORPHA-only diseases without onset data do not block the rule (7 genes, e.g. AP1S3, BCL6); ×0.01 bounds their
   effect.
3. **Sex:** genes whose every disease is limited to the other sex go below every other gene, keeping their order.
   There are 75 male-limited and 17 female-limited genes, after the 2026-10-08 curation removed 49 of 141
   (`data/curation/safe-v1-overrides.csv`).

**Deviations from ADR-0017, recorded before the read.**
- **Sex curation source (decision 8).** The 49 removals and 92 keeps came from the agents' own biomedical knowledge
  (`source_file: knowledge`), not from quotes of the pinned GeneReviews and MedlinePlus snapshots. That knowledge may
  include test papers.
  - Curation can only remove genes from the rule.
  - Uncurated, the 141-gene rule harmed 0 of 5,986 free patients and moved MRR by about 1e-6, so it cannot
    materially move Δ.
- **Onset curation dropped** (BITACORA 2026-10-08). The ×0.01 factor bounds the onset rule's worst case.
- **Residual knowledge leakage that PMID masking cannot reach:** Orphanet ages, and HPOA rows that cite OMIM or ORPHA
  instead of a PMID. Both can only add or lower onset bounds of a patient's own disease, so they lower harm; they do
  not create "helped" cases.

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
  - Sex known: 3,324. Age: 2,556. Excluded terms: 2,876.
  - Onset: the split stats count 1,870 with onset years or an onset class. The rule and the `onset_known` subset use
    onset years only; patients with only an onset class fall back to current age. On dev, that is 534 of 1,046.
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
- **Median over the dev configurations of the full system:** +0.00235. The four configurations are `safe-kb-v1a` with
  the hard block (+0.00196), onset ×0.1 (+0.00223), onset ×0.01 (+0.00246) and `safe-kb-v1` (+0.00246). The 33 probe
  configurations are rule subsets, listed in P2-PROBES-v1.
- **Train, where the patients' own papers are not masked:** −0.00005 [−0.00133, +0.00094], harmed 31, all from the
  negation rule.
- **Expected on test:** Δ between +0.0005 and +0.003, with harmed below 0.5%. If the train pattern carries over
  through publications whose obligate rows conflict with their patients, the lower bound may fall below 0. That
  outcome is reported as it comes.

- **Seed sensitivity:** the 98.33% bound rests on about 17 draws per tail. On dev, seeds 1–5 gave lower bounds from
  +0.00059 to +0.00069. Seed 0 binds. If the test lower bound lands within 1e-4 of 0, that is reported as
  seed-sensitive.
- **Independent review (2026-10-08, read-only):** GO, no blocking issue. Its notes are folded into this file before
  the read.

## Results
Read on 2026-10-08 from `6550485`. Ledger row `p2-v1/test | EXP-P-001 | 655048562d34`. Outputs:
`results/EXP-P-001/p2-v1-test-safe-kb-v1__*`; gate `..._safe-v1__gate.json`; manifest
`results-EXP-P-001-p2-v1-test-safe-kb-v1-safe-v1-safe-kb-v1`. The present-only view matches E0 bit for bit.

3,587 patients in 567 publication groups. E0 is the reference. Harmed and helped count patients whose true gene ranks
lower or higher than under E0.

| System | Δ MRR | 95% CI | 98.33% CI (gate) | Helped | Harmed | Top 1 | Top 10 |
|---|---|---|---|---|---|---|---|
| **safe-v1 (registered)** | **+0.00029** | [−0.00053, +0.00097] | **[−0.00075, +0.00115]** | 456 (12.7%) | 9 (0.25%) | +1/−1 | +2/−6 |
| safe-v1[sex] | +0.000003 | [+0.00000, +0.00001] | — | 74 | 0 | +0/−0 | +0/−0 |
| safe-v1[onset] | +0.00016 | [+0.00007, +0.00032] | — | 186 | 0 | +0/−0 | +1/−0 |
| safe-v1[negation] | +0.00020 | [−0.00061, +0.00088] | — | 301 | 9 (0.25%) | +1/−1 | +1/−6 |

- **Onset known (928 patients, onset in years):**
  - safe-v1: −0.00092 [−0.00366, +0.00085].
  - Onset rule alone: +0.00051 [+0.00015, +0.00104], 0 harmed.
- **The 9 harmed patients all come from the negation rule, in two publications.**
  - ATP6V0C, PMID:35600075, 6 patients: ranks 7 → 73 (×4), 58 → 108, 79 → 128.
  - HMGCR, PMID:37167966, 3 patients: ranks 1 → 2, 3 → 95, 7 → 15.
  - In each case an obligate annotation of the gene's disease is excluded in these patients. ATP6V0C also
    accounted for 24 of the 31 train harms in the dry run.
- **Dev → test:**
  - safe-v1: +0.00246 → +0.00029.
  - Onset rule: +0.00100 → +0.00016.
  - Sex rule: both ≈ 0.

## Verdict
**Gate not passed:** the 98.33% CI lower bound is −0.00075, not above 0. Harmed is 0.25%, within both the 5% gate and
the 0.5% production criterion. `safe-v1` as registered is not confirmed and does not go to production on this read.

Descriptive, not a confirmed claim: the sex and onset rules, alone, helped 74 and 186 test patients and harmed none;
onset alone gives +0.00016 [+0.00007, +0.00032]. The negation rule carries the variance and every harm. Testing sex +
onset as a pre-registered hypothesis needs data this read did not touch: the post-E0 final check (`p2-v1` vault plus
`p2-fresh-v1`). The choice of that hypothesis is informed by this read, and it is disclosed as such.

## Addendum 1, 2026-10-08: the read split by E0's training annotations (descriptive)
`scripts/analysis/exp_p001_by_citation.py` → `results/EXP-P-001/p2-v1-test-safe-kb-v1__by_citation.json`. A patient
counts as "cited" when HPO 2025-11-24, the annotations E0 was trained on, cites their publication.

| Patients | n (groups) | E0 MRR | safe-v1 Δ [95% CI] | Onset rule alone Δ [95% CI] |
|---|---|---|---|---|
| Cited in E0's training annotations | 2,398 (435) | 0.551 | +0.00030 [−0.00071, +0.00111] | +0.00016 [+0.00005, +0.00033] |
| Not cited | 1,189 (132) | 0.244 | +0.00028 [−0.00114, +0.00174] | +0.00017 [+0.00003, +0.00056] |

- Two thirds of the confirmation set come from publications E0's training annotations cite, and E0's MRR there is
  0.551, against 0.244 on the rest.
- The onset rule's gain has the same size in both groups. It does not depend on whether E0 saw the paper.
- Post-hoc and descriptive. The pre-registered verdict stands.
