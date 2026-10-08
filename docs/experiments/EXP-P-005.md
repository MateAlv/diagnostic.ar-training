# EXP-P-005: ft-v1.1 (the network with a sex/age/onset/negation branch, X-linked features fixed) on the Phase 2 confirmation set

- **Front:** Phase 2, Track 3 ([PHASE2.md](../PHASE2.md); [EXP-P-003](EXP-P-003.md) and its ft-v1.1 addendum)
- **Registered:** 2026-10-08, by the main session. It replaces EXP-P-004, which was withdrawn before its read. Mateo's
  go for a Track 3 confirmation read was given on 2026-10-08.
- **Status:** registered. The independent review (2026-10-08) gave GO, and its masking note is folded in above.

## Hypothesis
On `p2-v1` test, `ft-v1.1-c1-lin-all-ens` ranks the causal gene higher than E0 on average: Δ MRR > 0.

## Systems compared
| System | Artifact ids / code | Notes |
|---|---|---|
| E0 | `genphenia_v3` (model-v3.0.0), present terms | production today |
| `ft-v1.1-c1-lin-all-ens` | bundle `data/ft/ft-v1.1-c1-lin-all-ens/ft-v1-bundle.json`, sha256 `89e3ea09c1e491de29b2d7c6f7955bba7ab6bbb575c47fc17756336c601db340`; knowledge `ft-kb-all-v2` | E0's logits plus a zero-initialised residual: 7 learned non-negative weights over gene-agnostic knowledge features (sex mismatch; strict onset late and gap; lenient onset gap; `xlr_female`, now only for explicit HP:0001419 X-linked recessive; obligate negation; excluded-term embedding similarity). The mean of 3 seeds, selected by EXP-P-003's registered rule. |

## Data
- **Fitting:** `r1-v1` train, with every `r1-v1` PMID masked in the knowledge.
- **Selection:** `r1-v1` dev, under EXP-P-003's rule. This is the second dev search, after the feature fix.
- **Sealed read (this experiment):** `p2-v1` test, 3,587 patients in 567 groups. It is Phase 2 confirmation read 2 of
  3. EXP-P-001 read the same patients for `safe-v1`.
- **Disclosure:**
  - **What was fixed, and why.** EXP-P-004's review found the X-linked flaws on train; the fix and the reselection used
    train and dev only.
  - **What is already known about these patients.** `ft-v1.1` shares three features with `safe-v1` (sex mismatch,
    strict onset, obligate negation), whose results on these patients are known from EXP-P-001. The negation rule
    harmed 9 test patients there (ATP6V0C, HMGCR), and `neg_obligate` stays in.
  - **A known artefact of masking.** Four genes count as X-linked-recessive-only only because the mask removes their
    other inheritance rows: OFD1 and F8 (7 train females penalised), plus SLC9A6 (its X-linked-dominant
    female-restricted row cites PMID:35198730, which is outside train and dev) and THOC2. Female patients with these
    genes can be penalised. Found by the independent review; the candidate is not changed.
- **Command:** `DXT_SEALED_READ=EXP-P-005 .venv/bin/dxt ft confirm --exp EXP-P-005 --split p2-v1 --part test --bundle
  ft-v1.1-c1-lin-all-ens --kb ft-kb-all-v2 --reason "EXP-P-005 confirmation read"`
- **Then:** `.venv/bin/python scripts/analysis/exp_p_gate.py EXP-P-005 p2-v1-test-ft-v1.1-c1-lin-all-ens
  ft-v1.1-c1-lin-all-ens`

## Primary metric and gate (written before results)
- **Primary:** Δ MRR, ft-v1.1 − E0, over all 3,587 patients, with misses counted as 0. The bootstrap is paired and
  resamples publication groups (2,000 resamples, seed 0).
- **Gate:**
  - (a) The CI lower bound is above 0 at level 1 − 0.05/3 (98.33%).
  - (b) Harmed ≤ 5%.
  - Pass = (a) and (b).
- **Production criterion,** for Mateo: pass, harmed ≤ 0.5%, and the final check.

## Also reported (descriptive)
- the 95% CI;
- helped and harmed shares;
- top-1 and top-10 entries and exits;
- the dev → test drop;
- harms on EXP-P-001's 9 patients, and on female patients with OFD1, F8, SLC9A6 or THOC2;
- the split by E0's training annotations;
- a check that E0's ranks equal EXP-P-001's.

## Expectations
- **From dev:** +0.00289 [+0.00136, +0.00461]; 2 of 1,883 harmed. Post-E0 dev: +0.00007 [+0.00001, +0.00020].
- **From train:** +0.00034, 13 harmed.
- **Informed by EXP-P-001's test read:** a Δ close to `safe-v1`'s +0.00029, give or take 0.001. EXP-P-001 had a
  98.33% CI half-width of about 0.00095 on these patients, so "not passed" is a likely outcome. That would read as "not
  confirmed", not "no effect".

## Results
(Filled in after the read.)

## Verdict
(Filled in after the read.)
