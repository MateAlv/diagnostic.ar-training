# EXP-B-001: rr-v1, a feature-weighted re-ranker over v3.0, searched on R1-dev

- **Front:** B
- **Registered:** 2026-09-29, by Mateo Alvarez
- **Status:** done (2026-09-29)

## Hypothesis
Re-scoring v3.0's top-200 genes with knowledge-based compatibility features
for the patient's negated symptoms, sex, age and onset (`kb-v3`) improves R1
MRR over E0. Age and onset carry most of the gain, because 87% of v3.0 genes
have onset knowledge in `kb-v3`, against 4–7% for sex restriction or explicit
negation.

## Systems compared
| System | Artifact ids / code | Notes |
|---|---|---|
| E0 | `genphenia_v3` | Also the `identity` configuration. It must reproduce EXP-000's dev ranks exactly |
| rr-v1 | `rerank/features.py`, `rerank/model.py`, KB `kb-v3` | `score = log p_gnn + Σ w_f · feature_f` on the top-200 genes; the rest unchanged |

## Features (fixed before any result)
`FeatureParams`: `neg_strength` k = 0.5, `unknown_frequency` = 0.3 (the
qa-agent's prior), `epsilon` = 0.01, `onset_smoothing` = 0.1.

| Feature | Definition |
|---|---|
| **neg** | Σ over excluded terms t of log(1 − k·P(t\|gene)). P is the weight-mixture over the gene's diseases (`genes-v1`) of the noisy-OR of annotated frequencies of t and its descendants. It is 0 when the gene doesn't annotate t |
| **sex** | log(P(sex\|gene) / 0.5), with P(male) from inheritance (male-limited 0.99, female-limited 0.01, Y 0.99, XLR 0.9, XLD 0.33, X-linked 0.7, else 0.5), plus log(max(ε, P(t\|gene, sex) / P(t\|gene))) for each present term. The second part penalises findings the gene explains only through annotations restricted to the other sex |
| **age** | log(max(ε, P(onset ≤ age \| gene))), with onset intervals uniform. A disease without onset data counts as compatible |
| **onset** | log(P(onset bin \| gene) / P(onset bin \| background)) over 8 bins, smoothed with 0.1 uniform. Diseases without onset use the background |

Each feature is 0 when its input is missing, which makes the re-ranker
exactly the identity then (tested).

## Data
- **Fitting:** none. rr-v1 has four weights and no trained parameters.
- **Selection:** R1-dev (1,883 patients), publication-clustered bootstrap.
- **No sealed read in this experiment.** A test read for the chosen rr-v1
  happens only in Phase 4 under its own pre-registration.

## Search (budget: 16 configurations, all reported)
1. `identity`: all weights 0 (1 configuration).
2. **Stage 1:** each feature alone, w ∈ {0.5, 1, 2} (12 configurations).
   This doubles as the input-view ablation, because a weight of 0 is
   equivalent to removing that input.
3. **Stage 2, fixed by rule:** each feature takes its best stage-1 w if that
   configuration's dev Δ MRR > 0, else 0 (`stage2-combined`). The same
   combination runs at half strength (`stage2-combined-half`). That is 2
   configurations.

## Primary metric and selection rule
- **Primary:** Δ MRR vs E0 on R1-dev, all cases, with a paired
  publication-clustered 95% CI.
- **Also reported:** harmed/helped rates, top-1/10, subsets with each input.
- **rr-v1 := `stage2-combined`** if its Δ > 0 and its harmed rate ≤ 5%;
  otherwise the best single-feature configuration meeting the same rule;
  otherwise "no candidate".
- The candidate advances to the Phase 4 gate (R1-test, MCRD, DDD). Nothing
  here claims a confirmed improvement.

## Expectations (written before running)
| Component | Expectation |
|---|---|
| identity | Ranks identical to EXP-000 dev, case by case |
| age / onset alone | Small positive Δ (+0.005 to +0.03 MRR) |
| neg alone | ≈ 0, as the qa-agent measured with frequency-based negation |
| sex alone | ≈ 0 overall (few genes), possibly positive in the X-linked subset |
| Combined | Δ in [0, +0.04]; harmed rate < 5% |

## Results
Run from commit `863fa3d` (the pre-registration was committed first).
Everything is in `results/EXP-B-001/` (a ranks file per configuration and
`r1-v1-dev__rr-v1-grid.json`); manifest
`results-EXP-B-001-r1-v1-dev-rr-v1-grid`. The run took 52 s.

R1-dev, n = 1,883. Δ is vs E0 with a paired publication-clustered 95% CI:

| Config | MRR | Δ MRR | 95% CI | Harmed | Helped |
|---|---|---|---|---|---|
| identity | 0.4485 | +0.0000 | [+0.0000, +0.0000] | 0.000 | 0.000 |
| neg=0.5 | 0.4418 | −0.0067 | [−0.0235, +0.0051] | 0.116 | 0.079 |
| neg=1.0 | 0.4350 | −0.0135 | [−0.0425, +0.0059] | 0.147 | 0.098 |
| neg=2.0 | 0.4266 | −0.0219 | [−0.0611, +0.0060] | 0.186 | 0.112 |
| sex=0.5 | 0.4485 | +0.0000 | [−0.0008, +0.0008] | 0.011 | 0.018 |
| sex=1.0 | 0.4488 | +0.0003 | [−0.0006, +0.0014] | 0.019 | 0.033 |
| sex=2.0 | 0.4486 | +0.0001 | [−0.0009, +0.0013] | 0.032 | 0.040 |
| age=0.5 | 0.4470 | −0.0015 | [−0.0047, +0.0018] | 0.052 | 0.056 |
| age=1.0 | 0.4454 | −0.0031 | [−0.0084, +0.0024] | 0.071 | 0.081 |
| age=2.0 | 0.4406 | −0.0079 | [−0.0154, −0.0005] | 0.114 | 0.107 |
| onset=0.5 | 0.4502 | +0.0017 | [−0.0012, +0.0051] | 0.061 | 0.090 |
| onset=1.0 | 0.4462 | −0.0022 | [−0.0071, +0.0021] | 0.083 | 0.095 |
| onset=2.0 | 0.4394 | −0.0091 | [−0.0177, −0.0013] | 0.113 | 0.105 |
| stage2-combined (sex=1, onset=0.5) | 0.4504 | +0.0020 | [−0.0012, +0.0053] | 0.070 | 0.104 |
| stage2-combined-half | 0.4498 | +0.0014 | [−0.0005, +0.0037] | 0.047 | 0.077 |

**Identity check:** ranks equal to EXP-000 dev, case by case (1,883 of
1,883).

**Applying the pre-registered selection rule:**
- `stage2-combined` has Δ > 0 but a harmed rate of 7.0% > 5%, so it is
  rejected.
- The best single-feature configuration with Δ > 0 and harmed ≤ 5% is
  `sex=1.0` (Δ +0.0003).
- **So the rule yields rr-v1 = `sex=1.0`, an effect indistinguishable from
  zero.**

**Expectations vs outcome:**

| Component | Expected | Measured | Met? |
|---|---|---|---|
| identity | exact | exact | ✅ |
| neg | ≈ 0 | negative | ❌ worse than expected |
| sex | ≈ 0 | ≈ 0 | ✅ |
| age | small positive | negative | ❌ |
| onset | small positive | +0.0017 at w = 0.5 only, CI crosses 0 | weak |
| combined | [0, +0.04] | +0.002, but harmed > 5% | not met |

## Verdict
❌ **No useful rr-v1 on this data.** The pre-registered rule selects a
negligible configuration (`sex=1.0`); it does not advance to a Phase 4 gate
as an improvement. Knowledge-based compatibility features over v3.0 do not
improve R1-dev. For negation they hurt, for a reason diagnosed in Addendum 1.

## Addenda

### 2026-09-29, Addendum 1: why negation hurts on R1 (post-hoc, exploratory, dev only)
- Dev patients with excluded terms and a gene in the KB: 1,511.
- Excluded terms: 17,832, about 12 per patient.

| Excluded term is annotated to (kb-v3) | Share | Mean P(t\|gene) |
|---|---|---|
| the **true** gene | **45.1%** | 0.072 |
| the GNN's top-5 **wrong** candidates | 32.0% | 0.067 |

In phenopacket-store, absent findings are disproportionately the true
disease's own features. Publications tabulate which of the syndrome's typical
signs each patient lacks. A penalty on genes that annotate an absent finding
therefore works against the true gene.

Consequences (to act on, not tuned here):
- **Front B:** a negation feature must not assume that "absent" means "not
  this disease". Any learned re-ranker (rr-v2) should learn the sign from
  R1-train, not from priors.
- **Front A:** the simulator's negatives must reproduce this reporting
  process: mostly the true disease's own annotated terms that the patient
  lacks, which is the simulator's negative source (a). Otherwise the GNN
  learns the opposite of what real records show.
- **Validity:** negations in the web app come from the question agent asking
  about candidates' distinguishing features, a different process from a
  paper's cohort table. R1 may not measure deployment-time negation well.
  An evaluation scenario reproducing the question-agent flow is needed before
  any claim about negation in production.

### 2026-09-29, Addendum 2: age hurts slightly (first hypotheses; see Addendum 3)
`age` penalises genes whose annotated onset is later than the patient's age
at last encounter. Likely causes, to check on dev before any rr-v2:
- HPO "Adult onset" annotated for diseases with variable onset;
- presymptomatic diagnoses reported in phenopackets.

### 2026-09-29, Addendum 3: why age hurts (checked on dev, kb-v4)
- **Not presymptomatic diagnosis.** 128 of the 132 flagged patients with a
  reported onset had that onset before their age at last encounter.
- **Scale.** 1,335 dev patients have age and onset knowledge for their gene.
  For 177 of them (13.3%), P(onset ≤ age | true gene) < 0.5; their median age
  is 5.75 years.
- **Cause.** The feature *averages* over a disease's listed onset classes, and
  gives partial credit within an interval. Orphanet often lists several
  classes for one disease (e.g. Childhood 2–11 and Adult 18–65), so a
  6-year-old with such a disease scores about 0.5 instead of "compatible".
- **Implication for rr-v2.** Add an "any listed onset class fits" variant,
  P = max over intervals, alongside the mean, and let the learned model
  weigh them.
