# LITPANEL-v2: the evaluation literature panel (ADR-0012 G4)

- **Date:** 2026-09-30.
- **Artifacts:**
  - `literature-panel-v2`: `data/realism/literature-panel-v2.tsv` plus
    `.summary.json`, manifest `data/manifests/literature-panel-v2.json`.
  - `litpanel-split-v3`: the evaluation/construction boundary.
  - Extraction records in `data/realism/extraction/`: `curated.tsv`,
    `dropped.tsv`, `access-log.tsv` and `crosscheck.tsv`.
- **Use:** evaluation only. It is never a fitting target and never feeds
  simulator profiles (ADR-0012). It is private: it carries short verbatim
  quotes of copyrighted sources and must not be published as a release
  asset.

## 1. Result

| G4 requirement | Result |
|---|---|
| ≥ 50 diseases | **56 units** (gene + main disease), **531 rows**; 5–12 rows per unit, median 10 |
| The 8 diseases of `literature-panel-v1` | All 8 included (NF1, FBN1, PTPN11, KMT2D, TBX5, UMOD, FBXL4, ITPR1) |
| Every number carries a citation and a verbatim quote | All 531 rows. Every quote was machine-checked against the local text of its source, and is ≤ 25 words |
| 10% double-checked by the other model, ≥ 90% agreement | Codex: **52 of 54 agree (96.3%)**. Both disagreements were resolved in favour of the panel after re-reading the source (§5) |
| Separation from construction | Split frozen and committed before any extraction (§2); independence of each row is flagged (§4) |

Of the 10 ANALYSIS-001 genes, 9 are in the panel. SPTAN1 was dropped: its
DEE5 cohorts are not open access, and no reachable source states numbers
for 5 features.

## 2. The split: evaluation vs construction units
- **Unit:** a v3.0 vocabulary gene plus its main disease. The main disease
  is the simulable `genes-v1` entity with the highest `sim_weight`, with
  all of its OMIM/ORPHA ids. Pool: 5,050 units.
- **Selection:** `dxt litpanel split`, seed 20260930.
  - Anchors: the 10 ANALYSIS-001 genes.
  - 50 sampled units, using square-root allocation over three margins:
    - organ system: the child of HP:0000118 under which most of the
      entity's HPOA terms fall, with held-out-PMID rows masked;
    - inheritance: AD, AR, XL or other;
    - R1-train patients: 0, 1–9 or ≥ 10.

    Picks alternate with units that have ≥ 10 R1-dev patients: 25 of
    those 50, 35 of the 60 counting anchors.
  - An ordered reserve list, continuing the same sampler.
- **Freezes**, each committed before any extraction on the units it adds:

  | Split | Commit | Units | Why |
  |---|---|---|---|
  | `litpanel-split-v1` | `b9be9ba` | 60 + 20 reserves | the pre-registered design |
  | `litpanel-split-v2` | `410c035` | + reserves 81–100 | 15 of the first 38 units had been dropped |
  | `litpanel-split-v3` | `7399bc2` | + reserves 101–120 | 43 of the first 80 units survived |

  Each version's rows are a byte-identical prefix of the next.
- **All 120 units of `litpanel-split-v3` are evaluation-only**, whether or
  not they survived extraction: their genes and all their disease ids. Every
  other unit is construction. Any v0.5 literature enrichment must exclude
  them.
- **R1 parts read:** train and dev, for patient counts. No sealed data.

## 3. Extraction
- **Sources, in order of preference:**
  1. GeneReviews;
  2. cohort papers from Europe PMC (open-access full text, or the abstract
     when the number is there);
  3. Orphanet, as a last resort. It was never needed; its web pages were
     unreachable anyway (§6).
- **Rules:**
  - Only stated numbers: percentages, n/N counts, ranges (point = midpoint)
    and bounds (">x%" gives point x with range [x, 1]).
  - "All/none of a defined group" is accepted. Vague quantifiers ("most",
    "almost all", "up to") are rejected.
  - Prevalence means the share of affected individuals who have the
    feature.
  - One row per (gene, HPO id), using the most specific current HPO term
    that means the source's feature.
- **Who extracted:** 17 parallel Claude subagent batches following one
  written spec. Each batch had to pass `lit.py verify`: the quote is
  verbatim in the source text, the HPO id is current, and the prevalence is
  consistent with its range. `dxt litpanel build` then re-validates against
  the split and the pinned HPO release (2026-02-16).
- **Draft rows:** the 37-row draft for 8 genes was re-verified row by row,
  not copied. For example:
  - UMOD hyperuricemia: "almost all" (0.95) was replaced by a stated 0.87;
  - UMOD CKD "~100%" was dropped: it states penetrance, not prevalence;
  - KMT2D cleft palate and high palate were dropped: GeneReviews uses vague
    quantifiers;
  - ITPR1 ataxia was replaced by an SCA29-only cohort: the draft source
    mixed in Gillespie syndrome and is an R1-train paper.
- **Removed in my review** (`merge` exclusions, before the cross-check):

  | Unit | Rows removed | Reason |
  |---|---|---|
  | NHLRC1 | myoclonus 242/246 | a complement of "absent 4/246", not printed; the unit then fell to 4 rows and was dropped |
  | ELANE | gingivitis, lymphadenopathy, recurrent fever, fatigue | one GeneReviews sentence pools seven symptoms |
  | F8 | 4 bleed types | shares of patients *hospitalised* for that bleed, not prevalences; the unit fell to 4 rows and was dropped |
  | DCAF17 | dystonia | "up to 65%" |

## 4. Counts

| | Rows | Units |
|---|---|---|
| **By `source_kind`** | | |
| genereviews | 164 | 26 use it (13 only GeneReviews) |
| cohort_paper | 367 | 43 use it (30 only cohort papers) |
| orphanet | 0 | 0 |
| **Independence** | | |
| `independent = true` | 497 | 52 units have ≥ 5 independent rows |
| source PMID cited in `phenotype.hpoa` | 30 | NBAS, TGFB2, RPGRIP1 |
| source PMID in R1-train | 11 | RPGRIP1, TGFB3 |
| source PMID in R1 held-out parts | 12 | independent: masked from construction |

**Independent subset.** Filter on `independent == "true"`. That column is
derived from three others, which a consumer can also filter on directly:
- `source_kind != "orphanet"`: HPOA carries Orphanet's frequencies, and
  profiles are built from HPOA;
- `source_in_hpoa == "false"`: no cited PMID is a `phenotype.hpoa`
  reference;
- `source_r1_part` does not contain `train`: profiles recount from R1-train
  patients.

GeneReviews rows count as independent, because HPOA cites no GeneReviews
chapters. GeneReviews tables can pool papers that HPOA also cites, and
that indirect overlap is not traced.

**Other properties:**
- 351 rows carry n/N counts;
- 74 carry a stated range;
- 25 are male-only and 4 female-only;
- cited sources: 68 distinct PMIDs and 23 GeneReviews chapters;
- prevalence spread, in fifths of [0, 1] from lowest to highest: 112 /
  116 / 77 / 91 / 135.

**Access paths, rows:**
- `europepmc-fulltext` 261;
- `ncbi-litarch-genereviews-bulk` 164;
- `ncbi-efetch-pmc` 58;
- `europepmc-abstract` 43;
- `ncbi-efetch-pubmed-abstract` 5.

## 5. Cross-check with Codex
- **Sample:** 54 rows (10% of 531, rounded up), seed 20260930, drawn from
  the committed `curated.tsv` (`c4198e5`).
- **Method:** `dxt litpanel crosscheck` ran Codex CLI 0.155.1 (`codex exec
  --sandbox read-only`).
  - The prompt held only the gene, disease, feature and citation (with its
    section).
  - The cited document's full text was given on stdin: Codex's sandbox
    cannot read local files on this machine.
  - The panel's values and quotes were never shown.
- **Agreement rule:** the ranges overlap, or the point estimates differ by
  ≤ 0.10.

| Result | Rows |
|---|---|
| Agree | 52 |
| Disagree | 2 |

| Row | Unit / feature | Panel | Codex | Resolution after re-reading |
|---|---|---|---|---|
| 227 | RPS19 / short stature (< 10th centile) | 0.4474 | not found | Codex quoted the same table row (44.7%, DBA overall) but declined because it is not RPS19-specific. The panel keeps it, with `population` saying "all genes" |
| 446 | TNFRSF13B / lymphoproliferative disorder | 0.7222 (13/18) | 0.459 | The panel used the Biallelic (n = 18) column, the AR form this unit is about. Codex used the Total (n = 161) column |

## 6. Access problems (full log: `extraction/access-log.tsv`)
- **Blocked to scripts:**
  - NCBI Bookshelf and PMC article pages return a reCAPTCHA page;
  - orpha.net returns a bot-check page;
  - E-utilities `efetch db=books` does not serve full text.
- **What worked:**
  - **GeneReviews:** the NCBI litarch bulk archive `gene_NBK1116.tar.gz`
    (1,015 chapters; sha256 `53b1e181…7077`, Last-Modified
    2026-09-30 06:41 GMT), plus the GeneReviews FTP id maps. The archive
    stays outside the repo.
  - **Papers:** Europe PMC REST (`fullTextXML`, search, abstracts), with
    E-utilities `efetch db=pmc` / `db=pubmed` as fallbacks.
- **Europe PMC outages:** it returned HTTP 503 for several stretches of
  about 10 minutes. Some batches searched through E-utilities meanwhile.
- **Closed access:** many decisive cohorts are not open access (e.g. the
  SPTAN1, LZTR1/SMARCB1, TGFB3 and SOPH cohorts). This caused many of the
  drops.

## 7. Dropped units (64 of 120; full list with reasons in `extraction/dropped.tsv`)

| Kind | Units | Examples |
|---|---|---|
| `no_numbers`: no reachable source states numbers for ≥ 5 features | 51 | only case reports or families, per-patient tables (not counted, by rule), closed-access cohorts |
| `not_monogenic`: susceptibility, somatic or refuted link | 11 | CST3→ARMD11, UNC13A→ALS1, RB1CC1→breast cancer, PICALM (somatic fusion), BLK→MODY11 (refuted) |
| `post_review`: fell below 5 rows after my exclusions | 2 | NHLRC1, F8 |

- **By role:** 1 anchor (SPTAN1), 23 sampled, 40 reserves.
- **The main lesson:** a random sample of the 5,050-unit vocabulary is
  dominated by ultra-rare units, and most of them have no stated
  frequencies anywhere.
- The `not_monogenic` drops also expose `genes-v1` main-disease choices
  that `genes-v2` is meant to fix.

## 8. Coverage by stratum (kept units vs the pool)

| Organ system | Kept | Pool |
|---|---|---|
| Nervous system | 8 | 1,638 |
| Head or neck | 7 | 485 |
| Musculoskeletal | 7 | 685 |
| Cardiovascular | 6 | 202 |
| Respiratory | 4 | 97 |
| Metabolism/homeostasis | 3 | 225 |
| Endocrine | 3 | 76 |
| Eye | 3 | 331 |
| Genitourinary | 3 | 367 |
| Immune | 3 | 257 |
| Neoplasm | 3 | 52 |
| Digestive | 2 | 95 |
| Integument | 2 | 212 |
| Blood | 1 | 176 |
| Growth | 1 | 19 |
| **Ear** | **0** | 111 |
| Limbs, prenatal, breast, constitutional | 0 | 22 |

| Inheritance | Kept | Pool | | R1-train patients | Kept | Pool |
|---|---|---|---|---|---|---|
| AD | 16 | 1,583 | | 0 | 33 | 4,715 |
| AR | 23 | 2,632 | | 1–9 | 7 | 251 |
| XL | 6 | 231 | | ≥ 10 | 16 | 84 |
| other | 11 | 604 | | | | |

- **Units with ≥ 10 R1-dev patients:** 24 of 56. This is the G2b overlap.
- **Gap:** no ear/hearing unit survived. MYO3A, SMPX, ELMOD3, MYO6 and
  CLRN1 are nonsyndromic or single-family diseases.

## 9. Caveats a consumer should know
- **Disease-level figures:** several units use figures for the disease as a
  whole, not the gene, and the `population` column says so:
  - MT-TV and MT-TL2: MELAS, mostly m.3243A>G;
  - DNAAF2, DNAH11 and DNAAF6's heterotaxy row: PCD;
  - FANCD2: Fanconi anemia;
  - AP4M1: all AP-4 genes;
  - RPS19: DBA, except one row;
  - BMP10: pulmonary arterial hypertension.

  GLA and LAMP2 rows are per sex; `sex_restriction` says which.
- **Unit id quirks** inherited from `genes-v1`. Rows were extracted for the
  disease as the unit names it:
  - DNAH11 → OMIM:244400 is CILD1 (DNAI1);
  - SKIC2 → OMIM:222470 is THES1 (the SKIC3 form, clinically
    indistinguishable);
  - UNC13A, CST3 and others: see §7.
- **Small or clinically diagnosed cohorts:**
  - ELANE: n = 7, not genotyped;
  - NLRP3: linkage-defined FCAS family;
  - FERMT3: genotyping method not stated.

  `population` records each.
- **Judgment calls** kept in the panel:
  - "All have classic PCD features including…" gives 7 DNAAF6 rows at
    13/13;
  - PDX1 "n = 4"-style counts use the cohort size (19) as denominator;
  - PTPN11 cryptorchidism is taken as male-only, from the paired table;
  - SLC19A2 uses three organ-level terms, matching the source's
    categories;
  - RAB23 laterality defects are mapped to heterotaxy.
- **Source-text files are not in the repo.** Re-verifying a quote requires
  re-fetching the source by its citation. The build scripts of the batches
  also stay outside the repo; the curated TSV is the record.
