# EXP-V-002: the Phase 3 vault read of the v4 candidate

- **Front:** Phase 3 ([PHASE3.md](../PHASE3.md) §2f step 6, [ADR-0019](../decisions/0019-phase-3-v4-retraining.md)
  decision 7, the acceptance criterion and its amendments)
- **Registered:** 2026-10-15, by the main session for Mateo. Mateo decided to proceed to the vault on 2026-10-15,
  after the CONFIRM pass ([P3-CONFIRM](../analyses/P3-CONFIRM.md)). His go for the read itself comes after the
  independent review.
- **Independent review:** 2026-10-15, opus/xhigh, read-only. Verdict: GO with fixes. Its six must-fixes are folded
  in below: the contamination check, the earlier-reads disclosure, the selection section, the code and failure
  rule, the claim wording and sources, and the required reporting.
- **Status:** done. Read once on 2026-10-15T18:50Z by Mateo, from `575b847` (ledger row `p3-v1/vault`, EXP-V-002). **H1 passed; H2 passed.**

## Hypotheses
- **H1 (primary):** on vault patients whose publication is uncited by E0's knowledge, the v4 candidate F1 (network
  + add-on) ranks the causal gene higher than E0: Δ capped MRR > 0.
- **H2 (secondary, tested only if H1 passes):** the same for F2, the network alone.

## Systems compared
All systems are scored in one read by `scripts/analysis/p3_addon/vault.py`, on the same patients.

| System | Artifact | Notes |
|---|---|---|
| E0 | `genphenia_v3` (model-v3.0.0), present terms | production today |
| **F1: network + add-on** | network `R5x-f4-ef2f309462` `last.pt` (sha256 `22edfd7e…`); add-on `p3-addon-v1-all` (`31299383…`), knowledge `p3-addon-kb-v1` (`089ccf87…`) | frozen in P3-CONFIRM §1; passed CONFIRM |
| F2: network | `R5x-f4-ef2f309462` | the same network, no add-on |
| `p3-addon-v1-sex-age-onset` on the network | `360c5fe6…` | the same model as F1 (negation weights 0); scored as an agreement check |

- **The network** reads present terms only. It is R1c, trained from scratch on `sim4` preset `e0` (no fitted
  simulator parameters; HPOA 2025-03-03 with NOT, 0/n and 0% rows dropped, ADR-0019 decision 4 and SIM4-v1),
  fine-tuned with 4,369 real patients of `p3-v1` train folds 0–3 (728 publications), each gene drawn as often as
  the simulator draws it (no cohort gene prior).
- **The add-on** reads sex, age, onset and excluded terms, and can only lower a gene's score. Its sources are:
  - HPO annotations `phenotype.hpoa` 2025-03-03 and the HPO ontology 2025-03-03;
  - E0's `genes_to_phenotype` file for the gene list and gene–disease links (it matches no official release);
  - E0's frozen term embeddings, read only by `neg_embed`, whose weight is 0.

  Declared deviations are in P3-ADDON: zero-frequency rows dropped from the profiles, and no Orphanet, HGNC or
  curation overrides. `neg_obligate` is an obligate rule built from n/n rows, which ADR-0019 decision 4 excluded and
  the 2026-10-15 amendment readmits for the add-on. It sits in F1 at weight 0, so it changes no score.

## Data
- **`p3-v1` vault** (frozen 2026-10-13, `3e928b3d…`): `p2-v1` test + vault and `p2-fresh-v1`, 4,659 patients in
  788 publication groups. **Primary population:** the 2,678 patients in 417 groups whose publication is uncited by
  HPO 2025-03-03 (`uncited_e0_knowledge`). The largest uncited publication has 462 patients (17% of patients, 0.7%
  of the capped weight).
- **Train and vault are disjoint** at publication-group level: no shared case ids or PMIDs, and 1,818 groups =
  1,030 + 788 (the reviewer checked the split metadata).
- **Contamination check, done before this registration** (`scripts/analysis/p3_addon/overlap.py`, keys only,
  EVAL_PROTOCOL §4.2 and §9.7; `results/P3/EXP-V-002/overlap.json`, committed before this file):
  - 91 of 4,659 vault patients (17 groups) share their gene and exact present set with a training patient of
    folds 0–3: 84 cited, 7 uncited. 55 of them have a single present term, 12 have two and 13 have three.
  - With the excluded terms in the key: 4 patients (1 uncited).
  - These are few. F1 and F2 are also reported without the 91 (non-gating).
- **Opening:** once, by `splits.load_part("p3-v1", Part.VAULT, …)` under `DXT_SEALED_READ=EXP-V-002`. It runs from
  a clean tree with this file and `overlap.json` committed unchanged. The single opening is code-enforced and
  written to `docs/TEST_LEDGER.md`. Agents never open it.
- **Earlier reads of these patients** (ADR-0019 decision 2, corrected here):
  - Each vault patient was scored one to five times in Phases 1 and 2, depending on its part. The reads were
    EXP-000, B-003, B-006 and V-001 in Phase 1, and P-001, P-005 and P-006 in Phase 2; `p2-fresh-v1` was read
    only by P-006. The systems were E0, the Phase 1 re-rankers, `safe-v1` and `ft-v1.1`.
  - Those reads committed per-patient rank files of E0, `safe-v1` and `ft-v1.1` under `results/EXP-*`, and EXP-P-005
    and P-006 named harmed patients. No Phase 3 script reads those files.
  - **The add-on is `ft-v1.1`'s recipe,** which EXP-P-005 and P-006 confirmed on exactly these patients
    (3,587 + 732 + 340 = 4,659). It was adopted knowing that. F1 − F2 is therefore not an untouched test of the
    add-on. H1 rests on the network, which no earlier read touched.
  - The cap of 10 patients per publication was chosen knowing the vault's group sizes (case-ID metadata only;
    ADR-0019 capped-MRR amendment).

## Selection: what was tried on `p3-v1` train (folds 0–3)
Every configuration and seed is in `results/P3/` and BITACORA.
- **Ladder batch 1** (P3-BATCH1-DIAG §1–§3): R1–R4 from scratch and R4w (E0 start). All lost to E0 on SELECT
  (patient-weighted MRR), mostly because of a learning-rate schedule bug.
- **R1c** (cosine schedule): reproduces E0 (SELECT capped −0.008 [−0.031, +0.015]), Gate A.
- **K1 memory** (kNN over training patients, fused with E0): 40 configurations (8 λ × 5 thresholds), nested out of
  fold over folds 0–3: +0.076 [+0.041, +0.111].
- **K2** (harm control): 384 configurations, nested: +0.074, no gain.
- **K3**: 6 similarity variants, +0.070 to +0.103. `direct` was rejected because it depends on exact terms.
- **R5** (the network with real patients): real-patient shares 0.1, 0.3 (two seeds) and 0.9, read on SELECT:
  +0.038, +0.051 / +0.047, +0.027. R5 + K1: +0.048.
- **R5 cross-fitted** over folds 0–3 (R5x-f0/f1/f2 + R5-r30): +0.071 [+0.049, +0.096].
- **Add-on** (P3-ADDON): network + sex/age/onset, network + all features, and E0 + add-on: +0.0001, −0.0000 and
  +0.0003. Sex/age ceiling filters: 5 diagnostic readings, no room.
- **How F1 was picked:**
  - the network is R5-r30's recipe, with the real-patient share 0.3 chosen on fold 3 (SELECT);
  - its fold-3 reading (+0.051) is above the median of the SELECT candidates (+0.038 over R1c, K1 at fold 3, R5-r10,
    R5-r30, R5-r30 seed 1, R5-r90 and R5 + K1);
  - the add-on "all features" is Mateo's decision (ADR-0019 amendment 2026-10-15).
- **CONFIRM** (fold 4, read once): F1 +0.0717 [+0.0332, +0.1200].

## Command, code and failure rule
- **Code:** `vault.py`, `overlap.py` and `overlap.json` were merged to `main` before this file was committed (#166;
  #167 makes three tests skip without torch in CI). The read runs at the
  commit that registers this file.
- **Command** (Mateo, in his own terminal, after his go, with the GPU otherwise idle):
  `cd /home/mate/FIUBA/trabajo-profesional/diagnostic.ar-training && systemd-run --user --scope -q -p MemoryMax=8G
  -p MemorySwapMax=0 nice -n 10 env DXT_SEALED_READ=EXP-V-002 PYTHONPATH=src .venv/bin/python
  scripts/analysis/p3_addon/vault.py --reason "EXP-V-002 vault read (pre-registered <sha>; Mateo's go <date>)"`
- **Outputs:**
  - `results/P3/EXP-V-002/vault.json`;
  - the rank files under `results/P3/EXP-V-002/ranks/` (E0, network and bundles are written before the
    controls run);
  - the row in `docs/TEST_LEDGER.md`.

  All are committed right after the run, even if it fails.
- **If the run fails after the ledger row,** the vault counts as read and is not re-read. A bug gets a new
  registration and Mateo's decision.

## Primary metric and gate (written before results)
- **Metric:** capped MRR (ADR-0019 amendment 2026-10-14). Each publication counts at most 10 patients: a patient of
  a group with n patients weighs min(n, 10) / n. A gene outside E0's vocabulary or an unscorable patient counts as
  a miss for every system.
- **Δ:** F1 − E0 on the same patients. The 95% CI comes from the paired percentile bootstrap over publication
  groups (2,000 resamples, seed 0).
- **H1 passes** if the 95% CI lower bound of Δ capped MRR on the uncited patients is > 0. This is ADR-0019's
  acceptance criterion. With one primary hypothesis, the level is 95%.
- **H2** is read only if H1 passes (hierarchical, no extra alpha), with the same rule for F2.
- **What a pass means:**
  - The v4 candidate ranks the causal gene higher than GenPhenAI v3.0 on patients from publications v3.0 never saw.
  - It does so with the same HPO knowledge (HPOA 2025-03-03), plus 4,369 curated phenopacket-store training patients.
  - The claim is scoped to patients described with curator-coded HPO terms: at CONFIRM, the gain vanished when
    terms were moved to their parents (+0.0008).
  - Production needs Mateo's decision and a separate integration into `diagnostic.ar-model`, because the model
    format differs from E0's ONNX.
- **What a fail means:** E0 stays the base model, and `ft-v1.1` (ADR-0018) remains the production-ready Phase 2
  model. The result is reported as is.

## Also reported (not gating)
- **Strata:** uncited in-vocabulary, cited and all patients. For each: plain MRR, top-1, top-10, helped and harmed,
  out-of-vocabulary and unscorable counts.
- **Publication-mean MRR:** each publication weighs 1.
- **F1 − F2:** the add-on's contribution. It is not an untouched test (see Data).
- **Agreement:** F1 vs `p3-addon-v1-sex-age-onset`, which should differ in no rank.
- **Without the contamination check's 91 patients:** F1 and F2 vs E0.
- **Phenotype-swap control:**
  - capped Δ under a seeded swap within the vault;
  - the true gene's raw rank, split by whether the gene has real patients in folds 0–3.

  This is the no-cohort-prior control (ADR-0019 amendments 2026-10-14 and 2026-10-15). E0 + cohort gene prior
  (phenotype-blind) is not scored. Mateo excluded the prior from the system (P3-BATCH1-DIAG §4; on SELECT it
  reached most of the kNN gain: publication-weighted 0.524 vs E0 0.426), and the swap control measures the same
  risk on the candidate itself.
- **Parent terms:** every present term is moved to a seeded parent, network vs E0. This shows how much of the gain
  needs the curators' exact terms.
- **Declared now, computed after the read from the committed ranks:**
  - a bootstrap over gene clusters (publications that share a gene are not independent);
  - Δ split by whether the gene has training patients (unswapped);
  - Δ by vault source (`p2-v1` test, `p2-v1` vault, `p2-fresh-v1`);
  - a check that E0's ranks equal Phase 2's E0 rank files for the same patients;
  - the drop from CONFIRM to the vault (EVAL_PROTOCOL §5).
- **Ablation contributions in cross-validation** (ADR-0019 decision 7; folds 0–3, uncited, capped Δ vs E0):

  | Step | Contribution |
  |---|---|
  | Our pipeline (R1c) | reproduces E0: −0.008 on SELECT |
  | Simulator realism (R2–R4) | no gain (batch 1) |
  | Real patients (the network) | **+0.071 [+0.049, +0.096]** out of fold |
  | Memory (K1) | +0.076 alone; −0.003 on top of the network |
  | Add-on | +0.0001 [−0.0014, +0.0014] on top of the network |

## Expectations
- **Folds 0–3, out of fold** (P3-BATCH1-DIAG §11, P3-ADDON): network +0.071 [+0.049, +0.096], with a per-fold range
  of +0.051 to +0.089. The add-on adds about 0.
- **CONFIRM** (P3-CONFIRM §6, 406 uncited): F1 +0.0717 [+0.0332, +0.1200]; F1 − F2 +0.0004.
- **Expected here:** Δ around +0.04 to +0.08, with a narrower CI than CONFIRM (417 groups).
  - The vault mixes three sources. The post-E0 part (`p2-v1` vault + `p2-fresh-v1`, 1,072 patients) has E0 MRR
    0.128 and 55% of genes in E0's vocabulary (EXP-P-006), which dilutes the gain.
  - A pass is likely but not certain.
- **Parent terms:** about 0 to +0.03 (CONFIRM +0.0008; folds 0–3 +0.029).

## Disclosures
- **Development:** folds 0–3 of `p3-v1` train were read many times (see Selection). CONFIRM (fold 4) was read once,
  under its own protocol, before this registration.
- **The add-on** was fitted on the networks' out-of-fold logits of folds 0–3, but runs on `R5x-f4`, which trained
  on all of them.
- **Popularity lean:** R5's raw-rank lift under phenotype swap for genes with training patients is a reported
  control, accepted by Mateo on 2026-10-14.
- **Curation style:** the vault shares phenopacket-store's curation style with training, which favours the network.
  The parent-term reading is reported to bound this.
- **Dry runs:** `vault.py` ran in `--dry-run` on fold 3 only (no gate, no ledger) before this registration: once
  by the script's author, once by the reviewer, and once after the review fixes. All three gave the same numbers.

## Results
Read once on 2026-10-15T18:50:10Z, from `575b847`, by Mateo after his go. Outputs: `results/P3/EXP-V-002/vault.json`,
`results/P3/EXP-V-002/ranks/`, the `p3-v1/vault` row in `docs/TEST_LEDGER.md`. 4,659 patients in 788 publications:
2,678 uncited (417 publications; 628 with a gene outside E0's vocabulary) and 1,981 cited (371). No patient was
unscorable.

| Capped MRR, Δ vs E0 [95% CI] | uncited (H1/H2) | uncited in-vocab | cited | all |
|---|---|---|---|---|
| **F1 network + add-on** | **0.1956 → 0.2605, +0.0649 [+0.0473, +0.0833]** | +0.0980 [+0.0728, +0.1269] | +0.0604 [+0.0402, +0.0834] | +0.0627 [+0.0491, +0.0777] |
| **F2 network** | **+0.0639 [+0.0458, +0.0825]** | +0.0964 | +0.0602 | +0.0621 |
| F1 − F2 (add-on) | +0.0011 [−0.0004, +0.0030] | +0.0016 | +0.0002 | +0.0007 |

- **Uncited, F1:**
  - top-1 11.7% → 16.0%;
  - top-10 29.5% → 34.5%;
  - plain MRR Δ +0.047;
  - publication-mean MRR 0.253 → 0.347, Δ +0.094 [+0.070, +0.120];
  - helped 1,110, harmed 541.
- **Cited, F1:** top-1 55.7% → 62.5%; helped 511, harmed 293.
- **Agreement:** `p3-addon-v1-sex-age-onset` differs from F1 in no rank.
- **Without the contamination check's 91 patients** (7 uncited): F1 uncited +0.0620 [+0.0459, +0.0790], cited
  +0.0556.
- **Phenotype swap:** capped Δ +0.0005 [−0.0002, +0.0012]. True gene's raw rank:
  - genes with real patients in folds 0–3 (874): median 1,349 → 1,180, mean log2 ratio −0.25, 63% improved;
  - other genes (1,176): 1,059 → 997, −0.10, 55% improved.
- **Parent terms** (network vs E0): uncited +0.0226 [+0.0110, +0.0337], 35% of the gain kept; cited +0.0295
  [+0.0122, +0.0484].
- **Declared post-read readings** (gene-cluster bootstrap, Δ by gene with or without training patients, Δ by vault
  source, E0 parity with Phase 2's rank files, CONFIRM → vault drop): in an addendum.

## Verdict
- **H1 passed:** F1's 95% CI lower bound is +0.0473 > 0.
  - On 2,678 patients from 417 publications that GenPhenAI v3.0's knowledge never cited, the v4 candidate ranks the
    causal gene higher than v3.0: capped MRR 0.196 → 0.261, and the right gene is first for 16.0% of patients
    instead of 11.7%.
  - It uses the same HPO knowledge (HPOA 2025-03-03), plus 4,369 curated phenopacket-store training patients.
- **H2 passed:** the network alone gives +0.0639 [+0.0458, +0.0825]. The add-on adds +0.0011, not significant, and
  it is not an untouched test of the add-on.
- **The gain matches development:** folds 0–3 +0.071, CONFIRM +0.072, vault +0.065.
- **Scope:** the claim is for patients described with curator-coded HPO terms. With every term moved to a parent,
  35% of the gain remains (+0.023, CI above 0); at CONFIRM, none remained.
- **Controls:** the popularity control is about 0 in capped MRR. The raw-rank lean toward genes with training
  patients remains (log2 −0.25 vs −0.10), deep in the list.
- **Production** needs Mateo's decision and a separate integration into `diagnostic.ar-model` (ADR to follow).

## Addenda
