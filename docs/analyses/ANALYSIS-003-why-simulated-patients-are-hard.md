# ANALYSIS-003: Why simulated patients are too hard for E0, and the literature check's layer

- **Date:** 2026-09-30.
- **Data:** R1-train only, plus simulated candidate 2
  (`ds-sim0.4.2-full-n100-s1001`); 3,073 cases sampled by case-id hash
  (1 in 160). Nothing from R1-dev, test or vault.
- **Scripts:** `scripts/analysis/{e0_ablation,noise_types,uncited_categories,panel_layers}.py`.
- **Outputs:** `results/analyses/ANALYSIS-003/`.

## 1. E0 ablations: noise is what makes candidate 2 hard
E0 in-vocab MRR:

| Cases | MRR | Terms per case |
|---|---|---|
| Candidate 2, as exported | 0.163 | 7.45 |
| … without noise | 0.472 | 4.42 |
| … without generalisation | 0.179 | 7.45 |
| … without specialisation | 0.194 | 7.45 |
| … profile terms ungeneralised, no noise | 0.559 | 4.42 |
| … all true terms | 0.742 | 13.13 |
| … without vocabulary noise (related noise kept) | 0.384 | |
| … without related noise (vocabulary noise kept) | 0.194 | |
| R1-train, publication not cited in HPOA | 0.405 | 8.11 |
| … only the terms kb-v4 explains | 0.479 | 5.53 |

**Reading:**
- Without noise, simulated patients are about as hard as real ones (0.472
  vs 0.479).
- Real patients' unexplained terms cost E0 0.074. The simulator's noise
  costs 0.309, almost all of it from vocabulary noise (0.22).
- The simulator's **vocabulary** noise is no more specific than real
  unexplained terms (mean IC 4.79 vs 4.65, from
  `results/analyses/ANALYSIS-003/noise_types.json`), so specificity is not
  the difference. The related noise is more specific (7.28). All noise
  together averages 5.55 (`e0_ablation.json`).

## 2. The reference KB inflated "unexplained"
- **Where the inflation came from.** `calib-v1`, the ANALYSIS-002 targets
  and the noise vocabulary all measure R1-train patients against `kb-v4`,
  which masks **every** R1 publication. For a patient whose paper HPOA
  cites, masking removes the annotations taken from that very paper, so
  the disease's real features look "unexplained".
- **What those terms really are.** They are specific features of *some
  disease*. Drawn as noise for another gene, they point E0 at the wrong
  gene.
- **Why this is the wrong reference.** Simulator v0.4's profiles
  (`hpoa-recount-v1`) keep the R1-train papers' annotations. The matching
  reference is therefore:
  - patients whose paper HPOA does not cite (new patients);
  - measured against a KB with the same knowledge, `kb-v3` (R1 held-out
    PMIDs masked, train kept).

| R1-train, share of present terms | Uncited vs kb-v3 | Uncited vs kb-v4 | Cited vs kb-v4 | All vs kb-v4 (ANALYSIS-002) |
|---|---|---|---|---|
| explained | **0.668** | 0.641 | 0.482 | 0.538 |
| more specific | **0.093** | 0.087 | 0.130 | 0.115 |
| related (IC ≥ 2) | **0.082** | 0.088 | 0.120 | 0.108 |
| weakly related or unrelated (IC < 2) | **0.157** | 0.185 | 0.268 | 0.239 |
| unexplained terms per case | 1.92 | 2.20 | 3.10 | |

The noise target for new patients is therefore about 0.24 of present
terms (0.082 + 0.157), not 0.348. The vocabulary should be drawn from
those patients' unexplained terms.

## 3. G2a scored the wrong layer
- **The problem:** G2a compared the literature's prevalence (what
  patients *have*) with simulated **reported** rates.
- **The evidence:** on the 145 independent panel rows whose gene has at
  least 10 R1-train patients, real patients' own reported rates miss the
  literature by an MAE of **0.307**. Reporting alone costs that much.
- **Candidate 2:**
  - its **true** layer (`true_present`) scores 0.269 on the same rows and
    0.305 on all 497;
  - its reported layer scores 0.381 and 0.405.
- **The fix:** for a truth-then-reporting simulator, the literature check
  belongs on the truth layer; G2b already checks reporting against real
  patients. UP has no truth layer; its emission is its truth model, so
  its emission is scored.

## 4. Consequences
- **ADR-0012 amendment 3:** G2a is scored on the truth layer where a
  dataset has one.
- **ADR-0011 amendment 4 (candidate 3):**
  - noise calibration and pilot targets come from uncited R1-train
    patients measured against kb-v3;
  - a new noise vocabulary is built from their unexplained terms;
  - a train-side go/no-go check runs before the last R1-dev read.
