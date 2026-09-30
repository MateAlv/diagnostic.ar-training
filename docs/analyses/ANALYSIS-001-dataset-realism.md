# ANALYSIS-001: How realistic are our simulated patients, and is the disease→phenotype design at fault?

- **Date:** 2026-09-30.
- **Asked by:** Mateo, after Front A's negative results (EXP-A-001,
  A-002f, A-003f).
- **Data used:** R1-dev (its publications are masked from every profile,
  so it is out of sample for the simulator) and R1-train (fits only). No
  sealed data.
- **Literature:** checked by two research agents against GeneReviews,
  Orphanet, OMIM and published cohorts. Every literature number below
  carries its source in the agents' reports, quoted in §4.

## 1. Questions
1. Does building profiles as **disease → phenotypes**, weighted per gene,
   hurt, compared with using **gene → phenotypes** directly, as v3.0's
   upstream simulator did?
2. How good is the dataset we generated, and how was it evaluated?

## 2. What had been evaluated before this analysis
| Check | Done? | What it shows |
|---|---|---|
| Invariants (`validate`: sex-restricted terms, excluded vs true, onset ≤ age…) | ✅ | Internal consistency |
| Frequency calibration (simulated vs profile frequencies) | ✅ | The simulator follows its profiles |
| Aggregate targets vs R1-train (counts, missingness, negation mix) | ✅ (`calib-v1`) | Averages match |
| Contamination vs S3/R1 | ✅ | No overlap |
| **Per-disease realism vs real patients and literature** | ❌ until now | — |

## 3. Quantitative results

### 3.1 Ten genes, three generators, against R1-dev real patients
- **Genes:** NF1, LMNA, FBN1, PTPN11, KMT2D, TBX5, UMOD, FBXL4, SPTAN1,
  ITPR1.
- **Metric:** rank correlation between real and generated term
  frequencies, over the gene's annotated terms (ancestor closure).
- **Generators:**
  - ours: full profiles, `simcal-s3-v1`, 200 cases per gene, seed 777;
  - upstream: the gene→phenotype simulator v3.0 was trained on, 10 cases
    per gene.

| Gene | Real n | ρ ours | ρ upstream | Terms/case real / ours / upstream |
|---|---|---|---|---|
| NF1 | 151 | 0.14 | 0.58 | 2.3 / 13.0 / 4.9 |
| LMNA | 171 | 0.17 | 0.48 | 8.9 / 9.8 / 4.3 |
| FBN1 | 42 | 0.11 | 0.50 | 8.7 / 13.8 / 6.0 |
| PTPN11 | 29 | 0.33 | 0.52 | 7.2 / 14.3 / 3.5 |
| KMT2D | 29 | 0.04 | −0.05 | 9.4 / 28.0 / 4.6 |
| TBX5 | 28 | 0.00 | 0.55 | 3.7 / 9.2 / 4.8 |
| UMOD | 36 | 0.00 | 0.39 | 3.2 / 4.2 / 4.4 |
| FBXL4 | 50 | −0.14 | 0.11 | 11.4 / 10.4 / 4.8 |
| SPTAN1 | 43 | −0.16 | 0.31 | 5.8 / 8.1 / 5.9 |
| ITPR1 | 36 | 0.22 | 0.50 | 7.7 / 9.9 / 5.7 |
| **Mean** | | **0.07** | **0.39** | |

Both generators' term *sets* cover 97–100% of what real patients report:
`genes_to_phenotype` is itself the union of the gene's HPOA disease rows.
The gap is in *which* terms get emitted and *how many*.

### 3.2 HPO frequency barely predicts what real reports contain (64 dev genes with ≥ 5 patients)
Mean within-gene Spearman(HPOA frequency, real reporting rate) = **0.02**
with `kb-v3`, and 0.07 with `kb-v4`.

| HPOA frequency | Real reporting rate |
|---|---|
| 0.0–0.2 | 0.047 |
| 0.2–0.4 | 0.133 |
| 0.4–0.6 | 0.128 |
| 0.6–0.8 | 0.072 |
| 0.8–1.0 | 0.343 |
| unknown | 0.042 |

**A reporting model fitted on R1-train** (frequency, specificity, and the
term's general reportability across R1-train patients) raises R1-dev
within-gene ρ from 0.073 to **0.170**. Most of the gain comes from general
reportability (0.163 alone).

### 3.3 Our PMID masking removes cardinal cohort rows (over-masking)
- 15,412 HPOA rows are masked; **25% of them cite more than one PMID**,
  with a median of 56% of their PMIDs held out.
- A 2024 cohort row (e.g. hyperuricemia 91/182 over 26 PMIDs) is dropped
  whole when *any* cited paper is held out.

| Disease | Phenotype rows masked / total |
|---|---|
| UMOD ADTKD (OMIM:162000) | **30 / 33** (keeps 3) |
| Holt-Oram (OMIM:142900) | 77 / 98 |
| FBXL4 MTDPS13 (OMIM:615471) | 87 / 113 |

Two SPTAN1 entities (SPG91, DD±epilepsy) are left with no profile. This is
a flaw of our masking rule (EVAL_PROTOCOL §4.1): dropping a whole row is
leak-proof, but it guts the profiles of exactly the diseases that dev and
test measure.

## 4. Literature check (10 diseases; summary of the agents' reports)
**Cardinal features under-emitted** (literature → ours):

| Disease | Feature | Literature | Ours |
|---|---|---|---|
| NF1 | café-au-lait spots | > 99% | 0.36 |
| Holt-Oram | congenital heart defect | 90% | 0.56 |
| Holt-Oram | limb defect | 100% | ≤ 0.14 |
| ADTKD-UMOD | hyperuricemia | "almost all" | 0.00 (masked) |
| MTDPS13 | raised lactate | all patients | 0.10 |
| MTDPS13 | hypotonia | 93% | 0.14 |
| Kabuki | intellectual disability | 87% | 0.21 |
| ITPR1 disorders | ataxia | 97% | 0.53 |
| Noonan | pulmonic stenosis | 25–71% | 0.16 |

**Features over-emitted or wrong:**

| Disease | Feature | Literature | Ours / source of the error |
|---|---|---|---|
| NF1 | intellectual disability | 4–8% | 0.28 (Orphanet "very frequent") |
| Kabuki | kidney anomalies | > 25% | 0.81 |
| Kabuki | vertebral anomalies | 36% | 0.65 |
| Kabuki | seizures | 10–39% | 0.43 |
| Holt-Oram | split hand, cleft palate | explicitly outside the spectrum | 0.25 / 0.18 (Orphanet bin; a 1/1 row → 0.83) |
| ADTKD-UMOD | "nephritis" | the disease is not inflammatory | 0.34 (old automated annotation) |
| MTDPS13 | downslanted palpebral fissures | GeneReviews: *upslanted* | 0.21 |

**Systematic causes:**
1. **Emission model.** Independent draws with HPOA frequency, plus a
   uniform 0.59 observation rate. Rich profiles over-emit (Kabuki's
   profiles imply about 44 features), and cardinal features aren't
   favoured the way clinicians report them.
2. **Over-masking** (§3.3).
3. **Weak evidence taken at face value:**
   - 1/1 counts become 0.75 under Jeffreys;
   - unknown frequency becomes 0.5;
   - Orphanet "Very frequent" bins are sometimes wrong (NF1 ID, TBX5 split
     hand).
4. **Disease handling:**
   - OMIM and Orphanet profiles of the same disease are picked at random
     instead of merged, which halves features found in only one source;
   - spurious links: TBX5→LQT1 has 0 P/LP alleles; OMIM:607785 somatic
     JMML should never simulate a patient;
   - masked-away entities get weight 0.
5. **No per-feature age dependence** (neurofibromas, Lisch nodules, gout,
   ESKD, lentigines, teeth). HPOA's onset column is nearly empty.
6. **Coding granularity differs from clinicians':** aniridia vs iris
   hypoplasia; hypomyelination vs delayed myelination.

**Real R1-dev rates are not ground truth per gene.** Many are exact
fractions of a single paper's cohort:
- FBN1 0.76 = 32/42 (Le Goff 2011);
- LMNA 0.67 = 115/171 (Besci 2024);
- KMT2D 0.48 = 14/29 (Lin 2015).

They measure how papers report, and are useful only in aggregate.

## 5. Answers
1. **Disease vs gene framing is not the root problem.**
   - Gene→phenotype profiles are the same HPOA rows flattened across a
     gene's diseases. They would inherit over-masking and weak evidence,
     and would *worsen* multi-disease genes (LMNA's patients would mix
     lipodystrophy, cardiac disease and progeria).
   - The disease level is also needed for onset, sex and inheritance.
   - What hurts is **how the profiles are built and sampled** (causes
     1–6).
   - The upstream generator's better correlation comes from its small,
     fixed term budget, not from the gene framing.
2. **The dataset is internally consistent but not realistic per disease.**
   Our checks verified consistency and averages, not realism, and this
   analysis finds realism poor. Front A's negative results are therefore
   evidence about **this simulator**, not about retraining with new inputs
   in general. The informe should state that plainly.

## 6. Recommended changes (for decision)
**Profiles:**
1. **Replace whole-row masking with recounting.** For HPOA rows that touch
   held-out papers, recompute the frequency from **R1-train phenopackets**
   of the same disease, which the protocol allows. Keep a row as-is only
   if none of its papers are held out; drop it if R1-train has too few
   patients.
2. **Merge the OMIM and Orphanet profiles of a disease** instead of
   picking one per case. Shrink small counts toward a prior fitted on
   R1-train. Cap the Orphanet bins when HPOA counts disagree.
3. **Disease weights** from published patient counts (phenopacket-store
   train) combined with ClinGen/Orphanet validity. Drop links with no P/LP
   alleles and no product 6 support, and drop somatic entries.

**Emission:**

4. **Reporting-model emission:**
   - a term budget drawn from R1-train's per-case distribution;
   - terms chosen by the fitted reporting model (frequency, specificity,
     reportability);
   - cardinal features forced in, from Orphadata product 4
     `DiagnosticCriteria` flags (sparse: 223 of 4,357 disorders), GeneReviews
     "Suggestive findings", and consensus criteria for the evaluated
     diseases.
5. **Per-feature age dependence** from GeneReviews tables and phenopacket
   onset fields, where available.

**Sources to add** (license to be checked before use):
- **GeneReviews bulk XML** (NCBI litarch `gene_NBK1116.tar.gz`), for
  suggestive findings and frequency tables. GeneReviews content is
  copyrighted by the University of Washington, so check reuse terms first.
- **Orphadata product 4** (CC-BY-4.0).
- **phenopacket-store R1-train cohorts**, already pinned.

**Evaluation:** a per-disease realism check (this analysis) becomes a
standing step for every new simulator version, next to `validate`.
Evaluated against literature numbers and against R1-dev *in aggregate*,
never per gene.
