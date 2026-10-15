# P3-CONFIRM: the CONFIRM check of the frozen v4 candidate

**Protocol written 2026-10-15, before the CONFIRM fold was opened** (PHASE3 §2f steps 4–5). The ledger
`results/P3/CONFIRM_LEDGER.md` did not exist when this was committed: fold 4 has never been read.

## 1. Frozen system (PHASE3 §2f step 4)

| Part | Id | sha256 |
|---|---|---|
| Network | `R5x-f4-ef2f309462`, `last.pt` (R5-r30's recipe, real patients of folds 0–3) | `22edfd7ea56510d1210111797215a9a54c22d829979ef05b4e3cc85a758004da` |
| Add-on | `p3-addon-v1-all` (`ft-v1-bundle.json`) | `31299383a7dce279acdfae37248db8e7e04c62225fd892080c39758276a093b6` |
| Add-on knowledge | `p3-addon-kb-v1` (`ft-kb.json.gz`; HPOA 2025-03-03, E0's gene list) | `089ccf87af2347f19ae37464a4e55629bf43ca6a08cc1a8f70dca828d632535a` |

- The network reads present terms only; the add-on reads sex, age, onset and excluded terms (ADR-0019 amendment
  2026-10-15). The add-on's negated-symptom weights are 0 (P3-ADDON), so `p3-addon-v1-sex-age-onset`
  (`360c5fe6…`) is the same model. It is scored too, as a check that the two agree.
- Code: `scripts/analysis/p3_addon/confirm.py` at the commit that records this protocol. It refuses a dirty
  tree, verifies the knowledge and bundles, and checks that the network trained on exactly folds 0–3.

## 2. Finalists
1. **F1 (primary): network + add-on** (`p3-addon-v1-all`).
2. **F2: network alone.**

## 3. Reading
- Patients: `p3-v1` train, fold 4 (CONFIRM), every patient, opened once through `sim4.folds.cases_in`
  (DXT_P3_CONFIRM=1, ledger row).
- Metric: capped MRR (at most 10 patients per publication), Δ vs E0 with the publication-cluster bootstrap
  (2,000 resamples, seed 0), 95% CI. Primary stratum: uncited by E0's knowledge.
- Also reported, not gating:
  - uncited in-vocabulary, cited, helped and harmed counts;
  - F1 vs F2;
  - phenotype-swap control (network vs E0), including the true gene's raw rank split by whether the gene has
    real patients in folds 0–3;
  - parent terms (network vs E0).

## 4. Decision rule (fixed before the read)
| Outcome on F1, uncited, Δ capped MRR vs E0 | Then |
|---|---|
| 95% CI lower bound > 0 | **Pass:** vault pre-registration with F1 as the primary hypothesis and F2 as the secondary. |
| Pass, but F1 − F2 has a 95% CI entirely below 0 | Pass for the network: the vault primary becomes F2 and the add-on is dropped. |
| Point estimate > 0, CI includes 0 | No pre-registration without Mateo's decision (CONFIRM is small and may be underpowered). |
| Point estimate ≤ 0 | Stop: the gain did not replicate. Report to Mateo. |

- **Expectation** from folds 0–3 out of fold (P3-BATCH1-DIAG §11, P3-ADDON): F2 +0.071 [+0.049, +0.096], with a
  per-fold range of +0.051 to +0.089; F1 − F2 about 0.
- **One read.** Any further read of fold 4 is a new ledger row and is disclosed.

## 5. Disclosures
- The real-patient share (0.3) was chosen on fold 3. Folds 0–3 have been read many times; only CONFIRM and the
  vault count as confirmation.
- The add-on was fitted on the networks' out-of-fold logits of folds 0–3, but runs on `R5x-f4`, which trained
  on all of them.
- Before this protocol, `confirm.py` ran once in `--dry-run` on fold 3 (in-sample for this network; no gate, no
  ledger) to check the code path. It found and fixed one bug in the parent-term control. Its numbers match the
  harness's own readings of `R5x-f4` on fold 3 (+0.3620), E0's swap floor (0.0131) and E0's parent-term
  reading (0.1918).

## 6. Result (read once, 2026-10-15T16:45Z, main `d663d26`, run by Mateo; ledger row 1)
Fold 4: 933 patients; 406 uncited in 99 publications, 527 cited in 117. `results/P3/addon/confirm.json`.

| Capped MRR, Δ vs E0 [95% CI] | uncited | uncited in-vocab | cited |
|---|---|---|---|
| **F1 network + add-on** | **0.1512 → 0.2230, +0.0717 [+0.0332, +0.1200]** (161 helped / 109 harmed) | +0.0937 [+0.0421, +0.1564] | +0.0650 [+0.0345, +0.1017] |
| F2 network | +0.0713 [+0.0331, +0.1195] (159 / 110) | +0.0931 | +0.0645 |
| F1 − F2 | +0.0004 [+0.0000, +0.0010] (76 / 5) | +0.0006 | +0.0005 |

- Uncited top-1: 8.6% → 13.5%; top-10: 28.1% → 35.2% (F1 and F2 equal).
- `p3-addon-v1-sex-age-onset` gives the same numbers as `p3-addon-v1-all`, as expected.
- **Decision rule: pass.** F1's lower bound is above 0 and F1 − F2 is not below 0, so the vault pre-registration
  takes F1 as the primary and F2 as the secondary.
- **Phenotype-swap control:** capped Δ +0.0011 [−0.0003, +0.0032]. True gene's raw rank: genes with real patients in
  folds 0–3 (158) median 1,112 → 953, mean log2 ratio −0.12, 63% improved; other genes (148) 2,246 → 2,171, −0.06,
  51%. The lean seen before is smaller here.
- **Parent terms: the gain is gone.** Network vs E0, uncited: 0.1395 → 0.1403, +0.0008 [−0.0207, +0.0228]; cited
  +0.0221 [−0.0002, +0.0473]. Out of fold on folds 0–3 the network kept 40% (+0.029). On CONFIRM its advantage
  depends on the curators' exact terms: a patient described with the parent terms gets no benefit from it.
