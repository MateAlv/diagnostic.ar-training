# ADR-0011: Simulator v0.4, realism-first rebuild (and the artifacts it consumes)

- **Status:** Accepted, 2026-09-30 (Mateo: "Rebuild simulator").
- **Follows:** ANALYSIS-001.
- **Supersedes, for new artifacts:** the whole-row masking rule of
  EVAL_PROTOCOL §4.1 and the simulator's independent-emission model.

## Context
ANALYSIS-001 found the simulated patients internally consistent but not
realistic per disease, for these reasons:
- whole-row PMID masking gutted cohort rows (UMOD keeps 3 of 33);
- independent emission by HPOA frequency: real reporting is barely
  predicted (ρ 0.02–0.07) and rich profiles over-emit;
- weak evidence was taken at face value;
- OMIM and Orphanet profiles were picked at random;
- disease weights were wrong;
- symptoms never depended on age.

## Decision
The training repo builds four new artifacts; the simulator (v0.4) consumes
them. All of them use R1-train only, never dev, test or vault.

### 1. `hpoa-recount-v1`: masking by recounting, not dropping
- **Format:** a file with the same columns as `phenotype.hpoa`.
- **Rows citing no held-out PMID** stay unchanged.
- **A row citing a held-out PMID** (the `r1-v1.heldout-pmids.txt` list) is
  replaced by one row whose `frequency` is `n/m`, counted over **R1-train
  phenopackets of that disease**. The disease is matched by id (OMIM
  directly; ORPHA via exact validated alignments).
  - `n` = patients with the term or a descendant present;
  - `m` = patients with it present *or explicitly excluded*;
  - `reference = R1-TRAIN:r1-v1`, `evidence = PCS`.

  If `m < 3`, the row is dropped.
- **Manifest counts:** rows kept, recounted and dropped, per disease.
- **Leakage:** held-out publications contribute nothing. R1-train
  contributes by design (EVAL_PROTOCOL §4.3). The protocol's §4.1 is
  amended to "drop or recount from R1-train".

### 2. `genes-v2`: disease weights
- **Schema:** as `genes-v1`, plus per entity `r1_train_patients` (count of
  R1-train patients diagnosed with any id of the entity).
- **Weight:** `weight_raw = validity × sqrt(1 + clinvar_plp_alleles +
  r1_train_patients)`.
- **Weight 0, with the reason recorded:**
  - somatic-only entities (e.g. OMIM:607785 JMML);
  - links with none of: ClinVar P/LP alleles, an Orphanet product-6
    association, a ClinGen curation, an R1-train patient (e.g. TBX5 → LQT1).
- **Recalibrated** with `dxt genes calibrate` (R1-train).
- **Profiles:** built from `hpoa-recount-v1`, so entities whose rows were
  masked away keep their profiles where recounts exist.

### 3. `report-model-v1`: how clinicians report
- **Fitted on R1-train**, against a KB masking every R1 publication, as in
  ANALYSIS-001 §3.2.
- **Contents (JSON):**
  - feature definitions and coefficients: frequency, information content,
    ancestor count, log reportability, cardinal flag;
  - the reportability table (term → R1-train patient count, ancestor
    closure);
  - the term-budget distribution: histogram of reported present terms per
    R1-train case.

### 4. `cardinal-v1`: hallmark features
- **Format:** TSV `disease_id, hpo_id, kind, source`.
- **Kinds:**
  - `diagnostic_criterion` and `pathognomonic`, from Orphadata product 4
    `DiagnosticCriteria` (a new pinned source, CC-BY-4.0);
  - `cardinal_proxy`, for count-based rows with `m ≥ 10` and frequency
    ≥ 0.8 in `hpoa-recount-v1`.
- GeneReviews is **not** used until its reuse terms are cleared
  (`docs/TODO.md`).

### Simulator v0.4 (rare-disease-simulator)
1. **One merged profile per entity** (the `genes-v1/v2` entity =
   exactly-equivalent OMIM and ORPHA ids), replacing the random pick.
   - Term set: the union.
   - Frequency precedence: count-based (pooled) > percentages > categories.
   - An Orphanet category is capped at the count-based estimate when both
     exist and disagree by > 0.3.
2. **Shrinkage** of count-based frequencies toward a Beta prior: mean =
   the median count-based frequency in `hpoa-recount-v1`, strength = 2
   pseudo-patients. This replaces Jeffreys for n/m. It is recorded as an
   amendment to ADR-0007 for simulator v0.4 onward.
3. **Truth, then reporting.**
   - Truth: the patient's true phenotype is sampled as now (frequencies,
     sex restriction, onset gating) and fills `true_present`.
   - Budget: the **reported** set draws a budget `k` from
     `report-model-v1`'s distribution.
   - Forced: true cardinal terms (`cardinal-v1`) are reported first.
   - The rest are picked without replacement from true terms, with
     probability ∝ the reporting model's score.
   - Noise per `simcal`.
4. **Age dependence** where the data exist (per-phenotype onset in HPOA
   rows, and phenopacket onset fields aggregated in `hpoa-recount-v1`).
   Otherwise unchanged.

### Standing realism check (`dxt sim realism`, training repo)
- **Metrics** for a simulated export:
  - (a) the ANALYSIS-001 metrics against R1-dev **in aggregate**: mean
    per-gene ρ over genes with ≥ 10 dev patients, the terms-per-case
    distribution, the frequency-vs-reporting calibration;
  - (b) a **literature panel**: emission of the cardinal features of the
    10 ANALYSIS-001 diseases vs their literature prevalence
    (`data/realism/literature-panel-v1.tsv`, with a citation per row).
- **Anti-overfitting:** R1-dev is used here as a *check*.
  - At most 3 simulator versions may be compared on it before a version
    is frozen, and every comparison is logged.
  - All simulator parameters stay fitted on R1-train.
  - The sealed tests remain the arbiter for any model trained on the
    frozen version.

## Consequences
- New artifacts: `hpoa-recount-v1`, `genes-v2`, `report-model-v1`,
  `cardinal-v1`, `literature-panel-v1`. Also a new pinned source (Orphadata
  product 4 2026-06) and simulator v0.4 datasets.
- Front A is re-run as **A-002f-v2 / A-003f-v2**, each pre-registered, on
  v0.4 data.
- Front B's KB can adopt `hpoa-recount-v1` later (a separate decision).
- S3 v1 stays frozen as it is: its data came from simulator v0.3, which
  slightly reduces the same-generator bias for v0.4-trained models.

## Amendment 1 (2026-09-30): settings for candidate 1

Fixed before any R1-dev realism number exists for a v0.4 candidate. They
follow from the artifacts built in PR #22.

1. **Shrinkage prior mean μ₀:** the median over count pairs pooled over
   at least 10 patients (it was the median over all pairs).
   - **Why:** 18% of HPOA count pairs are 1/1, mostly single case reports.
     A case report lists what its patient had, so these pairs are biased
     upward. The all-pairs median (0.667) would shrink a 1/1 to 0.78, above
     Jeffreys' 0.75, which is the opposite of the intent.
   - **Evidence the median stabilises:**

     | Pairs with m ≥ | Median |
     |---|---|
     | 1 | 0.667 |
     | 3 | 0.400 |
     | 5 | 0.364 |
     | 10 | 0.300 |
     | 20 | 0.323 |

   - **Rejected alternatives:**
     - An empirical-Bayes beta-binomial fit on all pairs gave μ₀ 0.59; it
       has the same bias.
     - A fit that corrects for HPOA rarely listing unobserved features
       (zero-truncated) degenerated to α → 0.
   - **Strength:** stays at 2. With μ₀ = 0.30, 1/1 → 0.53, 2/2 → 0.65 and
     10/10 → 0.88.
2. **Cardinal terms are not forced** (`reporting.force_cardinal: false`).
   - `report-model-v2` already carries a `cardinal_flag` coefficient
     (+0.447), fitted on R1-train reporting without forcing. Forcing on top
     would count that effect twice.
   - Orphadata product 4 lists up to 34 criteria for some diseases (Marfan
     ORPHA:558), and forcing reports every true one beyond the budget.
   - Cardinal terms still enter the reporting score. G2a and the G3 cards
     check whether they end up under-emitted.
3. **One calibration file:** `simcal-v04-v2` = `simcal-train-v1`'s knobs
   (negatives, noise, missingness; R1-train only) + μ₀ from rule 1 +
   `reporting.force_cardinal: false`.
   - `presets.medium.noise_mean` stays at 3.7. That is R1-train's mean
     count of present terms per case not explained by the knowledge base,
     and noise now takes budget slots.
   - `positive_observation_rate` only acts in observation mode, so it is
     inert here.
4. **The candidate dataset is the Front A training shape** (half A of
   `annot-split-v1`, 100 cases per gene, seed 1001), the same shape as the
   V03 baseline, so G2 compares like with like.
5. **Coverage loss is accepted and recorded.** 159 v3.0-vocabulary genes
   have no simulable entity under `genes-v2`, because all their links lack
   supporting evidence. With the frozen base (ADR-0010), those genes keep
   v3.0's behaviour; Front A's new parameters just see no positives for
   them.

## Amendment 2 (2026-09-30): candidate 1 settings, revised before any R1-dev read

The first full candidate run (simulator 0.4.0) failed G1: 622 cases had a
`reported_count_mismatch`, caused by a simulator bug. So `dxt sim realism`
never ran, and nothing was read from R1-dev. The run's R1-train-only
diagnostics also showed that noise was drawn independently of each
record's budget: Poisson(3.7) noise slots out of a mean budget of 8.7.
- **Effect:** 41.6% of cases showed exactly one profile term, and small
  records were inflated. Cases with at most 2 terms were 2.6% of the
  candidate vs 11.0% of R1-train; p10 was 4 vs 2.
- **Changes** (the candidate keeps the name "candidate 1" and still uses
  R1-dev read 1 of 3):
  1. **Simulator 0.4.1** (rare-disease-simulator PR #6) fixes the bug. A
     picked term already shown through a generalized child now leaves its
     slot to another true term.
  2. **Noise scales with the record** (`reporting.noise_count:
     budget_share`). Each of the k budget slots is noise with probability
     0.4625, at most k − 1.
     - 0.4625 is R1-train's pooled share of present terms not explained by
       the knowledge base (kb-v4), from `calib-v1` →
       `unexplained_present_share`.
     - That is the same measurement that set `noise_mean` 3.7, so the
       average noise per case barely changes. What changes is its
       dependence on record size.
  3. **Calibration file** `simcal-v04-v3` = `simcal-v04-v2` + rule 2.
- **Ledger:** realism runs pass `--sim-version <version>-candN` so the
  3-candidate budget counts correctly.

## Amendment 3 (2026-09-30): candidate 2 design (R1-dev read 2 of 3)

Based on ANALYSIS-002 (R1-train only). Fixed before any candidate 2
number exists.

1. **Specialisation of reported terms** (simulator
   `reporting.specialize_rate`).
   - **Rule:** a reported profile term that was not generalized is
     replaced, with probability r, by one of its descendants: a uniformly
     chosen child; then, with probability 0.5, one of that child's
     children.
   - **Constraints:** the descendant must be a phenotypic abnormality,
     allowed for the patient's sex, and not already shown.
   - **Truth:** the patient truly has the reported descendant, so it
     joins `true_present`.
   - **Target:** R1-train's more-specific share, 0.115 of present terms.
2. **Disease-related noise** (simulator `noise.related_share`).
   - **Rule:** a share s of the noise slots is drawn near the disease
     rather than from the vocabulary. Take a uniformly chosen true term,
     go up to its parent (or, with probability 0.5, its grandparent), and
     pick a uniformly chosen descendant of that ancestor, at most 2 levels
     down.
   - **Exclusions:** the pick must not be one of the profile's terms, a
     present term or a negative, and must be allowed for the patient's
     sex. With no eligible term, the slot falls back to vocabulary noise.
   - **Target:** R1-train's related share, 0.108 of present terms
     (shared-ancestor IC ≥ 2).
3. **Noise share 0.348:** R1-train's truly unexplained share, which
   excludes more-specific terms. It was 0.4625, which counted them.
4. **Setting r and s by pilot rounds on R1-train targets only.**
   - At most 2 declared pilot rounds, on the same 505-gene subset as the
     simcal-train-v1 pilots (seed 91001), using full profiles.
   - **Starting values:** r = 0.15, s = 0.30.
   - **Targets:** the ANALYSIS-002 term categories on R1-train, i.e.
     more-specific 0.115; related (IC ≥ 2) 0.108; weakly related or
     unrelated 0.239.
   - **Selection:** the pair minimising the summed absolute error is
     frozen into `simcal-v04-v4`. Every tried pair is logged. No R1-dev,
     no E0.
5. **Scoring:** G2 scores the full-profile run
   (`ds-sim0.4.2-full-n100-s1001`), per ADR-0012 amendment 1. The Front A
   training set (`ds-sim0.4.2-A-n100-s1001`) is generated with the same
   settings and must pass G1.

## Amendment 4 (2026-09-30): candidate 3 design (R1-dev read 3 of 3, the last)

Based on ANALYSIS-003 (R1-train only). Fixed before any candidate 3
number exists.

1. **Reference population for noise.** R1-train patients whose
   publication the pinned HPOA does not cite, measured against `kb-v3`,
   which has the same knowledge as the simulator's profiles.
   - **New artifact `calib-v2`:** targets plus noise vocabulary from those
     patients, with the same rules as calib-v1 (vocabulary terms seen in at
     least 2 patients; the vocabulary size is reported).
   - Missingness and negation knobs stay those of simcal-train-v1.
2. **Noise share:** calib-v2's unexplained share (≈ 0.24). The vocabulary
   noise comes from calib-v2's vocabulary.
3. **Pilots** (at most 2 rounds, same pilot genes and rules as
   amendment 3) set r and s against calib-v2's categories:
   - more specific ≈ 0.093;
   - related ≈ 0.082;
   - weakly related or unrelated ≈ 0.157.

   Categories are measured against kb-v3. The result is frozen as
   `simcal-v04-v5`.
4. **Simulator 0.4.2 is unchanged;** only calibration changes.
5. **Go/no-go before the last R1-dev read.**
   - On the full candidate 3 dataset, run `dxt sim realism --no-dev`
     (G2a on the truth layer, G2c, G2d, G2e).
   - If any of them fails its gate threshold, **do not spend the last
     R1-dev read**. Stop, report, and design again.
   - These metrics compare with R1-train, so they may be measured more
     than once; every measurement is logged. G2b (R1-dev), G3 (cards) and
     G4 (the literature panel) remain the checks nothing was fitted to.

## Amendment 5 (2026-09-30): candidate 4 design (R1-dev read 3 of 3, still unspent)

Based on ANALYSIS-003, ANALYSIS-004 and the construction-side card audit
(ANALYSIS-004 §3). Fixed before any candidate 4 number exists.

1. **Simulator 0.5.0** (rare-disease-simulator PR #8, 020e41d).
   - `reporting.mode: independent`: each true term is reported with
     probability `min(1, π/f)`.
   - `reporting.noise_count: proportional`.
   - `age.duration_mean_by_onset`.
2. **`report-model-v3`:** the report-model-v2 procedure refit on uncited
   R1-train patients against kb-v3, in the same strict format. Report its
   in-sample fit, and its within-gene ρ on R1-train with each
   publication left out. No R1-dev.
3. **Noise:**
   - ρ = 0.207;
   - vocabulary from calib-v2;
   - the related share s comes from at most 2 pilot rounds, targeting an
     E0 MRR on noise-only terms of 0.026 (the ANALYSIS-004 component
     target);
   - the specialisation rate r comes from the same pilots, targeting
     calib-v2's more-specific share of 0.093.
4. **Age:** `age.duration_mean_by_onset` = the mean of (age − onset) over
   R1-train patients with both fields, per onset category, using the
   simulator's category windows. Categories with fewer than 20 patients
   use the overall mean.
5. **Go/no-go:** as in amendment 4 (G2a on the truth layer, G2c, G2d,
   G2e, G2b-train as stop conditions; age reported).
   - Only if all pass is the last R1-dev read spent.
   - If candidate 4 also stops, v0.4/0.5 is **not** frozen: the gate's
     result is recorded as unmet, and Mateo decides how to proceed.
6. **Run hygiene:** runs use a dedicated simulator worktree or tarball
   pinned at the release commit, never the shared checkout.

## Amendment 6 (2026-10-01): candidate 5 design (train-side only)

Mateo's 2026-10-01 decision allows up to two more reporting/noise
candidates, checked on R1-train only. Fixed before any candidate 5 number
exists.

1. **Simulator 0.5.1** (rare-disease-simulator PR #9, 09e5802), run from
   the GitHub tarball of that commit.
   - `reporting.q_scale`: independent mode reports each true term with
     `q = min(1, q_scale · π / f)`.
   - `noise.related_up_levels` 1 and `noise.related_down_levels` 1: related
     noise is a child of a true term's parent (a sibling), not up to two
     levels up and two down. Candidate 4's noise (87% related) had mean IC
     6.78, against 4.14 for R1-train's present terms.
   - No presentation ages (they come with candidate 6).
2. **Base calibration:** `simcal-v05-v2` (independent reporting,
   report-model-v3, proportional noise ρ 0.207, calib-v2 vocabulary, age
   durations by onset).
3. **Three knobs, set by at most 3 pilot rounds on R1-train targets only:**
   - `reporting.q_scale`: mean reported terms per case that kb-v3
     explains = the uncited R1-train value against kb-v3;
   - `noise.related_share`: E0 in-vocab MRR on noise-only terms = 0.026
     (ANALYSIS-004);
   - `reporting.specialize_rate`: more-specific share = 0.093 (calib-v2).

   The rules are in the BITACORA pre-registration entry. The winner is
   frozen as `simcal-v051-v1`.
4. **Dataset:** the full-profile run only (`ds-sim0.5.1-full-n100-s1001`);
   disk does not allow the half-A run as well.
5. **Go/no-go:** as in amendment 5 (G2a truth layer, G2c, G2d, G2e,
   G2b-train; age reported), with `dxt sim realism --no-dev`. **No R1-dev
   read in this round, whatever the result.** The last R1-dev read goes to
   the better of candidates 5 and 6, when Mateo decides.
