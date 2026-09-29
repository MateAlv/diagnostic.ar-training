# Evaluation protocol: how we avoid fooling ourselves

This protocol binds every experiment on both fronts. A rule marked
**[code]** is enforced by `diagnostic_ar_training` and covered by tests. A
rule marked **[discipline]** is enforced by review and by the log.

We claim an improvement only when we can show all three:
- the number was measured on data that never influenced any choice (training,
  tuning, selection, or the design of the simulator);
- it was measured against E0 on the same cases, by the same code;
- the uncertainty was reported.

---

## 1. Data parts and what each may be used for

| Part | What | May feed training / KB / simulator | May drive tuning or selection | Access |
|---|---|---|---|---|
| **R1-train** | 40% of phenopacket-store publications | yes | yes | free |
| **R1-dev** | 20% | **no [code]** | yes | free |
| **R1-test** | 20% | no | **no**, gates only | **sealed [code]** |
| **R1-vault** | 20% | no | no | **sealed, opens once [code]** |
| **R2 MCRD, R3 DDD** | external benchmarks | **no [code: role `eval`]** | no | **sealed [code]**: same rules as R1-test, ledgered |
| **S1** | our simulator's own held-out cases | yes (its train part) | early stopping only | free, never a headline number |
| **S2** | upstream-style simulated patients | no | no | free; overfitting-to-our-generator check |

- **The unit of splitting is the publication.** The split groups patients
  linked by any shared PMID and assigns each group by a salted hash. This
  prevents two leaks:
  - family members or a case series appearing on both sides;
  - one author's phenotyping style appearing on both sides.
- **The split is frozen.** It lives in `data/splits/r1-v1.json`; its content
  hash is checked on every load **[code]**, and re-freezing must reproduce it
  **[code]**.
- **A new split means a new id.** `r1-v2` never replaces `r1-v1`; results are
  only compared within the same split id.

## 2. Sealed parts: test and vault

- **Opening a sealed part requires three things [code]:**
  - a **pre-registered** experiment file `docs/experiments/<EXP-id>.md`,
    **committed and unmodified**. The commit is timestamped proof that the
    gate was written before the read;
  - a **clean git tree**, so the numbers are reproducible from the SHA. Files
    that runs write (`docs/TEST_LEDGER.md`, `docs/BITACORA.md`, `results/`,
    `data/manifests/`) don't count as dirty;
  - a reason.
- Every read appends a row to `docs/TEST_LEDGER.md` **[code]**. Commit the
  ledger together with the results.
- **The vault opens once for the whole project [code].** It is used at the end
  (Phase 4) to report the final chosen system and E0 side by side.
- **Test budget [discipline]:**
  - at most **one test read per release candidate**;
  - at most **3 candidates per front** over the 40 days.

  A candidate that fails its gate is not "fixed and re-tested" under the same
  id. A new candidate must first be justified on dev, and it spends budget.
- The test result is **reported, never tuned on**. If a test read reveals a
  bug, the fix gets a new pre-registration, and the log explains the bug and
  the re-read.

## 3. Pre-registration

Before any sealed read, and ideally before the experiment starts,
`docs/experiments/<EXP-id>.md` states the following (see `TEMPLATE.md`):
- the hypothesis and the single **primary metric** (default: R1 MRR, "all
  features" view);
- the **gate**: what counts as success, written before seeing results;
- the systems compared (always including E0) and their artifact ids;
- the dev configurations tried and how the final one was picked.

Editing the pre-registration after a sealed read is allowed only as a dated
addendum below the original text [discipline].

## 4. Leakage controls

1. **PMID masking [code: `splits.heldout_pmids`].** Every HPOA row citing an
   R1 dev, test or vault publication is dropped before building any KB or
   simulator profile. That is 15,412 rows (5.45%) for `r1-v1`. The manifest of
   each KB or dataset records the hash of the masked PMID list and the number
   of rows dropped.
2. **Contamination checks [code: `eval/contamination.py`].** These are run and
   logged for every training artifact against every eval cohort:
   - exact signature overlap;
   - present-set overlap;
   - PMID overlap.

   For R1 held-out parts, all three must be 0. Any other overlap is reported.
3. **Statistics come from R1-train only [discipline].** This covers noise
   vocabularies, frequency calibrations, missingness rates, age/sex priors
   and anything else the simulator or a re-ranker estimates from patients.
   It also covers the design choices of the simulator that are compared
   against real data (`validate`).
4. **No target leakage in features [discipline].** Inputs must be things
   available at inference time in the web:
   - present terms;
   - excluded terms;
   - sex;
   - current age;
   - optionally the age of onset.

   Never disease ids, gene-level metadata of the case, or the publication.
5. **E0 is optimistic on R1, and this cannot be removed.** v3.0 was trained on
   `genes_to_phenotype` that includes annotations from R1 publications. Note
   it next to every E0 comparison: our masked models are compared
   conservatively.

## 5. Model selection without overfitting dev

- **Log every configuration tried on dev**, not only the winner, in the
  experiment file: count, grid and the chosen one. Report the dev score of the
  winner *and* the median of all tried configurations.
- **Hyperparameter budget per experiment:** declared up front, e.g. ≤ 20
  configurations for rr-v1 and ≤ 8 for a GNN run.
- **Report the dev → test drop** for every gated candidate. A drop larger than
  the dev CI width is a warning sign, and it is written up.
- **Seeds:**
  - GNN results are reported as mean ± sd over **≥ 3 seeds**, or the single
    seed is declared;
  - never pick the best seed.
- Early stopping uses S1-val (simulated), not R1-dev, so that dev stays a
  clean selector across epochs and configurations.
- Prefer fewer free parameters when dev scores are within CI (rr-v1 over
  rr-v3; a linear head over an MLP).

## 6. Reporting and gates

- **Every comparison with E0 reports:**
  - both systems' metrics;
  - Δ with a **paired bootstrap 95% CI** (2,000 resamples, fixed seed) on the
    same cases in the same order;
  - the **harmed and helped rates**;
  - n, and the number of unrankable cases.
- **Ablation views** on the same cases:
  - present only;
  - + excluded;
  - + sex;
  - + age;
  - all.

  This attributes each gain.
- **Subsets:**
  - cases with known sex / age / excluded;
  - genes with sex-restricted or onset annotations.

  Report n for each.
- **Release gate** (both fronts; the details are in `PLAN.md` §6 A4 and §7 B3):
  1. R1-test primary metric Δ > 0, with the CI lower bound > 0.
  2. Present-only view: Δ CI lower bound ≥ −0.01 on R1-test, R2 and R3.
  3. Harmed rate ≤ 5% (Front B).
  4. The identity (B) or near-identity (A) holds when no new inputs are given.
- **Multiple comparisons.** Only the primary metric of the pre-registered
  candidate is a confirmatory claim. Everything else is exploratory and is
  labelled as such.

## 7. What "done" looks like for a result

A result is citable in the informe only if all of these hold:
- `dxt lineage verify` passed;
- the code SHA is pushed;
- the manifests are committed;
- the ledger row exists (if sealed);
- the `BITACORA.md` entry has the numbers and a verdict.
