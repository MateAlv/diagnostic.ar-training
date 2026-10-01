# Literature extraction guide (lit-extract-v1, ADR-0013)

You are a shard agent. You get one shard id, such as `C007` (10 GeneReviews
chapters) or `Q003` (12 open-access papers). `C` and `P` shards are listed in
`data/lit-extract/shards.tsv`; `Q` shards, the papers that passed the
`lit-papers-v2` re-screen, in `data/lit-extract/shards-papers-v2.tsv`. Paper
shards from now on are `Q` shards; the `P` shards are kept only for P001. You read each source of the
shard and write down, as rows of a TSV, the facts it **states**: how often a
clinical feature occurs among affected individuals, and at what age the
disease starts or is diagnosed. A validator then checks every row against the
source text. Read this whole guide before you start; it is the only
instruction you need.

## 0. Hard rules

1. **Only stated facts.** Every number in a row is printed in the source. You
   never estimate, average, add up, take a complement or read a number off a
   figure.
2. **Only allowed units.** A row names a (gene, disease) unit listed for that
   source in your worksheet. Never invent a unit. Never write a row for any
   other gene or disease, even if the source gives numbers for it.
3. **No text beyond the quote.** The only source text in a row is
   `evidence_quote`: at most 25 words, copied verbatim. Never paste
   paragraphs anywhere in the repo, in a commit message or in your report.
4. **Stay in your lane.** Work only in the checkout (worktree) you were given.
   Never write under `/home/mate/FIUBA/trabajo-profesional/GenPhenAI/`. Never
   touch another shard's files. Never read `data/splits/*.json` patients,
   R1-test, R1-vault, MCRD or DDD; you need none of them.
5. **One shard, one commit,** and only after `validate-shard` passes.
6. No AI attribution in commits (no `Co-Authored-By` lines). Never change
   `git config`.

## 1. Setup (once per checkout)

Run everything from the root of your checkout. If you are in a git worktree,
link the shared data and the virtualenv from the main checkout first:

```bash
set -euo pipefail
MAIN=/home/mate/FIUBA/trabajo-profesional/diagnostic.ar-training
[ -e data/raw ] || ln -s "$MAIN/data/raw" data/raw
[ -e data/interim ] || ln -s "$MAIN/data/interim" data/interim
[ -e .venv ] || ln -s "$MAIN/.venv" .venv
DXT=scripts/lit/dxt-local      # runs dxt from THIS checkout's code and data/
$DXT lit --help >/dev/null && echo ok
```

Always call `$DXT` (`scripts/lit/dxt-local`), never `.venv/bin/dxt`: the
latter may run another checkout's code and write into its `data/`.

## 2. Get the texts and your worksheet

```bash
$DXT lit fetch-text <SHARD>
```

This caches the plain text of every source under `data/interim/lit-text/`
(gitignored) and writes `data/interim/lit-extract/<SHARD>/worksheet.md`.
Open the worksheet. For each source it gives:
- the text file to read (`data/interim/lit-text/genereviews/NBK….txt` or
  `data/interim/lit-text/epmc/PMID….txt`);
- `source_kind`, `licence` and `access_path`, which you copy into each row;
- **the units the source may feed**: `gene | disease_id | disease name`.

Read the **text file**, not a web page or a PDF. Quotes are checked against
that file. Its layout:
- `#`, `##`, `###` … lines are section headings;
- a table is a block that opens with `[Table 2] caption`, has one line per
  table row with cells separated by ` | `, may have `[Table 2 note] …` lines
  and closes with `[/Table 2]`;
- superscript footnote markers are written `^1`.

## 3. Read each source

**GeneReviews chapter.** Read at least:
- `Clinical Description` (and its sub-sections), including the feature
  frequency table, usually titled "… Frequency of Select Features" or
  "… Clinical Features";
- `Genotype-Phenotype Correlations`, `Phenotype Correlations by Gene`;
- `Penetrance` only for the onset ages it may give (§9);
- for overview chapters, the per-gene sections and tables.

Skip `Diagnosis/testing` frequency tables ("Proportion of … attributed to
pathogenic variants in gene", detection rates), `Management`, `Genetic
Counseling`, `Differential Diagnosis` and `Molecular Genetics`: none of them
gives feature frequencies among affected individuals.

**Paper.** Follow "Papers" below: first the per-unit check, then only the
paper's own results. Supplementary files are out of scope.

Work source by source, in worksheet order. In the pilot (C001, 10 GeneReviews
chapters, 100 rows) reading and writing took 1-3 minutes per chapter; budget
up to 10 minutes for a rich source and stop at 20.

### Papers

**1. The per-unit check (do it first, from the abstract and Methods).** A
paper feeds a unit only through a group of **at least 20 genetically
confirmed patients of that unit** (gene, disease), or of that disease for a
`pooled` disease-level figure (§4).
- The n that counts is the size of the confirmed group the figure describes.
  It is not the number screened, sequenced or referred, nor the size of a
  whole registry or series.
- **A subgroup under 20 is never extracted,** even inside a qualifying paper.
  P001: the ENPP1 group (84) qualified, the ABCC6 group (19) and the ARHR2
  subgroup (≤ 11) did not.
- A figure for a smaller slice of a qualifying group (e.g. "34 of 48
  assessed" in an ENPP1 group of 84) is fine: the group qualifies, the
  denominator is what was assessed.
- No unit reaches 20: extract nothing, outcome `not_cohort`, and say in the
  note what the largest confirmed group was ("27 ARCI confirmed over 6
  genes; largest ALOX12B n=9").
- Typical dead ends, all `not_cohort`:
  - diagnostic-yield and NGS-panel or exome studies (n = those tested);
  - screening studies with few positives per gene;
  - association, susceptibility, predisposition or risk-factor designs;
  - penetrance in unaffected carriers;
  - drug trials, case reports, animal or cell studies.
- Other dead ends: a variant database (`no_numbers` if it has no phenotype
  numbers); a mixed multi-disease series or registry whose n counts the whole
  series and gives no per-gene or per-disease figure (`not_about_units`).

**2. Only the paper's own cohort.** Extract numbers from the Results, the
tables, and Abstract or Discussion sentences that restate the paper's own
results ("Seizures were reported in 13% ... of our ENPP1 cohort").
- Never extract an Introduction or Background figure.
- Never extract a sentence that cites other studies (a reference marker,
  "et al", "previously reported", "in the literature"), even in the Results.
- Never extract a literature-review table that pools published cases with
  the paper's own.

**3. Definitions come from Methods.** When Methods defines a term used in the
results ("symptomatic: signs of myelopathy"), map the HPO term to that
definition, not to the bare word. Write the definition in the note. The quote
stays the sentence or table row with the number (§10).

**4. Yes/no cells.** A table whose column says "Yes/no (% yes of assessed)"
and gives "36/38 (48.6)" counts yes against no, not n/m.
- Take the printed percentage as `prevalence`.
- Leave both counts empty: n_assessed would be yes + no, which you never add
  up (§0).
- If a cell is ambiguous between yes/no and n/m, skip it and say so in the
  note.

**5. Prenatal ages.** Ages are never negative (the validator requires
[0, 120]).
- A range that starts before birth ("-4.7 to 137 months", "from the prenatal
  period") keeps its high end, leaves the low end empty, and says `range
  starts prenatally` in `age_note`.
- A presentation stated only as prenatal ("diagnosed in utero") is low 0,
  high 0, `age_note` `stated: prenatal`, flag `named_period`.

**6. Screening age is not presentation age.** Age at newborn screening, at
a screening sample, or at cascade or predictive testing is not
`AGE_PRESENTATION`: skip it. Age at clinical diagnosis of a symptomatic
patient counts.

**7. Empty tables.** Some fetched texts have a table caption with no rows
(the table is an image).
- You cannot extract from it; never fall back to a PDF or a web page.
- Name it in the note ("Tables 1-5 empty in fetched text").
- If every number you would have used is in empty tables, the outcome is
  `no_numbers`.

## 4. Which unit a fact belongs to

**Check the disease name of every unit before you use it.** The worksheet
lists, for each gene the source covers, the disease(s) that gene has in our
gene table. When none of a gene's diseases is among the chapter's OMIM ids,
the gene's main disease is listed instead, and that may be a different
disease: in the Silver-Russell chapter, CDKN1C's unit is Beckwith-Wiedemann
syndrome and H19's is isolated hemihyperplasia. A unit whose disease is not
the one a figure describes never gets that figure.

Then, in this order:
1. **Gene-specific figure** (patients with variants in gene G): G's unit. If
   G has several allowed units, the one whose disease the figure describes
   (match the source's subtype or OMIM number, e.g. "SPG72A (OMIM 615625)").
2. **Disease-level figure, one disease** (pooled over the genes of a single
   disease, typical for a GeneReviews "frequency of select features" table):
   **one** row per feature on a unit with that `disease_id`: the gene the
   source names as the most common cause if it is listed, else the first unit
   with that `disease_id` in the worksheet (the gene does not matter for a
   disease-level row; the disease does). Flag `pooled`, and say so in
   `population` ("all EVC syndrome, pooled across genes").
3. **Figure for an umbrella disease that is itself a unit**: if one unit's
   disease *is* the group the source describes (often an Orphanet id named
   like the chapter, e.g. `CRH | ORPHA:98784 | Sleep-related hypermotor
   epilepsy` in the ADSHE chapter), put the pooled figure there, flag
   `pooled`.
4. **Figure pooled over several diseases** (an overview's "individuals with
   albinism", covering OCA1A, OCA2, OA1 …) with no umbrella unit: **one** row
   per feature, flag `pooled_group`, and list in `construction_unit` every
   unit of this source the group covers, `;`-separated, starting with the
   row's own unit (`TYR|OMIM:203100;OCA2|OMIM:203200;…`). Leave out units
   whose disease is not part of the group. `population` names the group.
   Do not copy the row to each unit.
5. Otherwise skip the figure and say so in the notes.

## 5. The row

File: `data/lit-extract/rows/<SHARD>.tsv`, tab-separated, UTF-8, the header
below exactly, one row per fact, no blank lines. Use Python's `csv` module
(`delimiter="\t"`, `lineterminator="\n"`) or write it carefully; a quote must
contain no tab or newline. Do not put quotation marks around fields.

```
source_id gene disease_id construction_unit disease_name feature_label hpo_id prevalence prevalence_low prevalence_high n_affected n_assessed sex_restriction population age_onset_low_years age_onset_high_years age_presentation_low_years age_presentation_high_years age_note flags source_kind citation section evidence_quote access_path licence
```

(The worksheet prints the same header with real tabs; copy it from there.)

| Column | What to write |
|---|---|
| `source_id` | `NBK1234` for a chapter, `PMID:12345678` for a paper, exactly as in the worksheet |
| `gene`, `disease_id` | the unit, exactly as in the worksheet (`EVC`, `OMIM:225500`) |
| `construction_unit` | `gene|disease_id`, e.g. `EVC|OMIM:225500`; for a `pooled_group` row, the group's units `;`-separated, own unit first (§4) |
| `disease_name` | the worksheet's name for the disease (informative only) |
| `feature_label` | the source's own name for the feature (short), or `AGE_ONSET` / `AGE_PRESENTATION` for an age row |
| `hpo_id` | the HPO id (§7); empty on age rows |
| `prevalence` | the share of the population with the feature, a decimal in [0, 1] (`0.66`, not `66%`) |
| `prevalence_low`, `prevalence_high` | only for a stated range or bound (§8); else empty |
| `n_affected`, `n_assessed` | whole numbers, only when the source states them (§8) |
| `sex_restriction` | `male` or `female` when the population is one sex; else empty |
| `population` | who the figure is about, in a few words: `all affected`, `probands`, `males`, `biallelic CHRNE`, `all EVC syndrome, pooled across genes`, `adults (≥18 y)` |
| `age_onset_low_years` … `age_presentation_high_years` | ages in years (§9); on feature rows only if the quote states the feature's onset age |
| `age_note` | short: `median`, `mean`, `stated: infancy`, `onset of seizures` |
| `flags` | `;`-separated, from: `small_n`, `pooled`, `pooled_group`, `named_period`; else empty |
| `source_kind`, `licence`, `access_path` | copy from the worksheet |
| `citation` | chapter: `GeneReviews NBK1234 (Chapter Title)`; paper: `PMID:12345678 (PMC1234567)` |
| `section` | the heading the quote is under, exactly as printed in the text file without the `#`s (deepest heading), or the table label (`Table 2`) |
| `evidence_quote` | ≤ 25 words copied from that section or table (§10) |

## 6. What counts as a stated number

| Source says | Row |
|---|---|
| "12 of 40 (30%)", "12/40" | `n_affected 12`, `n_assessed 40`, `prevalence 0.3` (from n/m, rounded to 4 decimals) |
| "66%" in a table column "% of persons w/feature" | `prevalence 0.66`; counts empty |
| "30% (n = 40)", or a column headed "n = 40" | `prevalence 0.3`, `n_assessed 40`, `n_affected` empty |
| "20%-30%", "between 20% and 30%" | `prevalence 0.25`, `low 0.2`, `high 0.3` |
| ">95%", "more than 95%" | `prevalence 0.95`, `low 0.95`, `high 1` |
| "<5%", "fewer than 5%" | `prevalence 0.05`, `low 0`, `high 0.05` |
| "all 23 individuals", "every patient" (in a defined group) | `prevalence 1`; counts if the group size is stated |
| "none of the 23" | `prevalence 0`, `n_affected 0`, `n_assessed 23` |
| "about one third", "half", "approximately 40%" | `prevalence 0.3333`, `0.5`, `0.4`; no range |

**Never** extract:
- vague quantifiers: "most", "majority", "almost all", "common", "frequent",
  "rare", "a few", "some", "occasionally", "typically", "usually";
- "up to x%", "as many as x%" (a maximum across studies, not a prevalence);
- complements: "absent in 4/246" does **not** give "present in 242/246";
- one number for several features ("gingivitis, fever and fatigue in 20%",
  "Umbilical hernia / diastasis recti | 22%-44%", "rare features (<5%)
  include: A, B, C"): ambiguous between "each" and "any";
- category bundles: a table row naming a heterogeneous category and listing
  its contents ("Skeletal features | 75% | Incl hypoplastic elbow joints,
  clinodactyly, contractures, scoliosis", "Craniofacial anomalies",
  "Dysmorphic & skin features"); a single feature with a definition is fine
  ("Macrosomia | 45%-65% | Defined as pre- &/or postnatal overgrowth");
- figures with no fitting HPO term (e.g. "bilateral pheochromocytoma",
  "metastatic", seizure counts per month);
- tallies of per-patient tables (one row per patient): do not count them
  yourself;
- penetrance or lifetime risk among unselected carriers ("40% of SDHB
  heterozygotes develop a paraganglioma"): that is not the share of
  *affected* individuals with a feature. A tumour risk stated among affected
  individuals of a subgroup ("BWS with CDKN1C variants: neuroblastoma 4.2%")
  is a prevalence and counts;
- conditional shares ("atrial septal defect in >80% of those with CHD",
  "bilateral in >95%" of those with polydactyly): the denominator is not the
  affected population;
- the share of a disease caused by a gene, detection rates, carrier
  frequencies, birth prevalence, mortality or treatment response;
- numbers about an evaluation unit or any gene or disease not in your
  worksheet for this source.

If the same feature has several figures in one source for the same
population, take the chapter's summary table; if the table itself has several
cohort columns ("% of 62 persons", "% of 34", "% of 321"), take the column with
the largest denominator that has a value for that feature, put its size in
`n_assessed`, name the cohort in `population`, and quote the column header
and the row joined with ` ... ` (§10). Write one row. Different populations
of the same feature (males vs females, biallelic vs heterozygous, 11p15 LOM vs
all SRS, adults vs children) are separate rows.

## 6a. Rulings on edge cases (v4)
These settle the ambiguities that the C002–C035 batches reported. When in
doubt, skip and write a note.

| Case | Ruling |
|---|---|
| Several separate cohorts of the **same** population in one source (e.g. onset in cohorts of 28 vs 29) | Take the largest cohort; name the others in the notes |
| Explicit, unhedged absence ("not observed in any of the 40", "is absent", "never") | `prevalence 0`, with counts if stated. Hedged absence ("rarely if ever") is skipped. "All normal" is never read as a complement |
| A hedge in the body, but unhedged wording in a summary or table | Use the unhedged statement and quote it. If every statement is hedged, skip |
| Frequency-bin tables with a legend that gives numbers (">75% / 25–75% / <25%") | `prevalence` = the bin midpoint, `low`/`high` = the bin limits, flag `binned`. "+++ = always present" gives 1 **only if** the legend says so. Symbols with no numeric legend are skipped |
| An organ-level category | Keep it when one HPO term covers the whole category (renal anomalies → HP:0000077). Multi-system or mixed categories are bundles (§6), so skip them |
| "A and/or B" with one number | Record it only when a single HPO term covers both; otherwise skip |
| Sub-items listed under a parent percentage ("neurologic signs 68%: ataxia 71%") | Skip the sub-items (conditional), unless the source says they are shares of all affected individuals |
| "invariable", "universal", "always" | `prevalence 1` |
| "at least X%" | `prevalence X`, `low X`, `high 1`, flag `lower_bound` |
| "nearly X", "almost X", "nearly half", "upward of" | Skip (vague) |
| Lifetime or cumulative risk by an age, among affected **or** carriers (cancer by 50, SCC in RDEB) | Skip; it is not a prevalence among the affected. A stated tumour prevalence in an affected cohort still counts |
| Diagnosis → Suggestive Findings with a stated prevalence | Allowed (skip only gene-share tables there) |
| One gene, one chapter, several OMIM diseases (WT1, FLNA, CYLD spectra) | `pooled_group` over those units |
| One disease under two unit ids (NKH via AMT/ORPHA and GLDC/OMIM) | One `pooled_group` row listing both units |
| Populations defined by treatment status or time of diagnosis | Use the untreated or at-diagnosis population; skip treated-subgroup outcomes |
| Table and text disagree | Use the table; note the difference |
| Onset of the defining feature used as disease onset (first Wilms tumour, first paralytic attack) | Allowed as `AGE_ONSET` when the source presents it as the disease's onset |
| Age phrases | "teens" → 13–19; "Xs" (a decade) → X–X+9; "early Xs" → X–X+3; "late Xs" → X+7–X+9; "within the first year" → 0–1; "neonatal" or "perinatal" → 0–0.08; mean or median only → low = high = that value; a median with IQR → low/high = the IQR |
| `n_affected` with no stated `n_assessed` | Leave both counts empty and keep the prevalence |
| A sub-heading missing from the text file | `section` = the nearest heading present in the text file |

## 7. Mapping a feature to HPO

Use the **most specific current HPO term that the text supports**, no more
specific than the text:
- "postaxial polydactyly (hands)" → `HP:0001162` Postaxial hand polydactyly,
  not Polydactyly;
- "congenital heart disease" → `HP:0001627` Abnormal heart morphology (the
  text says no more), not Atrial septal defect;
- "developmental delay" → `HP:0001263` Global developmental delay only if the
  text says global or describes several domains; otherwise the term the text
  names.

Find terms with the pinned HPO:

```bash
$DXT lit hpo postaxial polydactyly          # every word must occur in a label or synonym
$DXT lit hpo --term HP:0100259              # definition, synonyms, parents, children
```

Only current terms under Phenotypic abnormality (`HP:0000118`) are
accepted: no inheritance, onset or modifier terms, no obsolete ids. If no
term fits, skip the feature and note it. One row per (unit, HPO id,
population, sex) per source; two source features that map to the same term
for the same population are one row (keep the better-supported figure).

## 8. Ranges, pooled tables, small denominators

- **Ranges and bounds:** §6. `prevalence` must lie within
  [`prevalence_low`, `prevalence_high`].
- **Counts:** write `n_affected`/`n_assessed` only when printed. A table cell
  "12/40" counts. A percentage with a stated column total counts as
  `n_assessed` only. Never compute `n_affected` from a percentage.
- **Pooled tables:** record who is pooled in `population` (all genes, both
  sexes, all ages, probands plus relatives) and add `pooled` when it pools
  genes or subtypes of one disease, `pooled_group` when it pools several
  diseases (§4).
- **Small denominators:** keep them. If `n_assessed` < 5, add the flag
  `small_n` (the validator requires it exactly then).
- **Sex-specific features** (cryptorchidism, amenorrhea) or sex-specific
  denominators: set `sex_restriction` and say so in `population`.

## 9. Age facts

An age row has `feature_label` `AGE_ONSET` (age at first manifestations) or
`AGE_PRESENTATION` (age at diagnosis, presentation or ascertainment), an
empty `hpo_id`, empty prevalence and `n_affected`, and only its own two age
columns filled. `n_assessed` may hold the number of individuals the age
summarises, if stated.

| Source says | low | high | age_note | flags |
|---|---|---|---|---|
| "onset between 2 and 10 years" | 2 | 10 | | |
| "median age at diagnosis 4.5 years (range 1-12)" | 1 | 12 | median 4.5 | |
| "mean age at onset 31 years" | 31 | 31 | mean | |
| "onset before age 5 years" | | 5 | | |
| "onset after age 40" | 40 | | | |
| "onset at 6 months" | 0.5 | 0.5 | | |
| "present at birth", "congenital" | 0 | 0 | stated: at birth | `named_period` |
| "neonatal onset" | 0 | 0.08 | stated: neonatal | `named_period` |
| "onset in infancy" | 0.08 | 1 | stated: infancy | `named_period` |
| "onset in (early) childhood" | 1 | 5 | stated: childhood | `named_period` |
| "juvenile onset", "onset in adolescence" | 5 | 15 | stated: … | `named_period` |
| "adult onset", "adulthood" | 16 | | stated: adulthood | `named_period` |
| "early adulthood", "young adult" | 16 | 40 | stated: early adulthood | `named_period` |
| "late onset", "after age 60" | 60 | | stated: … | `named_period` only if no number |
| "2nd to 7th decades" | 10 | 70 | stated: 2nd to 7th decades | |
| "infancy to 7th decade" | 0.08 | 70 | stated: … | `named_period` |
| "from childhood to adulthood", "juvenile to adulthood" | 1 (5) | | stated: … | `named_period` |

A span between two periods takes the low end of the first and the high end of
the last (an open end stays empty). The n-th decade is ages 10(n−1) to 10n.

Units: months / 12, weeks / 52, days / 365, rounded to 2 decimals. Ages are
in [0, 120].

- Use the onset of the **disease**. If the source gives the onset of one
  feature only, record it as `AGE_ONSET` only when that feature is the
  disease's presenting manifestation, and write `onset of <feature>` in
  `age_note`. Otherwise skip it.
- One age row per (unit, kind, population, sex) per source. Prefer a stated
  range; put a stated median or mean in `age_note`.
- Do not record "variable", "any age", "wide range", vague words ("in later
  life") or hedged statements ("typically adulthood", "usually in the first
  two years").
- Overview tables often give onset per gene ("REEP1 | SPG31 (OMIM 610250) |
  2nd to 7th decades"): one `AGE_ONSET` row per gene, on the unit whose
  disease matches the row's subtype.

## 10. The evidence quote

- Copy it from the text file; do not retype, and keep the source's typos.
  At most 25 words (table pipes `|` and the ` ... ` gap do not count).
- It must contain the number you extracted, and enough words to show what
  it is about.
- For a table row, quote the row line as printed, e.g.
  `Postaxial polydactyly (hands) | 98% | Bilateral in >95%`.
- When the number's meaning needs the column header, join two pieces of the
  **same section or table** with ` ... ` (space, three dots, space): e.g.
  `Feature | % of Persons w/Feature ... Short stature | 73%`. Each piece must
  be verbatim and in the order it appears.
- `section` must name the heading or table that contains the quote (the
  validator checks that the quote is inside that block).

## 11. What never goes in a row

- a number you inferred, converted from a figure, or computed (except n/m and
  the unit conversions of §9);
- a number for an evaluation unit or for a gene or disease not listed for the
  source;
- any text beyond the ≤ 25-word quote;
- your own judgment as a value (if you hesitate whether a number is stated,
  it is not: skip it).

## 12. Notes

File: `data/lit-extract/notes/<SHARD>.tsv`, header
`source_id	outcome	rows	note`, one line per source of the shard
(every source exactly once):

| outcome | when |
|---|---|
| `extracted` | at least one row |
| `no_numbers` | read, but no stated number for an allowed unit |
| `not_cohort` | paper fails the per-unit check (§3, Papers) |
| `not_about_units` | the numbers are all about genes or diseases not allowed |
| `no_text` | the text is missing or unreadable (should not happen; say why) |

`rows` is the number of rows of that source. `note` is one short line in your
own words: required unless `extracted`; for `extracted`, list what you skipped
and why (e.g. "skipped Table 3: pooled over 4 HSP types; 2 vague features").

## 13. Validate, fix, commit

```bash
$DXT lit validate-shard <SHARD>
```

It checks every row and the notes file, writes
`data/lit-extract/reports/<SHARD>.json` and exits 1 with one `FAIL` line per
problem. Fix the rows and re-run until it prints `0 problems`. Typical fixes:
- "not verbatim in that section … it is elsewhere": correct `section`;
- "not verbatim": re-copy the quote from the text file;
- "not a current HPO id": look it up again with `$DXT lit hpo`;
- "is not n/m": `prevalence` must equal n/m to ±0.005.

Then commit exactly your three files, on the branch you were given:

```bash
git add data/lit-extract/rows/<SHARD>.tsv data/lit-extract/notes/<SHARD>.tsv data/lit-extract/reports/<SHARD>.json
git commit -m "lit-extract <SHARD>: <N> rows from <K> of <M> sources"
```

Read the commit message back before committing: no AI co-author lines. Do not
push unless told to.

**Report back** (to whoever gave you the shard): rows, rows per source,
outcomes, time taken, and anything in this guide that did not fit what you
met.

## 14. Worked examples (from the pilot, shard C001)

**Disease-level table** (`NBK596643`, Ellis-van Creveld syndrome; seven
genes share `OMIM:225500`, and EVC is the most common cause):

```
[Table 2] Ellis-van Creveld Syndrome: Frequency of Select Features
Feature | % of Persons w/Feature | Comment
Postaxial polydactyly (hands) | 98% | Bilateral in >95%
```

- Row: `gene EVC`, `disease_id OMIM:225500`, `construction_unit
  EVC|OMIM:225500`, `feature_label Postaxial polydactyly (hands)`, `hpo_id
  HP:0001162`, `prevalence 0.98`, `population all EVC syndrome, pooled across
  genes`, `flags pooled`, `section Table 2`, `evidence_quote Postaxial
  polydactyly (hands) | 98% | Bilateral in >95%`.
- "Bilateral in >95%" → nothing (conditional on having polydactyly).
- "About one third of individuals manifest growth deficiency in the perinatal
  setting" → nothing: no HPO term says exactly that.
- "Other rare features (described in <5% …) include: genitourinary
  abnormalities, CNS malformations, sensorineural deafness" → nothing (one
  number for several features).
- "Almost all individuals have hexadactyly" → nothing (vague).

**Several cohort columns** (`NBK1520`, MERRF):

```
Feature | % of 62 Persons w/Feature ^1 | % of 34 Persons w/Feature ^2 | % of 321 Persons w/Feature ^3
Myoclonus | 100% | 24% | 61%
Lactic acidosis | 83% | 65% |
```

- Myoclonus: the 321 column → `prevalence 0.61`, `n_assessed 321`,
  `evidence_quote % of 321 Persons w/Feature ^3 ... Myoclonus | 100% | 24% |
  61%`.
- Lactic acidosis has no 321 value → the 62 column: `prevalence 0.83`,
  `n_assessed 62`, quote `Feature | % of 62 Persons w/Feature ^1 ... Lactic
  acidosis | 83% | 65%`.

**Pooled over several diseases** (`NBK590568`, albinism overview: "Strabismus
is observed in approximately 71% of individuals with albinism"): one row,
`gene TYR`, `disease_id OMIM:203100`, `construction_unit` = all nine
albinism units starting with `TYR|OMIM:203100`, `flags pooled_group`,
`population individuals with albinism (OCA and OA types pooled)`,
`prevalence 0.71`.

**Umbrella unit** (`NBK1169`, ADSHE): the frequency table pools all ADSHE
genes; the worksheet lists `CRH | ORPHA:98784 | Sleep-related hypermotor
epilepsy`, the umbrella disease itself, so the rows go there with `pooled`.

**Onset per gene** (`NBK1509`, HSP overview, Table 1): `REEP2 | SPG72A (OMIM
615625) | Very early; average age 4 yrs` → `AGE_ONSET` on `REEP2|OMIM:615625`,
low 4, high 4, `age_note mean`; `ATL1 |  | Infantile to childhood (rarely,
adult onset)` → low 0.08, high 5, `named_period`.

## Changelog

- v1 (`769412e`): first guide, with the tooling.
- v2 (`182ee6e`): after the C001 pilot: `pooled_group` rows, umbrella units,
  checking each unit's disease, multi-cohort tables, bundle and conditional
  skip rules, decades and period spans.
- v3 (lit-papers-v2, after the P001 pilot): `Q` paper shards; a "Papers"
  section in §3: the per-unit 20-patient rule, own-cohort data only,
  definitions from Methods, yes/no cells, prenatal ages, screening age is not
  presentation age, empty tables.
- v4 (after batches C002–C035): §6a rulings on cohorts of one population,
  absence, hedges, frequency bins, organ categories, "and/or", sub-items,
  quantifiers, lifetime risk, Suggestive Findings, gene spectra, duplicate
  disease ids, treatment-defined populations, table vs text, defining-feature
  onset, age phrases, missing denominators and missing headings. Shards
  extracted before v4 are not re-extracted; the audit checks them against v4.
