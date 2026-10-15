# P4-CONFIRM: the second CONFIRM read, for the final model with the hard sex rule

**Protocol written 2026-10-15, before the second read of fold 4** (ADR-0020 decision 3). The first read
([P3-CONFIRM](P3-CONFIRM.md), ledger row 1) scored F1 and F2. This read adds the hard sex rule.

## 1. Final model (Mateo, 2026-10-15)
**F3 = network + add-on + hard sex rule.** Age is dropped as a hard rule ([P4-AGE](P4-AGE.md)). The add-on keeps its
vault-tested weights.

| Part | Id | sha256 |
|---|---|---|
| Network | `R5x-f4-ef2f309462`, `last.pt` | `22edfd7ea56510d1210111797215a9a54c22d829979ef05b4e3cc85a758004da` |
| Add-on | `p3-addon-v1-all` | `31299383a7dce279acdfae37248db8e7e04c62225fd892080c39758276a093b6` |
| Add-on knowledge | `p3-addon-kb-v1` | `089ccf87af2347f19ae37464a4e55629bf43ca6a08cc1a8f70dca828d632535a` |
| Sex rule knowledge | `sex-kb-v3` (101 male-, 36 female-limited genes; P4-SEX) | `7317a6bd5fa6b9b3fd67ae631bde203bb65fc1e5f9ebfb3f768c217ea665c971` |

- **The hard sex rule** moves every gene the patient's sex cannot have (`sex-kb-v3`) below all other genes. Unknown
  sex changes nothing.
- **Code:** `scripts/analysis/p4_confirm/confirm2.py`, merged in #177 before this file was committed; the read
  runs at the commit that registers this file. It refuses unless this file is committed unchanged, the tree is clean,
  DXT_P3_CONFIRM=1 is set, the ledger holds exactly one earlier row and every sha256 above matches. So this second
  read can happen only once.
- **Dry run:** `confirm2.py --dry-run` ran once on fold 3 (no gate, no ledger). It matched the earlier dry runs
  (network vs E0 uncited +0.3620).

## 2. Why a second read of fold 4 is fair
- No model, rule or knowledge was ever fitted or tuned on fold 4.
- The first read scored F1 and F2 and changed nothing in the sex rule. `sex-kb-v3` is built from knowledge, and its
  only data-informed check (zero harmed) used folds 0–3.
- The vault is spent and never reopened, so fold 4 is the only untouched check left for the sex rule.
- **Disclosed:** F1's and F2's numbers on fold 4 are already known (P3-CONFIRM §6). This read is a check of the
  sex rule, and a repeat reading of the add-on.

## 3. Reading
- Patients: fold 4, every patient, opened through `sim4.folds.cases_in` (DXT_P3_CONFIRM=1, ledger row 2).
- Systems on the same patients: E0, F2 (network), F1 (network + add-on), F3 (F1 + hard sex rule).
- Metric: capped MRR, Δ with the publication-cluster bootstrap (2,000 resamples, seed 0), 95% CI. Strata: uncited,
  uncited in-vocabulary, cited, all.
- Also reported:
  - helped and harmed counts;
  - top-1 and top-10;
  - how many patients F1's top 1, 5, 10 and 50 show a gene impossible for their sex.

## 4. Decision rule (fixed before the read)

| Check | Rule | If it fails |
|---|---|---|
| **Primary:** F3 vs E0, uncited capped Δ | 95% CI lower bound > 0 | No deployment without Mateo's decision |
| **Sex rule:** F3 vs F1 (`sex_rule_harmed`: patients F3 ranks below F1, any stratum) | **0 patients harmed** | Each harmed case is inspected. If the knowledge is wrong, the gene leaves the list (new knowledge id, disclosed). If the patient's recorded sex is wrong, it is reported. Mateo decides. |
| **Add-on:** F1 vs F2, all patients (`addon_helped_minus_harmed`) | helped ≥ harmed (Mateo's criterion); the net Δ is reported too | The add-on's weight is lowered or the add-on dropped for production; Mateo decides |

## 5. Expectations
- **F3 vs E0:** about +0.07, since F1 gave +0.0717 [+0.0332, +0.1200] at the first read.
- **Sex rule:** a handful of patients helped, 0 harmed, Δ about 0 (folds 0–3: 130 helped, 0 harmed).
- **Add-on:** at the first read, 76 helped and 5 harmed (uncited), 25 and 0 (cited). On folds 0–3, on top of
  network + sex rule, out of fold: 344 helped and 44 harmed (uncited), net Δ about 0.
- **Command** (Mateo, in his own terminal, after the protocol is merged):
  `cd /home/mate/FIUBA/trabajo-profesional/diagnostic.ar-training && systemd-run --user --scope -q -p MemoryMax=8G
  -p MemorySwapMax=0 nice -n 10 env DXT_P3_CONFIRM=1 PYTHONPATH=src .venv/bin/python
  scripts/analysis/p4_confirm/confirm2.py --reason "P4-CONFIRM second CONFIRM read of F3 (protocol <sha>)"`

## 6. Result
Not read yet.
