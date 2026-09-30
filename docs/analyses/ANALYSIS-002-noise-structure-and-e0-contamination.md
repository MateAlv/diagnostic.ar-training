# ANALYSIS-002: Structure of real patients' "noise", and the E0 difficulty target

- **Date:** 2026-09-30.
- **Data:** R1-train only; nothing from R1-dev, test or vault. The simulated
  data is a 1% sample (seed 7) of `ds-sim0.4.1-A-n100-s1001` (candidate 1).
- **Scripts:** `scripts/analysis/term_categories.py`,
  `scripts/analysis/e0_by_hpoa_citation.py`.
- **Outputs:** `results/analyses/ANALYSIS-002/`.

## 1. Where reported terms sit relative to the gene's annotations
Each present term is classified against `kb-v4`, which masks every R1
publication:
- **explained:** the gene's diseases give it probability > 0 (annotated,
  or an ancestor of an annotated term);
- **more specific:** a descendant of an annotated term;
- **unexplained:** neither. These are binned by the information content
  (IC) of the most informative common ancestor shared with any annotated
  term.

| Share of present terms | R1-train (26,173 terms) | Candidate 1 (35,902 terms) |
|---|---|---|
| explained | 0.538 | 0.494 |
| more specific than an annotated term | **0.115** | 0.050 |
| unexplained, shared-ancestor IC ≥ 4 | 0.009 | 0.002 |
| unexplained, IC 2–4 | **0.099** | 0.047 |
| unexplained, IC < 2 (weakly related or unrelated) | **0.239** | 0.406 |

**Reading.** `calib-v1`'s "unexplained share" (0.4625) lumps together
more-specific terms (0.115) and the truly unexplained ones (0.348).
Candidate 1 emitted that whole 0.4625 as gene-independent noise from a
vocabulary. Real records instead:
- use more specific terms than the annotations; v3.0 sees them through
  their ancestors;
- report findings related to the disease's annotations.

So simulated records carry less signal than real ones. This matches E0's
MRR of 0.092 on candidate 1.

## 2. E0 on R1-train, split by whether the patient's publication is cited in HPOA
v3.0 was trained on simulated patients built from HPOA, and HPOA
annotates many phenopacket-store papers. Patients from those papers are
easier for E0 than new patients would be.

| R1-train, in-vocab genes | n | E0 MRR |
|---|---|---|
| Publication cited in HPOA (pinned 2026-02-16) | 2,398 | 0.562 |
| Not cited | 1,124 | **0.405** |
| All (EXP-000) | 3,522 | 0.512 |

**Reading.** A simulator built from knowledge with R1 masked should match
the difficulty of patients whose papers v3.0 never saw. 0.512 overstates
that.

**Caveats:**
- v3.0 trained on an older HPOA than the pinned one. Some "cited" papers
  were added later, which would, if anything, shrink the gap.
- Uncited patients may also differ in other ways (newer papers, recently
  described genes). This is a correlational split, not a controlled one.

## 3. Consequences
- **ADR-0012 amendment 1:** the G2e target becomes the uncited subset's
  0.405, and G2 runs on full-profile datasets.
- **ADR-0011 amendment 3:** candidate 2 adds
  - specialisation of reported terms, and
  - disease-related noise,

  with the noise share reduced to 0.348. Both rates are set by declared
  pilot rounds against the R1-train targets above.
