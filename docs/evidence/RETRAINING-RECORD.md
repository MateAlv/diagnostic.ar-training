# Retraining record: Phase 3 (GenPhenAI v4) and Phase 4 (sex and age layer)

The complete record of the retraining work from 2026-10-13: what was asked, how it was measured, everything that
was tried, what worked, what did not, and the limits. Each number is copied from the source document or result
file named next to it. This is evidence, not informe prose: the students write the informe.

- **Decision records:** [ADR-0019](../decisions/0019-phase-3-v4-retraining.md) (Phase 3 and its amendments),
  [ADR-0020](../decisions/0020-v4-validated-and-next.md) (v4 validated; Phase 4; accepted 2026-10-15).
- **Plans and logs:** [PHASE3.md](../PHASE3.md), [BITACORA.md](../BITACORA.md) (every run and decision, dated).
- **Metric used throughout:** capped MRR (§2). "Δ" is always against E0 (GenPhenAI v3.0 as released) on the same
  patients, with a 95% CI from the paired bootstrap over publication groups (2,000 resamples, seed 0), unless said
  otherwise.

## 1. The question
- **Goal (Mateo, ADR-0019):** a GenPhenAI v4 that ranks the causal gene higher than v3.0 (E0) for patients from
  publications v3.0 never saw. The gain must be real: no leakage, no overfitting. Some patients may be harmed if the
  net gain is real.
- **Acceptance rule (written 2026-10-13, before any training):** one read of a sealed vault. PASS when the lower
  bound of the 95% CI of Δ (v4 − E0) on the vault's uncited patients is > 0. "Uncited" means no publication of the
  patient's group is cited by E0's knowledge (HPOA 2025-03-03).
- **Starting point** ([P3-AUDIT-v1](../analyses/P3-AUDIT-v1.md)):
  - E0 was trained only on simulated patients and selected on simulated data.
  - On new real patients with a known gene, its MRR is about 0.13 to 0.42, not the 0.6 seen on cited patients.
  - Patients whose phenotype the gene's annotations explain poorly score 0.04.
  - Phase 1's retraining losses were mostly lost memorisation of cited patients.

## 2. Data and protocol

| Set | Content | Patients (publications) | Use |
|---|---|---|---|
| `p3-v1` train | `p2-v1` train + dev (= R1 train + dev) | 5,986 (1,030) | development, split in 5 folds by publication |
| folds 0–2 (FIT) | | | fitting, real patients for training |
| fold 3 (SELECT) | | 1,456 (195) | selection |
| fold 4 (CONFIRM) | | 933 | one internal check of the frozen finalists, main session only, ledgered |
| `p3-v1` vault | `p2-v1` test + vault, `p2-fresh-v1` | 4,659 (788); **2,678 uncited (417)** | sealed: one read after pre-registration, independent review and Mateo's go |

- **Folds:** sha256 of the publication group mod 5. A publication's patients are never split across folds.
- **Knowledge parity:** v4 uses only E0's knowledge (HPOA 2025-03-03 and E0's gene list). A difference with E0 is
  then due to the method, not to newer knowledge.
- **No literature negation** (ADR-0019 decision 4): HPOA NOT, 0/n and 0% rows are dropped, and excluded terms are
  not network inputs. Case reports mention an absent finding mostly when it is expected in the disease, so learned
  negations would point toward the true gene.
- **Capped MRR** (amendment 2026-10-14, [P3-BATCH1-DIAG](../analyses/P3-BATCH1-DIAG.md) §1): each publication counts
  at most 10 patients (weight min(n, 10)/n).
  - Without the cap, one paper (ANKRD11, 333 patients) was 45% of SELECT, and the vault's largest paper is 17% of its
    uncited patients.
  - With the cap, the vault's largest paper weighs 0.7%.
- **No cohort gene prior** (amendment 2026-10-14): a gene must not gain from how many training patients it has.
  phenopacket-store's gene frequencies follow curation, not clinical incidence, and the vault shares them.
- **Popularity control:** every real-patient component is re-run with each patient's phenotype swapped for another
  patient's, true gene kept. Its gain there must be about 0.
- **Curated-terms stress test ("parent terms"):** every symptom term is moved to one of its parent terms. This
  shows how much of a gain needs the curators' exact wording.

## 3. What was tried, in order

### 3.1 A new simulator and the ablation ladder (failed; [SIM4-v1](../analyses/SIM4-v1.md), PHASE3 §2c)
- **The old simulator was audited and rewritten as `sim4`** (PR #149). Every layer of `rare-disease-simulator`
  fitted on patients had memorised them (per-gene rho 0.52 on train vs 0.16 on dev). The rewrite uses E0's
  knowledge, about 15 global parameters, and no per-gene parameter fitted on patients.
- **Ladder batch 1** (R1 = E0's recipe retrained; R2 frequency-weighted; R3 fitted reporting; R4 + off-profile
  noise; R4w from E0). No rung improved on SELECT. Three reasons were found afterwards:
  - a learning-rate schedule bug: the rate collapsed after about 150k steps, so runs effectively stopped learning;
  - R1 did not reproduce E0;
  - one publication dominated SELECT.
- **Weighted by publication, the simulator rungs are noise** (P3-BATCH1-DIAG §2):
  - SELECT's resolution is about ±0.05–0.07.
  - A simulator of the same annotations adds robustness, not knowledge.
- **Decision (Mateo, 2026-10-14):** re-centre v4 on real patients.

### 3.2 Fixing the pipeline (worked; P3-BATCH1-DIAG §7)
- **R1c** is R1 with a cosine schedule. Its final checkpoint reproduces E0: capped Δ on SELECT uncited −0.008
  [−0.031, +0.015], FIT uncited −0.005, SELECT cited −0.008. This is **Gate A**, and R1c is the base for every
  later model.

### 3.3 Real patients as a memory (worked alone, redundant later; P3-BATCH1-DIAG §4, §6, §8, §9)
- **K1:** for each query, the most similar training patients of each gene (ancestor-closure similarity). The
  evidence is calibrated per gene, so the number of patients earns nothing, and fused with E0.
  - Out of fold over folds 0–3: **+0.076 [+0.041, +0.111]**.
  - Swap control −0.048.
  - It harms many patients whose gene has no training patient: 423 helped, 916 harmed.
- **K2** (harm controls: cap, confidence gate): no gain, +0.074.
- **K3** (6 similarity variants):
  - +0.070 to +0.103;
  - `direct` (exact terms) was rejected: it keeps under 15% of its gain with parent terms;
  - the ancestor-closure variants keep 70–80%.
- **An early phenotype-blind gene prior** reached most of the memory's first SELECT gain (publication-weighted
  0.524 vs E0 0.426). This is why the no-prior rule was made.

### 3.4 Real patients inside the network: R5 (worked; P3-BATCH1-DIAG §10–§11)
- **R5:** R1c fine-tuned for 60 minutes with real FIT patients mixed into the simulated stream.
  - Each training item is a gene drawn as the simulator draws it. When that gene has real patients, the item is one
    of them with probability `real_ratio`. So no gene gains from having more patients.
- **SELECT readings** (fold 3; final checkpoints):

  | Run | Real share of items | Uncited Δ [CI] | Parent terms | Swap |
  |---|---|---|---|---|
  | R5-r10 | about 0.6% | +0.038 [+0.010, +0.073] | +0.019 | −0.000 |
  | **R5-r30** | about 1.8% | **+0.051 [+0.020, +0.090]** | +0.022 | −0.000 |
  | R5-r30, seed 1 | about 1.8% | +0.047 [+0.015, +0.086] | +0.020 | −0.000 |
  | R5-r90 | about 5.4% | +0.027 [−0.013, +0.072] | −0.006 | −0.000 |

  - Seed noise is 0.004.
  - More real data overfits the curators' term templates (r90).
  - The memory adds nothing on top of R5: −0.003.
- **Cross-fitted over folds 0–3** (each fold read by a network trained on the other three folds' real patients,
  `sim.real_folds`, PR #157):

  | Fold | 0 | 1 | 2 | 3 | **pooled 0–3** | pooled 0–2 (not used to choose r30) |
  |---|---|---|---|---|---|---|
  | Uncited Δ | +0.059 | +0.089 | +0.083 | +0.051 | **+0.071 [+0.049, +0.096]** | +0.077 [+0.051, +0.108] |

  - Every fold's CI excludes 0.
  - Cited, pooled: +0.060.
  - Parent terms: +0.029 (40% kept).
  - Swap capped Δ about 0. On raw ranks, genes with training patients rise about 20% under swap, deep in the list.
    Mateo accepted this as a reported control (2026-10-14).

### 3.5 Patient inputs: sex, age, onset, negated symptoms (no gain on top; [P3-ADDON](../analyses/P3-ADDON.md))
- **Mateo (2026-10-15):** the final model must use age, onset and negated symptoms (and sex). This is ADR-0019
  amendment 2026-10-15.
- **The add-on** is Phase 2's `ft-v1.1` design: a residual on the network's gene scores that can only lower a gene,
  with no per-gene weights. It is refit on the network's out-of-fold scores, with knowledge `p3-addon-kb-v1` built
  from HPOA 2025-03-03 only.
- **Out of fold, folds 0–3:** add-on on top of the network +0.0001 [−0.0014, +0.0014]. Sex carries the learned
  weight. Onset gets almost none. The negated-symptom weights end at 0.
- **Room for sex and age** (`ceiling.py`):
  - near the top of the list (true gene at ranks 2–10), only 1.3% of the genes above the true gene are ruled out
    by sex or onset;
  - HPOA's onsets contradict real patients: as a hard rule they removed the true gene of 34–39 uncited patients.
- **The onset data the pipeline ignored** (onset classes such as "congenital", per-symptom onsets; 31% of patients)
  was added to the analysis. It does not change the conclusion.

### 3.6 The frozen candidate, CONFIRM and the vault (passed)
- **Frozen** ([P3-CONFIRM](../analyses/P3-CONFIRM.md) §1):
  - network `R5x-f4-ef2f309462`: R5-r30's recipe with the real patients of folds 0–3 (4,369 patients, 728
    publications);
  - add-on `p3-addon-v1-all`;
  - F1 = network + add-on (primary), F2 = network alone.
- **CONFIRM** (fold 4, read once, protocol written first): F1 uncited +0.0717 [+0.0332, +0.1200]; F2 +0.0713.
  Pass. Parent terms +0.0008 (none kept).
- **Vault pre-registration** [EXP-V-002](../experiments/EXP-V-002.md):
  - independent review (opus/xhigh, read-only): GO with fixes, folded in;
  - keys-only contamination check: 91 of 4,659 vault patients share gene and present terms with a training patient
    (7 uncited), mostly 1–3 terms;
  - dry runs on fold 3 only.
- **Vault read** (once, 2026-10-15, run by Mateo from `575b847`):

  | Vault | E0 | v4 (F1) | Δ [95% CI] |
  |---|---|---|---|
  | **Uncited, capped MRR (gate)** | 0.196 | 0.261 | **+0.0649 [+0.0473, +0.0833] — PASS** |
  | Uncited, right gene first | 11.7% | 16.0% | |
  | Uncited, right gene in top 10 | 29.5% | 34.5% | |
  | Uncited, publication-mean MRR | 0.253 | 0.347 | +0.094 [+0.070, +0.120] |
  | Cited, capped MRR | 0.679 | 0.739 | +0.060 [+0.040, +0.083] |
  | Network alone (F2), uncited | | | +0.0639 [+0.0458, +0.0825] — H2 pass |
  | Add-on (F1 − F2), uncited | | | +0.0011 [−0.0004, +0.0030] |

  - Helped 1,110, harmed 541 (uncited).
  - Without the 91 overlapping patients: +0.062.
  - Swap +0.0005.
  - Parent terms +0.0226 [+0.0110, +0.0337] (35% kept).
- **Post-read readings** (EXP-V-002 Addendum 1, declared before the read):
  - **Gene-cluster bootstrap:** +0.0649 [+0.0367, +0.0976].
  - **The gain is on genes with real training patients:** +0.137 [+0.104, +0.174] (983 patients) against +0.001
    [−0.012, +0.015] (1,695).
  - **By vault source:** `p2-v1` test +0.123, `p2-v1` vault +0.030, `p2-fresh-v1` (newest publications) −0.001.
    Only 16% of the newest publications' genes have training patients.
  - **E0 parity:** our E0 ranks equal Phase 2's E0 ranks for all 4,659 patients.

### 3.7 Earlier re-rankers on top of v4 (no gain; P3-ADDON, "Earlier re-rankers")
Folds 0–3, network out of fold, uncited capped Δ vs the network:

| Re-ranker | Δ [CI] | Helped / harmed |
|---|---|---|
| `rerank-v1.0.0` (Phase 1, "no" answers) | −0.0030 [−0.0065, −0.0001] | 87 / 366 |
| `ft-v1.1` (Phase 2, production-ready) | −0.0003 [−0.0033, +0.0023] | 483 / 12 |
| `safe-v1[sex+onset]` (Phase 2 rules) | +0.0004 [+0.0000, +0.0012] | 217 / 0 |

`rerank-v1.0.0` was tested with publication negatives. Interview "no" answers have no real dataset.

## 4. Summary: what each piece contributed

| Piece | Contribution (uncited, capped Δ vs E0) | Where measured |
|---|---|---|
| Our training pipeline (R1c) | reproduces E0 (−0.008) | SELECT |
| Simulator realism (R2–R4) | none (noise at ±0.05) | SELECT, FIT |
| Real patients as memory (K1) | +0.076 alone; −0.003 on top of the network | folds 0–3 out of fold |
| **Real patients in the network (R5)** | **+0.071 (folds 0–3), +0.072 (CONFIRM), +0.065 (vault)** | out of fold, CONFIRM, vault |
| Sex/age/onset/negation add-on | +0.0001 (folds), +0.0011 (vault, n.s.) | folds 0–3, vault |
| Earlier re-rankers | −0.003 to +0.0004 | folds 0–3 |

## 5. Limits (stated with any claim)
- **The gain follows the genes with real training patients** (about 360 genes): +0.137 on them, about 0 elsewhere.
  It grows as phenopacket-store covers more genes.
- **Wording:** with every term moved to its parent, 35% of the vault gain remains (40% on folds 0–3, none at
  CONFIRM). The gain is largest for curator-coded HPO terms; clinicians' free text may gain less.
- **Newest publications:** no measurable gain (`p2-fresh-v1`, −0.001).
- **Popularity lean:** under phenotype swap, genes with training patients rise in raw rank (log2 −0.25 vs −0.10 on
  the vault), deep in the list. It is a reported control.
- **Same curation:** the vault is curated like the training patients (phenopacket-store), which favours the network.
- **Earlier reads of the vault patients:** Phases 1 and 2 scored them with other systems one to five times. The
  add-on's recipe (`ft-v1.1`) was confirmed on them in Phase 2. The network itself was never scored on them before.
- **Probabilities:** the claims are about the order of the list. Like E0, the network's top-1 probability is
  overconfident. When it is 80–95%, the top gene is right 54% of the time; at ≥ 99%, 94% of the time. E0's gap is
  larger: ECE 0.226 against 0.184 (folds 0–3, out of fold; `results/P3/addon/calibration.json`, 2026-10-16).

## 6. Phase 4: the sex and age layer (ADR-0020, accepted 2026-10-15)
Mateo (2026-10-15): "tiny gain is gold". Sex must be in the model deterministically, and age as far as it can be
made certain. The vault is spent and never reopened. The layer is checked on folds 0–3 (zero harmed as the bar) and
by a second, disclosed CONFIRM read.

### 6.1 Sex rule ([P4-SEX](../analyses/P4-SEX.md), done)
- **Knowledge `sex-kb-v2`:** E0's knowledge plus HGNC location (declared). 100 genes a woman cannot have, 36 a man
  cannot have.
  - A gene is listed only if every one of its diseases is limited to one sex, or it lies on Y outside the
    pseudoautosomal regions.
  - Never listed: X-linked recessive (carriers can be affected), disorders of sex development, genes with both
    sexes' diseases.
  - Compared with the earlier list: 4 genes added, 11 wrongly blocked genes removed, and a "male infertility" inside
    "female infertility" bug fixed.
- **Rule:** a gene impossible for the patient's sex goes to the bottom of the list. Unknown sex changes nothing.
- **Folds 0–3, on the network's out-of-fold scores:** 0 harmed, 130 helped. MRR change about +0.000002; top-1 and
  top-10 rates unchanged.
- **What the doctor sees:** without the rule, the network shows a gene impossible for the patient's sex in first
  place for 1 of 4,631 patients, in the top 10 for 10, and in the top 50 for 48. The rule removes all of them.
- **`sex-kb-v3`** fixes the one known miss: ADGRG2 (absent vas deferens) is now male-limited (101 male, 36 female
  genes). 0 harmed on folds 0–3.
- With the add-on (F1), the top 50 still shows a sex-impossible gene for 28 of 4,631 dev patients (top 10: 1). With
  the hard rule, none.

### 6.1b Final model (Mateo, 2026-10-15)
- **F3 = network + add-on (vault-tested weights) + hard sex rule (`sex-kb-v3`). Age is dropped as a hard rule.**
- The soft add-on stays because it helps more patients than it harms:
  - folds 0–3 out of fold, on top of network + sex rule: 344 helped, 44 harmed, net Δ about 0;
  - vault: 463 helped, 27 harmed, +0.0011.
- **Second CONFIRM read** ([P4-CONFIRM](../analyses/P4-CONFIRM.md), once, protocol written first; fold 4, 406
  uncited): all three checks pass.
  - F3 vs E0, uncited: +0.0717 [+0.0332, +0.1200].
  - Sex rule: 31 helped, 0 harmed.
  - Add-on: 101 helped, 5 harmed, +0.0005 [+0.0001, +0.0010].
  - Top 50 showing a sex-impossible gene: network 20 patients, F3 0.

### 6.2 Age rule ([P4-AGE](../analyses/P4-AGE.md), done; recommendation: drop)
- **Knowledge `age-kb-v1`** (HPOA 2025-03-03 onsets, E0's genes): 1,203 genes get a certain earliest onset (every
  disease of the gene annotated with onset).
- **Rule:** block a gene whose earliest onset is later than the patient's latest possible onset plus a margin. The
  patient's latest possible onset comes from onset age, onset class, per-symptom onsets and current age.
- **144 variants were tried on folds 0–3** (lowest blocking onset 1–60 years, margin 0–30 years, two patient sides,
  two gene sides), all reported.
  - Every variant that blocks the true gene of any dev patient harms at least 4 patients.
  - The causes are wrong or incomplete HPOA onsets: TUBA4A (13 uncited patients, onset in infancy to 25 years, E0
    knows only adult ALS), TAF4, EMILIN1, SOCS1 and SPATA22. None is a data error.
  - With margin 0, the minimum earliest onset of 1 year harms 31 and helps 286; 16 years harms 23; 40 years harms 13;
    60 years harms 0.
- **Only late-onset-only genes (≥ 60 years) harm no one.** The strictest such variant, `age-v1` (16 genes, 30-year
  margin), helps 49 uncited patients with MRR change about +0.00000001. No dev patient has any of its 16 genes, so
  its zero harm is not a test. Its genes are mostly type 2 diabetes susceptibility, which also occurs in young
  people.
- **Recommendation:** drop age as a hard rule. E0's onset knowledge is not reliable enough to block on with
  certainty. `age-v1` stays implemented and documented; it enters the layer only if Mateo decides so.

## 7. Process notes (all disclosed in BITACORA)
- **K2 draft leak:** a first draft left the query's own publication in the per-gene null (+0.081). It was fixed
  (+0.076) before any decision.
- **Classifier block:** the automatic permission check blocked the main session from running the CONFIRM and vault
  reads (patient data), so Mateo ran both commands himself, as pre-registered.
- **Red merge:** PR #166 (vault script) merged with 3 failing CI tests (torch absent in CI). #167 fixed it before
  the read, and merges now wait for a passing check.
- **PC freeze:** an analysis script froze the PC for about 15 minutes (out of memory). It was fixed, and analysis
  jobs now run under a 4–8 GB memory cap.

## 8. Where everything is

| What | Where |
|---|---|
| Decisions | ADR-0019 (+ amendments 2026-10-14 ×2, 2026-10-15), ADR-0020 |
| Plan and status | PHASE3.md §2e–§2f |
| Batch 1, memory, R5, cross-fit | `docs/analyses/P3-BATCH1-DIAG.md` §1–§11 |
| Add-on, room for sex/age, earlier re-rankers | `docs/analyses/P3-ADDON.md` |
| CONFIRM protocol and result | `docs/analyses/P3-CONFIRM.md`, `results/P3/addon/confirm.json`, `results/P3/CONFIRM_LEDGER.md` |
| Vault pre-registration, result, addendum | `docs/experiments/EXP-V-002.md`, `results/P3/EXP-V-002/` (vault.json, ranks, overlap.json, post_read.json), `docs/TEST_LEDGER.md` |
| Sex rule | `docs/analyses/P4-SEX.md`, `src/diagnostic_ar_training/v4/sexrule.py`, `results/P4/sex/` |
| Published release | `model-v4.0.0` (pre-release), MateAlv/diagnostic.ar-model, PR #12 |
| Release artifacts and handoff | `docs/HANDOFF-v4-prod.md`, `dist/v4-layer/`, `dist/genphenia-v4.0/MANIFEST.json`, `results/P4/release/` |
| Second CONFIRM read (F3) | `docs/analyses/P4-CONFIRM.md`, `results/P4/confirm2/`, `results/P3/CONFIRM_LEDGER.md` row 2 |
| Age rule | `docs/analyses/P4-AGE.md`, `src/diagnostic_ar_training/v4/agerule.py`, `results/P4/age/` |
| Run rows | `results/P3/runs/*.json` |
| Code | `src/diagnostic_ar_training/sim4/`, `v4/` (harness, `addon.py`, `sexrule.py`); `scripts/analysis/p3_batch1/`, `p3_addon/`, `p4_sex/` |
| PRs | MateAlv/diagnostic.ar-training #149–#174 |
