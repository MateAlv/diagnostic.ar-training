# SOURCES-ACQUISITION-001: Tier-1 curated sources and the frozen extraction lists (lit-sources-v1)

- **Date:** 2026-10-01.
- **Rules:** ADR-0013, including amendment 1 (verified sources only).
- **What was done:**
  - every Tier-1 curated source was acquired and registered;
  - coverage was measured over the v3.0 vocabulary;
  - the GeneReviews and Tier-2 extraction lists were frozen as
    `lit-sources-v1`, committed (`6e7ebd7`) **before any extraction**.
- **What was not done:** no LLM extraction of free text, and no LLM
  classification of papers. Every paper decision is a deterministic screen.
- **Raw results:**
  - coverage: `results/analyses/SOURCES-ACQUISITION-001/` (`genes.tsv`,
    `summary.json`);
  - the paper-screen QA sample: `papers_qa40.tsv`, same folder;
  - the lists: `data/lit-sources/lit-sources-v1/`, manifest
    `data/manifests/lit-sources-v1.json`, release `lit-sources-v1`.
- **Code:**
  - `src/diagnostic_ar_training/knowledge/{lit_sources,medlineplus,gene2phenotype,panelapp}.py`;
  - `dxt lit-sources fetch|freeze`;
  - `scripts/analysis/sources_acquisition.py`;
  - `scripts/sources/snapshot_{medlineplus,panelapp}.py`.
- **Boundaries:**
  - the 120 `litpanel-split-v3` units, their genes and every disease id are
    evaluation-only. They appear below only in the evaluation columns;
  - R1 held-out PMIDs were used only as a mask;
  - no sealed data was read.

## 1. Sources acquired

Each source is pinned in `data/sources.yaml` as a private release asset
of this repo, with its upstream URL, sha256, role `knowledge`, licence, and
in `notes` the terms URL, the date checked (2026-10-01) and a quote of the
clause.

| Source | Snapshot (release tag) | Content | Terms | Verdict |
|---|---|---|---|---|
| **GeneReviews** | `data-snapshot-2026-10-01-genereviews`, 32 MB | The 1,015 chapter NXML files and `license.txt`, byte-identical members of the litarch bulk archive (upstream sha256 `119439c7…`, Last-Modified 2026-10-01 06:41 GMT), plus the 4 FTP index files. PDFs and images left out | Copyright Univ. of Washington: "Permission is hereby granted to reproduce, distribute, and translate copies of content materials for noncommercial research purposes only", with credit and copyright | **Usable** for noncommercial research. No ML/AI clause. Written confirmation still pending (TODO) |
| **MedlinePlus Genetics** | `data-snapshot-2026-10-01-medlineplus`, 13.5 MB | `ghr-summaries.xml` (1,305 conditions) plus the 1,305 condition pages, unmodified; the pages add the Frequency, Causes and Inheritance sections | "Works produced by the federal government are not copyrighted under U.S. law. You may reproduce, redistribute, and link freely"; the list includes "Summaries on Genetics pages" | **Usable**, public domain. Images not used |
| **Gene2Phenotype** | `data-snapshot-2026-10-01-g2p` | All panels, 3,851 records: DD 2,866, Eye 789, Skin 608, Skeletal 346, Cardiac 179, Cancer 125, Ear 98. Each row keeps its panel | "The G2P dataset is released under the Creative Commons Attribution 4.0 (CC BY 4.0) licence." | **Usable**. DDD caveat recorded (DD panel) |
| **PanelApp** (Genomics England) | `data-snapshot-2026-10-01-panelapp` | 433 panels, 32,534 gene entries (green 19,552, amber 3,425, red 9,557); 138 carry HPO ids, 20,818 an OMIM number | §1.1: "You agree not to use PanelApp for any commercial purposes …, or for diagnostic use, medical decision-making or providing a healthcare service … unless you have entered into a separate agreement with GEL" | **Registered but restricted.** No ML/AI or private-storage ban, so the stop rule does not trigger. But feeding diagnostic.ar's production model is arguably "diagnostic use". It may feed research analyses only, pending Mateo's decision or GEL's agreement |
| **ClinGen**, beyond validity | not added | Dosage sensitivity has no phenotype content. Actionability: 443 topics, 303 genes (281 construction, 155 weak; 16 evaluation). Prevalence, penetrance and features exist only as prose in the full reports. The summary files carry only severity and penetrance scores | CC0 | **Nothing worth adding now.** Prose would need free-text extraction, and the full reports timed out twice |

**Holes found in the sources:**
- **G2P:**
  - phenotypes are attached to records, not to papers, so held-out masking
    can only drop whole records. A record citing a held-out PMID touches
    150 construction genes;
  - the column `additional mined publications` comes from G2P's ML
    pipeline, so the parser ignores it.
- **PanelApp:** its phenotype strings are OMIM-derived, which also puts
  them under its OMIM clause (§6).

**Other human-curated candidates** (proposed, not added; amendment 1
requires recording them first):
- **GenCC:** CC0, an aggregate of gene-disease validity from ClinGen, G2P,
  PanelApp, Orphanet and others. It overlaps what we already have.
- **ClinGen Actionability full reports:** disease prevalence and
  penetrance, but as prose.
- **UniProtKB/Swiss-Prot disease comments:** believed CC BY 4.0, terms not
  checked; prose.
- **PanelApp Australia:** no data licence found, so not usable as is.

## 2. Coverage of the v3.0 vocabulary

**Units:**
- 5,108 construction genes and 120 evaluation genes (the padding token is
  excluded);
- weakness tiers as in SOURCES-SCOPING-001 §3.

**Notes on the counts:**
- The construction columns still include the 204 genes whose main disease
  is an evaluation disease. They can't be enriched at the disease level,
  and the frozen lists exclude them.
- "New terms": HPO ids under Phenotypic abnormality that the main
  disease's `hpoa-recount-v1` profile lacks.
- GeneReviews and Tier-2 rows count the **frozen** lists (§3). They match
  by previous symbols too, so they read 1,086 and 777 here vs 1,084 and
  775 in the list summary.

| Source and measure | Construction (5,108) | Weak W1–W4 (2,571) | Evaluation (120) |
|---|---|---|---|
| **GeneReviews, usable chapter** | 1,086 | 517 | 0 (by rule) |
| ... numeric frequency table | 536 | 249 | 0 |
| ... numeric age sentence | 719 | 349 | 0 |
| **Tier-2 selected paper** | 777 | 476 | 0 (by rule) |
| **Chapter or paper** | 1,307 | 737 | 0 |
| MedlinePlus: covered | 2,548 | 1,309 | 82 |
| ... prevalence states a number (disease prevalence) | 2,007 | 1,050 | 61 |
| ... numeric age | 126 | 61 | 4 |
| ... inheritance | 2,378 | 1,233 | 78 |
| G2P: covered | 2,847 | 1,293 | 74 |
| ... HPO terms | 1,986 | 902 | 60 |
| ... new terms vs HPOA | 1,445 | 640 | 49 |
| ... new and unrelated (not an ancestor or descendant of a profile term) | 1,049 | 487 | 42 |
| ... confidence definitive or strong | 2,371 | 1,067 | 71 |
| PanelApp: covered | 4,562 | 2,320 | 108 |
| ... green on some panel | 3,888 | 1,910 | 101 |
| ... new HPO terms | 27 | 11 | 1 |
| ClinGen validity: covered | 2,786 | 1,379 | 80 |
| ... definitive or strong | 2,066 | 946 | 67 |

| What each source offers | Feature terms | Feature frequency | Disease prevalence | Age (onset/diagnosis) | Gene–disease confidence |
|---|---|---|---|---|---|
| GeneReviews | yes (text; known only after extraction) | yes: numeric tables in 48% of usable chapters | sometimes | numeric in 75% of usable chapters (screen) | no |
| Tier-2 papers | yes (after extraction) | yes, n/N | rarely | often | no |
| MedlinePlus | prose only (HPO labels found by exact matching, a rough indicator) | no | yes, prose | rare (126 genes numeric) | no |
| G2P | yes, HPO ids | no | no | no | yes |
| PanelApp | rarely (138 entries with HPO) | no | no | no | yes (green/amber/red) |
| ClinGen validity | no | no | no | no | yes |

**Crossed with the weakness tiers** (construction genes):

| Tier | Genes | GeneReviews | Tier-2 paper | Chapter or paper | G2P (new terms) | MedlinePlus | PanelApp | ClinGen |
|---|---|---|---|---|---|---|---|---|
| W1 mostly no frequency | 440 | 67 | 108 | 139 | 219 (90) | 247 | 395 | 225 |
| W2 Orphanet bins only | 314 | 80 | 76 | 106 | 154 (117) | 176 | 260 | 168 |
| W3 no counts, other | 405 | 147 | 110 | 181 | 192 (108) | 261 | 372 | 231 |
| W4 counts from < 5 patients | 1,412 | 223 | 182 | 311 | 728 (325) | 625 | 1,293 | 755 |
| ok | 2,205 | 561 | 297 | 562 | 1,493 (779) | 1,165 | 2,076 | 1,344 |
| W0 no profile | 332 | 8 | 4 | 8 | 61 (26) | 74 | 166 | 63 |

**Reading:**
- **The literature lists reach 737 of 2,571 weak genes (29%).** This
  matches SOURCES-SCOPING-001's estimate of about 700.
- **The Tier-1 KBs add terms, not frequencies.** G2P offers new terms for
  640 weak genes. MedlinePlus offers disease prevalence for 1,050, but
  numeric ages for only 61.
- **No Tier-1 KB gives feature frequencies.** Only GeneReviews and Tier-2
  papers can.
- **W2 genes** (Orphanet-only profiles) almost never match a KB's disease
  by OMIM id: MedlinePlus 2, G2P 4, PanelApp 5.

## 3. lit-sources-v1: the frozen lists

Built by `dxt lit-sources freeze --id lit-sources-v1` from `7474c4c`
(clean tree), published with `--publish`.

**Outputs:**
- `chapters.tsv`: all 882 gene-map chapters with their status; usable
  ones are ranked;
- `papers.tsv`: 14,332 screened open-access records with status and
  reason;
- `gene-queries.tsv`: the second-pass query and hits per gene;
- `summary.json`;
- the raw Europe PMC cache: release only. It holds abstracts, so it stays
  out of git.

### 3.1 GeneReviews chapters

| Status | Chapters | Construction genes named |
|---|---|---|
| **usable** | **695** | **1,084** (515 weak) |
| dropped: touches an evaluation unit (gene map or OMIM id) | 78 | 525 |
| dropped: cites ≥ 1 R1 held-out PMID (206 distinct PMIDs) | 99 | 227 (197 reachable through no other chapter) |
| dropped: no construction gene | 10 | 0 |

- **Evaluation boundary:** a gene counts as construction only if it is not
  an evaluation gene and its main disease is not an evaluation disease.
  6 genes named in usable chapters are blocked for that reason and listed
  per chapter.
- **The screen** (SOURCES-SCOPING-001):
  - numeric frequency table: 332 of 695 usable chapters (48%);
  - numeric age sentence: 520 (75%).

  The 30-chapter sample's hand verdicts were 0.57 and 0.47; the age regex
  over-counts.
- **Weak-profile priority:** a recorded order, then more weak genes, more
  numeric table rows, NBK id.

| Class | Rule | Chapters | Construction genes | Weak genes |
|---|---|---|---|---|
| P1 | weak gene + numeric table | 157 | 346 | 249 |
| P2 | weak gene, no table | 193 | 420 | 289 |
| P3 | numeric table, no weak gene | 175 | 197 | 0 |
| P4 | rest | 170 | 188 | 0 |

### 3.2 Tier-2 papers

**Pass 1: papers cited by usable chapters.**
- Usable chapters cite 27,326 PMIDs.
- The Europe PMC query `(EXT_ID:… OR …) AND SRC:MED AND OPEN_ACCESS:y`,
  in batches of 150, returned 4,942 open-access records.

**Pass 2: weak genes with no usable chapter.**
- 1,970 simulable weak construction genes, one recorded query each:
  `TITLE:"SYM" AND (TITLE:(design) OR ABSTRACT:(design)) AND OPEN_ACCESS:y AND SRC:MED`.
- The design terms are cohort, natural history, registry, case series,
  clinical or phenotypic spectrum, genotype-phenotype, clinical features
  and clinical characteristics.
- A record is kept only if a gene symbol is in its title
  (case-sensitive): 9,390 records.

**The screen.** It is deterministic and applied in this order. The first
rule that fails sets the reason.
1. R1 held-out PMID.
2. literature-panel-v2 source.
3. Licence not in {CC BY, CC0, CC BY-NC, CC BY-NC-SA, CC BY-NC-ND}.
4. Preprint.
5. Excluded publication type: case report, review, systematic review,
   meta-analysis, editorial, comment, erratum, guideline, news.
6. "Case report" in the title.
7. Any evaluation gene symbol in the title or abstract.
8. Literature-review wording.
9. Association or susceptibility wording.
10. Somatic or oncology-treatment wording.
11. No germline genetic-confirmation wording.
12. Pass 2 only: the gene not named as the carrier of the variants
    ("SYM-related", "variants in SYM", …).
13. No patient count stated.
14. Fewer than 20 stated. The count is the nearest number before a
    patient noun ("12 of 40 patients" gives 40), ignoring controls and
    "%".

Then:
- **cited by HPOA:** a passing paper that HPOA cites for a main disease of
  its genes is excluded as `in_hpoa`, and the PMID is kept;
- **cap:** pass 2 keeps at most 5 papers per gene, largest n first.

| Outcome | Pass 1 (GeneReviews-cited) | Pass 2 (Europe PMC query) |
|---|---|---|
| Records screened | 4,942 | 9,390 |
| **Selected** | **707** | **304** |
| Publication type (case report / review / other) | 1,657 (846 / 767 / 44) | 1,086 (672 / 354 / 60) |
| No germline genetic-confirmation wording | 1,108 | 3,309 |
| Somatic or oncology treatment | 139 | 2,210 |
| Association or susceptibility | 133 | 1,209 |
| No count stated / n < 20 | 411 / 371 | 168 / 262 |
| Licence outside the set (mostly none stated) | 239 | 163 |
| Gene not in variant context | — | 300 |
| Names an evaluation gene | 68 | 117 |
| Literature review / "case report" title | 65 / 32 | 144 / 23 |
| Already cited by HPOA (`in_hpoa`) | 12 | 2 |
| R1 held-out PMID | 0 | 9 |
| Per-gene cap | — | 84 |

**What was selected:**
- **Genes:** the 1,011 selected papers cover 775 construction genes.
  - Pass 1: 562 genes, 262 of them weak.
  - Pass 2: 218 weak genes.
  - Gene attribution in pass 1: the citing chapter's construction genes
    named in the title or abstract (509 papers), otherwise all of them
    (198 papers).
- **Licences:** CC BY 696, CC BY-NC-ND 187, CC BY-NC 101, CC BY-NC-SA 26,
  CC0 1.
- **Stated n:** median 105 (IQR 44–401).
- **in_hpoa:** 108 screened records are flagged; 14 passed the rest of the
  screen and were excluded for it.

**Screen QA** (`papers_qa40.tsv`):
- **Method:** a seeded sample (20261001) of 40 selected papers. I read each
  title and the context of its stated n, and asked whether it is a
  phenotype cohort, registry or natural-history series of ≥ 20
  genetically confirmed patients of the gene's disease.
- **This is QA only.** It changed nothing in the frozen list.
- **Result:** 23 of 40 yes, **precision 0.58 (Wilson 95% CI 0.42–0.72)**.
  Pass 1: 17/30; pass 2: 6/10.
- **Main false positives:**
  - screening or diagnostic-yield cohorts, where n counts those screened,
    not the carriers;
  - association or risk-factor studies that avoid the keywords;
  - drug trials;
  - stated n that is a year after a month name ("July 2018") or the size
    of a whole registry.

    15 selected papers have n between 1990 and 2030.

**Screen revisions,** all made before freezing and recorded in commit
`7474c4c`. After reading samples of the first screen's output, I:
- narrowed the genetic-confirmation words to germline ones;
- added the somatic/oncology rule, which pass 2 needed because of EGFR-
  and BRCA-type hits;
- added susceptibility and polymorphism wording;
- added the variant-context rule for pass 2 (CD4, C4A-type collisions);
- added the per-gene cap.

No extraction had started.

### 3.3 Sizes

| | Chapters | Papers | Construction genes | Weak genes |
|---|---|---|---|---|
| GeneReviews (usable) | 695 | | 1,084 | 515 |
| Tier-2, pass 1 | | 707 | 562 | 262 |
| Tier-2, pass 2 | | 304 | 218 | 218 |
| **lit-sources-v1 total** | **695** | **1,011** | **1,304** | **735** |

Of the 2,485 simulable weak construction genes outside evaluation
diseases, 735 (30%) have a chapter or a paper.

## 4. Recommended extraction shards

**Throughput used:** LITPANEL-v2.
- 97 raw rows per agent-hour;
- 7.1 rows per used chapter;
- 5.4 rows per paper;
- Codex checked 54 rows in about 9 minutes.

**GeneReviews:**
- **Expected yield:** 695 chapters × 0.63 (≥ 5 stated numbers) × 7.1 ≈
  3,100 rows, about **32 agent-hours**.
- **Shards:** 10 chapters each, in priority order, which is about 70 rows
  or 45 agent-minutes. That gives 70 shards: P1 is 16 shards and P1 + P2
  is 35.
- **Order:** P1 first, then P2. P1 + P2 (350 chapters) alone covers the
  515 weak genes, in about 16 agent-hours.

**Tier-2 papers:**
- **Expected yield:** 1,011 × 0.58 relevant × 5.4 ≈ 3,200 rows, about **33
  agent-hours**, plus dead ends (closed full text, no per-feature numbers).
- **Shards:** 12 papers each, about 85 shards.
- **Order:** sort at shard-assignment time by:
  1. weak gene first;
  2. a recorded design-keyword tier in the title (cohort, natural history,
     registry, phenotype or "-related");
  3. PMID.

  A worker should stop on a paper whose abstract shows < 20 confirmed
  patients.

**Cross-check:**
- a seeded 10% of rows, about 630, given to Codex with the full text on
  stdin, as in LITPANEL-v2;
- about 1.5–2 Codex hours.

**Wall time at 8 Claude agents in parallel:**
- GeneReviews P1 + P2: about 2 hours;
- all chapters: about 4;
- papers: about 4 more.

## 5. Open items and risks
- **PanelApp:** Mateo decides whether it may feed anything that reaches
  production (diagnostic use, §1.1), or asks Genomics England.
- **GeneReviews:** the written confirmation is pending (TODO).
- **G2P:** use it as knowledge (like HPOA), but drop records citing
  held-out PMIDs. Disclose G2P on any DDD no-regression result (DD panel).
- **The screen is coarse** (precision 0.58), so expect about 40% dead ends
  in the paper shards.
- **Pass 2 relies on title hits,** so genes whose cohorts name only the
  disease are missed.
- **Held-out drops cost 197 construction genes** their only usable
  chapter. The weak ones among them were eligible for pass 2.
- **Overview chapters touching evaluation units** stay excluded, under the
  strict rule (78 chapters, 525 construction genes named).
