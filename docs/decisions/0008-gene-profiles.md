# ADR-0008: Gene profiles from open sources, and how a gene's diseases are weighted

- **Status:** Accepted, 2026-09-29.
- **Artifact:** `genes-v1` onward.

## Context
The GNN predicts genes, but patients have diseases, and a gene can cause
several of them. To simulate a patient for gene G, the simulator must pick
which of G's diseases the patient has, and with what inheritance. Part 1 of
the simulator labelled multi-gene diseases with the alphabetically first
gene, and had no notion of how likely each of a gene's diseases is.

Mateo proposed GeneCards. Its terms forbid AI training without written
permission (BITACORA 2026-09-29, `docs/TODO.md`), so profiles are built from
the open sources GeneCards itself aggregates. All are pinned in
`data/sources.yaml`:

| Source | Contributes | License |
|---|---|---|
| HGNC complete set | Approved symbol, aliases, previous symbols, chromosome, locus type | CC0 |
| HPO `genes_to_disease` (+ `genes_to_phenotype` pairs) | Gene–disease links used by the HPO | HPO license |
| Orphanet product 6 (2026-06-23) | Association type and status | CC-BY-4.0 |
| ClinGen gene–disease validity | Curated strength + mode of inheritance per pair | CC0 |
| MONDO (v2026-09-01) | MONDO → OMIM/ORPHA equivalences, to join ClinGen | CC-BY-4.0 |
| Orphanet product 1 (2026-06-23) | Exact, validated OMIM ↔ ORPHA equivalences | CC-BY-4.0 |
| ClinVar variant_summary (2026-09) | Pathogenic/likely-pathogenic germline variant counts per (gene, condition) | Public domain |
| Orphanet product 9 prevalence (2026-06-23) | Prevalence class per disorder (recorded, not weighted in v1) | CC-BY-4.0 |

## Decision
1. **Disease entities.** OMIM and ORPHA ids that are exactly equivalent are
   one entity. "Exactly equivalent" means Orphanet exact + validated
   alignments, or the same MONDO class with `MONDO:equivalentTo`. The
   entity's primary id is its OMIM id if it has one, else its ORPHA id.
   `profile_ids` lists the entity's ids that have HPOA phenotypes after the
   held-out-PMID mask; only those can be simulated.
2. **Validity factor** `v`, the first rule that applies:

   | Rule | Values |
   |---|---|
   | ClinGen curation exists (max over curations) | Definitive 1.0, Strong 1.0, Moderate 0.6, Limited 0.3, Disputed 0.05, Refuted 0, No Known Disease Relationship 0 |
   | Else Orphanet association (max over associations) | disease-causing germline (any, incl. LoF/GoF) 1.0, role in the phenotype 0.5, major susceptibility factor 0.3, modifying germline mutation 0.2, candidate gene tested 0.1; somatic / fusion / biomarker 0 (our patients' variants are germline). ×0.5 if the association status is "Not yet assessed" |
   | Else an HPO link only | 1.0 |

3. **Evidence factor:** `sqrt(1 + c)`, where `c` is the number of distinct
   ClinVar P/LP germline GRCh38 alleles of that single gene annotated to any
   id of the entity. It is sublinear, so a heavily sequenced disease does not
   swamp the others.
4. **Weight:** `w = v × sqrt(1 + c)`, normalised over the gene's simulable
   entities (`sim_weight`). Entities with `v = 0` stay listed, with the
   reason, but get no weight.
5. **Inheritance per (gene, entity):** ClinGen mode of inheritance when
   curated:

   | ClinGen | HPO term |
   |---|---|
   | AD | HP:0000006 |
   | AR | HP:0000007 |
   | XL | HP:0001417 |
   | MT | HP:0001427 |
   | SD | HP:0032113 |
   | UD | none |

   Otherwise the HPOA aspect-I terms of the entity's profiles are used.
6. **Symbols** resolve to HGNC-approved symbols; previous symbols win over
   aliases, and ambiguous aliases are not resolved. The v3.0 vocabulary
   keeps its own spelling, and the profile records the approved symbol next
   to it.

## Alternatives dropped
- **GeneCards.** A license restriction (see above).
- **Uniform weight over a gene's diseases** (what `kb-v1` does). This ignores
  that some links are candidate or refuted, and that some diseases are far
  more common for a gene.
- **Prevalence as a weight.** Orphanet prevalence covers ORPHA entities, is
  population-level, and 30% of its records are "Unknown" or empty. It is
  recorded, so the simulator's ablation A-006 can test it.
- **Linear ClinVar counts.** They over-reward genes' most-sequenced
  disease.

## Validation
The weights are calibrated only against **R1-train**. For train patients
whose gene has ≥ 2 simulable entities, we measure how often the patient's own
disease is the gene's top-weighted entity, compared with uniform weighting.
Dev, test and vault are never used here (`EVAL_PROTOCOL.md` §4.3).

**Result** (`dxt genes calibrate --id genes-v1`,
`results/genes-v1/calibration-r1-train.json`). 2,544 train patients from 418
publications, with 4.18 candidate diseases per gene on average. Weight
`v × (1 + c)^γ`:

| γ | Mean log p(true disease) | Top-1 | Mean p |
|---|---|---|---|
| uniform | — | — | 0.346 |
| 0 (validity only) | −1.060 | 0.264 | 0.417 |
| 0.25 | −0.849 | 0.642 | 0.514 |
| **0.5 (ADR)** | **−0.777** | 0.642 | 0.574 |
| 0.75 | −0.781 | 0.642 | 0.607 |
| 1.0 (linear) | −0.825 | 0.642 | 0.626 |
| 1.5 | −0.964 | 0.643 | 0.643 |

- γ = 0.5 maximises log-likelihood, so the pre-specified weight is kept.
- It was also best or tied on held-out halves in a 2-fold split by
  publication *within train* (A→B: best 0.5; B→A: fitted 0.75 but 0.5
  scored higher on the held-out half).
- Linear weights look better on mean p but are overconfident, and they lose
  on log-likelihood.

## Leakage note
ClinVar and ClinGen evidence cites publications, some of which may be R1
papers. Neither contributes phenotype terms: they only shift a disease's
weight within its gene. This is declared in `DATA_LINEAGE.md` §5.
