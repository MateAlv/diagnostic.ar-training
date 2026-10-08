# EXP-P-006: the Phase 2 final check, on publications GenPhenAI never saw

- **Front:** Phase 2 ([PHASE2.md](../PHASE2.md), [ADR-0017](../decisions/0017-phase-2-real-patient-restart.md)
  decisions 3–5)
- **Registered:** 2026-10-08, by the main session for Mateo (go for the final check given 2026-10-08)
- **Status:** done. Read once on 2026-10-08 (ledger `70efa8d0cdf0`, both vaults). **H1 passed; H2 holds.** The independent review (2026-10-08) gave GO, and its notes are folded in. ADR-0017 Amendment 2 moves the `p2-fresh-v1` freeze to 2026-10-08T19:35:00Z, before any read. The read
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
- **`p2-v1` vault:** the R1 test and vault publication groups that are post-E0. 732 patients in 135 groups. Never
  scored by a Phase 2 candidate. Phase 1 did score them: E0 and the Phase 1 re-rankers in EXP-000, B-003, B-006
  (67 groups from R1 test) and EXP-V-001 (68 groups from R1 vault).
- **`p2-fresh-v1` vault:** phenopacket-store `main` at its last commit before 2026-10-08T19:35:00Z (ADR-0017 Amendment 2), under ADR-0017 §4's
  rule. Frozen on 2026-10-08 (`2a9438d0…`): 340 patients in 86 groups, at `main@85ffd78`. It has never been read; it is pinned
  and frozen by DATA_LINEAGE §9's procedure before the read.
- **Post-E0:** no PMID of the publication group is in phenopacket-store 0.1.25, and none is cited in HPO 2025-11-24,
  the annotations E0 was trained on.
- **Disclosure:** H1 was chosen after EXP-P-001's read of `p2-v1` test. There the onset and sex rules alone harmed no
  patient, onset alone gave +0.00016 [+0.00007, +0.00032], and the negation rule carried every harm. The final-check
  patients are disjoint from `p2-v1` test and from every development part, and no Phase 2 candidate has scored
  them. EXP-P-001 Addendum 1 also showed onset on test patients from papers E0 does not cite: +0.00017 [+0.00003,
  +0.00056]. The hypothesis was
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
- **H2:** read `ci[0] >= 0` from the H2 `gate.json` (95%, n_reads 1). The script's `passed` field tests a lower
  bound above 0, so it is not H2's rule. `ft-v1.1` may go to production if H2 holds, after Mateo's go.
- **What an H1 pass means for production:** `safe-v1[sex+onset]` becomes a production candidate (knowledge-only) if
  H1 passes with harmed ≤ 0.5%, after Mateo's go. It has no separate confirmation read: this read is its
  confirmation, on data independent of every earlier choice.
- **Knowledge that PMID masking cannot reach, disclosed before the read:** `genes_to_disease`, HPOA rows referenced
  by OMIM or ORPHA, Orphanet ages (2026-06-23, newer than HPO 2026-02-16), and the agent-curated sex removals.
  - These can only reduce harms, so they favour the candidates.
  - In the other direction, the all-mask artefact of EXP-P-005 (OFD1, F8, SLC9A6 and THOC2 in females) can recur for
    `ft-v1.1`.

## Also reported (descriptive)
- every system vs E0, overall and per vault, with harmed and helped and top-1 and top-10 entries and exits;
- the subsets: sex known, age known, onset known, excluded known, gene in vocabulary;
- E0's MRR on these patients;
- the share whose gene is outside E0's vocabulary.

## Expectations
- **Post-E0 R1 train + dev patients** (1,034; P2-PROBES-v1 §5):
  - E0 MRR 0.066, and 52% have a gene in E0's vocabulary.
  - Sex + age/onset (hard): +0.00010 [+0.00003, +0.00020], 0 harmed.
  - ft-v1.1: +0.00007 [+0.00001, +0.00020], 0 harmed.
- **Dev, `safe-v1[sex+onset]`:** +0.00100 [+0.00030, +0.00179], 0 harmed. Train: +0.00036 [+0.00007, +0.00080], 0
  harmed.
- **Expected here:** a Δ near +0.0001, with harmed near 0. With about 220 publication groups, the CI may still include
  0. If so, the result reads "not confirmed on post-E0 patients", not "no effect".

## Results
Read on 2026-10-08 from `70efa8d`. Ledger rows: `p2-v1/vault` and `p2-fresh-v1/vault`, both under EXP-P-006. Outputs:
`results/EXP-P-006/final-check/` (report, ranks per system, `*__gate.json`); manifest `results-EXP-P-006-final-check`.

1,072 patients (732 + 340) in 221 publication groups, all from publications E0's training annotations never cite.
E0's MRR here is 0.128; 55.2% have a gene in E0's vocabulary. Δ is against E0, with the 95% CI of the publication-cluster
bootstrap.

| System | All (1,072) | `p2-v1` vault (732) | `p2-fresh-v1` (340) | Helped / harmed | Top 10 |
|---|---|---|---|---|---|
| **`safe-v1[sex+onset]` (H1)** | **+0.00029 [+0.00001, +0.00075]** | +0.00042 [+0.00002, +0.00112] | +0.000003 [0, 0] | 180 / 3 (0.28%) | +1/−0 |
| **`ft-v1.1-c1-lin-all-ens` (H2)** | **+0.00054 [+0.00005, +0.00129]** | +0.00067 [+0.00004, +0.00175] | +0.00027 [+0.00001, +0.00093] | 257 / 3 (0.28%) | +2/−0 |
| `safe-v1` (as in EXP-P-001) | +0.00031 [+0.00002, +0.00078] | +0.00045 [+0.00003, +0.00115] | +0.000003 | 223 / 3 | +1/−0 |
| `safe-v1[onset]` | +0.00029 [+0.00001, +0.00075] | +0.00042 [+0.00002, +0.00112] | +0.000003 | 134 / 3 | +1/−0 |
| `safe-v1[negation]` | +0.00002 [+0.00000, +0.00006] | +0.00003 | +0.00000 | 110 / 0 | 0 |
| `safe-v1[sex]` | +0.000002 | +0.000003 | +0.000001 | 75 / 0 | 0 |

- **Harmed:** the same 3 patients under both systems, from one family (PMID:40210435, CDK4). Their true gene was deep
  in E0's list: ranks 3,466 → 3,680, 3,982 → 4,210 and 3,488 → 3,691 under `safe-v1[sex+onset]`; up to 4,360 under
  `ft-v1.1`.
- **The `p2-fresh-v1` part** (86 publications released after 0.1.27) has small effects. Under `ft-v1.1`: +0.00027
  [+0.00001, +0.00093], 61 helped, 0 harmed.

## Verdict
- **H1 passed:** the 95% CI lower bound of `safe-v1[sex+onset]` is +0.00001 > 0, and harmed is 0.28%.
  - On patients from publications GenPhenAI never saw, the knowledge-only sex and onset rules rank the causal gene
    higher than E0.
  - The production criterion (harmed ≤ 0.5%) is met; production needs Mateo's go.
- **H2 holds:** the 95% CI lower bound of `ft-v1.1` is +0.00005 ≥ 0, with harmed 0.28%. With EXP-P-005's
  confirmation, `ft-v1.1` meets PHASE2.md's production criteria for a learned candidate; production needs Mateo's go.
- **Size:** the effects are small in MRR (+0.0003 to +0.0005 on a baseline of 0.128) and positive with few harms on
  both independent checks.
