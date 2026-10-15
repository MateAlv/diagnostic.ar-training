# P4-AGE: a certain age rule on top of the network

- **Date:** 2026-10-15. `p3-v1` train folds 0–3 only, read out of fold. No CONFIRM read, no vault patient
  read, no fitting.
- **Code:** `src/diagnostic_ar_training/v4/agerule.py` (knowledge `age-kb/1` and the rule `AgeRule`),
  `scripts/analysis/p4_age/` (`kb.py`, `harm.py`, `read.py`), `tests/test_v4_agerule.py`. Knowledge
  `age-kb-v1` (built from 2b56874): stats `data/p4-age/age-kb-v1.stats.json`, manifest
  `data/manifests/age-kb-v1.json`. Numbers: `results/P4/age/harm.json` (every variant, run from ceb03fe) and
  `results/P4/age/oof.json` (the chosen rule, run from 1588d87).
- **Rule:** a gene whose certain earliest onset is later than the patient's latest possible onset plus a
  margin is moved below every other gene (their own order kept, `sexrule.block`); unknown age and onset change
  nothing. Pure numpy (`AgeRule`), applied to any score vector: the network's logits or F1's scores.
- **Chosen variant, `age-v1`:** only late-onset genes (certain earliest onset ≥ 60 years: 16 genes), margin 30
  years, the patient's ages in years only. It harms no dev patient, **but no dev patient has one of its 16
  genes as true gene, so the harm check could not fail** (§2, §4).
- **Metric:** as P4-SEX. Capped MRR (10 patients per publication), Δ with the publication-cluster bootstrap
  (`v4.report`); plain MRR Δ; helped / harmed are patient counts. "Removed above" counts the patients with at
  least one removed gene ranked above their true gene. F1 = network + `p3-addon-v1-all` (`v4.addon.Addon`); it
  was fitted on these folds, so F1's own Δ is in-sample (the rules' Δ on top of it is not fitted at all).

## 1. Readings, pooled over folds 0–3 (5,053 patients)

The network alone reproduces +0.0714 (uncited, capped, vs E0), F1 reproduces +0.000149 vs the network, and
the sex rule reproduces P4-SEX (130 / 0 uncited on the network, 110 / 0 on F1). "age" is `age-v1`; "sex" is
the hard sex rule on `sex-kb-v2`; "age + sex" moves the union of their genes to the bottom.

| Comparison | Stratum | n (pubs) | capped MRR (ref) | Δ capped [95% CI] | Δ MRR [95% CI] | helped / harmed | removed above |
|---|---|---|---|---|---|---|---|
| network vs E0 | uncited | 2,316 (402) | 0.2840 (0.2126) | +0.0714 [+0.0488, +0.0962] | +0.0399 [+0.0064, +0.0812] | 631 / 551 | |
| | uncited in-vocab | 1,633 (311) | 0.4375 (0.3287) | +0.1088 [+0.0755, +0.1446] | +0.0566 [+0.0088, +0.1304] | 631 / 551 | |
| | cited | 2,737 (412) | 0.7355 (0.6758) | +0.0597 [+0.0368, +0.0829] | +0.0683 [+0.0392, +0.0953] | 832 / 442 | |
| **network + age vs network** | uncited | | | **+9.3e-9 [+3.8e-9, +1.7e-8]** | +1.0e-8 [+3.1e-9, +2.2e-8] | **49 / 0** | 49 |
| | uncited in-vocab | | | +1.4e-8 [+5.5e-9, +2.4e-8] | +1.5e-8 [+4.3e-9, +3.2e-8] | 49 / 0 | 49 |
| | cited | | | +1.3e-10 [0, +4.1e-10] | +1.7e-10 [0, +5.6e-10] | 4 / 0 | 4 |
| network + sex vs network | uncited | | | +2.4e-6 [+8.9e-8, +7.0e-6] | +1.6e-6 [+6.2e-8, +5.1e-6] | 130 / 0 | 130 |
| | uncited in-vocab | | | +3.6e-6 [+1.4e-7, +1.1e-5] | +2.3e-6 [+9.9e-8, +7.4e-6] | 130 / 0 | 130 |
| | cited | | | +9.1e-7 [0, +2.8e-6] | +5.6e-7 [0, +1.9e-6] | 4 / 0 | 4 |
| **network + age + sex vs network** | uncited | | | **+2.4e-6 [+9.7e-8, +7.0e-6]** | +1.6e-6 [+7.3e-8, +5.2e-6] | **134 / 0** | 134 |
| | uncited in-vocab | | | +3.6e-6 [+1.5e-7, +1.1e-5] | +2.3e-6 [+1.1e-7, +7.4e-6] | 134 / 0 | 134 |
| | cited | | | +9.1e-7 [0, +2.8e-6] | +5.6e-7 [0, +1.9e-6] | 6 / 0 | 6 |
| network + age + sex vs network + sex | uncited | | | +9.3e-9 [+3.8e-9, +1.7e-8] | +1.0e-8 [+3.1e-9, +2.2e-8] | 49 / 0 | |
| | cited | | | +1.3e-10 [0, +4.1e-10] | +1.7e-10 [0, +5.6e-10] | 4 / 0 | |
| network + age + sex vs E0 | uncited | | 0.2840 (0.2126) | +0.0714 [+0.0488, +0.0962] | +0.0399 [+0.0064, +0.0812] | 632 / 550 | |
| | uncited in-vocab | | 0.4375 (0.3287) | +0.1088 [+0.0755, +0.1446] | +0.0566 [+0.0088, +0.1304] | 632 / 550 | |
| | cited | | 0.7355 (0.6758) | +0.0597 [+0.0368, +0.0829] | +0.0683 [+0.0392, +0.0953] | 832 / 442 | |
| F1 vs network (in-sample) | uncited | | 0.2841 (0.2840) | +0.0001 [−0.0014, +0.0015] | +0.0007 [−0.0006, +0.0018] | 334 / 25 | |
| **F1 + age vs F1** | uncited | | | **+9.1e-9 [+3.7e-9, +1.6e-8]** | +1.0e-8 [+3.0e-9, +2.2e-8] | **49 / 0** | 49 |
| | uncited in-vocab | | | +1.4e-8 [+5.3e-9, +2.4e-8] | +1.5e-8 [+4.1e-9, +3.3e-8] | 49 / 0 | 49 |
| | cited | | | +1.3e-10 [0, +4.1e-10] | +1.7e-10 [0, +5.7e-10] | 4 / 0 | 4 |
| F1 + sex vs F1 | uncited | | | +9.5e-7 [+6.0e-8, +2.7e-6] | +6.5e-7 [+4.4e-8, +2.0e-6] | 110 / 0 | 110 |
| **F1 + age + sex vs F1** | uncited | | | **+9.6e-7 [+6.8e-8, +2.7e-6]** | +6.6e-7 [+5.4e-8, +2.0e-6] | **116 / 0** | 116 |
| | uncited in-vocab | | | +1.5e-6 [+1.1e-7, +4.2e-6] | +9.4e-7 [+8.1e-8, +2.9e-6] | 116 / 0 | 116 |
| | cited | | | +9.1e-7 [0, +2.8e-6] | +5.6e-7 [0, +1.9e-6] | 6 / 0 | 6 |
| F1 + age + sex vs F1 + sex | uncited | | | +9.2e-9 [+3.7e-9, +1.6e-8] | +1.0e-8 [+3.0e-9, +2.2e-8] | 49 / 0 | |
| F1 + age + sex vs E0 | uncited | | 0.2841 (0.2126) | +0.0715 [+0.0488, +0.0963] | +0.0406 [+0.0069, +0.0804] | 639 / 544 | |
| | uncited in-vocab | | 0.4377 (0.3287) | +0.1090 [+0.0762, +0.1450] | +0.0576 [+0.0099, +0.1300] | 639 / 544 | |
| | cited | | 0.7359 (0.6758) | +0.0601 [+0.0373, +0.0831] | +0.0686 [+0.0393, +0.0955] | 837 / 437 | |

Network + age vs E0 and F1 + age vs E0 equal the base vs E0 to four decimals in every stratum. No rule makes
any patient's rank worse on either base (`checks.rules_worse_any_patient` = 0).

**Per fold** (helped / harmed; every Δ of a rule is below 1.3e-5 in absolute value, the age rule's below
4e-8):

| Fold | uncited n (pubs) | network vs E0 | net + age vs net | net + age + sex vs net | F1 + age vs F1 | F1 + age + sex vs F1 | cited: net + age / + age + sex |
|---|---|---|---|---|---|---|---|
| 0 | 498 (112) | +0.0588 | 8 / 0 | 66 / 0 | 8 / 0 | 52 / 0 | 0 / 0, 0 / 0 |
| 1 | 630 (113) | +0.0890 | 22 / 0 | 39 / 0 | 22 / 0 | 37 / 0 | 4 / 0, 5 / 0 |
| 2 | 453 (84) | +0.0833 | 14 / 0 | 23 / 0 | 14 / 0 | 22 / 0 | 0 / 0, 0 / 0 |
| 3 | 735 (93) | +0.0511 | 5 / 0 | 6 / 0 | 5 / 0 | 5 / 0 | 0 / 0, 1 / 0 |

Per stratum and fold, every number is in `results/P4/age/oof.json`.

**What a doctor sees** (network's out-of-fold lists, scored patients the rule touches: 3,501 for age, 4,631
for sex, 4,801 for either): patients whose top k shows a gene the rule blocks.

| Shown in | age (`age-v1`) | sex (`sex-kb-v2`) | age + sex |
|---|---|---|---|
| first place | 0 | 1 (1 gene) | 1 (1) |
| top 5 | 0 | 2 (3) | 2 (3) |
| top 10 | 0 | 10 (15) | 10 (15) |
| top 50 | 3 (3 genes) | 48 (80) | 51 (83) |

**Reading.** The chosen age rule is safe on dev and almost empty: it helps 49 uncited patients by a few ranks
far down the list (Δ ≈ 1e-8); none of the genes it blocks is in a top 10, and 3 are in a top 50. With the sex
rule it adds 4 helped uncited patients to the sex rule's 130 on the network (6 on F1). Its "0 harmed" is not
evidence of certainty: none of the 5,053 dev patients has one of its 16 genes as true gene (§2).

## 2. Every variant tried (harm check, `harm.py`)

Patients whose true gene a variant blocks, over all 5,053 dev patients. Dimensions, all chosen on these dev
patients and all disclosed here:
- **min earliest:** the onset classes allowed to block, as the lowest gene bound that blocks: 1 (every class
  above congenital/neonatal/infantile), 5 (juvenile and later), 16 (adult classes), 25, 40 (middle age or
  later), 60 (late onset only).
- **margin:** 0, 5, 10, 15, 20, 30 years added to the patient's latest onset.
- **patient side:** `classes` (onset years, upper end of the onset class, per-symptom onsets, current age;
  4,465 patients have a value) or `years` (no onset class; 4,160).
- **gene side:** `rows` (`age-kb-v1`'s bound, lowered by HPOA's per-phenotype onsets) or `classes` (aspect C
  onset classes alone).

Cells: **harmed (uncited harmed) / helped uncited + cited** (helped: true gene not blocked, at least one
blocked gene above it on the network). "Exposed" counts the patients whose true gene the variant could block
at all (its bound is at least min earliest).

`rows` gene bound, `classes` patient side:

| min earliest (blockable genes, exposed) | margin 0 | 5 | 10 | 15 | 20 | 30 |
|---|---|---|---|---|---|---|
| 1 (360, 187) | 31 (21) / 286+102 | 19 (13) / 254+68 | 17 (13) / 240+54 | 13 (12) / 160+46 | 8 (8) / 113+10 | 4 (4) / 104+9 |
| 5 (233, 67) | 23 (13) / 275+85 | 19 (13) / 254+68 | 17 (13) / 240+54 | 13 (12) / 160+46 | 8 (8) / 113+10 | 4 (4) / 104+9 |
| 16 (156, 52) | 23 (13) / 268+72 | 19 (13) / 254+68 | 17 (13) / 240+54 | 13 (12) / 160+46 | 8 (8) / 113+10 | 4 (4) / 104+9 |
| 25 (27, 17) | 13 (13) / 129+15 | 13 (13) / 126+15 | 13 (13) / 125+11 | 12 (12) / 122+10 | 8 (8) / 113+10 | 4 (4) / 104+9 |
| 40 (25, 17) | 13 (13) / 127+14 | 13 (13) / 124+14 | 13 (13) / 123+11 | 12 (12) / 121+10 | 8 (8) / 112+10 | 4 (4) / 104+9 |
| 60 (16, **0**) | 0 / 66+4 | 0 / 63+4 | 0 / 62+4 | 0 / 61+4 | 0 / 53+4 | 0 / 53+4 |

`rows` gene bound, `years` patient side:

| min earliest | margin 0 | 5 | 10 | 15 | 20 | 30 |
|---|---|---|---|---|---|---|
| 1 | 26 (18) / 249+82 | 17 (13) / 209+55 | 15 (13) / 183+35 | 11 (11) / 120+20 | 7 (7) / 89+8 | 4 (4) / 77+6 |
| 5 | 21 (13) / 238+74 | 17 (13) / 209+55 | 15 (13) / 183+35 | 11 (11) / 120+20 | 7 (7) / 89+8 | 4 (4) / 77+6 |
| 16 | 21 (13) / 231+65 | 17 (13) / 209+55 | 15 (13) / 183+35 | 11 (11) / 120+20 | 7 (7) / 89+8 | 4 (4) / 77+6 |
| 25 | 13 (13) / 102+13 | 13 (13) / 98+13 | 13 (13) / 97+9 | 11 (11) / 94+8 | 7 (7) / 89+8 | 4 (4) / 77+6 |
| 40 | 13 (13) / 100+12 | 13 (13) / 96+12 | 13 (13) / 95+9 | 11 (11) / 93+8 | 7 (7) / 88+8 | 4 (4) / 77+6 |
| **60** | 0 / 59+4 | 0 / 56+4 | 0 / 55+4 | 0 / 53+4 | 0 / 50+4 | **0 / 49+4 (`age-v1`)** |

- `classes` gene bound (no per-phenotype onsets): identical harm in all 72 cells; it blocks 4 more genes at
  min earliest 1 and 3 more at 5, which only adds helped patients at margin 0 (289+116 and 275+86 on the
  `classes` patient side, 251+89 and 238+74 on `years`).
- Reference, `p3-addon-kb-v1`'s strict onsets (only OMIM diseases need an onset class; ceiling.py's bound),
  margin 0: 58 (47) / 363+200 on `classes`, 50 (41) / 311+157 on `years`; 2,548 blockable genes, 1,808
  exposed.
  Requiring every disease, ORPHA ones included, removes 5 harmed genes (IKZF1, NRL, LGI1, PARK7, GAA, §3).
- Exposed patients: 187 at min earliest 1, 67 at 5, 52 at 16, 17 at 25 and 40, **0 at 60**. Every variant
  that can harm anyone does: the smallest harm with any exposure is 4 (margin 30), all TUBA4A.

## 3. Harmed patients: the knowledge, not the data

Every harmed patient, over every variant (`harm.json`, `harmed_patients`):

| Gene | Patients | Gene bound | Patients' latest onset | E0's diseases and onset classes | Why |
|---|---|---|---|---|---|
| TUBA4A | 13 uncited (PMIDs 37024973, 38413182, 38884572) | 40 | 0.1–25 y | ALS 22 ± FTD (OMIM:616208): middle age, late | Knowledge incomplete: the 2023–24 publications report onsets from infancy to 25 years, which E0's only TUBA4A disease does not cover |
| TAF4 | 8 cited (33875846, 35904126) | 16 | 0.1–14 y | Intellectual developmental disorder (OMIM:620450): young adult | Annotation error: an intellectual developmental disorder annotated "young adult onset"; patients are infants and children |
| EMILIN1 | 6 uncited (36351433) | 1 | 0–0.08 y (antenatal, congenital, neonatal) | Distal hereditary motor neuronopathy X (OMIM:620080): childhood | Knowledge too narrow: the publication reports onset before or at birth |
| SOCS1 | 2 uncited (32853638, 36890397) | 1 | 0.4 y | Autoinflammatory syndrome ± immunodeficiency (OMIM:619375): childhood to middle age | Knowledge too narrow: onset at 5 months, below the childhood class |
| SPATA22 | 2 cited (35285020) | 16 | 13–14 y | Spermatogenic failure 96, POF 25: young adult | Class boundary: a pubertal sign (onset 13–14) of a disease annotated from 16 |
| IKZF1, NRL, LGI1, PARK7, GAA | 12 + 4 + 6 + 1 + 4 (reference only) | 1–16 in `p3-addon-kb-v1` | 0–13 y | each has an unannotated ORPHA disease; GAA's OMIM Pompe disease is annotated "young adult" only | Not blocked by `age-kb-v1` (every disease must be annotated) |

No harmed case is a data error: each patient's onset or age agrees with its publication's phenotype (infants
with an intellectual disability, congenital neuropathy, childhood TUBA4A disease). The onsets in HPOA
2025-03-03 are typical onsets, often from OMIM clinical synopses, and miss the earliest cases, especially
those published after the annotation (TUBA4A, EMILIN1) or never re-curated (TAF4, GAA).

## 4. The chosen rule and why

- **Protocol:** the strictest variant with 0 harmed that still blocks something. Only min earliest 60 reaches
  0 harmed, at every margin and on both patient sides; the strictest of those is margin 30, `years` patient
  side, `rows` gene bound: `age-v1` (`agerule.MIN_EARLIEST_YEARS`, `MARGIN_YEARS`, `ONSET_CLASSES`). It blocks
  the 16 late-onset genes for patients whose disease started before 30. The `years` side is also what the
  production API carries (age and onset in years, no onset class).
- **Its 0 harmed is vacuous.** No dev patient has one of the 16 genes as true gene, so the check could not
  fail. Every variant with exposed patients (any gene annotated earlier than late onset) harms 4 to 31. The
  rule's certainty rests only on HPOA's "late onset" annotation, the same annotation type that §3 shows wrong
  for TAF4, GAA and TUBA4A.
- **The 16 genes:** 12 are type 2 diabetes susceptibility genes (GPD2, HMGA1, IGF2BP2, IRS1, IRS2, MAPK8IP1,
  MTNR1B, PPP1R3A, PTPN1, RETN, SLC30A8, TCF7L2; OMIM:125853, "Diabetes mellitus, noninsulin-dependent"),
  plus BLVRA (hyperbiliverdinemia), HMCN1 (age-related macular degeneration 1), KLKB1 (prekallikrein
  deficiency) and KRT18 (familial cirrhosis). For some of them late onset is clinically doubtful as a hard
  bound (type 2 diabetes occurs in adolescents and young adults; prekallikrein deficiency is usually found as
  a prolonged aPTT at any age). Worth a clinical look before shipping.
- **Assessment:** dropping age is the plainer option. `age-v1` changes no top 10 and about 1e-8 of capped
  MRR, and its safety cannot be shown on dev. Keeping it is defensible only as a guard against showing a child
  a late-onset susceptibility gene, with the caveat above.

## 5. Knowledge: `age-kb-v1` (`age-kb/1`)

**Sources.** E0's knowledge only, as `p3-addon-kb-v1`: HPOA 2025-03-03 (unmasked; aspect C onset classes and
the onset column of phenotype rows, NOT and zero-frequency rows skipped), the 2025-03-03 ontology (the onset
subtree under HP:0003674), E0's gene list and gene → disease links (`e0_genes_to_phenotype`,
GraPhens@7aef83d). No Orphanet, no HGNC. `p3-addon-kb-v1` is a manifest input for the comparison only. A test
checks that the build opens exactly the three sources.

**Rules** (fixed before any patient was read):
- a disease's bound is the lowest `safe.knowledge.HPO_ONSET_LOWER` of its onset classes; its phenotype rows'
  onsets can only lower it (19 genes lowered). A disease without an onset class, or with an onset term outside
  the table (puerperal, perimenopausal, postmenopausal), has no bound;
- a gene has a bound only if it has diseases and **every** one, ORPHA included, has a bound: the minimum.
- patient side: `agerule.ONSET_UPPER` gives each class's upper end (the values of ceiling.py's `UPPER`); adult
  and late onset have no upper end.

**Counts** (E0's 5,229 genes): 1,203 with a bound (100 without diseases, 3,926 with a disease lacking an onset
class). Bounds: antenatal (−1) 90, 0 753, 1 127, 5 77, 16 129, 25 2, 40 9, 60 16. `p3-addon-kb-v1` gives 2,743
genes a bound; every `age-kb-v1` bound is one of them, equal or lower.

## 6. Caveats

- **Certainty is relative to HPOA 2025-03-03.** A gene with an early-onset form E0's knowledge does not link
  would be wrongly blocked, and dev cannot show that for `age-v1`'s genes.
- **Patient ages read the start of a range.** The phenopacket parser reads an `ageRange` as its start, for
  onset and for the current age, so an onset given as a range can be later than the value read; the 30-year
  margin covers ranges up to 30 years.
- Every number in §2 is a choice made on dev patients, disclosed. Nothing was fitted; the grid was fixed
  before it was run, and only the reading in §1 was run after the choice.
