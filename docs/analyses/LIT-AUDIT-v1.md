# LIT-AUDIT-v1: Codex re-read of 98 sampled literature sources

Evidence for ADR-0013 amendment 4 (section 3.2). Written 2026-10-02; the last 15 sources
(items 0084 to 0098) were adjudicated 2026-10-03 and every number below covers all 98.
Nothing here is informe prose.

Files:

- `data/lit-extract/audit/lit-extract-v1.items.tsv`: the frozen sample.
- `data/lit-extract/audit/lit-extract-v1.summary.json`: output of
  `dxt lit audit score`.
- `data/lit-extract/audit/lit-extract-v1.issues.tsv`: the 265 issues the
  auditor raised.
- `data/lit-extract/audit/lit-extract-v1.adjudication.tsv`: the same 265
  issues with `valid` (yes/no) and `resolution`.
- Per-item inputs and answers: `data/interim/lit-extract/audit/lit-extract-v1/items/`.

## Sample

- 98 sources, seeded 5% of sources per shard with a floor of one per shard and
  two for C036 (seed 20261002).
- All 98 sources were answered (items 0084 to 0098 came in a second run, after
  the Codex limit ran out on the first).
- 852 rows of the 98 sources were audited (814 in items 0001 to 0083, 38 in
  items 0084 to 0098). 58 of the 98 sources (59.2%) got at least one issue.
  The first version of this file said 852 rows of 83 sources; the 852 already
  included the 38 rows of the 15 then-pending sources, so its rates used a
  denominator that was too large for 83 sources. The numbers below are for all
  98 sources and are consistent.
- `dxt lit audit score --from-item 0084` was added so the 83 first items keep
  their frozen issue list. Their shards lost rows to the fixes below, which
  changed the row numbers the issues refer to, and the plain command stops on
  that.
- The adjudication used `docs/lit/EXTRACTION_GUIDE.md` v4 (sections 6, 6a, 9)
  and the guide wins over the auditor. For `wrong_unit` and `bad_row` I read
  the source text (the audit excerpts are cut at a character cap, so the full
  cached text was used when the issue said "not in the excerpt"). `missed`
  issues were only classified.

## Verdicts

| Kind | Issues | valid = yes | valid = no |
|---|---|---|---|
| `wrong_unit` | 6 | 1 | 5 |
| `bad_row` | 116 | 17 | 99 |
| `missed` (recall estimate only) | 143 | 60 | 83 |
| Total | 265 | 78 | 187 |

Items 0084 to 0098 raised 21 issues: 0 `wrong_unit`, 4 `bad_row` (2 valid) and 17
`missed` (8 valid). All of them are in Q012, Q015 and Q018.

Why `no`, for the 104 dismissed (exclusive counts) `wrong_unit` and `bad_row` issues:

- 55 "computed or inferred midpoint" complaints. The guide requires
  midpoint plus low/high for a range or bound (section 6), and in every one
  low/high equal the printed range. Of the 57 midpoint-worded issues, one is
  real (C016 LVOTO, "At least 25%-30%", see below) and one (C037 diaphragm)
  is counted under categories.
- 27 category and "A and/or B" complaints (2 of them from Q018, delay and
  learning disabilities under HP:0012759), kept under section 6a:
  an organ-level category stays when one HPO term covers it, and
  "A and/or B" stays when one term covers both (HP:0012759 for delay or
  intellectual disability). This is the weakest block, a judgement call
  that the reader may overrule. If all of them were valid, the row error rate
  would be 44/852 (5.2%).
- 5 `wrong_unit` on C001: SRS1 (OMIM:180860) is the entry for the 11p15
  methylation defects, and guide section 6 names "11p15 LOM vs all SRS" as
  a separate population. Also a judgement call.
- Age phrases that the guide converts (named periods and spans, section 9):
  7 issues.
- HPO synonyms (aortic dilatation under HP:0004942, dizziness under
  HP:0002321, hyperalgesia under HP:0012534, low birth weight under
  HP:0001518): 5 issues, plus the C004 aortic dilatation midpoint issue.
- Same-denominator sub-items (PURA MRI, n=184): 3 issues.
- Quote present in the full text but cut from the audit excerpt: 1 issue
  (another one sits among the midpoints).
- Tumour share in a "% of persons" table (C004): 1 issue.

## Row error rate

- Valid `wrong_unit` plus valid `bad_row` issues: 18 (1 + 17). Two of them
  hit the same row (C063 line 28), so **17 distinct rows** are wrong.
- **Row error rate: 17 / 852 = 2.00%, Wilson 95% CI 1.25% to 3.17%.**
  With issues instead of rows (18 / 852) it is 2.11%, CI 1.34% to 3.31%.
- Items 0001 to 0083 alone: 15 / 814 = 1.84% (CI 1.12% to 3.02%).
- The blind cross-check on a separate 744 rows gave 0.13% (CI 0.02% to 0.76%)
  with a Codex and Haiku checker. The two do not agree, because the audit
  reads the whole source with the rule book while the cross-check re-extracts
  one row at a time. The audit rate is the better estimate of what the guide
  would reject.

What the 17 rows were:

| Shard | Rows | Why |
|---|---|---|
| C061 | 5 | "consistently present" read as 100% (not in the 6a list) |
| C041 | 2 | sub-items (ventriculomegaly, Chiari) under a 92% parent |
| C063 | 1 | late-onset LAMA2-MD onset on the congenital MDC1A unit |
| C001 | 1 | renal anomalies 10%, sub-item of GU 40% in males |
| C013 | 1 | "100% penetrant" (penetrance wording) |
| C017 | 1 | lifetime 76% from one cited study |
| C028 | 1 | 60% of a compound statement from cited reports |
| C055 | 1 | "more than half" (a word quantifier) |
| Q001 | 1 | sentence with a reference marker |
| Q018 | 2 | rod-cone dystrophy shares among patients with recordable ERG (denominator is a test-outcome subset, conditional) |
| C016 | 1 | "at least 25%-30%" stored as a midpoint (fixed, not removed) |

By error type: wording not in the 6a list (7: five "consistently present",
"more than half", "100% penetrant"), conditional or sub-item (5), citation or
lifetime or compound statement (3), wrong unit (1), bound stored as midpoint
(1).

## Recall (rough)

- 143 `missed` issues, **60 valid** (the guide would extract them), 83 not
  extractable. The 83 are 28 counts with no denominator (plus 4 whose count,
  percent and table-note n disagree), about 31 with no fitting HPO term, 6
  diagnostic criteria or differential-diagnosis cells, 4 age rows the guide
  skips or already covers by a both-sexes row, and a few hedged or
  conditional statements.
- Extracted rows in the 98 sources: 852 (836 after the 16 removals). Rough
  recall = 836 / (836 + 60) = **93.3%**, Wilson 95% CI 91.5% to 94.8%.
  Without the removals: 852 / 912 = 93.4% (CI 91.6% to 94.9%).
- Items 0001 to 0083 alone: 799 / (799 + 52) = 93.9% (CI 92.1% to 95.3%).
- This is a floor on the miss rate and a loose one. The auditor lists only
  what it noticed, I judged "would extract" with a quick HPO search rather
  than a full re-extraction, and the CI treats facts as independent although
  they cluster by source.
- Valid misses are concentrated: C007 (9, SCA6 five-column table), C020 (7,
  legend-binned table), Q018 (8, ocular Table 1 of PMID:34940782), C003 (5,
  OI type table), C036 (4), C025, C045, C047 (3 each). The commonest type is an unhedged absence statement (16 of 52,
  "do not have ...", "not seen in ..."), which the guide allows as prevalence 0.

## Patterns

- **C070 and C037 had the most flags (14 and 15 `bad_row`) and none are
  errors.** All 29 are bin-table midpoints with the bin limits as low/high
  (section 6a), so the auditor was applying a stricter reading than the
  guide. C070 has a numeric legend (++ over 50%, + under 50%). C037 prints
  the bins in the cells (over 90%, 25%-90%, under 25%) with no legend.
  Flag for the lead: for those 7 over-90% and under-25% cells, section 6
  read literally would give 0.9 and 0.25 as the point value, instead of
  the 0.95 and 0.125 bin midpoints now in the rows. The rows follow 6a and
  the shard note says "binned midpoints".
- Errors are not concentrated by shard. The sole shard with more than two
  is C061, one source (NBK1878) whose 5 rows share one phrase.
  C001 (10 issues, the pilot shard) had 1 real error.
- Most real errors are guide-wording slips: words that look like a number
  but are not in the section 6 and 6a lists ("consistently", "more than half",
  "100% penetrant"), and sub-items under a parent percentage.
- The auditor over-flags in three ways: midpoints (guide requires them),
  organ-level categories (guide 6a keeps them), and HPO synonyms.
- Possible extension, not done (outside this task's scope): scan all shards
  for rows whose quote says "Consistently", "more than half" or a "%
  penetrant" wording, since the guide does not allow them.

## What was fixed

17 rows over 11 shards; each shard validated with `dxt lit validate-shard`
(0 problems) and committed on its own. Rows 1 to 15 below were fixed on
2026-10-02, the Q018 removals on 2026-10-03.

- Removed 16 rows: C001 (1), C013 (1), C017 (1), C028 (1), C041 (2),
  C055 (1), C061 (5), C063 (1), Q001 (1), Q018 (2). The notes row counts were
  updated and a note line records the removal.
- Corrected 1 row: C016 LVOTO, now prevalence 0.25, low 0.25, high 1, flag
  `lower_bound` (guide section 6, "at least X%").
- No new facts were added and no missed fact was extracted.

Row totals after the fixes: C001 99, C013 109, C016 42, C017 8, C028 24,
C041 143, C055 30, C061 46, C063 29, Q001 139, Q018 65.

## Limits

- One adjudicator (Claude), no second reader. The verdicts that rest on a
  reading of section 6a (27 category issues, 5 C001 `wrong_unit`, the C037
  bins) are the ones most worth a second look.
- The 15 sources added on 2026-10-03 are mostly `not_cohort` or
  `no_numbers` (10 of 15, 0 rows), so they add 38 rows and 21 issues, all in three
  sources.
- The `valid` column of the issues file was pre-filled with `true` by the
  scorer. The adjudication file replaces it with yes/no.
