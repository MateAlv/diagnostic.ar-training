# EXP-B-006: release candidate rr-v1[neg=0.5] + onset 0.25 (rerank-v1.1.0), R1-test no-regression read

- **Front:** B
- **Registered:** 2026-10-04, by Mateo Alvarez (release path approved 2026-10-04; written by the assistant)
- **Status:** pre-registered, sealed read not done. The phase 1 text of this file (dev justification plan) is
  superseded by this one; its dev rule is repeated below unchanged.
- **Governing decisions:** ADR-0015 (onset), ADR-0014 (rr-v1, S3), EXP-B-003 (the gate this one mirrors),
  EXP-B-005 (onset on S3 v3b).

## Hypothesis
Adding the `onset` feature at weight 0.25 to the production re-ranker (rr-v1[neg=0.5], `rerank-v1.0.0`) improves
ranking on interviewed simulated patients without exceeding the 5% harm cap (shown on dev here, on S3-v3b-test for
F + onset 0.25 in EXP-B-005), and causes no clear harm to real patients (R1-test, the one sealed read of this
experiment).

## Systems compared
| System | Config | Hash | Notes |
|---|---|---|---|
| E0 | genphenia_v3 (model-v3.0.0) | | R1 reference |
| **Reference: rr-v1 = `rerank-v1.0.0`** | `RerankConfig(kb-v3, llr, k 0.5, top_k 200, neg_llr 0.5)`; code path `Weights(neg=0.5)` | `fe58053033fa` | what production serves |
| **Candidate: rr-v1 + onset 0.25** | the same plus `onset` 0.25; `Weights(neg=0.5, onset=0.25)` | **`71713c8d15b0`** | the only candidate |

- **Knowledge: kb-v3**, the KB inside `rerank-v1.0.0` (sha256
  `39d5f9213afab40090d15bdace663dc94d650b099e6b13643ced0633f4970fa8`, verified against the local artifact).
  Schema 2; R1 dev/test/vault PMIDs masked (15,412 HPOA rows dropped, onset rows included).
- **Hash note.** `8488e32fc7c2` is the same formula with `kb_id = kb-v5` (the form scored on S3-v1 in EXP-B-003 and
  as the bar in EXP-B-004). The hash covers `kb_id`, so on kb-v3 the same formula is `fe58053033fa`. The
  `RerankConfig` of the candidate is `to_dict()` of: `kb_id` kb-v3, `neg_form` llr, `neg_strength` 0.5,
  `neg_tau` null, `neg_cap` null, `top_k` 200, `weights` {`neg_llr` 0.5, `onset` 0.25, every other component 0}.
  `FeatureParams` are the defaults (`unknown_frequency` 0.3, `epsilon` 0.01, `onset_smoothing` 0.1).
- **kb-v3 carries the onset data the feature needs** (checked in the artifact): 9,487 of 12,802 diseases have
  `onset_years` (HPOA 4,303, Orphanet 3,789, Orphanet via exact alignment 1,395 per `data/kb/kb-v3.stats.json`);
  4,642 of 5,192 genes have at least one disease with onset. On the 12,773 diseases shared with kb-v6 (the S3
  KB), `onset_years` is identical in all of them, so the onset component of the dev run and of this read read
  the same onset data; only the phenotype annotations (which kb-v6 thins by half B) differ.
- **Code commit:** the sealed read runs from the commit that registers this file (a clean tree is enforced). The
  check code (`eval/release_check.py`, `dxt rerank release-check`) is in `4db2add`.
- **Path parity** (`scripts/exp_b006_path_parity.py`, R1-train, 400 patients, kb-v3): the `RerankConfig` path used
  by the S3 dev sessions and the `Weights` path used by this read give bit-identical distributions for both systems
  (0 mismatches).

## Dev justification (one dev configuration; S3-v3b-dev only; logged)
EXP-B-005 measured onset on top of F. This is the same question on top of the rr-v1 formula.
- **Rule, fixed before the run (phase 1 commit `5e35051`):** the candidate exists only if, on the
  literature-onset dev cases, the paired Δ CI lower bound is > 0 and harmed vs E0+answers is <= 5%, and the R1-dev
  no-harm check (EXP-B-003 N2 form: CI upper bound >= 0, point estimate >= -0.02) passes.
- **Run (`4648847`, session code `5e35051`):** S3-v3b-dev, 4,562 cases (15 excluded), one Q2b interview (lambda 0.6,
  budget 9, noise 0) driven by rr-v1 on kb-v6; both arms scored on the same answers; the driver's own ranks equal
  its scoring-path ranks on every case. Arms: rr-v1 on kb-v6 (`2b6a00674f4c`) and rr-v1 + onset 0.25 on kb-v6
  (`4c5bdea377e0`). kb-v6 stands in for kb-v3 because S3 needs a KB without half B of `annot-split-v2`.
- **Configurations tried: 1** (plus its reference arm). The median of the tried configurations is the winner.
- **Result** (`results/EXP-B-006/dev-analysis.{md,json}`, CI over genes, seed 0, 2,000 resamples):

  | Check | Result |
  |---|---|
  | Δ (rr-v1 + onset 0.25) − rr-v1, 2,934 literature-onset cases | **+0.0021 [+0.0007, +0.0035]** |
  | harmed vs E0+answers (same cases) | **4.40%** (helped 27.64%); rr-v1 alone 3.00% |
  | R1-dev no-harm (all view, vs E0, 1,883 patients, kb-v6) | −0.0006 [−0.0086, +0.0060], harmed 10.7%: pass (rr-v1: −0.0020 [−0.0097, +0.0044]) |
  | all 4,562 cases | +0.0025 [+0.0013, +0.0038], harmed 4.84% |
  | 2,755 known-onset cases | +0.0041 [+0.0022, +0.0063], harmed 5.99% |

  Candidate exists: CI lower bound > 0, harmed 4.40% <= 5%, R1-dev passes. As in EXP-B-005, all of the gain comes
  from cases that report an onset, and among them harm exceeds 5% (literature cases with known onset: 5.92%).
- **Dry run of this read on R1-dev** (`dxt rerank release-check --cohort r1-v1/dev`, kb-v3, 1,883 patients, code
  `4db2add`; `results/EXP-B-006/r1-v1-dev__release-check__report.json`): identity checks all 0 mismatches; rr-v1 vs
  E0 −0.0067 [−0.0235, +0.0051], harmed 0.116, which reproduces EXP-B-003's R1-dev numbers exactly; candidate vs
  E0 −0.0048 [−0.0221, +0.0073], harmed 0.130; candidate − rr-v1 **+0.0019 [−0.0002, +0.0046]**, harmed 0.041,
  helped 0.066. 1,039 of the 1,883 patients carry a usable onset; on the other 844 the candidate equals rr-v1 exactly.
  The dry-run verdict is PASS.
- **Not covered by sealed S3 evidence.** The sealed S3-v3b-test read of EXP-B-005 scored F + onset 0.25, not this
  system. For this system, S3 evidence is dev only. Nothing here re-reads S3 test.

## Onset in R1 (R1-train counts only; `scripts/exp_b006_r1_onset_availability.py`, `results/EXP-B-006/r1-train-onset.json`)
**R1 patients do carry onset, so this read can measure onset's effect on real patients, not only identity.**
- R1-train has 4,103 patients. **2,408 (58.7%) have a usable onset**, the input `case_onset_years` reads:
  - 1,085 an exact age (`diseases[0].onset` as an age, ISO 8601 or gestational);
  - 1,323 an HPO onset class that the feature maps (one of `HPO_ONSET_YEARS`); another 36 carry a class that is
    not an age class (HP:0034197/8/9, acute, subacute, chronic) and are unusable.
- 1,292 (31.5%) also have onsets on individual symptoms (`feature_onsets`); 2,567 (62.6%) have either.
  Where both exist (1,133 patients), the earliest symptom onset and the disease onset fall in the same onset bin in
  954 (84.2%).
- 3,713 (90.5%) have excluded terms; 2,160 have both. Usable onset by feature bin: prenatal 52, neonatal 755,
  infantile 721, early childhood 338, childhood 185, young adult 246, adult 98, late 13. It is skewed to early
  onset; late-onset patients are rare.
- R1-dev, for the sealed read's expected size: 1,039 of 1,883 (55.2%) usable.
- **What the read can show:** the candidate's effect on real patients' MRR with their recorded onset (candidate −
  rr-v1, publication bootstrap), on the 55% who have one. **What it cannot show:** efficacy for the app's
  interview (R1 negations are author-chosen), efficacy for late onset (13 R1-train patients), or anything about
  onset collected by the web form (a patient's own answer, not a curated phenopacket field).
- Onset is not invented for R1: it is the field the phenopacket records, fed as recorded. Cases without one
  receive no onset input.

## Data and reads
- **Step 0, before the sealed read (not sealed):** at the commit that registers this file,
  `dxt rerank release-check --exp EXP-B-006 --cohort r1-v1/dev` must reproduce the dry-run numbers above exactly.
  If it does not, stop: no sealed read, the mismatch is logged and investigated.
- **Step 1, R1-test, sealed, read once** (2,548 patients, as in EXP-B-003):

  ```
  DXT_SEALED_READ=EXP-B-006 .venv/bin/dxt rerank release-check --exp EXP-B-006 --cohort r1-v1/test \
    --reason "EXP-B-006 R1-test no-regression (pre-registered <registering commit>)"
  ```
- **Input.** R1 patients as the cohort records them (`splits.load_part` through `cohorts.access`): present and
  excluded terms, sex and age ignored by both systems (weight 0), onset as `case_onset_years` reads it: the exact
  onset age if recorded, else the midpoint of the HPO onset class, else none. KB kb-v3, base E0 = genphenia_v3,
  top_k 200.
- **Views from the same GNN output per case:** `given` (as recorded), `no_onset` (onset removed), `present`
  (excluded terms and onset removed).
- **Statistics, as EXP-B-003:** MRR; paired bootstrap 95% CI resampling publications, 2,000 resamples, seed 0;
  harmed = share of cases whose rank gets worse, helped = better; n and unrankable cases reported.
- **Not read:** the R1 vault; S3 test (S3-v3b-test was read once, in EXP-B-005); MCRD and DDD. MCRD and DDD carry
  neither excluded terms nor onset, so both systems equal E0 there (the `present` identity below shows it exactly);
  EXP-B-003 skipped them for the same reason, under the same rule, so they are not read and not ledgered.

## Gate (fixed before the read; numbers pinned in `eval/release_check.py` and its test)
All five must hold. A PASS makes the candidate a release candidate; the release itself still goes through
`diagnostic.ar-model` (below).

| Check | Rule | Why |
|---|---|---|
| ID1, identity without onset | `no_onset` view: candidate and rr-v1 distributions identical bit for bit on every case (0 mismatches of 2,548) | no onset input gives rr-v1 exactly |
| ID2, identity without inputs | `present` view: candidate equals E0 bit for bit on every case | EXP-B-003 N1, carried over |
| ID3, cases with no usable onset | `given` view, cases with no usable onset: candidate equals rr-v1 bit for bit | the feature acts only where onset is given |
| N2, no clear harm vs E0 | `given` view, candidate vs E0: CI upper bound >= 0 **and** point estimate >= −0.02 | EXP-B-003 N2 |
| N3, onset costs nothing vs production | `given` view, candidate − rr-v1: CI lower bound >= −0.01 | EVAL_PROTOCOL §6 no-regression margin |

- **Not gated, reported:** candidate − rr-v1 on the cases with usable onset and on the rest; harmed and helped
  shares. A positive CI there would be supporting evidence, not a release condition: Mateo's path asks for a
  no-regression check. A 5% harmed cap is not applied on R1: rr-v1 itself harms 9.0% there (EXP-B-003).
- **Primary release evidence is therefore:** dev S3 (this file) + EXP-B-005's sealed P1 for the onset feature on F
  + this R1 no-regression. Nothing here claims more.

## Expectations (written before the read; from the R1-dev dry run)
| Check | Expected |
|---|---|
| ID1, ID2, ID3 | 0 mismatches (the dev dry run had 0) |
| N2 | candidate vs E0 about −0.005, CI including 0; passes |
| N3 | candidate − rr-v1 about +0.002, CI lower bound near 0 (dev −0.0002); passes with room (margin −0.01) |

## Production input mapping (diagnostic.ar PR #87, `frontend/src/lib/onset.ts`)
The web sends, to `/rank-genes`, optional `onset_hpo_id` (the earliest class among the symptoms, ranked
HP:0030674, HP:0003577, HP:0003623, HP:0003593, HP:0011463, HP:0003621, HP:0011462, HP:0003596, HP:0003584),
`onset_age_years` (the earliest exact age, only if one was given) and `symptom_onsets[]` (per symptom). The API
should build the feature's one number, `onset_years`, like this, the same as `case_onset_years`:
1. If `onset_age_years` is present and a finite number >= 0: that age (this is how EXP-B-005 fed S3).
2. Else, if `onset_hpo_id` is one of the nine ids: the midpoint of its interval in `HPO_ONSET_YEARS`
   (HP:0030674 -0.375, HP:0003577 0, HP:0003623 0.038, HP:0003593 0.538, HP:0011463 3, HP:0003621 10,
   HP:0011462 28, HP:0003596 50, HP:0003584 80). Each lands in the onset bin of its own class (tested in
   `tests/test_release_check.py`). This is also how R1 patients with a class and no age are fed.
3. Else, no onset: the output is bit-identical to rerank-v1.0.0.
Unknown ids, a missing id, or negative or non-numeric ages are treated as no onset, never as an error.

**Mismatches to flag (none changes the read; all matter for the release):**
1. **Patient-level fields are independent minima.** `onset_hpo_id` is the earliest class and `onset_age_years`
   the earliest age among symptoms with an age; they can come from different symptoms (a symptom with an early
   class and no age, another with a later class and an age). Then rule 1 uses an age that is later than the earliest
   symptom. Safer, and still consistent with "onset of the first symptom": when `symptom_onsets` is present, take
   per symptom the age if given else the class midpoint, and use the minimum; fall back to rules 1-3 otherwise.
   The release must pick one and state it; the choice is not validated on web data (none exists).
2. **S3 exercised only exact ages; R1 mostly classes.** S3 cases carry `onset_years` only (a sampled age), while the
   web will mostly send classes (the exact age is optional). R1 exercises both (45% age, 55% class among usable).
   The efficacy evidence is for exact ages; for class midpoints the evidence is R1 no-regression only.
3. **Class edges differ slightly.** The web assigns 15 to 16 years to juvenile and treats 60 as middle age;
   the feature bins start at 15 and 60. An exact age of 15.5 is "juvenile" in the form and bin 5 (15 to 40) in the
   feature, and 60.0 is bin 7. Immaterial in size; a given exact age wins over the class (rule 1).
4. **Per-symptom vs patient-level onset.** The feature was built and tested on a patient's disease onset (S3:
   the literature onset age; R1: the phenopacket's disease onset). The web asks per symptom and sends the earliest.
   On R1-train, the earliest symptom onset falls in the disease-onset's bin in 84.2% of the 1,133 patients that
   have both. The release notes should say onset means "when the first symptom began".
5. **Chip classes exclude two usable classes.** The form lacks pediatric (HP:0410280), adult (HP:0003581) and the
   early/intermediate/late young adult subclasses; all are in `HPO_ONSET_YEARS` and harmless.
6. **The feature needs the ontology-independent table** (`HPO_ONSET_YEARS`) and `kb-v3`'s `onset_years`; it does not
   need the HPO graph.

## What diagnostic.ar-model has today
`diagnostic.ar-model` main (rerank-v1.0.0, read through the GitHub API; the local checkout is behind and has no
rerank code) **does not implement onset**: `rerank/knowledge.py` has only the negation path (`neg_llr`),
`rerank/model.py` applies `neg_weight` alone, `rerank.json` fixes `weights.onset = 0.0` and
`bundle.verify` rejects any non-negation weight. A release needs: the onset code (provenance-copied:
`_interval_bins`, `onset_bin`, `GeneKnowledge.onset_distribution`, the background, `case_onset_years` and
`HPO_ONSET_YEARS`), `onset_smoothing` 0.1 in the bundle params, a new bundle `rerank-v1.1` with
`weights.onset` 0.25 and the same kb-v3, parity fixtures against this repo, and an identity test: without onset,
bit-identical to rerank-v1.0.0.

## Budget (EVAL_PROTOCOL §2: one test read per release candidate, at most 3 candidates per front)
Front B, from `docs/TEST_LEDGER.md`:

| Candidate | Sealed reads | Gated? |
|---|---|---|
| 1. rr-v1[neg=0.5] | EXP-B-003: s3-v1/test, r1-v1/test | yes; released as rerank-v1.0.0 |
| (EXP-B-004: F and descriptive contrasts) | s3-v2/test, one session (its first row has the reason `x`) | no: "nothing gated", stated in its verdict |
| 2. F + onset 0.25 | EXP-B-005: s3-v3b/test | yes (P1 passed) |
| **3. rr-v1 + onset 0.25** | **this: r1-v1/test, one read** | yes |

- **This is the 3rd and last Front B release candidate if EXP-B-004 is not counted** (it declared nothing gated,
  and `rerank-v1.1` was explicitly not gated there). **If a reviewer counts EXP-B-004's descriptive read as a
  candidate, this would be the 4th and exceeds the budget.** This needs Mateo's explicit ruling. It is an
  onset-on-rr-v1 re-basing of candidate 2, spending no new S3-test read.
- After this, no Front B candidate is left under the conservative count.

## On PASS and on FAIL
- **PASS:** the candidate is a release candidate for `rerank-v1.1.0`: build and gate the bundle in
  `diagnostic.ar-model` (a PR there, tag `rerank-v1.1.0`) after Mateo's go-ahead. Onset stays an optional API
  field; the production effect also needs the web PR #87 merged and the API to feed the mapping above. Rollback is
  "send no onset": identical to rerank-v1.0.0.
- **FAIL:** no release. The result is reported as it is, in this file and BITACORA, and nothing is re-tuned or
  re-tested under this id. A new candidate would need its own dev justification and (by the count above) none is
  left.
- Either way, the dev -> test drop is reported (N3 dev +0.0019 [−0.0002, +0.0046]); a drop larger than the dev CI
  width is written up.

## Declared limits
- E0 knows half B (EVAL_PROTOCOL §4.5); R1's negations and onset are author-curated.
- The S3 efficacy is simulated, on exact ages, with kb-v6; kb-v3 differs from it in phenotype knowledge only.
- 36 R1-train patients carry non-age onset classes; they receive no onset input.

## Results
(After the sealed read.)

## Verdict
(After the sealed read.)

## Addenda
