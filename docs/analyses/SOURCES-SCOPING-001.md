# SOURCES-SCOPING-001: would better sources improve the simulator's disease profiles?

- **Date:** 2026-09-30.
- **Scope:** counts only. Nothing was extracted into a profile, and no
  artifact was built.
- **Question:** can primary literature (GeneReviews, open-access cohort
  papers) fill the gaps in the profiles, which today come only from HPOA
  2026-02-16 and Orphadata? If so, which sources, in which order, and at
  what cost?
- **Raw counts:** `results/analyses/SOURCES-SCOPING-001/`. `summary.json`
  holds every number quoted here, and `sources.json` records the URLs and
  sha256 of the external files.
- **Scripts:** `scripts/analysis/sources_scoping.py` (per gene),
  `sources_scoping_gr_sample.py` (30 chapters), `sources_scoping_epmc.py`
  (Europe PMC) and `sources_scoping_summary.py`.
- **No sealed data was read.** The R1 held-out PMID list was used only as a
  mask. Patient counts come from `genes-v2`, which is R1-train only.

## 0. Units and boundaries

| | Genes |
|---|---|
| v3.0 vocabulary (`genes.json`: 5,229 entries, of which one is the `-` padding token) | 5,228 |
| **Evaluation genes** (`litpanel-split-v3`, all 120 units: genes and every disease id) | 120 |
| **Construction genes** | 5,108 |
| ... with a simulable entity in `genes-v2` (the population for §3–§5) | 4,776 |
| ... whose main disease id is also an evaluation unit's disease id | 204 |

- **Main disease:** the simulable `genes-v2` entity with the highest
  `sim_weight`, as in `litpanel-split-v3`. Its profile is the union of the
  `hpoa-recount-v1` rows of its `profile_ids`, which is the file the
  simulator reads.
- **The 204 construction genes that share a main disease id with an
  evaluation unit** are mostly generic OMIM ids that HPOA gives to many genes:
  - OMIM:268000 (RP), 51 genes;
  - OMIM:244400 (PCD), 34;
  - DBA, 20;
  - ALS, 18;
  - and others: FA, Noonan, MELAS, PAH.

  Under the rule that an evaluation unit's disease ids never feed
  construction, these genes cannot be enriched at the disease level.

## 1. GeneReviews

**Source:** NCBI litarch bulk archive `gene_NBK1116.tar.gz`, plus the
GeneReviews FTP index files (fetched 2026-09-30).

- **Archive:**
  - 639 MB compressed;
  - 1,015 NXML files (201 MB), 1,100 PDFs (680 MB) and 814 images;
  - the index maps 882 chapters to genes, and 892 chapters have a title.
- **What was read:** only the archive listing and the 30 sampled chapters.
  The copy used is the one downloaded for LITPANEL-v2. Its sha256 was
  re-checked, and a HEAD request shows the same size and Last-Modified.

### 1.1 Coverage

| | Construction (5,108) | Evaluation (120) |
|---|---|---|
| Gene named in any chapter | 1,772 (34.7%) | 68 (56.7%) |
| ... in a chapter with ≤ 10 genes | 1,126 | 38 |
| ... in a chapter that lists the main disease's OMIM id | 1,291 | 54 |
| **Usable chapter** (touches no evaluation gene or disease id) | **1,289 (25.2%)** | 0 by definition |
| Named only in chapters that touch an evaluation unit | 483 | 68 |
| ... all of them overviews with > 10 genes | 426 | 30 |

- **78 of the 882 chapters touch an evaluation unit.** The worst are
  overviews:
  - Nonsyndromic RP overview (80 genes);
  - Nuclear Leigh overview (78);
  - Genetic hearing loss overview (64);
  - PCD (58);
  - CMT (36).
- **426 construction genes are blocked only by such overviews.** A
  per-gene rule could release them: use an overview's rows only for the
  construction gene's own disease, and never pooled rows. That is a
  decision for Mateo (§7). All counts below use the strict rule.
- **Simulable construction genes with a usable chapter:** 1,279 of 4,776
  (26.8%). They are spread over 794 distinct chapters.

### 1.2 What a chapter contains (sample of 30)

- **Frame:** the 794 usable chapters. Simple random sample, seed 20260930
  (`gr_sample30.frame.json`).
- **Method:** a script screened each chapter (`gr_sample30.auto.tsv`), and
  I read the flagged tables and sentences to give the verdicts
  (`gr_sample30.verdicts.tsv`).
- **Rules:** the same as LITPANEL-v2. Only stated numbers count, and vague
  quantifiers ("up to", "most") do not.

| In the chapter | Chapters | Rate (95% CI) |
|---|---|---|
| A feature-frequency table with numbers ("Frequency of Select Features", n/N or %) | 17 | 0.57 (0.39–0.73) |
| ≥ 5 features with stated numbers (the panel's inclusion bar) | 19 | 0.63 (0.46–0.78) |
| Either of the two | 20 | 0.67 (0.49–0.81) |
| Age at onset, presentation or diagnosis stated numerically (cohort figure, not a single case) | 14 | 0.47 (0.30–0.64) |
| Only a qualitative age ("at birth", "in infancy") | 7 | 0.23 (0.12–0.41) |
| No age statement found | 9 | 0.30 |
| Cites ≥ 1 R1 held-out PMID | 4 | 0.13 (0.05–0.30) |

- **Numeric table rows:** median 11 per table chapter (range 0–23).
- **Size:** the mean chapter is 168 KB of NXML, with 35 cited PMIDs.
- **Held-out citations:** 13 of the 1,048 PMIDs cited by the sample are R1
  held-out publications.
  - White-Sutton cites 10: its n/76 frequency table pools R1 held-out
    patients.
  - A chapter's table can therefore carry held-out patients even though
    HPOA-style row masking would never see it (§7).
- **Typical small denominators:** n/6 (MBTPS1), n/11 (NOTCH3 LMS) and n/14
  (SPTBN4). GeneReviews aggregates, but for ultra-rare genes the aggregate
  is the whole published world.

## 2. Europe PMC open-access cohort papers

- **Sample:** 200 simulable construction genes, drawn with seed 20260930
  from 4 strata of 50 each: usable GeneReviews chapter (yes/no) × weak
  profile (yes/no, §3). All 120 evaluation genes were also queried and are
  reported separately.
- **What was fetched:** search metadata only. No full text.
- **Queries,** all with `OPEN_ACCESS:y`:
  - `broad`: the symbol anywhere AND (cohort OR "case series" OR "clinical
    spectrum" OR "phenotypic spectrum") anywhere. This is the suggested
    pattern.
  - `ta`: the symbol and the keywords in the title or abstract.
  - `title`: the symbol in the **title**, and the keywords in the title or
    abstract. This is the estimate used below.

| Hits per gene, stratum-weighted to the 4,776 simulable construction genes | 0 | 1–4 | 5+ |
|---|---|---|---|
| `broad` | 0% | 0% | 100% (median 235–517 hits: the symbol appears in gene panels and supplements) |
| `ta` | 7.4% | 38.7% | 53.9% |
| **`title`** | **35.7%** | **48.8%** | **15.5%** |
| Evaluation genes, `title` (n = 120, unweighted) | 25.0% | 55.0% | 20.0% |

| `title`, per stratum (n = 50 each) | 0 | 1–4 | 5+ | Median |
|---|---|---|---|---|
| GeneReviews chapter, profile ok | 11 | 22 | 17 | 2 |
| GeneReviews chapter, weak profile | 13 | 21 | 16 | 2 |
| No chapter, profile ok | 20 | 26 | 4 | 1 |
| No chapter, weak profile | 20 | 25 | 5 | 1 |

- **Precision** (`epmc_precision.tsv`). Among 40 random sampled genes with
  ≥ 1 `title` hit, I read up to 6 titles each. 22 (0.55, CI 0.40–0.69)
  have at least one real phenotype series of the gene's Mendelian disease.
  - The misses are symbol collisions (APP, CAT, SET, ADA, TAT, APOB) and
    association, cancer-marker or susceptibility studies (PTPN22, VPS13C).
  - The 5+ bin is dominated by the collisions.
- **Estimate:** about **35% (26–45%)** of simulable construction genes, or
  about 1,700, have at least one open-access phenotype series. Most have
  1–4 such papers.
  - GeneReviews chapters themselves appear among the hits (INSR, SERAC1).
  - Genes that already have a GeneReviews chapter are also the ones with
    more papers.
- **Licences of the retrieved `title` hits** (1,103 records, 1,066 PMIDs):

  | Licence | Records | Share |
  |---|---|---|
  | CC BY | 714 | 64.7% |
  | CC BY-NC-ND | 211 | 19.1% |
  | CC BY-NC | 139 | 12.6% |
  | none stated | 21 | 1.9% |
  | CC0 | 9 | 0.8% |
  | CC BY-NC-SA | 8 | 0.7% |
  | CC BY-ND | 1 | 0.1% |

  CC BY and CC0 are clearly compatible: 65.5%. The NC variants suit a
  noncommercial academic tool. ND licences forbid derivatives: extracted
  facts are arguably not derivatives, but that is a judgement (§7).
- **Masks:**
  - 3 of the 1,066 construction PMIDs are R1 held-out (0.3%) and would be
    excluded;
  - 6 are already cited in `phenotype.hpoa` (0.6%), so they add nothing new;
  - none is a literature-panel source.
  - The evaluation genes' hits include 10 panel sources and 6 held-out
    PMIDs, as expected.

## 3. Where current profiles are weakest (per construction gene, main disease)

**Tiers**, exclusive, applied in this order. Thresholds were set before
looking at the crosses.
- **W1:** no n/m row, and ≥ 50% of the terms have no frequency;
- **W2:** no n/m row, and the profile is Orphanet-only (frequency bins
  only);
- **W3:** no n/m row, otherwise;
- **W4:** n/m rows exist, but only from series of < 5 patients (maximum
  denominator < 5);
- **ok:** at least one n/m row with m ≥ 5.

| Tier (4,776 simulable construction genes) | Genes | Usable GeneReviews chapter | ... that lists the main disease | Main disease is an evaluation disease |
|---|---|---|---|---|
| W1 mostly no frequency | 440 | 78 | 58 | 8 |
| W2 Orphanet bins only | 314 | 103 | 1 (no OMIM id to match) | 3 |
| W3 no counts, other | 405 | 164 | 136 | 41 |
| W4 counts from < 5 patients only | 1,412 | 261 | 206 | 34 |
| ok | 2,205 | 673 | 571 | 118 |
| **Weak (W1–W4)** | **2,571 (53.8%)** | **606 (23.6%)** | | |

Other profile facts:
- 3,617 genes (75.7%) have some n/m row;
- the median share of terms without frequency is 0.11;
- 332 construction genes have no simulable entity at all, and are out of
  scope.
- **Evaluation genes, separately:** ok 66, W4 21, W1 13, W3 12, W2 4, no
  profile 4.

**Crossed with §1 and §2:**
- **Weak genes with a usable chapter:** 606. At the sample's rate (0.63),
  about **384 (276–473)** would get ≥ 5 literature-stated frequencies.
- **Weak genes without a chapter:** 1,965.
  - `title` hits: 40% have 0, 50% have 1–4, and 10% have 5+.
  - After precision, about **650** have ≥ 1 real open-access phenotype
    series.
  - At LITPANEL-v2's survival rate (56 of 120 units reached ≥ 5 stated
    numbers), about **300** would yield a usable profile. That rate came
    from units that could also use GeneReviews, so for this group it is
    optimistic.
- **Together:** about 700 of 2,571 weak genes (≈ 27%) could be reached. The
  rest have no stated numbers anywhere reachable, consistent with the
  panel's main lesson.
- **The tiers miss the audit's problems.**
  - The 26 ANALYSIS-004 §4 audit genes, all with ≥ 10 R1-train patients,
    are almost all "ok" (22 ok, 2 W4, 1 W1, 1 W2). Yet 25 of 26 cards were
    implausible, and 11 miss a real feature.
  - So count-based HPOA rows do not guarantee a plausible truth layer.
  - Of those 26 genes, 13 have a usable GeneReviews chapter. SMAD3 is
    blocked by the thoracic-aortic overview.

## 4. Age

| Simulable construction genes (4,776) | Usable chapter | No chapter | Total |
|---|---|---|---|
| Onset from HPOA and Orphadata | 564 | 978 | 1,542 |
| HPOA onset only | 278 | 1,348 | 1,626 |
| Orphadata onset only | 293 | 672 | 965 |
| No onset at all | 144 | 499 | 643 |

- **Orphadata** gives onset for 2,507 genes (52.5%), as classes (antenatal
  … elderly).
- **GeneReviews numeric age:** 1,279 genes have a usable chapter. At 0.47,
  about **597 (387–817)** would get a numeric age at onset, presentation or
  diagnosis, plus about 300 more with a qualitative one. This includes:
  - about 137 of the 965 genes that have Orphadata classes only;
  - about 67 of the 643 that have no onset at all.
- **What GeneReviews adds over Orphadata:** feature-level onset ages (e.g.
  CTX movement disorder 40 ± 12 years; pEDS periodontitis median 14 years;
  VHL retinal hemangioblastoma about 25 years), not just a disease class.
  This is what the "age wrong" audit finding (4 of 26 cards) needs.

## 5. Effort (LLM extraction, Claude plus a 10% Codex cross-check)

**Throughput of LITPANEL-v2** (batch files' start and end times,
BITACORA 2026-09-30):
- 17 batches, 120 units attempted, 549 raw rows;
- 339 agent-minutes in about 55 minutes of wall time (up to 8 in parallel);
- that is 97 raw rows per agent-hour, or 2.8 agent-minutes per unit
  attempted;
- Codex cross-check: 54 rows in about 9 minutes.
- **Realised yield:** 164 rows from 23 GeneReviews chapters (7.1 per
  chapter); 367 rows from 68 papers (5.4 per paper, 8.5 per paper-sourced
  unit).

| Scenario | Units | Rows | Agent-hours | Wall-hours at 8 parallel | Cross-check hours |
|---|---|---|---|---|---|
| A. GeneReviews, chapters of weak genes (396 usable; about 251 with ≥ 5 numbers) | 251 | ≈ 1,790 | 18 | 2.3 | 0.5 |
| B. GeneReviews, all usable chapters (794; about 503 with ≥ 5 numbers) | 503 | ≈ 3,590 | 37 | 4.6 | 1.0 |
| C. Open-access papers, weak genes without a chapter (about 648 candidates, about 302 kept) | 648 attempted | ≈ 2,580 | 31 | 3.8 | 0.7 |

- **What the estimates leave out:**
  - the lead reviewer's pass (in the panel it removed 10 more rows);
  - HPO mapping disputes;
  - Europe PMC 503 outages.
- **Where they may be off:**
  - GeneReviews should run faster than the panel: the chapter is known and
    local, with no search.
  - Papers will run slower: search, closed-access dead ends, and small
    tables.
- **A realistic total,** with review: **A in one working day, A + B in
  two, C in two to three more.**

## 6. Recommendation

1. **GeneReviews first, for weak construction genes (scenario A), then
   every usable chapter (B).**
   - It gives 1,279 genes a usable chapter.
   - About 63% of chapters state ≥ 5 numeric feature frequencies, often
     in a ready-made table, and about 47% state a numeric onset or
     diagnosis age.
   - It is the one source that also addresses the age finding.
   - Expected gain: about 384 weak genes get literature frequencies (A),
     and about 800 genes in all (B). About 600 genes get a numeric age.
   - Blocked only by the pending written confirmation (TODO).
2. **Europe PMC open-access cohorts second,** for the weak genes that have
   no chapter (scenario C).
   - Use the title-restricted query, with a symbol-collision filter
     (HGNC symbols that are common words or markers) and a
     publication-type filter.
   - Expected gain: about 300 more genes.
   - Keep CC BY, CC0 and CC BY-NC(-SA), and decide on ND (about 19% of
     hits) before extracting.
3. **Do not expect a large gain from volume alone.**
   - About 1,890 weak genes (73%) have no reachable stated numbers.
   - Literature enrichment raises the quality of profiles for the genes
     that matter most clinically: the ones with a chapter or a cohort.
   - It does not fix the long tail.
   - For the realism gate, the audit shows that genes with ≥ 10 R1-train
     patients already have counts and are still implausible. There,
     GeneReviews should be used to check or correct the truth layer
     (missing or over-produced features, onset), not only to fill empty
     frequencies.
4. **Not recommended:** GeneCards (terms forbid AI training), OMIM
   clinical synopses (not automatable, and already in HPOA), and more
   Orphanet (already in HPOA and Orphadata).

## 7. Open risks

- **GeneReviews licence:** the confirmation is pending. If the answer is
  no, only Europe PMC remains, and the expected gain falls to about 300
  weak genes.
- **R1 held-out patients inside aggregates.** 13% of the sampled chapters
  cite held-out PMIDs, and a pooled table (White-Sutton: 10 held-out
  papers) cannot be row-masked.
  - Options: drop such chapters (about 13%), or keep only rows whose
    cited sources exclude held-out PMIDs.
  - Pre-register the rule before any extraction.
- **The evaluation boundary is wider than the 120 genes:**
  - 78 chapters touch an evaluation unit;
  - 483 construction genes are reachable only through them;
  - 204 construction genes share a main-disease id with an evaluation
    unit.

  Mateo decides whether an overview chapter may feed a construction
  gene's own rows (it would release up to 426 genes). The strict reading
  used here says no.
- **HPOA overlap:** GeneReviews tables pool papers that HPOA also cites.
  This is not independent evidence, and double counting in a
  pooled-frequency estimator must be avoided (weight or replace, don't
  add).
- **Small denominators:** many "tables" are n/6 to n/14. A shrinkage prior
  is still needed. Literature does not remove it.
- **Main-disease choice:** `genes-v2` quirks (e.g. generic OMIM ids for RP
  or PCD) decide which disease a chapter must match. W2 genes (Orphanet
  only) cannot be matched to chapters by OMIM id; this needs ORPHA↔OMIM
  alignment first.
- **Estimate precision:**
  - n = 30 chapters and 40 precision genes give wide CIs.
  - The verdicts were given by one reader (me), with no second rater.
  - The age screen may miss statements, so its rate is a lower bound.
- **Europe PMC outages** (503s) and closed-access cohorts (LITPANEL-v2 §6)
  will lower realised coverage below the search-based estimate.
