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
| 2026-09-30T18:27:48+00:00 | r1-v1/test | EXP-B-003 | d4dcf67ad84a | EXP-B-003 no-regression (pre-registered, step 2) |
| 2026-10-03T20:59:30+00:00 | s3-v2/test | EXP-B-004 | ba3ebcdbcf72 | x |
| 2026-10-03T22:27:58+00:00 | s3-v2/test | EXP-B-004 | c1342164fcb4 | EXP-B-004 and EXP-Q-001 sealed read, pre-registered 75cb7f0, Q2b lam 0.6 with F |
| 2026-10-03T22:32:02+00:00 | s3-v2/test | EXP-B-004 | c1342164fcb4 | EXP-B-004 and EXP-Q-001 sealed read, pre-registered 75cb7f0, Q0 with F |
| 2026-10-03T22:33:28+00:00 | s3-v2/test | EXP-B-004 | c1342164fcb4 | EXP-B-004 and EXP-Q-001 sealed read, pre-registered 75cb7f0, Q1 agent 48d901e with F |
| 2026-10-03T22:44:09+00:00 | s3-v2/test | EXP-B-004 | c1342164fcb4 | EXP-B-004 and EXP-Q-001 sealed read, pre-registered 75cb7f0, noise-Q2b |
| 2026-10-03T22:48:03+00:00 | s3-v2/test | EXP-B-004 | c1342164fcb4 | EXP-B-004 and EXP-Q-001 sealed read, pre-registered 75cb7f0, noise-Q0 |
| 2026-10-03T22:49:24+00:00 | s3-v2/test | EXP-B-004 | c1342164fcb4 | EXP-B-004 and EXP-Q-001 sealed read, pre-registered 75cb7f0, B-rrv1-kbv6 |
| 2026-10-03T22:50:44+00:00 | s3-v2/test | EXP-B-004 | c1342164fcb4 | EXP-B-004 and EXP-Q-001 sealed read, pre-registered 75cb7f0, B-F-kbv7 |
| 2026-10-03T22:52:04+00:00 | s3-v2/test | EXP-B-004 | c1342164fcb4 | EXP-B-004 and EXP-Q-001 sealed read, pre-registered 75cb7f0, B-F-onset |
| 2026-10-03T22:53:26+00:00 | s3-v2/test | EXP-B-004 | c1342164fcb4 | EXP-B-004 and EXP-Q-001 sealed read, pre-registered 75cb7f0, B-F-sex |
| 2026-10-03T22:54:47+00:00 | s3-v2/test | EXP-B-004 | c1342164fcb4 | EXP-B-004 and EXP-Q-001 sealed read, pre-registered 75cb7f0, B-F-agemean |
| 2026-10-03T22:56:09+00:00 | s3-v2/test | EXP-B-004 | c1342164fcb4 | EXP-B-004 and EXP-Q-001 sealed read, pre-registered 75cb7f0, B-frontier75 |
| 2026-10-03T22:57:31+00:00 | s3-v2/test | EXP-B-004 | c1342164fcb4 | EXP-B-004 and EXP-Q-001 sealed read, pre-registered 75cb7f0, B-frontier10 |
| 2026-10-04T18:31:09+00:00 | s3-v3b/test | EXP-B-005 | a7f83f5856b3 | EXP-B-005 sealed read (pre-registered a7f83f5) |
| 2026-10-05T16:31:35+00:00 | r1-v1/test | EXP-B-006 | 885c825268ca | EXP-B-006 R1-test no-regression (pre-registered db8175f) |
