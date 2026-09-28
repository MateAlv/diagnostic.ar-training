# Sealed-split ledger

`diagnostic_ar_training.lineage.ledger` appends one row per read of a sealed
part (R1 test/vault). Do not edit rows; commit this file with the results
they produced. Gate reads of R2/R3 are logged here by hand in the same format.
Rules: `docs/EVAL_PROTOCOL.md` §2.

| UTC time | split/part | experiment | code SHA | reason |
|---|---|---|---|---|
