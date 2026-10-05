# EXP-Q-001: Better questions (L4) on S3 v2

- **Front:** B (questioner)
- **Registered:** 2026-10-03, by Mateo Alvarez (written by the assistant)
- **Status (updated 2026-10-04):** completed. The dev search and the one sealed S3-v2-test read (2026-10-03) are done, P1 passes; see "Dev search log", "Results (sealed S3-v2-test, 2026-10-03)" and "Verdict" below. The status and 2026-10-03 lines that follow are the text as registered, left unchanged.
- **Status at registration:** planned. The strategy list for the sealed read is added as an
  addendum before the read.
- **2026-10-03:** the dev search (phase 3) is done and logged below; the sealed read has not happened.
- **Governing decision:** ADR-0014.

## Hypothesis
A re-ranker-aware, adaptive question strategy gets more out of the
patient's answers than the S3 v1 questioner and the current production
agent strategy, with the same question budget and the same re-ranker.

## Strategies (budget 9 questions each)
| Id | Strategy |
|---|---|
| Q0 | S3 v1 questioner: information gain over E0's top-10 with P(term \| gene) from the knowledge; never asks reported terms or their relatives; non-adaptive, 9 at once |
| Q1 | The production agent's selector, imported read-only from MarBL00126/diagnosticar-question-agent `feat/rerank-negaciones`: top-50 posterior, P(term \| disease), MMR diversity; 3 rounds × 3, adaptive |
| Q2 | Re-ranker-aware adaptive: after each round, recompute the posterior **with the re-ranker applied to the answers so far**, then pick the 3 terms with the highest expected information gain under that posterior; 3 × 3 |
| Q2b | Q2 without diversity: an ablation of Q2's diversity term, if Q2 has one |

The ≤ 6 strategy budget includes Q1 parameter settings, if any are tried.

## Data and systems
- **Patients:** `s3-data-v2`; search on S3-v2-dev only.
- **Answers:** from truth (ADR-0014 §4), plus a 5% noise sensitivity run.
- **Re-ranker:** EXP-B-004's selected final system, frozen before L4's
  final comparison. During the search: rr-v1 (as a stand-in) and the
  provisional best.
- Questioners see a `PublicCase` only.

## Metrics (fixed now)
- **Primary:** Δ MRR vs **E0-initial** (no questions) after the interview +
  re-ranker, with a paired bootstrap CI over genes, per strategy, on the
  same patients.
- **Secondary:**
  - the questioner effect alone: E0 + "yes" answers, without the re-ranker;
  - harmed and helped;
  - yes/no counts per case;
  - top-10 hit rate.
- **Selection on dev:** maximise the primary metric subject to harmed ≤ 5%
  vs E0+answers under Q0.

## Dev search log
Phase 3 of ADR-0014 (L4), on `phase4/dev-search`. **S3-v2-dev only**, all 9,750 cases after the
exclusion list; S3-v2-test and R1-test were not read. Every run is a row of
`results/EXP-Q-001/dev-search.tsv` (the header fixes the interpretation of the selection rule before the
first run); reports and per-case interviews are in `results/EXP-Q-001/dev/` and `results/EXP-Q-001/noise/`.

- **Re-ranker:** the provisional EXP-B-004 winner F (`results/EXP-Q-001/dev-search/rerank-provisional.json`,
  hash `8ecd5b320f33`: propagated, k = 0.5, neg weight 0.5, kb-v6). Questioner knowledge kb-v6. Budget 9,
  answers from the truth, noise 0, one seed.
- **Budget:** 5 of 6 strategies (Q0, Q1, Q2, Q2b λ = 0.3, Q2b λ = 0.6). Q1 has no tried parameter settings.
- **Smoke:** a 24-case run of Q2b (λ = 0.3) with this re-ranker, label `smoke-l4`, checked the pipeline
  (`results/EXP-Q-001/smoke-l4/`); it is not a logged configuration and not evidence.
- **Cross-check:** Q0's re-ranker effect (+0.0063, harmed 4.85%) equals EXP-B-004's F row exactly, as it should.
- Primary metric is Δ MRR of the final system vs E0-initial (no questions), CI over genes. Hash column = run hash
  (strategy, λ, re-ranker, KB, budget, noise, seed).

### Results, noise 0
| strategy | hash | MRR initial | MRR +answers | MRR final | primary Δ vs E0-initial [95% CI] | harmed | helped | questioner effect | re-ranker effect [CI] | rr harmed | top-10 initial → final | yes/no per case |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Q0 | d6649651bbf6 | 0.3185 | 0.3397 | 0.3460 | +0.0275 [+0.0250, +0.0298] | 0.081 | 0.379 | +0.0212 [+0.0190, +0.0233] | +0.0063 [+0.0051, +0.0075] | 0.049 | 0.451 → 0.474 | 1.10 / 7.82 |
| Q2 | 1fc2b42bfc6b | 0.3185 | 0.3450 | 0.3513 | +0.0328 [+0.0300, +0.0355] | 0.085 | 0.392 | +0.0265 [+0.0240, +0.0291] | +0.0063 [+0.0051, +0.0076] | 0.051 | 0.451 → 0.478 | 1.12 / 7.79 |
| Q2b-lam0.3 | ba350eb94073 | 0.3185 | 0.3460 | 0.3522 | +0.0337 [+0.0308, +0.0365] | 0.086 | 0.394 | +0.0275 [+0.0248, +0.0301] | +0.0062 [+0.0049, +0.0075] | 0.049 | 0.451 → 0.476 | 1.10 / 7.81 |
| Q2b-lam0.6 | 9963dbe02527 | 0.3185 | 0.3464 | 0.3525 | +0.0339 [+0.0310, +0.0368] | 0.084 | 0.393 | +0.0279 [+0.0252, +0.0306] | +0.0060 [+0.0049, +0.0073] | 0.048 | 0.451 → 0.475 | 1.05 / 7.86 |
| Q1 | 12b03165b15d | 0.3185 | 0.3463 | 0.3517 | +0.0332 [+0.0302, +0.0361] | 0.077 | 0.399 | +0.0278 [+0.0250, +0.0305] | +0.0054 [+0.0041, +0.0066] | 0.059 | 0.451 → 0.482 | 1.14 / 7.77 |

Selection (re-ranker-effect harmed <= 5%, primary CI lower bound > 0, ties within 0.001 -> simpler):
- feasible: ['Q0', 'Q2b-lam0.3', 'Q2b-lam0.6']; best Δ +0.0339; within 0.001: ['Q2b-lam0.3', 'Q2b-lam0.6']
- winner: Q2b-lam0.6 (9963dbe02527), primary Δ +0.0339

Paired difference in final MRR vs Q0 (same cases, 95% CI over genes):
- Q2: +0.0054 [+0.0037, +0.0070]
- Q2b-lam0.3: +0.0062 [+0.0043, +0.0081]
- Q2b-lam0.6: +0.0065 [+0.0044, +0.0086]
- Q1: +0.0057 [+0.0035, +0.0080]
- not feasible: [('Q2', 0.05067), ('Q1', 0.05887)]

- **The questioner matters more than the re-ranker.** E0 alone gains +0.021 (Q0) to +0.028 (Q2b λ = 0.6,
  Q1) in MRR from the answers; the re-ranker adds +0.005 to +0.006 on top, with the CI above 0
  in every strategy. Every adaptive strategy beats Q0 on final MRR by +0.005 to +0.007 (paired CIs above 0).
- **Winner by the rule: Q2b with λ = 0.6** (`9963dbe02527`), primary Δ +0.0339 [+0.0310, +0.0368],
  +0.0065 [+0.0044, +0.0086] over Q0. λ = 0.3 is within 0.001 (Δ +0.0337), so the choice between the two λ
  is not resolved by the data; the higher Δ was taken.
- **Q2 and Q1 fail the harm cap** with this re-ranker: the re-ranker effect harms 5.07% (Q2) and 5.89% (Q1)
  of cases. Their primary Δ is +0.0328 and +0.0332 (0.0011 and 0.0007 below the winner's). Q1 has the highest
  top-10 rate (0.482), a different trade-off from MRR.
- **Q2 (re-ranker-aware) vs Q2b (diversity).** Diversity adds +0.0009 to +0.0011 of primary Δ (not tested for significance); the plan's
  hypothesis (re-ranker-aware adaptive beats the S3 v1 questioner) holds on dev: Q2 − Q0 = +0.0054 [+0.0037, +0.0070].

### Noise sensitivity (5% of answers flipped or "unknown"), winner and Q0
| strategy | hash | MRR initial | MRR +answers | MRR final | primary Δ vs E0-initial [95% CI] | harmed | helped | questioner effect | re-ranker effect [CI] | rr harmed | top-10 initial → final | yes/no per case |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Q0 | abdad4c63756 | 0.3185 | 0.3272 | 0.3334 | +0.0148 [+0.0117, +0.0176] | 0.166 | 0.353 | +0.0086 [+0.0058, +0.0114] | +0.0062 [+0.0050, +0.0074] | 0.049 | 0.451 → 0.460 | 1.24 / 7.46 |
| Q2b-lam0.6 | f4bbbc0d67fd | 0.3185 | 0.3331 | 0.3388 | +0.0203 [+0.0170, +0.0236] | 0.168 | 0.364 | +0.0146 [+0.0113, +0.0178] | +0.0057 [+0.0046, +0.0070] | 0.049 | 0.451 → 0.461 | 1.20 / 7.49 |

Paired difference in final MRR vs Q0 (same cases, 95% CI over genes):
- Q2b-lam0.6: +0.0055 [+0.0028, +0.0083]
- not feasible: []

With 5% noise the questioner effect falls from +0.021 to +0.009 (Q0) and from +0.028 to +0.015 (Q2b λ = 0.6);
the re-ranker's effect hardly moves (+0.0062 and +0.0057, harmed 4.9% in both). The ordering holds:
Q2b λ = 0.6 − Q0 = +0.0055 [+0.0028, +0.0083]. The share of cases harmed against E0-initial rises from 8% to 17%.

### Proposal for the sealed read (not committed; Mateo approves before phase 4)
The L4 winner Q2b λ = 0.6, Q0 and Q1, each with the final re-ranker of EXP-B-004 (if that changes from F,
Q2b's λ and the L4 comparison should be re-run on dev first, since Q2 and Q1's eligibility depends on the
re-ranker's harm).

## Sealed read
Shared with EXP-B-004: the same single S3-v2-test read scores the selected
strategy, Q0 and Q1, with the final re-ranker.

## Deployment note
If a strategy wins, it is a proposal for the production agent (its repo is
editable by us since 2026-10-03). It would go through a PR there, after the
sealed result.

## Addendum (2026-10-03): final pre-registration of the sealed S3-v2-test read
This is written after the dev search (PR #101) and **before** any
S3-v2-test read. Mateo approved it on 2026-10-03: "questions first", and the
5% harm cap is kept.

- **Re-ranker for every strategy:** **F** = `propagated`, k 0.5, weight 0.5,
  on kb-v6 (config `8ecd5b320f33`), selected on dev by the pre-registered
  rule. It is leak-free for S3 v2 (half B of annot-split-v2 dropped).
- **Strategies scored,** budget 9 and noise 0 for each:

  | Strategy | Config |
  |---|---|
  | **Q2b** (λ 0.6) | `9963dbe02527` |
  | **Q0** | — |
  | **Q1** | agent `feat/rerank-negaciones` @ 48d901e |

- **Primary hypothesis (P1):** Q2b beats Q0 on S3-v2-test. Primary Δ vs
  E0-initial, as the paired difference Q2b − Q0. **It passes if the paired
  bootstrap 95% CI over genes has its lower bound > 0, and the re-ranker
  effect's harmed share under Q2b is ≤ 5%.**
- **Secondary (S1):** Q2b − Q1, the paired difference with its CI. It is
  reported, not gated.
- **Secondary (S2):** the 5% answer-noise run for Q2b and Q0, reported.
- **Procedure:**
  - one evaluation session, with `DXT_SEALED_READ=EXP-B-004` set only for it
    (the harness's sealed experiment id);
  - each strategy is one invocation, so there is one ledger row per
    invocation, all within this session;
  - the systems are fixed above, with no re-runs and nothing chosen after
    seeing test numbers;
  - the exclusion list `s3-data-v2-excl-v1` is applied.
- **If P1 passes:** Q2b goes to the production question agent as a PR
  (repo editable since 2026-10-03), described as validated on simulated
  interviews only.


## Results (sealed S3-v2-test, 2026-10-03)
One session, 12 invocations, 9,565 cases (S3-v2-test minus 131 `s3-data-v2-excl-v1` cases), re-ranker F
(`8ecd5b320f33`), budget 9, answers from truth. Run at code `c1342164fcb4`; the ledger has one row per invocation.
The runs were made under `--exp EXP-B-004` (the only id the harness opens the sealed part for), so their outputs and
manifests are in `results/EXP-B-004/sealed/`; the analysis (`scripts/sealed_analysis.py`, paired bootstrap over genes,
2000 resamples, seed 0) is in `results/EXP-Q-001/sealed-analysis.{md,json}`. Q2b's run hash is `9963dbe02527`.
Q1 ran the agent at `feat/rerank-negaciones` @ 48d901e3a0197984c2811345c115c99f3e42d54c (clean).

| strategy | noise | primary Δ vs E0-initial [95% CI] | harmed | helped | questioner effect [CI] | re-ranker effect [CI] | re-ranker harmed |
|---|---|---|---|---|---|---|---|
| Q2b λ 0.6 | 0 | +0.0330 [+0.0301, +0.0360] | 0.0811 | 0.3803 | +0.0263 [+0.0236, +0.0290] | +0.0067 [+0.0055, +0.0079] | 0.0477 |
| Q0 | 0 | +0.0281 [+0.0255, +0.0308] | 0.0825 | 0.3606 | +0.0215 [+0.0191, +0.0240] | +0.0066 [+0.0054, +0.0079] | 0.0506 |
| Q1 | 0 | +0.0312 [+0.0284, +0.0340] | 0.0792 | 0.3800 | +0.0256 [+0.0230, +0.0282] | +0.0056 [+0.0044, +0.0068] | 0.0558 |
| Q2b λ 0.6 | 0.05 | +0.0177 [+0.0143, +0.0210] | 0.1603 | 0.3570 | +0.0118 [+0.0084, +0.0149] | +0.0059 [+0.0047, +0.0071] | 0.0490 |
| Q0 | 0.05 | +0.0153 [+0.0120, +0.0185] | 0.1612 | 0.3428 | +0.0089 [+0.0057, +0.0119] | +0.0063 [+0.0052, +0.0076] | 0.0528 |

MRR (noise 0): E0-initial 0.3281; E0+answers 0.3544 (Q2b), 0.3495 (Q0), 0.3537 (Q1); final 0.3611, 0.3562, 0.3593.
Top-10 final 0.4926, 0.4894, 0.4955 (initial 0.4673).

- **P1, Q2b − Q0 (final MRR, same cases): +0.0049 [+0.0027, +0.0069]**; harmed 0.1476, helped 0.2027.
  Re-ranker-effect harmed share under Q2b: 0.0477 (cap 0.05).
- **S1, Q2b − Q1: +0.0017 [-0.0006, +0.0043]**; harmed 0.2186, helped 0.2043.
- **S2, 5% noise, Q2b − Q0: +0.0024 [-0.0002, +0.0050]**.

## Verdict
- **P1 passes:** the CI lower bound (+0.0027) is above 0 and the re-ranker effect harms 4.77% of cases (cap 5%).
  The effect is +0.0049 on test against +0.0065 on dev.
- **S1:** Q2b is not distinguishable from Q1 (CI includes 0). Q1's re-ranker effect harms 5.58% of cases, above the cap.
- **S2:** under 5% answer noise the point estimate stays positive (+0.0024) but the CI includes 0, so the
  noise-robustness seen on dev (+0.0055 [+0.0028, +0.0083]) is not confirmed on test.
- Q2b → propose to the production question agent (a separate PR, not part of this task)
- Validated on simulated interviews only.
