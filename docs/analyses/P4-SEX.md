# P4-SEX: a certain sex-impossibility list and a hard sex rule on top of the network

- **Date:** 2026-10-15. `p3-v1` train folds 0–3 only, read out of fold. No CONFIRM read, no vault patient
  read, no fitting.
- **Code:** `src/diagnostic_ar_training/v4/sexrule.py` (knowledge `sex-kb/2` and the rule),
  `scripts/analysis/p4_sex/` (`kb.py`, `read.py`), `tests/test_v4_sexrule.py`. Knowledge `sex-kb-v2`
  (built from f8a677a): stats and audit `data/p4-sex/sex-kb-v2.{stats,audit}.json`, manifest
  `data/manifests/sex-kb-v2.json`. Numbers `results/P4/sex/oof.json` (run from 41ddb03).
- **Rule:** genes the patient's recorded sex cannot have are moved below every other gene (their own order
  kept); unknown sex (422 of 5,053 patients) changes nothing. Pure numpy (`SexRule`, `block`), applied to any
  score vector: the network's logits or F1's scores.
- **Metric:** capped MRR (10 patients per publication), Δ with the publication-cluster bootstrap
  (`v4.report`); plain MRR Δ; helped / harmed are patient counts. "Removed above" counts the patients with at
  least one removed gene ranked above their true gene. F1 = network + `p3-addon-v1-all` (`v4.addon.Addon`),
  the vault-tested candidate; it was fitted on these folds, so F1's own Δ is in-sample (the rule's Δ on top of
  it is not fitted at all).

## 1. Readings, pooled over folds 0–3 (5,053 patients)

The network alone reproduces +0.0714 (uncited, capped, vs E0), its ranks equal P3-ADDON's out-of-fold ranks on
every patient, and F1 reproduces P3's +0.000149 vs the network (`rerankers.py`).

| Comparison | Stratum | n (pubs) | capped MRR (ref) | Δ capped [95% CI] | Δ MRR [95% CI] | helped / harmed | removed above |
|---|---|---|---|---|---|---|---|
| network vs E0 | uncited | 2,316 (402) | 0.2840 (0.2126) | +0.0714 [+0.0488, +0.0962] | +0.0399 [+0.0064, +0.0812] | 631 / 551 | |
| | uncited in-vocab | 1,633 (311) | 0.4375 (0.3287) | +0.1088 [+0.0755, +0.1446] | +0.0566 [+0.0088, +0.1304] | 631 / 551 | |
| | cited | 2,737 (412) | 0.7355 (0.6758) | +0.0597 [+0.0368, +0.0829] | +0.0683 [+0.0392, +0.0953] | 832 / 442 | |
| network + sex v1 vs network | uncited | | | +2.4e-6 [+1.1e-7, +7.0e-6] | +1.6e-6 | 148 / 0 | 148 |
| | uncited in-vocab | | | +3.7e-6 [+1.8e-7, +1.1e-5] | +2.3e-6 | 148 / 0 | 148 |
| | cited | | | +9.5e-7 [+4.6e-10, +2.9e-6] | +6.0e-7 | 9 / 0 | 9 |
| **network + sex v2 vs network** | uncited | | | **+2.4e-6 [+8.9e-8, +7.0e-6]** | +1.6e-6 | **130 / 0** | 130 |
| | uncited in-vocab | | | +3.6e-6 [+1.4e-7, +1.1e-5] | +2.3e-6 | 130 / 0 | 130 |
| | cited | | | +9.1e-7 [0, +2.8e-6] | +5.6e-7 | 4 / 0 | 4 |
| network + sex v2 vs E0 | uncited | | 0.2840 (0.2126) | +0.0714 [+0.0488, +0.0962] | +0.0399 [+0.0064, +0.0812] | 632 / 550 | |
| | uncited in-vocab | | 0.4375 (0.3287) | +0.1088 [+0.0755, +0.1446] | +0.0566 [+0.0088, +0.1304] | 632 / 550 | |
| | cited | | 0.7355 (0.6758) | +0.0597 [+0.0368, +0.0829] | +0.0683 [+0.0392, +0.0953] | 832 / 442 | |
| F1 vs network (in-sample) | uncited | | 0.2841 (0.2840) | +0.0001 [−0.0014, +0.0015] | +0.0007 [−0.0006, +0.0018] | 334 / 25 | |
| | uncited in-vocab | | 0.4377 (0.4375) | +0.0002 [−0.0020, +0.0024] | +0.0010 [−0.0011, +0.0024] | 334 / 25 | |
| | cited | | 0.7359 (0.7355) | +0.0004 [−0.0001, +0.0011] | +0.0003 [+0.0000, +0.0008] | 147 / 6 | |
| F1 + sex v1 vs F1 | uncited | | | +9.7e-7 [+8.0e-8, +2.7e-6] | +6.7e-7 | 124 / 0 | 124 |
| | uncited in-vocab | | | +1.5e-6 [+1.3e-7, +4.2e-6] | +9.5e-7 | 124 / 0 | 124 |
| | cited | | | +9.1e-7 [0, +2.8e-6] | +5.6e-7 | 5 / 0 | 5 |
| **F1 + sex v2 vs F1** | uncited | | | **+9.5e-7 [+5.9e-8, +2.7e-6]** | +6.5e-7 | **110 / 0** | 110 |
| | uncited in-vocab | | | +1.5e-6 [+9.3e-8, +4.2e-6] | +9.3e-7 | 110 / 0 | 110 |
| | cited | | | +9.1e-7 [0, +2.8e-6] | +5.6e-7 | 3 / 0 | 3 |
| F1 + sex v2 vs E0 | uncited | | 0.2841 (0.2126) | +0.0715 [+0.0488, +0.0963] | +0.0406 [+0.0069, +0.0804] | 639 / 544 | |
| | uncited in-vocab | | 0.4377 (0.3287) | +0.1090 [+0.0762, +0.1450] | +0.0576 [+0.0099, +0.1300] | 639 / 544 | |
| | cited | | 0.7359 (0.6758) | +0.0601 [+0.0373, +0.0831] | +0.0686 [+0.0393, +0.0955] | 837 / 437 | |
| network + sex v2 vs network + sex v1 | uncited | | | −2.8e-8 [−6.0e-8, −8.3e-9] | −3.8e-8 | 4 / 79 | |
| F1 + sex v2 vs F1 + sex v1 | uncited | | | −2.0e-8 [−4.8e-8, −4.2e-9] | −1.6e-8 | 5 / 47 | |

F1 + sex v1 vs E0 equals F1 + sex v2 vs E0 to four decimals in every stratum. Top-1 and top-10 never change.

**Per fold, uncited** (network of the fold: `R5x-f0-34cd370c47`, `R5x-f1-fc60f6a846`, `R5x-f2-bcb6ff0d93`,
`R5-r30-fa772ffa7e`). Every Δ of the rule is below 4e-5 in absolute value; helped / harmed:

| Fold | n (pubs) | network vs E0 | net + v1 vs net | net + v2 vs net | F1 vs net | F1 + v1 vs F1 | F1 + v2 vs F1 |
|---|---|---|---|---|---|---|---|
| 0 | 498 (112) | +0.0588 | 67 / 0 | 66 / 0 | −0.0019, 103 / 3 | 52 / 0 | 52 / 0 |
| 1 | 630 (113) | +0.0890 | 41 / 0 | 38 / 0 | +0.0023, 103 / 4 | 37 / 0 | 35 / 0 |
| 2 | 453 (84) | +0.0833 | 32 / 0 | 20 / 0 | −0.0001, 37 / 13 | 30 / 0 | 18 / 0 |
| 3 | 735 (93) | +0.0511 | 8 / 0 | 6 / 0 | +0.0002, 91 / 5 | 5 / 0 | 5 / 0 |

Cited, per fold, the rule helps 0–4 patients and harms none. Per stratum and fold, every number is in
`results/P4/sex/oof.json`.

**Reading.** The rule is safe and nearly empty. It harms no patient with either list, on either base, in any
fold. It helps 130 uncited patients on the network (110 on F1), each by a few ranks far down the list: the
capped MRR gain is about 2e-6 and no patient moves into the top 10. The genes it removes (spermatogenic
failure, oocyte maturation defects, Y-chromosome genes) almost never compete with the network's top
candidates. v2 helps fewer patients than v1 (130 vs 148) because v1 also blocked 11 genes it should not have
(§2); those genes are never a true gene here, so dropping them costs about 3e-8.

## 2. Knowledge: `sex-kb-v2` (`sex-kb/2`)

**Sources.** E0's knowledge, as `p3-addon-kb-v1`: HPOA 2025-03-03 (unmasked; NOT rows never read,
zero-frequency rows dropped), the 2025-03-03 ontology, E0's gene list and gene → disease links
(`e0_genes_to_phenotype`, GraPhens@7aef83d). **Declared extra source:** `hgnc` (2026-09-25, pinned in
`data/sources.yaml`), read for chromosome locations only. `p3-addon-kb-v1` is a manifest input for the audit
only; the rules never read it. A test checks that the build opens exactly these four sources.

**Rules** (fixed from the knowledge alone, before any patient was looked at):
- A gene is limited to a sex only if **every** one of its diseases is, or it is on the Y chromosome outside
  the pseudoautosomal regions (HGNC location starts with Y and has no X).
- A disease is limited by:
  - `y_linked_inheritance`: Y-linked (HP:0001450) is its only inheritance term;
  - `names`: safe-v1's name lists, extended (male: vas deferens, prostate cancer, chromosome Y microdeletion,
    "Müllerian" spelling; female: Müllerian aplasia, MRKH, eclampsia, embryo maturation arrest). The name must
    **start** with the sex-limited condition, and each part joined by "with", "with or without", "and" or
    "/" must be sex-limited too or a bare qualifier (types I and II). safe-v1 matched the phrase anywhere;
    "male infertility" now needs a word boundary (it matched inside "female infertility"). safe-v1's
    "recurrent pregnancy loss" stays in the list and matches no E0 disease name;
  - `phenotypes`: every annotated phenotype is under HP:0000078 (genital system) and at least one is in one
    sex's subtrees. Male: HP:0010461 (Abnormality of the male genitalia), HP:0012874 (Abnormal male
    reproductive system physiology), HP:0012863 (Abnormal male germ cell morphology). Female: HP:0010460
    (Abnormality of the female genitalia), HP:0030012 (Abnormal female reproductive system physiology),
    HP:0033338 (Abnormal female meiosis), HP:0020155 (Abnormal oocyte morphology). Ids checked in the
    2025-03-03 ontology: HP:0000032 is only "Abnormal male external genitalia morphology", so the male root
    is HP:0010461; sperm morphology sits under HP:0012863 and oocyte terms under HP:0033338 / HP:0020155,
    outside both genitalia subtrees.
- A disease is not limited when it also has evidence for the other sex, or any phenotype in the other sex's
  subtrees (`contradicted`).
- **Never limited:**
  - X-linked recessive: inheritance is never evidence for females (manifesting carriers exist);
  - differences of sex development, for **both** sexes: a gene is skipped when any of its diseases has a DSD
    name (safe-v1's sex-reversal list plus "sex development", "hermaphroditism", "ambiguous genitalia",
    "ovotesticular", "pseudovaginal") or a DSD phenotype (HP:0000062 ambiguous genitalia, HP:0000037 /
    HP:0010458 pseudohermaphroditism, HP:0000133 gonadal dysgenesis, HP:0012244 abnormal sex determination,
    HP:0031170 female fetal virilization). The recorded sex can differ from the karyotype there, so neither
    sex is certain. This also drops genes with "46,XX gonadal dysgenesis", which only XX people have, and
    persistent Müllerian duct syndrome (AMH, AMHR2);
  - genes with limits of both sexes (`ambiguous`), e.g. meiosis genes with both spermatogenic and ovarian
    failure.

**Counts** (E0's 5,229 genes):

| | v1 (`p3-addon-kb-v1`) | v2 (`sex-kb-v2`) |
|---|---|---|
| male-limited | 101 | 100 |
| female-limited | 42 | 36 |
| kept from v1 / added / removed | | 132 / 4 / 11 |

| Reason (a gene can have several) | male | female |
|---|---|---|
| names | 99 | 36 |
| phenotypes | 90 | 9 |
| y_linked_inheritance | 17 | |
| y_chromosome | 19 | |
| names only | 9 | 27 |

Not limited despite some evidence: 18 DSD, 11 ambiguous, 2 contradicted, 29 partial (only some diseases
limited, e.g. CFTR, DNAH1, prostate-cancer genes with other cancers), 17 compound names.

**Added vs v1** (all male):

| Gene | Reasons | Diseases |
|---|---|---|
| DAZ4 | y_chromosome, names, phenotypes | Chromosome Y microdeletion syndrome (Yq11.23) |
| TSPY1 | y_chromosome, names, phenotypes | Chromosome Y microdeletion syndrome (Yp11.2) |
| MXI1 | names, phenotypes | Prostate cancer |
| RNASEL | names, phenotypes | Prostate cancer, hereditary, 1 |

**Removed vs v1:**

| Gene | v1 | Why | Disease |
|---|---|---|---|
| EIF2B2, EIF2B3, EIF2B4, EIF2B5 | female | compound name | Leukoencephalopathy with vanishing white matter 2–5, with or without ovarian failure |
| GGPS1 | female | compound name | Muscular dystrophy, congenital hearing loss, and ovarian insufficiency syndrome |
| CDC14A | male | compound name | Deafness, autosomal recessive 32, with or without immotile sperm |
| CFAP45, CFAP52, MNS1 | male | compound name | Heterotaxy, visceral, 9–11, autosomal, with male infertility |
| CLDN2 | male | compound name | Azoospermia, obstructive, with nephrolithiasis |
| MCM8 | female | contradicted | Premature ovarian failure 10 (annotated with male reproductive phenotypes) |

v1 blocked these for the other sex although both sexes have the disease (vanishing white matter, deafness,
heterotaxy, muscular dystrophy) or HPOA annotates both sexes (MCM8). No dev patient has one of them as true
gene, which is why v1's harm check is also 0.

## 3. Harm check (dev folds 0–3, sex known)

Patients whose true gene the list makes impossible for their recorded sex: **0 with v2, 0 with v1.** 14
patients have a sex-limited true gene under either list (9 male with a male-limited gene, 5 female with a
female-limited gene), and their recorded sex always matches. No rule was tightened, so no decision was taken on
dev data.

**Disclosed:** an exploratory build of the same rules that also listed "pregnancy loss" as female-limited
(adding ANXA5, "Pregnancy loss, recurrent, susceptibility to, 3") was harm-checked on these patients (0 harmed)
before `sex-kb-v2` was built. "pregnancy loss" was then dropped on knowledge grounds, not because of the check:
the ANXA5 M2 haplotype is a susceptibility factor carried by either partner, so a male carrier is not
impossible. Removing a gene can only lower the rule's effect; the check gave 0 both ways.

## 4. Caveats and open points

- **Certainty is relative to E0's knowledge.** A gene counts as one-sex when every disease E0 links it to is.
  A gene with a second, other-sex disease unknown to HPOA 2025-03-03 would be wrongly blocked; the harm check
  only covers the 14 patients whose true gene is on a list.
- Kept from v1 on purpose, worth a clinical look: preeclampsia genes (FLT1, STOX1; for FLT1 the fetal genotype
  matters, so a fetus recorded as male could carry it) and ESR2 ("Ovarian dysgenesis 8"; OMIM also mentions a
  46,XY DSD case, but HPOA annotates no male or DSD phenotype). INSL3 (isolated cryptorchidism) stays male.
- Known misses of the name rule: ADGRG2 ("Congenital bilateral absence of vas deferens" does not start with
  the phrase) is not limited. Being conservative, nothing was relaxed after the build.
- The gain is about 2e-6 capped MRR: the rule is a correctness guard (never show a man an ovarian-failure gene
  above a plausible one), not a ranking improvement.

## What a doctor would see without the rule (`topk.py`)
The network's out-of-fold lists on folds 0–3, for the 4,631 scored patients with a known sex. The table counts
lists that show at least one gene the patient's sex cannot have (`sex-kb-v2`):

| Shown in | Patients | Impossible genes shown |
|---|---|---|
| first place | 1 (0.02%) | 1 |
| top 5 | 2 (0.04%) | 3 |
| top 10 | 10 (0.22%) | 15 |
| top 50 | 48 (1.04%) | 80 |

The hard rule removes every one of them, and it harms no patient. Its value is mostly correctness of what the doctor
sees, not MRR.

