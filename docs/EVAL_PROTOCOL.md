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
    same cases in the same order. **On R1 the bootstrap resamples
    publications, not patients**: patients of one paper are correlated, and
    the case bootstrap understates R1 uncertainty 3–7× (EXP-000 Addendum 2).
    `eval.harness.compare` does this automatically when records carry their
    publication group;
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
     R3 (DDD) is annotation-derived (EXP-000 Addendum 1): it counts only as a
     no-regression check, never as evidence of accuracy.
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

## 8. S3: simulated question-agent evaluation (negated symptoms as the app produces them)

**Why.** R1 cannot validate negation for deployment (EXP-B-001 Addendum 1,
EXP-B-002). Its absent findings are the ones authors chose to report because
they are typical of the syndrome. In the web app, a negation is a patient's
"no" to a question the question agent asked about the candidates' features.
S3 reproduces that process on simulated patients whose true phenotype is
known. The design goal is that **nothing a system under test uses can have
been derived from the test patients' truth**.

**Protocol (sketch; the parameters are pre-registered in the S3 experiment
file).**
1. **Knowledge split.** Every positive HPOA annotation (disease, term) goes
   to half **A** (known) or half **B** (held out) by a salted hash, fraction
   `h` held out. The split is a frozen artifact (`annot-split-vN`). `h` is
   chosen, from R1-train only, so that S3 patients' share of present terms
   their gene does not explain matches R1-train's (46%, `calib-v1`).
2. **Test patients** are generated from the **full** profiles (A ∪ B) by the
   simulator: gene-first, `calib-v1` noise and missingness, a fixed seed
   range. Each case carries its `true_present` set.
3. **Systems under test** only ever see **A**:
   - the KB (`kb` built with B dropped);
   - the re-rankers' features;
   - the questioner;
   - Front A's training data (simulator profiles with B dropped, a
     disjoint seed range).

   E0 is the exception: v3.0 was trained on full `genes_to_phenotype` and
   cannot be masked. That favours E0, so comparisons against it are
   conservative. This is declared.
4. **Questioner** (fixed, identical for every system).
   - **Sees:** only the initial presentation (the reported present terms
     plus sex and age when reported), E0's distribution over genes for that
     presentation, and KB-A. It never sees the gene, the disease or the
     truth. This is enforced by type: it receives a `PublicCase` that has no
     such fields.
   - **Asks:** Q terms chosen by expected information gain over E0's top-N
     candidates, with P(t | gene) from KB-A. It never asks a term already
     reported, or an ancestor or descendant of one.
5. **Answers** come only from the truth. "Yes" if the asked term is a true
   term or an ancestor of one; otherwise "no". Answers are recorded per case
   and are identical for every system.
6. **Inputs per system**, the same for all of them, so Δs isolate what each
   system does with them:

   | System | Receives |
   |---|---|
   | E0 | reported present + "yes" answers |
   | Any other system | the same + "no" answers as excluded terms + sex/age as reported |

   "E0 without questions" is also reported, to measure the questions
   themselves.
7. **Splits and sealing.** S3 cases are assigned to **S3-dev** (selection)
   or **S3-test** (sealed, ledgered, pre-registered reads only) by a salted
   hash of the case id. The split is frozen before any system is run on it.
8. **Contamination checks, all enforced and logged:**
   - no Front A training case shares a (gene, present, excluded) signature
     with an S3 case;
   - training and test seed ranges are disjoint;
   - every system input artifact's manifest must list the annotation split
     with "B dropped".

**Declared residual dependencies.**
- `genes-v1` weights (which of a gene's diseases) and inheritance are shared
  by the generator and the systems. They carry no phenotype terms.
- The simulator's structural assumptions (frequency sampling, onset gating)
  are shared by S3 and Front A's training data. S3 can therefore overstate
  Front A relative to real patients; R1 remains the check against that.
