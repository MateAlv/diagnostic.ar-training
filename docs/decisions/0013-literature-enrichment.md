# ADR-0013: Enrich construction profiles from the literature (GeneReviews, open-access cohorts)

- **Status:** Accepted, 2026-10-01 (Mateo). Written before any extraction.
- **Context:**
  - The ADR-0012 gate was unmet after 4 candidates.
  - The construction-side audit (ANALYSIS-004 §4) found features missing
    from the truth layer in 11 of 26 diseases, over-produced in 5, and wrong
    ages in 4.
  - SOURCES-SCOPING-001: 52k OMIM rows have no frequency, 2,571 of 4,776
    simulable construction genes have weak profiles, and GeneReviews covers
    1,289 construction genes.
- **Time box:** together with two more reporting/noise candidates, about one
  week (to 2026-10-08).

## Scope
- **Construction units only.** Excluded:
  - all 120 units of `litpanel-split-v3`, whether gene or disease;
  - every disease id shared with one of them.
- **Sources:**
  - **GeneReviews** (NCBI litarch bulk archive): noncommercial research use.
    Written confirmation is pending (Mateo is emailing); the work doesn't
    wait for it.
  - **Europe PMC open-access cohort papers:** CC BY, CC0, CC BY-NC,
    CC BY-NC-SA and CC BY-NC-ND. Papers with no stated licence are excluded.
- **Not used:** GeneCards (its terms forbid AI training), OMIM (not
  automated), and more Orphanet (already in the profiles).

## Exclusion rules
1. **Held-out patients.** A GeneReviews chapter that cites **any** R1
   held-out PMID (`data/splits/r1-v1.heldout-pmids.txt`) is dropped
   entirely. Its pooled tables can't be masked row by row. An OA paper that
   is itself an R1 held-out PMID is dropped.
2. **Evaluation units.** A chapter that mentions any evaluation unit's gene
   or disease, including overview chapters (RP, Leigh, hearing loss, PCD,
   CMT), is dropped.
3. **No double counting.** A literature row whose source PMIDs are already
   cited by an HPOA row for the same disease and term is dropped; HPOA
   already counts those patients.
4. **What is used.** Facts only: feature, prevalence, n/m, age. Each fact
   carries a citation and a verbatim quote of at most 25 words. No text is
   redistributed, and this holds for no-derivatives licences too. The
   extracted data stays in this private repo; it is not a public release
   asset.

## Extraction
- **Schema:** the same as literature-panel-v2. Feature label, HPO id (valid
  in the pinned HPO), prevalence (point estimate and range), n_affected /
  n_assessed, sex restriction, population, age at onset, age at diagnosis
  or presentation, citation (NBK id plus section/table, or PMID/PMCID),
  evidence quote, licence. Only stated numbers are extracted; nothing is
  inferred.
- **Freezing:** the list of usable chapters and papers (`lit-sources-v1`)
  is frozen, hashed and committed **before** extraction. Shards are
  assigned from that list.
- **Verification:** a seeded 10% sample is re-extracted blind by Codex.
  Agreement must be at least 90%, and every disagreement is resolved by
  re-reading the source and logged.

## Integration
- **Frequencies:** literature counts become count-notation rows in a new
  HPOA-format layer (`hpoa-lit-v1`). Together with `hpoa-recount-v1` they
  give `hpoa-enriched-v1`. The simulator's existing precedence applies:
  counts pool by summing n/m, and counts beat percentages beat categories.
  Literature rows may add features that HPOA lacks.
- **Age:** age at diagnosis or presentation per disease goes into a
  side file that simulator 0.5.1 can read (presentation ages). Onset is
  unchanged.
- **Artifacts:** each gets a manifest:
  - `lit-sources-v1` (the frozen list);
  - `lit-extract-v1` (the raw rows plus the cross-check);
  - `hpoa-lit-v1`;
  - `hpoa-enriched-v1`;
  - `presentation-ages-v1`.

## Evaluation
Nothing changes in the gate:
- G4 (literature-panel-v2) stays independent, because its units are
  excluded by rule 2;
- G2 and G3 apply as before;
- the last R1-dev read goes only to a candidate that passes the train-side
  go/no-go (ADR-0011 amendment 4 §5).

## Amendment 1 (2026-10-01): verified sources only
Mateo: "the actual verified sources around this only, like humanly
curated, … or important papers around big investigations". Written before
any acquisition or extraction. It replaces the open-ended OA cohort scope
above.

- **Tier 1: human-curated knowledge bases.** Each is registered in
  `data/sources.yaml` as a pinned snapshot, with its licence checked and
  recorded.
  - **GeneReviews:** expert-authored, peer-reviewed chapters.
  - **MedlinePlus Genetics:** NLM editorial review; public domain.
  - **Gene2Phenotype (EBI G2P):** curated gene–disease–phenotype records
    with HPO terms.
  - **Genomics England PanelApp:** expert-reviewed gene–disease panels.
  - Already in use: HPOA (HPO biocuration), Orphanet / Orphadata, ClinGen,
    MONDO.
  - Any other candidate is used only if it is human-curated, has a
    reuse-compatible licence, and is recorded here first.
- **Tier 2: major studies only.** Peer-reviewed cohort, registry or
  natural-history studies with **at least 20 genetically confirmed
  patients**. Preferably the paper is **cited by a usable GeneReviews
  chapter**, i.e. selected by expert curators. Otherwise it must be found by
  a recorded Europe PMC query.
  - Licences: CC BY, CC0, CC BY-NC, CC BY-NC-SA, CC BY-NC-ND, used as facts
    plus citations only.
  - Excluded: case reports, small series (under 20 patients), preprints,
    and studies that are R1 held-out publications.
- **The exclusion rules above apply unchanged.** No held-out-citing
  chapters, no evaluation units, no double counting with HPOA.
- **DDD caveat.** DDG2P (G2P's developmental-disorders panel) was curated
  partly from the DDD study, and DDD is a sealed eval cohort used only as a
  no-regression check. G2P rows are allowed as knowledge (like HPOA), but
  the DDD no-regression result must disclose that G2P contributed.

## Amendment 2 (2026-10-01): integration rules, fixed before any enriched profile is built
These rules turn `data/lit-extract/rows/*.tsv` into `hpoa-lit-v1` (an HPOA-
format layer), `hpoa-enriched-v1` (`hpoa-recount-v1` + `hpoa-lit-v1`) and
`presentation-ages-v1`. They are written before any enriched profile or
gate number exists.

1. **Feature rows → HPOA phenotype rows** (aspect P) on the unit's disease
   id. The reference is the row's `source_id`: `PMID:…`, or `NBK…` for
   GeneReviews.
   - With `n_affected`/`n_assessed` → count notation `n/m`.
   - With a prevalence only → percentage notation (`X%`). Its precedence is
     below counts, by the simulator's existing rule (counts > percentages >
     categories).
   - `prevalence 0` with counts → `0/m`. With no counts → the row is
     recorded as an excluded (NOT) annotation only when the source states an
     explicit absence (guide v4 §6a).
2. **`pooled_group` rows** (one figure for several units' diseases) → a
   **percentage** row on every listed unit's disease. Never counts, so the
   same patients are not counted once per unit. Skipped for a unit that
   already has a unit-specific row from the same source for the same term.
3. **`pooled` rows** (a disease-level figure placed on one unit) → kept on
   that unit's disease id only.
4. **`small_n`, `binned`, `lower_bound`** → kept. `binned` and
   `lower_bound` use the stated point estimate; the simulator's shrinkage
   tempers small denominators.
5. **No double counting with HPOA.** A literature row whose `source_pmids`
   are already cited by an HPOA row for the same disease and term is dropped
   (ADR-0013 rule 3). GeneReviews chapters synthesise literature that HPOA
   may also cite; overlap at the patient level cannot be detected, so it is
   declared as a residual dependency.
6. **Several literature rows for the same disease and term** → count rows
   pool by summing n/m (distinct sources only). For percentage rows, the
   one with the largest stated population is kept.
7. **Ages → `presentation-ages-v1`** (disease_id, age_low_years,
   age_high_years, source), from `AGE_PRESENTATION` rows only:
   - one row per disease;
   - prefer a GeneReviews row, then the row with the largest population;
   - a single-value age is widened to ±10% (at least ±1 year), so a case
     doesn't get one exact age.

   `AGE_ONSET` rows are not used for presentation ages; onset stays with
   Orphadata. Their coverage is reported, as a possible later use.
8. **Never used:** rows for evaluation units (the validator already blocks
   them) and any row failing `validate-shard`.
9. **Every artifact gets a manifest** listing the shard files and their
   sha256. A dropped row is counted by reason.
