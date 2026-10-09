# ADR-0018: `ft-v1.1-c1-lin-all-ens` is the production-ready model; integration comes later

- **Status:** Accepted, 2026-10-08 (Mateo).
- **Context:** Phase 2 ([ADR-0017](0017-phase-2-real-patient-restart.md), [PHASE2.md](../PHASE2.md)).

## Context
`ft-v1.1-c1-lin-all-ens` is GenPhenAI v3.0 (E0), frozen, plus a trained branch. The branch is a zero-initialised
residual on E0's gene logits: 7 non-negative weights over knowledge-derived features of (patient, gene). They cover
sex mismatch, onset later than the patient's, X-linked recessive in females and an absent obligate symptom. The
weights were fitted on 4,103 real patients (`r1-v1` train). Architecture:
`docs/evidence/figures/fig_f_ft_v11_architecture.png`.

It passed both pre-registered, independently reviewed sealed reads on real patients:

| Read | Patients | Δ MRR vs E0 [95% CI] | Harmed | Outcome |
|---|---|---|---|---|
| [EXP-P-005](../experiments/EXP-P-005.md), `p2-v1` test | 3,587 (567 groups) | +0.00138 [+0.00070, +0.00232] (98.33% CI [+0.00058, +0.00256]) | 6 (0.17%) | gate passed |
| [EXP-P-006](../experiments/EXP-P-006.md), final check, post-E0 | 1,072 (221 groups) | +0.00054 [+0.00005, +0.00129] | 3 (0.28%) | H2 holds |

The knowledge-only `safe-v1[sex+onset]` also passed the final check (H1: +0.00029 [+0.00001, +0.00075]).

## Decision
1. **`ft-v1.1-c1-lin-all-ens` is the production-ready model of Phase 2:**
   - bundle `data/ft/ft-v1.1-c1-lin-all-ens/ft-v1-bundle.json`, sha256 `89e3ea09c1e491de29b2d7c6f7955bba7ab6bbb575c47fc17756336c601db340`;
   - knowledge `ft-kb-all-v2`;
   - inference through the numpy `FtResidual.apply` in `ft/bundle.py`, on top of E0's logits.

   The git tag `ft-v1.1-production-ready` marks the commit that records this.
2. **Integration is a later, separate step** (Mateo). It goes through `diagnostic.ar-model`, staging first, then
   production. It needs:
   - the API to pass sex, age, onset and excluded terms;
   - a knowledge build for production (below);
   - a staging check that E0 is unchanged when no new input is given.
3. **`safe-v1[sex+onset]` stays the knowledge-only fallback.** It is confirmed by EXP-P-006 and has no trained
   parameters.

## Before integration
- **Production knowledge.** The evaluated knowledge masks every R1 publication, which is what evaluation requires.
  Production should rebuild it with the same code and no mask (a new id, e.g. `ft-kb-prod-v1`), keeping θ fixed.
  Masking caused all 6 EXP-P-005 harms: females with OFD1 and SLC9A6, whose other inheritance rows were masked. An
  unmasked build should remove that artefact; this is expected, not measured.
- **Inputs in the app.** R1's excluded terms are publication negatives, while the app's absent findings come from the
  question agent (Phase 1, EXP-B-002). The negation feature can only lower a gene, which keeps that difference
  bounded, but it is not measured on interview answers.

## Consequences
- STATE, README, INDEX and EVIDENCE_INDEX name `ft-v1.1` as production-ready.
- `diagnostic.ar-model` is unchanged until integration.
- **2026-10-09, production package.** Built as decided:
  - knowledge `ft-kb-prod-v1` (no mask);
  - bundle `ft-v1.1-prod` (θ of `ft-v1.1-c1-lin-all-ens`, not refitted);
  - a standalone export with its parity fixture in `dist/ft-v1.1-prod/`.

  OFD1, F8, SLC9A6 and THOC2 are no longer X-linked-recessive-only. A dev sanity run is descriptive only, because
  the knowledge includes the dev papers: 11 harmed patients, all through `neg_obligate`, 8 of them from their own
  paper's n/n annotations. Steps, files and limits: [HANDOFF-ft-v1.1-prod.md](../HANDOFF-ft-v1.1-prod.md).
- **2026-10-09, recommended package.** The production default is `dist/ft-v1.1-confirmed/`
  (`ft-v1.1-confirmed-package`): the confirmed bundle on `ft-kb-all-v2`, exactly what passed EXP-P-005 and EXP-P-006.
  - Its known limitation is the masking artefact (OFD1, F8, SLC9A6, THOC2; 6 harms, 0.17%, in EXP-P-005).
  - The unmasked `ft-v1.1-prod` is built but not recommended. On dev (descriptive) it gives +0.00168 with 11 harmed,
    all through the n/n ≥ 5 obligate rule, 8 of them on rows from the patients' own paper. It has no sealed
    confirmation. This replaces "Before integration"'s plan to ship an unmasked build.

