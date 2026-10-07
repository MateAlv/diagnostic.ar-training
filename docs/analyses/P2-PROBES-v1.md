# P2-PROBES-v1: sizing the Phase 2 candidates on R1 train + dev

- **Date:** 2026-10-07, before [ADR-0017](../decisions/0017-phase-2-real-patient-restart.md).
- **Data:** R1 train + dev (`r1-v1`): 5,986 patients in 1,030 publication groups. These parts are free to read.
  - For R1 test and vault, only case ids and PMIDs were counted (§6). No sealed patient was loaded, no ledger row was added.
- **Code:** `scripts/analysis/p2_probes.py` at `4772852`.
- **Outputs:** `results/analyses/P2-PROBES-v1/`:
  - `report.json`;
  - `sex_limited_genes.json`;
  - `new-since-0.1.27_main-85ffd78.txt`, the phenopacket files on phenopacket-store `main` @85ffd78 that are not in 0.1.27, listed with `gh api`.
- **Method:**
  - E0 (GenPhenAI v3.0, present terms) scores every patient, then each rule changes E0's ranking.
  - Δ MRR is measured against E0 on all patients, with misses counted as 0. It is paired, with a publication-cluster bootstrap (2,000 resamples, seed 0, 95% CI).
  - "Helped" and "harmed" count patients whose true gene ranked higher or lower than under E0. "Top 10 +a/−b" counts true genes that entered or left the top 10.
- **Knowledge:**
  - HPO 2026-02-16 annotations, with every row citing any R1 publication masked;
  - Orphanet ages of onset (2026-06);
  - HGNC chromosome locations.
- **E0 here:** MRR 0.4424.

Every configuration tried is listed, winners and losers (EVAL_PROTOCOL §5): 33 in total.

## 1. Knowledge-only constraints
A demoted gene goes below every other gene. Demoted genes keep their order among themselves.

| Rule | n | Helped | Harmed | Δ MRR [95% CI] | Top 10 |
|---|---|---|---|---|---|
| **Sex:** demote genes whose every disease is limited to the other sex | 5,986 | 187 | 0 | +0.00000 [+0.00000, +0.00000] | +0/−0 |
| Age, lenient onset, margin 0 | 5,986 | 248 | 60 | −0.00256 [−0.00507, −0.00081] | +1/−20 |
| Onset, lenient, margin 0 | 5,986 | 318 | 86 | −0.00638 [−0.01228, −0.00230] | +5/−48 |
| Age, lenient, margin 2 y | 5,986 | 205 | 41 | −0.00115 [−0.00235, −0.00025] | +0/−10 |
| Onset, lenient, margin 2 y | 5,986 | 265 | 29 | −0.00136 [−0.00274, −0.00036] | +3/−13 |
| Age, lenient, margin 5 y | 5,986 | 176 | 31 | −0.00035 [−0.00096, +0.00009] | +0/−4 |
| Onset, lenient, margin 5 y | 5,986 | 240 | 25 | −0.00071 [−0.00173, +0.00003] | +2/−9 |
| **Age, strict, margin 0** | 5,986 | 237 | **0** | **+0.00043 [+0.00014, +0.00079]** | +0/−0 |
| **Onset, strict, margin 0** | 5,986 | 296 | **0** | **+0.00065 [+0.00022, +0.00122]** | +3/−0 |
| Age, strict, margin 2 y | 5,986 | 189 | 0 | +0.00026 [+0.00002, +0.00057] | +0/−0 |
| Onset, strict, margin 2 y | 5,986 | 228 | 0 | +0.00026 [+0.00006, +0.00055] | +2/−0 |
| Age, strict, margin 5 y | 5,986 | 165 | 0 | +0.00016 [+0.00001, +0.00040] | +0/−0 |
| Onset, strict, margin 5 y | 5,986 | 203 | 0 | +0.00024 [+0.00004, +0.00053] | +1/−0 |
| Negation, obligate, hard | 5,986 | 686 | 11 | −0.00014 [−0.00269, +0.00135] | +9/−8 |
| **Sex + age/onset strict** (onset when known, else current age) | 5,986 | **493** | **0** | **+0.00088 [+0.00039, +0.00151]** | +3/−0 |

- **Sex:** a gene is limited to one sex when every disease it causes is. That holds for:
  - Y-chromosome genes outside the pseudo-autosomal regions;
  - Y-linked-only inheritance;
  - disease names for male infertility (spermatogenic failure, azoospermia, sperm flagellum defects, cryptorchidism, hypospadias, persistent Müllerian duct);
  - female-only conditions (ovarian failure or dysgenesis, oocyte maturation defects, hydatidiform mole, early embryonic arrest).

  Sex-reversal and DSD diseases block the rule; for example, SRY causes 46,XY sex reversal in phenotypic females. This gives 100 male-limited and 41 female-limited genes. The 187 patients it helps had their true gene deep in E0's list (median rank 2,593), so MRR barely moves.
- **Age/onset:** the earliest onset of a gene is the lowest onset class (as a lower bound in years) among its diseases.
  - Sources: HPO onset annotations and Orphanet ages.
  - **Lenient** uses any disease with onset data. **Strict** requires every OMIM disease of the gene to have onset data.
  - The gene is demoted when its earliest onset is later than the patient's onset (or current age) plus the margin.
  - 2,786 genes have a strict earliest onset. It is ≥ 1 y for 596 genes, ≥ 5 y for 296, ≥ 16 y for 192 and ≥ 40 y for 7.
- **Negation:** a gene is "contradicted" when every annotated disease of the gene has an obligate phenotype and the patient's excluded terms cover it. Obligate means HP:0040280, "100%", or n/n with n ≥ 5. Covering means an excluded term that is that phenotype or one of its ancestors.

## 2. Soft variants and an X-linked prior
The listed genes' probabilities are multiplied by the factor.

| Rule | Helped | Harmed | Δ MRR [95% CI] | Top 10 |
|---|---|---|---|---|
| Negation, obligate ×0.3 | 336 | 5 | +0.00056 [+0.00016, +0.00106] | +1/−1 |
| **Negation, obligate ×0.1** | 455 | 6 | **+0.00067 [+0.00012, +0.00129]** | +6/−1 |
| Negation, obligate ×0.01 | 577 | 8 | +0.00053 [−0.00043, +0.00131] | +7/−1 |
| Age, lenient, ×0.3 | 158 | 44 | −0.00013 [−0.00053, +0.00016] | +0/−2 |
| Onset, lenient, ×0.3 | 212 | 41 | +0.00017 [−0.00025, +0.00069] | +1/−1 |
| Age, lenient, ×0.1 | 188 | 45 | −0.00003 [−0.00056, +0.00042] | +1/−2 |
| Onset, lenient, ×0.1 | 250 | 45 | +0.00029 [−0.00025, +0.00096] | +3/−2 |
| X-linked recessive ×0.5 for women | 349 | 10 | +0.00025 [−0.00017, +0.00063] | +2/−0 |
| X-linked recessive ×0.3 for women | 433 | 12 | +0.00017 [−0.00047, +0.00068] | +2/−2 |
| X-linked recessive ×0.1 for women | 538 | 14 | +0.00014 [−0.00061, +0.00075] | +3/−2 |
| X-linked dominant ×0.5 for men | 126 | 0 | +0.00004 [+0.00001, +0.00011] | +0/−0 |
| Both: XLR ×0.3 for women, XLD ×0.5 for men | 559 | 12 | +0.00022 [−0.00044, +0.00072] | +2/−2 |

"X-linked recessive only" means all the gene's HPO inheritance terms are X-linked recessive or X-linked (164 genes); "X-linked dominant only" means all are X-linked dominant (23 genes).

## 3. Per-gene priors learned from R1-train, scored on R1-dev (n = 1,883)
Each prior uses a gene's sex, age-band or onset-band counts among R1-train patients, shrunk toward the overall share (strength 5). The weight w is applied as an exponent.

| Prior | w | Helped | Harmed | Δ MRR [95% CI] | Top 10 |
|---|---|---|---|---|---|
| Sex | 0.5 | 115 | 144 | −0.00297 [−0.00814, +0.00098] | +1/−2 |
| Sex | 1.0 | 181 | 214 | −0.00497 [−0.01074, −0.00038] | +3/−27 |
| Age band | 0.5 | 250 | 231 | −0.00534 [−0.02072, +0.00481] | +14/−22 |
| Age band | 1.0 | 296 | 294 | −0.00949 [−0.03429, +0.00662] | +20/−38 |
| Onset band | 0.5 | 105 | 74 | +0.00009 [−0.00214, +0.00213] | +6/−2 |
| Onset band | 1.0 | 119 | 84 | −0.00001 [−0.00377, +0.00310] | +8/−7 |

## 4. How often the doctor's top 10 shows an impossible gene
- **Sex:** 9 of 5,489 patients with a known sex (0.16%) had a gene limited to the other sex in E0's top 10.
- **Age/onset:** 257 of 4,934 patients with a known onset or age (5.2%) had a gene whose every disease starts later (strict rule). Examples: SLC12A3, LIPE, KCNC3, MUC1, PSENEN, DNAJC5, CEL.

## 5. E0 by publication era (home advantage), R1 train + dev
E0 was trained on simulated patients from HPO annotations of 2025-11-24 (DATA_LINEAGE §4).

| Publications | n | Gene in E0's vocabulary | E0 MRR | E0 MRR, in vocabulary |
|---|---|---|---|---|
| In phenopacket-store ≤ 0.1.25 and cited in E0's HPO | 3,190 | 100% | **0.612** | 0.612 |
| In ≤ 0.1.25, not cited | 1,214 | 97% | 0.411 | 0.423 |
| Released after 0.1.25, cited | 548 | 54% | 0.237 | 0.438 |
| **Released after 0.1.25, not cited ("post-E0")** | 1,034 | 52% | **0.066** | 0.127 |

The safe rules on the post-E0 patients:

| Rule | n | Helped | Harmed | Δ MRR [95% CI] |
|---|---|---|---|---|
| Sex + age/onset strict | 1,034 | 263 | 0 | +0.00010 [+0.00003, +0.00020] |
| Negation ×0.1 | 1,034 | 92 | 0 | +0.00003 [+0.00000, +0.00012] |

## 6. Candidate sets for ADR-0017 (case-level counts)
These counts use each patient's own PMIDs; the frozen split counts publication groups.

| r1-v1 part | ≤ 0.1.25, cited | ≤ 0.1.25, not cited | After 0.1.25, cited | **After 0.1.25, not cited** |
|---|---|---|---|---|
| train | 1,958 | 1,006 | 456 | 683 |
| dev | 1,232 | 208 | 92 | 351 |
| test | 1,066 | 929 | 140 | **413** |
| vault | 947 | 260 | 245 | **319** |

- **New on phenopacket-store `main` since 0.1.27** (@85ffd78, 2026-10-07): 406 patients, all from publications not in 0.1.27.
  - 349 come from publications cited in neither HPO 2025-11-24 nor 2026-02-16.
  - 57 come from publications cited in both.

## Reading
- **Knowledge-only rules help with no harm, but only when the knowledge is complete.**
  - The strict onset rule moves no true gene down in 5,986 patients; the lenient one moves 60 to 86 down.
  - Sex + age/onset strict: +0.00088 [+0.00039, +0.00151].
  - The soft obligate negation (×0.1) adds +0.00067 [+0.00012, +0.00129], with 6 harmed.
- **Per-gene sex and age statistics learned from R1-train do not carry to new publications** (sex, w 1: −0.00497 [−0.01074, −0.00038]). Learned Phase 2 models therefore use gene-agnostic features.
- **E0's MRR depends strongly on whether it saw the publication:** 0.612 when its HPO cites it, 0.066 for post-E0 publications.
  - Only about half of post-E0 patients have a gene in E0's 5,229-gene vocabulary (ADR-0006).
  - Phase 2's final check uses post-E0 publications for this reason.
