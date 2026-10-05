# EXP-V-001: the final R1-vault read (E0, rerank-v1.0.0 and rerank-v1.1.0 side by side)

- **Front:** B
- **Registered:** 2026-10-05, by Mateo Alvarez (the one vault read approved 2026-10-05; written by the assistant)
- **Status:** pre-registered, vault read not done.
- **Governing rules:** EVAL_PROTOCOL §2 ("the vault opens once for the whole project, at the end, to report the final
  chosen system and E0 side by side"), §6 (reporting), EXP-B-003 and EXP-B-006 (metrics and views).

## Hypothesis
None to confirm. This is a **descriptive final report, not a gate.** It states, on 20% of R1's publications that no
choice ever touched, how the final chosen system and the system in production compare with E0.

**The vault result cannot change a release decision.** `rerank-v1.1.0` is already chosen and approved (it passed the
EXP-B-006 gate on R1-test, Mateo approved its release); a bad number here does not withdraw it and a good one does
not add a claim to it. Nothing is tuned on the vault.

**If a bug is found** (in the scoring code, the cohort handling or the report), it gets a **new pre-registration**
with its own id that explains the bug. **The vault is not re-read**: the ledger refuses a second read and this
experiment does not ask for an exception.

## Systems compared
All three are scored in one session, from the same GNN output per case, by `eval/final_report.py` (which reuses
`eval/release_check.py`'s views and records).

| System | Config | Config hash | Notes |
|---|---|---|---|
| **E0** | genphenia_v3 (model-v3.0.0) | | the GNN alone; R1 reference (optimistic on R1, EVAL_PROTOCOL §4.5) |
| **rerank-v1.0.0** | rr-v1[neg=0.5] on kb-v3: `RerankConfig(kb-v3, llr, k 0.5, top_k 200, neg_llr 0.5)`; `Weights(neg=0.5)` | `fe58053033fa` | deployed to staging |
| **rerank-v1.1.0** | the same plus `onset` 0.25: `Weights(neg=0.5, onset=0.25)` | `71713c8d15b0` | the **final chosen system**; passed EXP-B-006, release approved by Mateo |

- **Knowledge:** kb-v3, as in EXP-B-006 (sha256 `39d5f9213afab40090d15bdace663dc94d650b099e6b13643ced0633f4970fa8`;
  R1 dev/test/vault PMIDs masked). `FeatureParams` are the defaults. The hashes above are pinned by a test
  (`tests/test_final_report.py`).
- **Code commit:** the read runs from the commit that registers this file (a clean tree is enforced and the SHA goes
  in the ledger row and the manifest). The code is `eval/final_report.py` and `dxt rerank final-report`.

## Cohort
- **R1-vault**, `r1-v1/vault`, loaded through `splits.load_part` (the frozen split, content hash checked). Patients
  as the cohort records them: present terms, excluded terms, onset as `case_onset_years` reads it (exact onset age
  if recorded, else the midpoint of the HPO onset class, else none). Sex and age are ignored by every system
  (weight 0). Cases whose gene is not in the model's vocabulary are unrankable and counted, as in EXP-B-003.
- **Views (from the same GNN output per case):**
  - `given`: excluded terms and onset as recorded;
  - `present`: excluded terms and onset removed (the present-only view).
- **Subset (given view):** cases with a usable onset, and the rest.

## Metrics and contrasts
- **Primary: MRR** (given view). Also reported: top-1, top-10 and top-100.
- **Statistics, as EXP-B-003 and EXP-B-006:** paired bootstrap 95% CI, **resampling publications**, 2,000 resamples,
  seed 0, over the same cases in the same order. Harmed = share of cases whose rank gets worse, helped = share whose
  rank gets better. n, unrankable cases and the number of publications are reported.
- **Contrasts**, each in both views, for MRR, top-1, top-10 and top-100:
  1. rerank-v1.1.0 vs E0;
  2. rerank-v1.0.0 vs E0;
  3. rerank-v1.1.0 − rerank-v1.0.0.
- **Onset subset:** the three contrasts on the cases with a usable onset, and on the rest.
- **Not gated, not confirmatory.** Per EVAL_PROTOCOL §6 only a pre-registered candidate's primary metric is a
  confirmatory claim, and that claim was EXP-B-006's. Everything here is descriptive and is labelled so in the report
  JSON (`descriptive_only`).

## The command
One command, one ledger row, run once from the commit that registers this file:

```
DXT_SEALED_READ=EXP-V-001 .venv/bin/dxt rerank final-report --exp EXP-V-001 --cohort r1-v1/vault \
  --reason "EXP-V-001 final R1-vault read (pre-registered <registering commit>)"
```

- **Refusals, all before any data is loaded, any artifact fetched or the ledger touched:**
  - `DXT_SEALED_READ` not equal to `EXP-V-001`;
  - a missing reason;
  - this file not committed and unmodified;
  - a dirty tree;
  - the ledger already holds an `r1-v1/vault` row (the vault opens once).
- **The ledger row** (`docs/TEST_LEDGER.md`) is appended by `splits.load_part`, once, just before the cases are
  read. If the run then fails, the vault counts as read and is not re-read; the failure is logged and, if it is a
  bug, handled as above.
- **Outputs**, under `results/EXP-V-001/`: per system and view `r1-v1-vault__<system>__<view>.ranks.jsonl` and
  `.summary.json`; `r1-v1-vault__final-report__report.json`; manifest `results-EXP-V-001-r1-v1-vault-final-report`.
  Commit them with the ledger row.
- **Step 0 (not sealed, before the read):** the same command with `--cohort r1-v1/dev` (no env var, no reason) is the
  dry run. Its rr-v1 vs E0, rerank-v1.1.0 vs E0 and v1.1 − v1.0 MRR numbers must reproduce EXP-B-006's R1-dev
  dry-run numbers exactly (E0 0.4485; rr-v1 vs E0 −0.0067 [−0.0235, +0.0051]; candidate vs E0 −0.0048
  [−0.0221, +0.0073]; candidate − rr-v1 +0.0019 [−0.0002, +0.0046]). The result is in BITACORA.
- **Not read:** R1-test, S3, MCRD, DDD. This experiment spends no other sealed budget.

## Expectations (written before the read; from EXP-B-006's R1-test numbers)
The vault holds different publications, so values will move. What carries over:

| Quantity | Expected (given view, R1-test numbers) |
|---|---|
| present view, every contrast vs E0 | exactly 0, harmed 0, helped 0 (the two re-rankers equal E0 without excluded terms or onset; EXP-B-006 ID2) |
| rerank-v1.0.0 vs E0, MRR | about −0.0025, CI including 0; harmed about 9%, helped about 6% |
| rerank-v1.1.0 vs E0, MRR | about −0.003, CI including 0; harmed about 11%, helped about 13% |
| rerank-v1.1.0 − rerank-v1.0.0, MRR | about 0 (R1-test −0.0003 [−0.0019, +0.0008]; R1-dev +0.0019); CI including 0 |
| onset subset, v1.1 − v1.0 | about 0 (R1-test −0.0006 [−0.0038, +0.0015]); on cases without usable onset exactly 0 |
| E0 MRR | not predicted: R1-dev 0.4485, R1-test 0.3698, the spread shows how much cohorts differ |

In words: **no measurable gain from either re-ranker on real patients, and no clear harm.** A result outside these
bands is reported as it is, with no re-reading and no change to the release decision.

## Declared limits
- **No interviews.** The vault is R1 phenopackets: there is no question-agent session in it. **Q2b and the question
  agent cannot be evaluated on it**, and neither can the interview-driven negations the re-ranker is meant for. The
  R1 negations are the ones authors chose to report because they are typical of the syndrome (EXP-B-001
  Addendum 1), not a patient's "no".
- **R1 onset comes from publications, not from the web form.** It is a curated phenopacket field (an age, or an HPO
  class), not a patient's answer per symptom. Late onset is rare in R1 (EXP-B-006: 13 R1-train patients).
- **E0 is optimistic on R1** (v3.0 was trained on annotations from R1 publications; EVAL_PROTOCOL §4.5), so every
  contrast against E0 is conservative for the re-rankers.
- Sex and age are not used by either re-ranker (weight 0), so they are not evaluated here.
- All efficacy evidence for the interview path stays simulated (S3, dev and the sealed reads of EXP-B-004,
  EXP-B-005); this read adds real-patient evidence only for the no-interview case.
- MCRD and DDD carry neither excluded terms nor onset, so both re-rankers equal E0 there; not read.

## Results
(filled after the read)

## Verdict
(filled after the read: descriptive only; no release decision depends on it)

## Addenda
