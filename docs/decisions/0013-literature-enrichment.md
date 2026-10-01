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
