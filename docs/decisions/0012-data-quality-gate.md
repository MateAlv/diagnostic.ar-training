# ADR-0012: No retraining until the simulated data passes a pre-registered quality gate

- **Status:** Accepted, 2026-09-30 (Mateo: "not move forward until the
  simulator and data is pristine … GenPhenAI … only used a gen/phenotype
  HPO synthetic simulator … We should be able to do better").
- **Criteria written:** before any simulator-v0.4 number exists.
- **Blocks:** A-002f-v2, A-003f-v2 and any other training on simulated
  data until the gate passes for a frozen simulator version.

## Comparators
| Id | What |
|---|---|
| **UP** | GraPhens' gene→phenotype simulator, the one v3.0 was trained on. Its outputs: source `graphens_sim_20251202` |
| **V03** | Our simulator v0.3 (`ds-sim0.3.1-A-n100-s1001`) |
| **CAND** | The candidate version (v0.4, or later) |

## Gate criteria
CAND must pass **all** of them.

**G1: Integrity**
- `validate`: 0 invariant violations.
- `dxt lineage verify` ok.
- Contamination vs R1 (all parts) and S3: 0 after exclusion.
- A rerun is byte-identical.

**G2: Beats UP and V03 on every realism metric** (`dxt sim realism`)

| # | Metric | Must be |
|---|---|---|
| a | Evaluation literature panel (G4): mean absolute error between simulated emission and literature prevalence, on the rows not sourced from Orphanet. Profiles are built from HPOA, which already carries Orphanet's frequencies, so those rows would not be an independent check. All rows are reported as secondary | lower than UP's and V03's |
| b | R1-dev aggregate: mean per-gene Spearman of term frequencies (genes with ≥ 10 dev patients) | higher than UP's and V03's |
| c | Terms per case: Wasserstein distance to R1-train's distribution | lower than UP's and V03's |
| d | Classifier two-sample test: AUC of a classifier telling R1-train patients from simulated ones (source-neutral features: term count, mean IC and depth, organ-system histogram, share of terms annotated to the gene, noise share; publication-grouped cross-validation) | lower than UP's and V03's, and ≤ 0.75 |
| e | Difficulty match: \|E0 MRR on CAND − E0 in-vocab MRR on R1-train (0.512, EXP-000)\| (simulated genes are all in vocabulary, so the in-vocab figure is the fair target) | smaller than UP's (0.812 → 0.300) and V03's (0.176 → 0.336), and ≤ 0.10 |

**G3: Disease cards reviewed by a person**
- Cards: a stratified sample of **30 diseases**, the 10 of ANALYSIS-001 plus
  20 new ones. Each shows the simulated patients' top reported features
  next to the literature prevalence and the real R1 reports.
- Reviewer: Mateo, or someone he designates.
- No card may remain flagged "clinically implausible" without a fix or a
  written, accepted reason.

**G4: An evaluation literature panel independent of construction**
- **Size:** ≥ 50 diseases, stratified by organ system, inheritance and
  prevalence. The 8 diseases of `literature-panel-v1` are included.
- **Built by** LLM-assisted extraction (Claude Code or Codex on this PC)
  from GeneReviews (see licensing below), Orphanet and cohort papers. Every
  number carries a citation and a verbatim evidence quote.
- **Double-check:** a random 10% is re-extracted by the other model or
  reviewed by a person; agreement ≥ 90%, and every disagreement resolved.
- **Separation from construction:** these diseases' literature numbers are
  **never** used to build or tune profiles. If literature-derived
  enrichment is used (a v0.5 option), it draws only on diseases *outside*
  the evaluation panel. The split is frozen and hashed before any
  extraction for construction.

**G5: Freeze**
When G1–G4 pass, the simulator version, its artifacts and the dataset are
frozen (tags and manifests). STATE records "data gate passed". Only then
does retraining resume.

## Budgets (anti-overfitting of the simulator)
- R1-dev may be consulted for at most **3 candidate versions** before one
  is frozen, logged in `results/realism/LEDGER.md`. UP and V03 are
  baselines and don't count.
- All simulator parameters are fitted on R1-train only.
- The evaluation panel is a check, never a fitting target.

## Licensing of literature sources
- **GeneReviews:** the copyright notice permits reproduction "for
  noncommercial research purposes only", with credit, a link, and "No
  further modifications". We extract *facts* (feature prevalences, onset),
  with citations, for a free, non-commercial academic tool, and never
  redistribute text. Written confirmation is requested from the address the
  notice gives (`docs/TODO.md`).
- **Orphanet:** CC-BY-4.0.
- **Cohort papers:** facts with citations only.
- **OMIM:** not automated.

## Consequences
- `dxt sim realism` gains G2 c–e and runs UP as a comparator.
- New artifacts: `literature-panel-v2` (evaluation, ≥ 50 diseases) and the
  frozen construction/evaluation disease split.
- If v0.4 fails the gate, v0.5 adds literature-derived enrichment on the
  construction diseases. The gate is re-run within the 3-version budget.

## Amendment 1 (2026-09-30): two corrections, made after candidate 1's R1-dev read

**Disclosure.** Both corrections were found after candidate 1's realism
read (ledger row `v0.4-cand1`), by R1-train analysis (ANALYSIS-002) and
by reading the G2b code. They apply equally to every dataset: baselines
are recomputed, and neither correction changes candidate 1's verdict. The
thresholds are unchanged.

1. **G2e target.** It is now E0's in-vocab MRR on R1-train patients whose
   publication is **not** cited in the pinned HPOA: **0.405** (n = 1,124),
   replacing 0.512. v3.0 learned from annotations of the cited papers, so
   the full-train figure is inflated for a simulator built on masked
   knowledge.

   | Dataset | E0 MRR | Gap to 0.405 | ≤ 0.10? |
   |---|---|---|---|
   | UP | 0.819 | 0.414 | no |
   | V03 | 0.168 | 0.237 | no |
   | Candidate 1 | 0.092 | 0.313 | no |

2. **Which dataset G2 scores.**
   - **The problem:** G2b's reference set is each gene's full
     `hpo_genes_to_phenotype` annotations. A half-A dataset, with 30% of
     annotations held out for S3 (ADR-0004 / §8), shows a zero rate on
     every held-out term by construction, while UP samples from that
     very file.
   - **The fix:** G2 is scored on a **full-profile** run of the candidate,
     with the same simulator, settings and seed and no half-B drop. The
     V03 baseline is regenerated the same way; baselines don't count
     against the budget.
   - **The training data:** the half-A Front A training set is the same
     generator with half B dropped. It must pass G1, and its G2 is
     reported as secondary.
- **Accepted by Mateo, 2026-09-30.**

## Amendment 2 (2026-09-30): who reviews the G3 disease cards
Mateo delegated the G3 review ("Do it yourself and I'll check when all is
done").
- **Two independent reviewers:** the assistant (Claude Code) reviews each
  of the 30 cards. Codex CLI reviews each card independently, without
  seeing the first verdict.
- **Verdicts:** plausible, or implausible with a reason.
- **Rules:**
  - a card flagged by either reviewer is either fixed or carries a written,
    accepted reason;
  - disagreements are listed;
  - Mateo spot-checks the cards and both verdicts afterwards, and can
    overturn any of them before G5.
- The cards and verdicts are committed as evidence.

## Amendment 3 (2026-09-30): G2a scores the truth layer, made after candidate 2's read

**Disclosure.** This change was found after candidate 2's read, by
ANALYSIS-003 §3. G2a reads no R1-dev. The rule applies to every dataset,
and baselines are recomputed.

- **Primary G2a:** MAE between literature prevalence and the simulated
  **true** rate (`true_present`, with more specific terms included) on the
  independent panel rows.
- **Datasets without a truth layer** (UP): scored on emission, their only
  layer.
- **Secondary G2a:** the reported-layer MAE, next to the real-patient
  reference (R1-train reported rates, 0.307 on the rows where the gene has
  at least 10 train patients).
- **Why:** the literature describes what patients have. Real patients'
  reports miss it by about 0.3, so scoring reports against prevalence
  penalises a correct reporting layer.
- **Amendment 3 accepted by Mateo, 2026-10-01.**

## Amendment 5 (2026-10-03): candidate 6 accepted with a documented G2c shortfall (Mateo's decision)
**This is a post-hoc decision,** recorded as such. It was made after
candidate 6's train-side go/no-go and before any R1-dev read of it.

**Candidate 6** (simulator 0.5.4, `simcal-v053-v1` with `hpoa-enriched-v1`,
`presentation-ages-v1` and `onset-ages-v1`; PR #86) passes four of the five
train-side checks:

| Check | Candidate 6 | Rule | Result |
|---|---|---|---|
| G2a (truth layer) | 0.304 | — | pass |
| G2d | 0.730 [0.699, 0.764] | ≤ 0.75 | pass |
| G2e gap | 0.079 | ≤ 0.10 | pass |
| G2b-train | 0.519 | — | pass |
| G2c | 1.795 | must beat V03-full's 1.653 | **fail** |

It beats UP on every G2 metric.

**Why G2c is accepted as a documented shortfall:**
- **V03 passes G2c by over-reporting:** 8.42 terms per case vs 8.70 real.
  Candidate 6 under-reports: 6.90 terms per case (p90 13 vs 17).
- The W1 distance favours V03's error, while every other check, including
  the classifier-based G2d, favours candidate 6 by a wide margin.
- **The informe states the shortfall:** simulated records are about 20%
  shorter than real ones, mostly in the upper tail.
- **Also declared:** the literature ages do not reach the genes the age
  check scores, so simulated ages remain a known weakness. The median
  |log ratio| is 0.585 vs V03-full's 0.537.

**Decisions:**
1. Mateo authorises the **last R1-dev realism read (3 of 3)** on candidate
   6: `ds-sim0.5.4-full-n100-s1001`, label `v0.5.4-cand6`, sim version
   `0.5.4-cand6`.
2. **Fixed before the read:** the read decides only **G2b on R1-dev**.
   - If candidate 6's dev ρ beats both UP (0.231) and V03-full (0.095),
     the gate proceeds to G3 (cards) and G5 (freeze).
   - If not, candidate 6 is **not** frozen; Front A moves to option B
     (train the new parameters on real R1-train patients). No further
     simulator candidates.
   - The other G2 values from this read are reported, but they cannot
     change the decision; their train-side versions already decided.
3. **G3 reviewers** (amendment 2): Codex first, then a Claude reviewer
   (Sonnet). Mateo spot-checks.
- **Correction (2026-10-03).** Found by the evidence pack's number check.
  Amendment 5 above says V03 shows "8.42 terms per case". That figure is
  V03 **half A**. The G2c baseline is **V03-full**, which shows **10.21**
  terms per case (`results/realism/v0.3-full-baseline.json`; p10/p90 4/18,
  vs R1-train 2/17). The reasoning holds, and more strongly: V03-full
  over-reports by about 1.5 terms per case, while candidate 6 under-reports
  by about 1.8. The decision is unchanged.
