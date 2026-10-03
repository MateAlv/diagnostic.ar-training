# LIT-AUDIT-v1: Codex re-read of 83 sampled literature sources

Evidence for ADR-0013 amendment 4 (section 3.2). Written 2026-10-02.
Nothing here is informe prose.

Files:

- `data/lit-extract/audit/lit-extract-v1.items.tsv`: the frozen sample.
- `data/lit-extract/audit/lit-extract-v1.summary.json`: output of
  `dxt lit audit score`.
- `data/lit-extract/audit/lit-extract-v1.issues.tsv`: the 244 issues the
  auditor raised.
- `data/lit-extract/audit/lit-extract-v1.adjudication.tsv`: the same 244
  issues with `valid` (yes/no) and `resolution`.
- Per-item inputs and answers: `data/interim/lit-extract/audit/lit-extract-v1/items/`.

## Sample

- 98 sources, seeded 5% of sources per shard with a floor of one per shard and
  two for C036 (seed 20261002).
- 83 sources were answered. 15 (Q012 to Q026, items 0084 to 0098) are pending
  because the Codex limit ran out. Nothing from them is in the numbers below.
- 852 rows of the 83 answered sources were audited. 55 of the 83 sources
  (66.3%) got at least one issue.
- The adjudication used `docs/lit/EXTRACTION_GUIDE.md` v4 (sections 6, 6a, 9)
  and the guide wins over the auditor. For `wrong_unit` and `bad_row` I read
  the source text (the audit excerpts are cut at a character cap, so the full
  cached text was used when the issue said "not in the excerpt"). `missed`
  issues were only classified.

## Verdicts

| Kind | Issues | valid = yes | valid = no |
|---|---|---|---|
| `wrong_unit` | 6 | 1 | 5 |
| `bad_row` | 112 | 15 | 97 |
| `missed` (recall estimate only) | 126 | 52 | 74 |
| Total | 244 | 68 | 176 |

Why `no`, for the 102 dismissed (exclusive counts) `wrong_unit` and `bad_row` issues:

- 55 "computed or inferred midpoint" complaints. The guide requires
  midpoint plus low/high for a range or bound (section 6), and in every one
  low/high equal the printed range. Of the 57 midpoint-worded issues, one is
  real (C016 LVOTO, "At least 25%-30%", see below) and one (C037 diaphragm)
  is counted under categories.
- 25 category and "A and/or B" complaints, kept under section 6a:
  an organ-level category stays when one HPO term covers it, and
  "A and/or B" stays when one term covers both (HP:0012759 for delay or
  intellectual disability). This is the weakest block, a judgement call
  that the reader may overrule. If all 26 were valid, the row error rate
  would be 40/852 (4.7%).
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

- Valid `wrong_unit` plus valid `bad_row` issues: 16 (1 + 15). Two of them
  hit the same row (C063 line 28), so **15 distinct rows** are wrong.
- **Row error rate: 15 / 852 = 1.76%, Wilson 95% CI 1.07% to 2.88%.**
  With issues instead of rows (16 / 852) it is 1.88%, CI 1.16% to 3.03%.
- The blind cross-check on a separate 744 rows gave 0.13% (CI 0.02% to 0.76%)
  with a Codex and Haiku checker. The two do not agree, because the audit
  reads the whole source with the rule book while the cross-check re-extracts
  one row at a time. The audit rate is the better estimate of what the guide
  would reject.

What the 15 rows were:

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
| C016 | 1 | "at least 25%-30%" stored as a midpoint (fixed, not removed) |

By error type: wording not in the 6a list (7: five "consistently present",
"more than half", "100% penetrant"), conditional or sub-item (3), citation or
lifetime or compound statement (3), wrong unit (1), bound stored as midpoint
(1).

## Recall (rough)

- 126 `missed` issues, **52 valid** (the guide would extract them), 74 not
  extractable. The 74 are 28 counts with no denominator, about 30 with no
  fitting HPO term, 6 diagnostic criteria or differential-diagnosis cells,
  and a few hedged or conditional statements.
- Extracted rows in the 83 sources: 852 (837 after the removals). Rough
  recall = 837 / (837 + 52) = **94.2%**, Wilson 95% CI 92.4% to 95.5%.
  Without the removals: 852 / 904 = 94.2% (CI 92.5% to 95.6%).
- This is a floor on the miss rate and a loose one. The auditor lists only
  what it noticed, I judged "would extract" with a quick HPO search rather
  than a full re-extraction, and the CI treats facts as independent although
  they cluster by source.
- Valid misses are concentrated: C007 (9, SCA6 five-column table), C020 (7,
  legend-binned table), C003 (5, OI type table), C036 (4), C025, C045, C047 (3
  each). The commonest type is an unhedged absence statement (16 of 52,
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

15 rows over 10 shards; each shard validated with `dxt lit validate-shard`
(0 problems) and committed on its own.

- Removed 14 rows: C001 (1), C013 (1), C017 (1), C028 (1), C041 (2),
  C055 (1), C061 (5), C063 (1), Q001 (1). The notes row counts were
  updated and a note line records the removal.
- Corrected 1 row: C016 LVOTO, now prevalence 0.25, low 0.25, high 1, flag
  `lower_bound` (guide section 6, "at least X%").
- No new facts were added and no missed fact was extracted.

Row totals after the fixes: C001 99, C013 109, C016 42, C017 8, C028 24,
C041 143, C055 30, C061 46, C063 29, Q001 139.

## Limits

- One adjudicator (Claude), no second reader. The verdicts that rest on a
  reading of section 6a (25 category issues, 5 C001 `wrong_unit`, the C037
  bins) are the ones most worth a second look.
- 15 sources are pending, so the error rate and the recall come from 83
  sources and say nothing about Q012 to Q026.
- The `valid` column of the issues file was pre-filled with `true` by the
  scorer. The adjudication file replaces it with yes/no.
