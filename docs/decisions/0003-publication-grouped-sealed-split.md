# ADR-0003: Publication-grouped R1 split with sealed test and vault

- **Status:** Accepted, 2026-09-28.

## Context
- phenopacket-store 0.1.27 has 10,305 usable single-gene patients with sex,
  age, onset and excluded features. It is the only real cohort that exercises
  all three new inputs.
- It is also the most valuable training signal we have for them.
- Over 40 days both fronts will iterate many times, which creates the risk of
  overfitting whatever set we look at.

## Decision
- Split by **publication** (the connected components of shared PMIDs), using
  a salted hash of the component's smallest PMID.
- Four parts:

  | Part | Share | Use |
  |---|---|---|
  | train | 40% | free |
  | dev | 20% | selection |
  | test | 20% | sealed; pre-registered gate reads, ledgered |
  | vault | 20% | sealed; opens once, at the end |

- The split is frozen as `data/splits/r1-v1.json` (content sha256
  `b007aa17…`) on 2026-09-28, before any model output on the cohort was
  looked at.
- The rules are enforced in code (`splits.load_part`, `lineage.ledger`).

## Alternatives dropped
- **Patient-level random split.** Family members and case series would leak
  across parts.
- **Gene-disjoint split.** Meaningless for a gene classifier: every test gene
  must be a known class.
- **Train/test only.** Repeated gate reads would slowly overfit test. The
  vault gives one number nobody has optimised against.
- **Stratified split.** It is harder to keep stable when the cohort grows, and
  the parts came out balanced enough (235–409 genes and 324–706 publications
  per part).

## Consequences
- Test and vault are smaller than the whole cohort, so CIs are wider. We
  accept that for credibility.
- HPOA rows citing dev, test or vault publications (5.45%) must be masked from
  every KB and simulator profile.
