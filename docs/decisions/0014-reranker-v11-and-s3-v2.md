# ADR-0014: Re-ranker v1.1 and better questions, evaluated on a new sealed S3 v2

- **Status:** Accepted, 2026-10-03 (Mateo). Written before any S3 v2 data
  exists and before any new system is run.
- **Context:**
  - `rr-v1[neg=0.5]` passed its sealed gate (EXP-B-003) and is released as
    `rerank-v1.0.0`. Its gain is small: S3-test Δ MRR +0.0044, harming 3.9%.
  - Sex and age carry weight 0, because they were never fairly testable
    (EXP-S3-001 addendum 1).
  - S3 v1's sealed test has been read once (for rr-v1), and its patients come
    from the v0.3-era simulator.
  - Mateo wants to push the re-ranker as far as it honestly goes, test sex
    and age fairly, and improve the questions, which is the core of the
    trabajo.

## The four levers
| # | Lever | What is tried |
|---|---|---|
| L1 | **The negation strength limit** | Penalty variants and weights, mapping the gain–harm frontier, not just one point |
| L2 | **Better symptom frequencies** | The re-ranker's P(term \| gene) from the literature-enriched knowledge (`hpoa-enriched-v2`) instead of kb-v5's |
| L3 | **Sex and age, tested fairly** | The existing `sex`, `age` and `onset` features (and refinements of them), on an S3 v2 built so that the generator's sex and onset facts come from **sources the re-ranker does not use** |
| L4 | **Better questions** | Question-selection strategies compared on the same patients and answer rules: the S3 v1 questioner, the production agent's strategy, and a re-ranker-aware strategy |

## S3 v2: a new sealed evaluation set
1. **Generator: simulator 0.5.4, the candidate 6 configuration**
   (`simcal-v053-v1`), with full profiles from `hpoa-enriched-v2`, gene-first,
   4 cases per gene, medium, **seed 3003**. That seed is disjoint from S3 v1
   (2002), the Front A data (1001) and the pilots (91001).
   - Candidate 6 did not pass the Front A data gate (ADR-0012 amendment 5),
     but it is the most realistic generator we have, and S3 only needs it
     to produce evaluation patients, not training data. This is declared.
2. **Phenotype knowledge split, `annot-split-v2`.** Every positive
   (disease, term) pair of `hpoa-enriched-v2`, literature rows included,
   goes to half A (known) or half B (held out) by a salted hash, with 30%
   held out, as in v1.
   - Every system's knowledge is built with **half B dropped**.
   - The generator uses A ∪ B.
3. **Source separation for sex and age (L3).**
   - **Age:**
     - the generator draws onset from **literature onset ages**
       (`onset-ages-v2`, GeneReviews and major studies; simulator 0.5.4
       `--onset-ages`) where they exist, and from Orphanet categories
       otherwise;
     - the re-ranker's age and onset features use **only Orphanet onset**
       (kb `onset_years`);
     - **L3's age claims are made only on cases whose entity has a
       literature onset** (the "lit-onset subset"), where the two sources
       are independent extractions of the same truth.
   - **Sex:**
     - the generator's male share per inheritance class is **measured on
       R1-train patients** (an empirical calibration file);
     - the re-ranker uses its own `MALE_SHARE` heuristic table;
     - inheritance itself (X-linked, etc.) is shared truth, which is real
       signal and not leakage.
4. **Questioner and answers.**
   - The answer rule is the same as v1: "yes" if the asked term is true or
     an ancestor of a true term, otherwise "no".
   - "No sé" is never produced in the main analysis. An answer-noise
     sensitivity run (5% of answers flipped or set to unknown) is reported
     as secondary.
5. **Split `s3-v2`** by a salted hash of the case id, **dev 50% / test 50%**.
   It is frozen and committed **before any system runs**.
   - **Test is sealed.** Exactly **one** pre-registered read (EXP-B-004) at
     the end scores every pre-registered final system and ablation in that
     same read. There are no adaptive re-reads.
6. **Contamination checks:**
   - no S3 v2 case shares a (gene, present, excluded) signature with R1,
     S3 v1 or any training data;
   - the seeds are disjoint;
   - every system's knowledge manifest lists `annot-split-v2` with half B
     dropped.

## Rules against overfitting
- **Search happens on S3-v2-dev only.**
  - Every configuration tried is logged, with a budget written per lever in
    the experiment plans (L1 ≤ 48 configs, L2 ≤ 6, L3 ≤ 12, L4 ≤ 6
    strategies).
  - The selection rule is fixed before the search: **maximise Δ MRR subject
    to harmed ≤ 5% and CI lower bound > 0** (L1 also reports the full
    frontier).
- **Systems that saw a test set are not re-scored on it as new evidence.**
  - rr-v1 (tuned on S3-v1-dev) may be scored on S3 v2, which it never saw,
    as the reference.
  - S3-v1-test is not read again.
  - Nothing tuned on S3-v2-dev is reported as a test result except through
    EXP-B-004.
- **Real-patient safety.** The final system gets **one** pre-registered
  R1-test no-regression read (as in EXP-B-003 N1/N2), plus the R1-dev check
  during the search.
- **E0 knows half B** (v3.0 was trained on full annotations). This is
  declared and favours E0.
- **L2's circularity is declared.** The generator's frequencies and the
  enriched knowledge share half-A numbers, so L2's gain may be inflated. It
  is reported separately on half-B-only terms (excluded terms whose
  (disease, term) pair is in half B), where the re-ranker cannot know the
  generator's number.

## L4 metric
- **The metric:** Δ MRR after the interview, from E0 with no questions to
  the final system, with the questioner's effect and the re-ranker's effect
  reported separately on the same patients.
- **Same question budget for every strategy:** 9 questions; 3 rounds of 3
  where adaptive, otherwise 9 in one batch.
- **The production agent's strategy is run through its own selector code**
  (MarBL00126/diagnosticar-question-agent, `feat/rerank-negaciones`),
  imported read-only, not re-implemented.
- Questioners only ever see a `PublicCase` (reported terms, sex, age), as in
  v1.

## Order of work (each step merged before the next starts)
| Phase | Work | Output |
|---|---|---|
| 0 | This ADR + experiment plans EXP-B-004 (L1–L3) and EXP-Q-001 (L4) | committed |
| 1 | `annot-split-v2`, sex calibration from R1-train, S3 v2 patients, split `s3-v2` frozen, contamination | artifacts + manifests |
| 2a | Knowledge variants without half B: `kb-v6` (old sources) and `kb-v7` (enriched) | artifacts |
| 2b | Re-ranker feature variants (L1 penalty forms; L3 refinements) behind config, with tests | code |
| 2c | Questioner harness: strategies Q0, Q1 (agent), Q2 (re-ranker-aware) | code |
| 3 | Dev search, all levers, everything logged | dev results |
| 4 | Pre-register the finals → **one** S3-v2-test read + **one** R1-test read → `rerank-v1.1.0` if it beats rr-v1 | EXP-B-004 results |

## Not in scope
- Changing the GNN (that is A-005, later).
- Free-text negations: not validated, and R1 shows no gain.
- Production deployment of anything new: only after phase 4, through
  diagnostic.ar-model.

## Addendum, 2026-10-03: S3 v2 phase 1 done
- `s3-data-v2`: 19,568 cases, 4,892 genes. Split `s3-v2` frozen before any
  system ran: dev 9,872, test 9,696, content sha256
  `fb7d47f04d161aa3c01dbcec133717de52ee06c6a16709872a205f18ef65c58e`.
- Cases whose entity used literature onset: 1,027 (5.25%).
- Exclusion list `s3-data-v2-excl-v1`: 253 cases, residual overlap 0.
- A ledger row `s3-v2/test | EXP-B-004` (reason `x`) exists from an accidental
  load; see the BITACORA entry of the same date.

## Note, 2026-10-03: sealed-read guard
- The 2026-10-03 20:59 ledger row for s3-v2/test (EXP-B-004, reason 'x') was
  a non-substantive technical access during phase 1 checks; nothing was
  inspected; Mateo ruled it does not consume EXP-B-004's read; guard added.
- Guard: every sealed load of R1 test/vault and S3 test now also requires the
  environment variable `DXT_SEALED_READ` to equal the `exp_id` being read
  (EVAL_PROTOCOL §2). The ledger row stays; it is not edited.

## Addendum (2026-10-03, phase 2b): wording correction and the propagated form
- **Re-ranker onset source.** §3 says the re-ranker uses "only Orphanet
  onset". In fact the knowledge builder takes **HPOA onset annotations
  first and Orphanet as a fallback** (`onset_source` ∈ {hpoa, orphanet,
  orphanet_exact_alignment}). The source separation holds either way: the
  re-ranker never reads `onset-ages-v*`, which a test enforces (AST scan and
  runtime). L3's age analysis reports the lit-onset subset split by
  `onset_source`.
- **L1 form (iv), `propagated`.** P(t | g) already includes descendants
  (noisy-OR propagation), so "a no to a parent counts against genes
  annotating a child" is already true in every form. Form (iv) is therefore
  defined as: **only the most general excluded terms count**, i.e. no
  double charge when a parent and its child are both excluded.
- **To check at the start of phase 3:** each gene's disease weights sum
  to 1 in kb-v6 and kb-v7. The `onset` and `term_probability` features
  assume it.
