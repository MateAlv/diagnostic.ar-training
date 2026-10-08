# EXP-P-004: ft-v1 (the network with a sex/age/onset/negation branch) on the Phase 2 confirmation set

- **Front:** Phase 2, Track 3 ([PHASE2.md](../PHASE2.md), [EXP-P-003](EXP-P-003.md))
- **Registered:** 2026-10-08, by the main session for Mateo (go given 2026-10-08, after an independent review)
- **Status:** **withdrawn before its read** (2026-10-08). No sealed data was loaded and no ledger row exists; see
  Addendum 1.

## Hypothesis
On `p2-v1` test, `ft-v1-c1-lin-all-ens` ranks the causal gene higher than E0 on average: Δ MRR > 0.

## Systems compared
| System | Artifact ids / code | Notes |
|---|---|---|
| E0 | `genphenia_v3` (model-v3.0.0), present terms | production today |
| `ft-v1-c1-lin-all-ens` | bundle `data/ft/ft-v1-c1-lin-all-ens/ft-v1-bundle.json`, sha256 `5a26e537624651c737a18c044a41ea6072fac09d580e5ffda77a095ce04c80fa`; knowledge `ft-kb-all-v1` | E0's logits plus a zero-initialised residual: 8 learned non-negative weights over gene-agnostic knowledge features (sex mismatch, strict onset late and gap, lenient onset gap, X-linked × sex, obligate negation, excluded-term embedding similarity). The mean of 3 seeds; selected in EXP-P-003 by its pre-registered rule. |

## Data
- **Fitting:** `r1-v1` train (4,103 real patients), with every `r1-v1` PMID masked in the knowledge.
- **Selection:** `r1-v1` dev, under EXP-P-003's registered rule (8 configurations × 3 seeds).
- **Sealed read (this experiment):** `p2-v1` test, 3,587 patients in 567 groups. It is Phase 2 confirmation read 2 of
  3. EXP-P-001 read the same patients for `safe-v1`.
- **Disclosure:** the candidate and its bundle were fixed in EXP-P-003 before EXP-P-001's read and are unchanged.
  EXP-P-001 found that the negation rule harmed 9 test patients (ATP6V0C, HMGCR). `ft-v1` contains a negation
  feature, `neg_obligate`, and it was not removed after that read.
- **Command:** `DXT_SEALED_READ=EXP-P-004 .venv/bin/dxt ft confirm --exp EXP-P-004 --split p2-v1 --part test --bundle
  ft-v1-c1-lin-all-ens --kb ft-kb-all-v1 --reason "EXP-P-004 confirmation read"`
- **Then:** `.venv/bin/python scripts/analysis/exp_p_gate.py EXP-P-004 p2-v1-test-ft-v1-c1-lin-all-ens
  ft-v1-c1-lin-all-ens`

## Primary metric and gate (written before results)
- **Primary:** Δ MRR, ft-v1 − E0, over all 3,587 patients, with misses counted as 0. The bootstrap is paired and
  resamples publication groups (2,000 resamples, seed 0).
- **Gate:**
  - (a) The CI lower bound is above 0 at level 1 − 0.05/3 (98.33%), Phase 2's Bonferroni bound for 3 reads.
  - (b) Harmed ≤ 5%.
  - Pass = (a) and (b).
- **Production criterion,** for Mateo: pass, harmed ≤ 0.5%, and the final check (PHASE2.md gates for learned
  candidates).

## Also reported (descriptive)
- the 95% CI;
- helped and harmed shares;
- top-1 and top-10 entries and exits;
- the subsets `dxt ft confirm` reports;
- the dev → test drop;
- the patients EXP-P-001 harmed;
- the split by E0's training annotations (`scripts/analysis/exp_p001_by_citation.py` logic).

## Expectations (from dev)
- **Dev:** +0.00313 [+0.00159, +0.00485]; 2 of 1,883 harmed; top-1 +7/−0. Post-E0 dev: +0.00009
  [+0.00001, +0.00023].
- **Train, in-sample:** +0.00023 [−0.00152, +0.00181], 21 harmed.
- **Expected on test:** a Δ similar to `safe-v1`'s +0.00029, give or take +0.001, with harmed below 1%. The 9 patients
  `safe-v1`'s negation rule harmed may be harmed again.

## Results
(Filled in after the read.)

## Verdict
(Filled in after the read.)

## Addendum 1, 2026-10-08: withdrawn before the read
The independent review (verdict GO, no blocking issue) found two flaws in the candidate's features, both visible on
train:
- **`xlr_female` counts generic HP:0001417 ("X-linked inheritance") as recessive.** It therefore penalises female
  patients for disorders that affect females, such as PCDH19, OFD1, F8 and ZIC3. 16 of the 21 train patients the
  candidate harms are such females.
- **`xld_male` has θ≈5.3** although train and dev hold no patient with an X-linked-dominant-only gene. It would
  penalise males for genes such as PHEX, where males are affected.

Mateo's go covered this read, but the read would have measured a candidate with a known defect. The features are
fixed and the candidate reselected on dev under EXP-P-003's registered rule (EXP-P-003 addendum), and a new
pre-registration replaces this one. Phase 2 confirmation reads used: still 1 of 3.
