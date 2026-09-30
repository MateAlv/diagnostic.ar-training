# Sealed-split ledger

`diagnostic_ar_training.lineage.ledger` appends one row per read of a sealed
part (R1 test/vault). Do not edit rows; commit this file with the results
they produced. Gate reads of R2/R3 are logged here by hand in the same format.
Rules: `docs/EVAL_PROTOCOL.md` §2.

| UTC time | split/part | experiment | code SHA | reason |
|---|---|---|---|---|
| 2026-09-29T00:28:28+00:00 | r1-v1/test | EXP-000 | 17f1392281d3 | E0 reference (pre-registered in EXP-000) |
| 2026-09-29T00:28:34+00:00 | mcrd/all | EXP-000 | 17f1392281d3 | E0 reference (pre-registered in EXP-000) |
| 2026-09-29T00:28:34+00:00 | ddd/all | EXP-000 | 17f1392281d3 | E0 reference (pre-registered in EXP-000) |
| 2026-09-30T18:17:57+00:00 | s3-v1/test | EXP-B-003 | 0b1bae814524 | EXP-B-003 Phase-4 gate (pre-registered, step 1) |
