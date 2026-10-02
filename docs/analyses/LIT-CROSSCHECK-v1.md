# LIT-CROSSCHECK-v1: blind re-extraction of a seeded 10% of the literature rows

Evidence for ADR-0013 (path to candidate 6, step 1). Written 2026-10-02.
Nothing here is informe prose.

Files:

- `data/lit-extract/crosscheck/lit-extract-v1.items.tsv`: the frozen sample.
- `data/lit-extract/crosscheck/lit-extract-v1.tsv`: score per item.
- `data/lit-extract/crosscheck/lit-extract-v1.summary.json`: output of
  `dxt lit crosscheck score --name lit-extract-v1`.
- `data/lit-extract/crosscheck/lit-extract-v1.adjudication.tsv`: one line per
  disagreement, with verdict and reason.
- `scripts/tools/claude_reextract.py`: the Haiku wrapper.

## Sample

- 744 rows, drawn by `dxt lit crosscheck prepare` with fraction 0.1 and seed
  20261001, from 97 shards.
- C001 is excluded: the pilot already checked it (10 of 10 agree,
  `pilot-C001.*`).
- The list was frozen (`lit-extract-v1.items.tsv`) before any answer existed.
- 689 are prevalence rows and 55 are age rows (`AGE_ONSET` or
  `AGE_PRESENTATION`).

## Checkers

Each checker saw only the passage (the cited section or table), the unit, the
feature and the question, never our value. Items with no `claude_usage.json`
were answered by Codex; items with one by Claude Haiku.

- **Codex, high effort:** the first items.
- **Codex, low effort:** after the 16:47 run on 2026-10-02.
- **Claude Haiku** through `scripts/tools/claude_reextract.py`, for the last 390
  items, after the Codex usage limit was reached.
- **Haiku calibration:** 40 items first (`data/interim/lit-extract/crosscheck/xc-calib-haiku`).
  - 35 of 40 agree, and Haiku agreed on every item where Codex agreed.
  - The first attempt failed on a 0-1 versus percent format; fixed in the
    wrapper's system prompt.

The effort split of the 354 Codex answers below is reconstructed from the
mtimes of `answer.json` (local time, -03), not from a recorded field.

## Agreement

| Checker | Items | Agree | Rate |
|---|---|---|---|
| Codex, answered before 16:47 (high effort) | 216 | 211 | 97.7% |
| Codex, answered from 16:47 (low effort) | 138 | 131 | 94.9% |
| Codex, all | 354 | 342 | 96.6% |
| Claude Haiku | 390 | 373 | 95.6% |
| All | 744 | 715 | 96.1% |

By row type: prevalence rows 668 of 689 (97.0%); age rows 47 of 55 (85.5%).

## Adjudication of the 29 disagreements

Each item was read against its `prompt.txt`, `passage.txt` and `answer.json`,
our row, and, where the passage is cut, the cached source text, under guide v4
and the ADR-0013 amendments.

| Verdict | Count |
|---|---|
| `ours_correct` | 26 |
| `checker_correct` | 0 |
| `both_acceptable` | 2 (0546, 0557) |
| `row_should_not_exist` | 1 (0533) |

By checker: Codex 12 `ours_correct`; Haiku 14 `ours_correct`, 2
`both_acceptable`, 1 `row_should_not_exist`.

Why the 26 `ours_correct` disagreed:

- **Named age periods (8, all age rows):** 0002, 0161, 0190, 0194, 0202, 0296,
  0561, 0573. The source states a period ("Childhood onset", "Adulthood",
  "Prenatal") and guide section 9 maps it to an age range with `named_period`.
  The checker prompt does not give that mapping, so it answers not found.
- **Wording without a number (8):** 0218, 0224, 0235, 0236, 0242, 0246, 0446,
  0688. "Universal", "all", "absent", "none" and "fewer than 10%" are covered by
  guide 6a, but the checker prompt asks for a stated number.
- **Spurious age field (6):** 0473, 0537, 0586, 0600, 0601, 0638. The checker
  returned our prevalence and counts and also filled an age field that the
  prompt told it to leave null; the scorer counts that as a disagreement.
- **Checker misread or lacked context (4):**
  - 0497: it took another presenting-finding row of Table 3.
  - 0674: it mixed the pooled Totals column with the "New" column.
  - 0710: it said the MCN row does not exist.
  - 0599: Methods, which defines "symptomatic", was not in its passage.

The two `both_acceptable` items are wording judgments: "consistently present"
(0546) is not on the guide 6a list of always/universal, and "have not been
observed" (0557) sits between the guide's explicit "not observed" and the
amendment 4 not-reported class.

**Row removed (1):** item 0533, shard C059, OPA3, "Structural brain
abnormalities", prevalence 0. The quote "No cardiac or structural brain
abnormalities have been reported." is a not-reported absence (amendment 4), and
the build's `NOT_REPORTED_PATTERNS` regex (`not (been )?(reported|...)`) does
not match "No ... have been reported", so the build would have kept it as a NOT
row. The row was removed and the notes row count of NBK1473 changed from 6 to 5.
`dxt lit validate-shard C059` passes (55 rows, 0 problems). Items 0534 and 0535
(also C059) now sit one row earlier than their frozen row numbers; the score was
computed before the edit.

## Error-rate estimate

Error = `checker_correct` + `row_should_not_exist` = 0 + 1 = 1 of 744.

- Point estimate 0.13%.
- Wilson 95% CI: 0.02% to 0.76%.

Upper bound if both `both_acceptable` items were counted as errors: 3 of 744,
0.40%, Wilson 95% CI 0.14% to 1.18%.

## Caveats

- **Haiku is the same model family as the extractor,** so for the 390 items it
  answered it is less independent than Codex. Its agreement (95.6%) is not
  higher than Codex's, and its single `row_should_not_exist` finding came from
  the adjudication, not from the checker.
- **The check sees one passage.** It cannot detect a fact present in the source
  but not extracted (that is the audit, `dxt lit audit`), a wrong unit that the
  passage does not reveal, or a wrong HPO mapping when the prevalence matches.
- **Agreement measures numbers, not wording rules.** Most disagreements come
  from the checker prompt (no named-period mapping, number-only answers), so the
  96.1% is a floor on number agreement, not a count of 29 errors.
- **Adjudication was by one reader** (the agent that ran this step), under the
  guide; it is not itself blind.
- **Possible residue of the 0533 type.** A scan of prevalence-0 rows without
  counts for quotes that say "reported/described/documented/observed" but do not
  match the build pattern lists 7 rows (C014 TFAP2B, C056 GARS1, C057 TFR2, C061
  GNPTAB, C064 FGF3 twice, C069 BCL11A); none was changed here. C069 "no other
  vision or hearing impairments have been documented" is the same kind as 0533.
