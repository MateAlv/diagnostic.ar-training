# EXP-P-006: the Phase 2 final check, on publications GenPhenAI never saw

- **Front:** Phase 2 ([PHASE2.md](../PHASE2.md), [ADR-0017](../decisions/0017-phase-2-real-patient-restart.md)
  decisions 3–5)
- **Registered:** 2026-10-08, by the main session for Mateo (go for the final check given 2026-10-08)
- **Status:** registered. ADR-0017 Amendment 2 moves the `p2-fresh-v1` freeze to 2026-10-08T19:35:00Z, before any read. The read
  follows: once, all systems together.

## Hypotheses
- **H1 (primary):** on post-E0 patients, `safe-v1[sex+onset]` ranks the causal gene higher than E0 on average:
  Δ MRR > 0.
- **H2 (secondary; production criterion for a learned candidate):** `ft-v1.1-c1-lin-all-ens` has a Δ MRR whose 95% CI
  lower bound is ≥ 0 (PHASE2.md gates).

## Systems compared
All systems are scored in one read by `dxt final-check` (`cli_final.py`, `eval/final_check.py`), on the same cases.

| System | Artifact | Notes |
|---|---|---|
| E0 | `genphenia_v3`, present terms | production today |
| **`safe-v1[sex+onset]`** | `safe-kb-v1` (bundle sha256 `28646c4a…`) | sex hard block (92 genes) plus onset ×0.01; knowledge-only |
| `ft-v1.1-c1-lin-all-ens` | bundle sha256 `89e3ea09…`, knowledge `ft-kb-all-v2` | passed EXP-P-005 on `p2-v1` test |
| `safe-v1` | `safe-kb-v1` | as registered in EXP-P-001; descriptive |
| `safe-v1[sex]`, `[onset]`, `[negation]` | `safe-kb-v1` | descriptive |

## Data
- **`p2-v1` vault:** the R1 test and vault publication groups that are post-E0. 732 patients in 135 groups; never
  read.
- **`p2-fresh-v1` vault:** phenopacket-store `main` at its last commit before 2026-10-08T19:35:00Z (ADR-0017 Amendment 2), under ADR-0017 §4's
  rule. 340 patients on `main@85ffd78`; the frozen count is recorded at freeze. It has never been read; it is pinned
  and frozen by DATA_LINEAGE §9's procedure before the read.
- **Post-E0:** no PMID of the publication group is in phenopacket-store 0.1.25, and none is cited in HPO 2025-11-24,
  the annotations E0 was trained on.
- **Disclosure:** H1 was chosen after EXP-P-001's read of `p2-v1` test. There the onset and sex rules alone harmed no
  patient, onset alone gave +0.00016 [+0.00007, +0.00032], and the negation rule carried every harm. The final-check
  patients are disjoint from `p2-v1` test and from every development part, and they are unread. The hypothesis was
  informed by test, and it is tested here on independent data.
- **Command, after the freeze:**
  `DXT_SEALED_READ=EXP-P-006 .venv/bin/dxt final-check --exp EXP-P-006 --safe-kb safe-kb-v1 --ft-bundle
  ft-v1.1-c1-lin-all-ens --ft-kb ft-kb-all-v2 --reason "EXP-P-006 final check"`
- **H1 gate:** `.venv/bin/python scripts/analysis/exp_p_gate.py EXP-P-006 final-check/p2-v1+p2-fresh-v1-vault
  "safe-v1[sex+onset]" 1`. With one primary hypothesis, the level is 95%.
- **H2:** the same script, with system `ft-v1.1-c1-lin-all-ens` and n_reads 1.

## Primary metric and gate (written before results)
- **Primary:** Δ MRR, `safe-v1[sex+onset]` − E0, over all final-check patients (both vaults), with misses counted as
  0. The bootstrap is paired and resamples publication groups (2,000 resamples, seed 0).
- **H1 passes** if the 95% CI lower bound is above 0 and harmed ≤ 5%.
- **H2** is reported with its CI. `ft-v1.1` may go to production if the H2 lower bound is ≥ 0, after Mateo's go.

## Also reported (descriptive)
- every system vs E0, overall and per vault, with harmed and helped and top-1 and top-10 entries and exits;
- the subsets: sex known, age known, onset known, excluded known, gene in vocabulary;
- E0's MRR on these patients;
- the share whose gene is outside E0's vocabulary.

## Expectations
- **Post-E0 dev patients** (1,034; P2-PROBES-v1 §5):
  - E0 MRR 0.066, and 52% have a gene in E0's vocabulary.
  - Sex + age/onset (hard): +0.00010 [+0.00003, +0.00020], 0 harmed.
  - ft-v1.1: +0.00007 [+0.00001, +0.00020], 0 harmed.
- **Dev, `safe-v1[sex+onset]`:** +0.00100 [+0.00030, +0.00179], 0 harmed. Train: +0.00036 [+0.00007, +0.00080], 0
  harmed.
- **Expected here:** a Δ near +0.0001, with harmed near 0. With about 220 publication groups, the CI may still include
  0. If so, the result reads "not confirmed on post-E0 patients", not "no effect".

## Results
(Filled in after the read.)

## Verdict
(Filled in after the read.)
