# ADR-0019: Phase 3, a v4.0 retrained on a pristine simulator and real patients, with one sealed read

- **Status:** Accepted, 2026-10-13 (Mateo: options 1 and 3 of P3-AUDIT-v1 §6, freeze the sealed set now, open it
  only on his word). Open points are listed at the end.
- **Evidence:** [P3-AUDIT-v1](../analyses/P3-AUDIT-v1.md). **Plan and backlog:** [PHASE3.md](../PHASE3.md).

## Context
- **E0 learned annotation profiles, not patients** (P3-AUDIT-v1 §1).
  - It was trained only on simulated patients from HPO 2025-03-03.
  - Terms were drawn uniformly; imprecision was the only noise, with no off-profile terms.
  - It was selected on simulated validation.
- **On a new patient with a known gene, E0's MRR is about 0.13 to 0.42** (uncited & in-vocabulary 0.330). Patients
  whose phenotype the gene's annotations explain poorly score 0.04 (§2).
- **Phase 1's retraining losses were mostly lost memorisation:** EXP-A-001 c1 −0.125 on cited, −0.010
  [−0.036, +0.014] on uncited (§3).
- **Literature negations are a trap.** Case reports state that a finding is absent because it is expected in the
  disease. Excluded terms therefore point *towards* the true gene (P2-PROBES-v1; the FBXO11 n/n artefact in ft-v1.1's
  production knowledge).

## Decision
1. **Scope.** Two families of change, measured separately:
   - a **pristine simulator**: frequency-weighted, and fitted to real training patients for term count, imprecision
     and off-profile terms;
   - **input encoding**: an observed-term flag and specificity on nodes, edges in both directions, sex and age as
     native inputs, and no `"-"` class.
   - Each change is an ablation step, so its own effect is visible (PHASE3.md §2).
   - Real training patients are mixed into training as a separate step.
2. **Data: the union split `p3-v1`,** frozen on 2026-10-13 (`3e928b3d…`, `data/splits/p3-v1.json`).

   | Part | Content | Patients (publications) | Uncited by E0's knowledge | Access |
   |---|---|---|---|---|
   | train | `p2-v1` train + dev | 5,986 (1,030) | 2,722 (501) | free: fitting, simulator statistics, publication-grouped cross-validation |
   | vault | `p2-v1` test + vault, `p2-fresh-v1` | 4,659 (788) | 2,678 (417) | sealed: one read, only after Mateo's go |

   - The vault's patients were each read before, once or twice, to score E0 / safe-v1 / ft-v1.1 (TEST_LEDGER). No
     v4.0 decision used them, and the earlier reads produced only aggregate metrics of other systems. This is
     disclosed with any v4.0 claim.
   - The vault is opened by `splits.load_part` only under a pre-registered experiment, `DXT_SEALED_READ`, a clean
     tree and a ledger row, and only once (code-enforced). Agents never open it.
3. **Knowledge cut = E0's own.** For the evaluated v4.0, the simulator and every knowledge-derived input use only:
   - HPO `phenotype.hpoa` 2025-03-03 (registered as `hpo_annotations_2025_03_03`; byte-identical to E0's);
   - E0's gene list.

   v4.0 and E0 then compete with the same knowledge, so a difference is due to the method.
   - **Uncited by E0's knowledge:** no PMID of the publication group is in that release's reference column. Every
     `p3-v1` group carries this status.
   - Newer knowledge (HPO 2026-09-01, Orphanet 2026) is a production step after the claim, not part of it.
4. **No literature negation enters v4.0:**
   - HPOA rows with qualifier `NOT` or frequency 0/n or 0% are dropped;
   - phenopacket excluded terms are neither training inputs nor evaluation inputs;
   - no "obligate" rule is derived from n/n rows.

   Absent symptoms remain outside v4.0; ft-v1.1's branch (or a refit) can sit on top later, measured separately.
5. **Development** uses publication-grouped cross-validation on `p3-v1` train only.
   - Fold assignment is a salted hash of the publication group.
   - Every simulator statistic estimated from patients is fitted on the training folds only.
   - Every configuration and seed is logged (`results/P3/`, BITACORA), including grid searches.
6. **Primary population.** Patients whose publication is uncited by E0's knowledge: the production case, a patient
   E0 has not memorised.
   - Cited patients are reported. A loss there is expected by construction and is accepted (Mateo, 2026-10-13).
7. **The claim** is one pre-registered read of the `p3-v1` vault, after an independent review. It reports:
   - Δ MRR vs E0 with a publication-cluster CI;
   - helped and harmed counts;
   - the cited and uncited strata;
   - the ablation contributions measured in cross-validation.

## Consequences
- ADR-0012's simulated-data gate does not apply. Selection is on real patients, in cross-validation.
- E0 stays the production model until a v4.0 passes the read and Mateo decides.
- The prospective set (phenopacket-store 0.1.28+, probably 2027) stays available for a later, cleaner check.

## Open (for Mateo before pre-registration)
- **The gate's form.** Recommended: the CI lower bound of Δ MRR on uncited vault patients > 0, with cited reported.
  The alternative is to also require overall Δ > 0, which is unlikely given the cited loss.
