# EXP-Q-001: Better questions (L4) on S3 v2

- **Front:** B (questioner)
- **Registered:** 2026-10-03, by Mateo Alvarez (written by the assistant)
- **Status:** planned. The strategy list for the sealed read is added as an
  addendum before the read.
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

## Sealed read
Shared with EXP-B-004: the same single S3-v2-test read scores the selected
strategy, Q0 and Q1, with the final re-ranker.

## Deployment note
If a strategy wins, it is a proposal for the production agent (its repo is
editable by us since 2026-10-03). It would go through a PR there, after the
sealed result.
