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
