# ADR-0015: Does symptom-onset age help the re-ranker? A fair test on S3 v3

- **Status:** Accepted, 2026-10-04 (Mateo: "let's do onset follow up").
  Written before any S3 v3 data exists.
- **Context:** EXP-B-004's sealed read showed F + onset 0.5 at +0.0124 vs
  F's +0.0066, with harm 4.99%.
  - On the **fair subset** (cases whose generator onset came from the
    literature, n = 509) the gain over F was +0.0021 [−0.0027, +0.0063].
  - So the overall gain was probably mostly source overlap: for about 95% of
    S3 v2 cases, the generator and the re-ranker both used HPOA/Orphanet
    onset.
  - Promoting onset on that read would mean selecting on test, so it needs
    its own fair, pre-registered test.

## S3 v3 design
1. **Every case is a fair onset case.**
   - Generate only for genes whose simulated entity has a literature onset
     row (`onset-ages-v2`), so 100% of cases take their onset from the
     literature.
   - The re-ranker's onset feature uses only the knowledge onset (HPOA first,
     Orphanet fallback; kb-v6). The two sources are independent extractions
     of the same truth.
2. **Generator:** the same as S3 v2 (simulator 0.5.4 at cfc20da from
   `sim-pins/`, `simcal-s3-v2`, full profiles from `hpoa-enriched-v2`,
   `--onset-ages onset-ages-v2`, `--presentation-ages presentation-ages-v2`).
   **Seed 4004.**
   - Cases per gene = ceil(10,000 / eligible genes), for about 10,000 cases.
   - Onset missingness stays realistic (simcal's `onset_unknown`).
3. **Knowledge:** reuse `annot-split-v2`. Systems use kb-v6, with half B
   dropped.
4. **Split `s3-v3`:** **dev 30% / test 70%**, frozen and committed before
   any system runs. The test is larger for statistical power; dev is only
   for choosing the weight. **Test is sealed:** one read, guarded by
   `DXT_SEALED_READ`.
5. **Contamination:** signatures vs R1, S3 v1, S3 v2 and all simulated
   training data, with an exclusion list.

## Systems and selection
- **Interview:** **Q2b** (λ 0.6), the production default since 2026-10-03,
  budget 9, noise 0.
- **Reference:** F (`8ecd5b320f33`).
- **Candidate:** F + onset with weight w ∈ {0.25, 0.5, 1}, at most 3 dev
  configurations, all logged.
- **Selection on dev:** maximise the paired Δ (F + onset − F) subject to the
  whole system's harmed share vs E0+answers ≤ 5% and the R1-dev no-harm
  check. A tie goes to the smaller w.

## Primary hypothesis and gate (EXP-B-005)
- **P1:** on S3-v3-test, the paired difference (F + onset_w) − F has a
  bootstrap 95% CI over genes with lower bound > 0, and the harmed share of
  F + onset_w vs E0+answers is ≤ 5%.
- **Secondary:**
  - the same on known-onset cases only;
  - split by the kb `onset_source`.
- **If P1 passes and Mateo wants a release:** one pre-registered R1-test
  no-regression read (the EXP-B-003 N1/N2 rules), then `rerank-v1.1.0`.

## Deployment prerequisite (declared now)
- The app does **not** collect symptom-onset age today:
  - the question agent only uses disease onset from its knowledge;
  - the website stores sex and birth date only.
- An onset feature can only help in production if the app asks for it,
  e.g. "¿A qué edad empezaron los síntomas?". That is a product change,
  outside this experiment.

## Order
| Phase | Work |
|---|---|
| 1 | Build S3 v3, freeze the split, contamination checks |
| 2 | Dev selection of w (≤ 3) |
| 3 | Pre-registration addendum, then one sealed S3-v3-test read |

## Addendum, 2026-10-04: S3 v3 phase 1 done
- **Eligible genes: 120** (126 entities; every drawable entity of the gene has an `onset-ages-v2` row), so 84 cases
  per gene. This is far fewer than the 4,892 genes of S3 v2; the gene-level bootstrap has 120 clusters.
  277 more genes have only some entities listed and are left out, because their cases would not all use literature onset.
- `s3-data-v3`: 10,080 cases, 100% literature onset, onset reported on 59.43%, sex known on 92.06%.
- Split `s3-v3` frozen before any system ran: dev 3,106, test 6,974 (sealed), content sha256
  `746ca7bca7efa24eb4e5497731a063a4d092dc8ced55b1f0ef0993a0e56164db`.
- Exclusion list `s3-data-v3-excl-v1`: 24 cases (dev 9, test 15), residual overlap 0.
