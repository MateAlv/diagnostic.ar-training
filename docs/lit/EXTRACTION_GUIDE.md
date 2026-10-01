# Literature extraction guide (lit-extract-v1, ADR-0013)

You are a shard agent. You get one shard id, such as `C007` (10 GeneReviews
chapters) or `P031` (12 open-access papers). You read each source of the
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

**Paper.** First read the abstract and the methods' patient description. The
paper must be a cohort, registry or natural-history series of **at least 20
genetically confirmed patients** with the disease of one of its units. If it
is not (a screening or diagnostic-yield study where most participants have no
variant, an association study, a drug trial, a case report, an animal or
cell study, fewer than 20 confirmed patients), extract nothing and record
`not_cohort` in the notes (§12). Otherwise read the results text and every
table. Supplementary files are out of scope.

Work source by source, in worksheet order. Budget about 5 minutes per source
with little numeric content and about 10 for a rich one.

## 4. Which unit a fact belongs to

- A fact about patients with pathogenic variants in gene G goes to G's unit.
  If G has several allowed units, choose the disease the figure describes.
- A fact about the disease as a whole, pooled over its genes (typical for a
  GeneReviews "frequency of select features" table), goes to **one** row per
  feature for that `disease_id`: use the unit of the gene the source names as
  the most common cause; if it names none, the first unit with that
  `disease_id` in the worksheet. Set `population` to say it is pooled
  ("all EVC syndrome, pooled across genes") and add the flag `pooled`.
- A figure pooled over **several different diseases** among the units (for
  example, one table for all forms of an overview's group) is **not**
  extracted. Note it in the notes as skipped.
- If no allowed unit is about the disease a figure describes, skip the
  figure. A gene listed for the source does not make every figure in the
  source about that gene.

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
| `construction_unit` | `gene|disease_id`, e.g. `EVC|OMIM:225500` |
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
| `flags` | `;`-separated, from: `small_n`, `pooled`, `named_period`; else empty |
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
- one number for a list of features ("gingivitis, fever and fatigue in 20%"):
  ambiguous between "each" and "any". If the list has an umbrella name
  ("genitourinary anomalies (hypospadias, cryptorchidism) in 5%"), extract
  the umbrella term only;
- tallies of per-patient tables (one row per patient): do not count them
  yourself;
- penetrance among unselected carriers ("40% of SDHB heterozygotes develop
  a paraganglioma"): that is not the share of *affected* individuals with a
  feature;
- the share of a disease caused by a gene, detection rates, carrier
  frequencies, birth prevalence, mortality or treatment response;
- numbers about an evaluation unit or any gene or disease not in your
  worksheet for this source.

If the same feature has several figures in one source for the same
population, take the one with the largest stated denominator (or the
chapter's summary table) and write one row. Different populations of the same
feature (males vs females, biallelic vs heterozygous, EVC vs EVC2) are
separate rows.

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
  genes or subtypes (§4).
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
| "adult onset" | 16 | | stated: adulthood | `named_period` |

Units: months / 12, weeks / 52, days / 365, rounded to 2 decimals. Ages are
in [0, 120].

- Use the onset of the **disease**. If the source gives the onset of one
  feature only, record it as `AGE_ONSET` only when that feature is the
  disease's presenting manifestation, and write `onset of <feature>` in
  `age_note`. Otherwise skip it.
- One age row per (unit, kind, population, sex) per source. Prefer a stated
  range; put a stated median or mean in `age_note`.
- Do not record "variable", "any age", "wide range" or decades written as
  vague words ("in later life").

## 10. The evidence quote

- Copy it from the text file; do not retype. At most 25 words.
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
| `not_cohort` | paper fails the §3 cohort check |
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

## 14. Worked examples

From `NBK596643` (Ellis-van Creveld syndrome), whose units are the EVC
syndrome genes (`OMIM:225500`) plus DYNC2H1, SMO and WDR35 with their own
diseases:

```
[Table 2] Ellis-van Creveld Syndrome: Frequency of Select Features
Feature | % of Persons w/Feature | Comment
Postaxial polydactyly (hands) | 98% | Bilateral in >95%
```

- The table pools the EVC syndrome genes, so it is a disease-level figure.
  EVC and EVC2 cause most cases; the worksheet lists `EVC|OMIM:225500`.
- Row: `gene EVC`, `disease_id OMIM:225500`, `feature_label Postaxial
  polydactyly (hands)`, `hpo_id HP:0001162`, `prevalence 0.98`, `population
  all EVC syndrome, pooled across genes`, `flags pooled`, `section Table 2`,
  `evidence_quote Postaxial polydactyly (hands) | 98% | Bilateral in >95%`.
- "About one third of individuals manifest growth deficiency in the perinatal
  setting" → prevalence 0.3333 for the perinatal growth deficiency term.
- "Other rare features (described in <5% of individuals …) include:
  Genitourinary abnormalities (…)" → one row for the umbrella
  (`HP:0000119`, prevalence 0.05, low 0, high 0.05), none for the listed
  sub-features.
- "Almost all individuals have hexadactyly" → nothing (vague).
