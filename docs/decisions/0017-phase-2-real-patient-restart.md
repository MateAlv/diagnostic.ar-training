# ADR-0017: Phase 2, a restart on real patients with a post-E0 final check

- **Status:** Accepted, 2026-10-07 (Mateo).
- **Supersedes:** decision 3 of [ADR-0016](0016-final-deployment-and-close-out.md) ("no more model experiments"). ADR-0016's deployment decisions stand.
- **Plan and tracking:** [PHASE2.md](../PHASE2.md). **Evidence for this decision:** [P2-PROBES-v1](../analyses/P2-PROBES-v1.md).

## Context
- **Phase 1 (2026-09-28 to 10-05) selected its systems on simulated patients.** On real patients the final systems measured:
  - R1-test, `rerank-v1.0.0` vs E0: −0.0025 [−0.0070, +0.0013] (EXP-B-003).
  - R1 vault, MRR: E0 0.4136, `rerank-v1.0.0` 0.4114, `rerank-v1.1.0` 0.4106 (EXP-V-001).
  - R1-test has been read three times and the vault once.
- **The anteproyecto** promises a model that uses sex, age and absent symptoms and performs better than the same model without them (l. 126–130, 191–193, 414–421).
- **Mateo's goal for Phase 2 (2026-10-07):** a real gain on real patients, pre-registered and measured once. A small, guaranteed gain comes before a larger, uncertain one.
- **Development probes on R1 train + dev** (P2-PROBES-v1, 5,986 patients):
  - Knowledge-only rules: sex plus strict age/onset gives Δ MRR +0.00088 [+0.00039, +0.00151], 493 helped, 0 harmed. The obligate-negation penalty ×0.1 gives +0.00067 [+0.00012, +0.00129], 6 harmed.
  - Per-gene sex and age priors learned from R1-train lower R1-dev MRR (sex −0.00497 [−0.01074, −0.00038]).
  - **E0's home advantage:** MRR 0.612 on patients from publications cited in E0's training annotations (HPO 2025-11-24). It is 0.066 on patients from publications released after phenopacket-store 0.1.25 and not cited there; 52% of those have a gene outside E0's vocabulary.

## Decision
1. **Restart on real patients.** Phase 2 designs, fits and selects on R1 train + dev only: 5,986 patients, the free parts of `r1-v1`. No Phase 2 claim rests on simulated patients.

2. **Definition.** A publication group is **post-E0** when none of its PMIDs appears in phenopacket-store 0.1.25 and none is cited in HPO `phenotype.hpoa` 2025-11-24.
   - 0.1.25 (2025-08-04) is the last release before E0's training annotations.
   - HPO 2025-11-24 is E0's training annotation release.
   - Both sources are pinned in `data/sources.yaml` and used for nothing else.

3. **New split `p2-v1`**, derived from `r1-v1` (which stays frozen and unchanged). No patient moves between development and confirmation.

   | `p2-v1` part | Content | Access |
   |---|---|---|
   | train | `r1-v1` train | free; fitting |
   | dev | `r1-v1` dev | free; selection |
   | test, the **confirmation** set | `r1-v1` test and vault groups that are not post-E0 (≈ 3,587 patients) | sealed; one pre-registered read per candidate; at most 3 candidates in Phase 2 |
   | vault, the **R1 part of the final check** | `r1-v1` test and vault groups that are post-E0 (≈ 732 patients) | sealed; opens once |

4. **Fresh split `p2-fresh-v1`, frozen on 2026-10-20.**
   - Source: phenopacket-store `main` at its last commit before 2026-10-20T00:00Z.
   - A patient is included when all of these hold:
     - the phenopacket id is not in 0.1.27;
     - no PMID is in 0.1.27;
     - the publication group is post-E0;
     - no PMID is cited in HPO 2026-02-16, the knowledge the safe rules use;
     - there is one causal gene;
     - it passes the parser `r1-v1` uses.
   - Everything goes to its sealed vault, which opens once. On 2026-10-07 this rule selects 349 patients (`main` @85ffd78).

5. **The final check is `p2-v1` vault + `p2-fresh-v1` vault**, about 1,081 patients on 2026-10-07.
   - It is read once, with E0 and every pre-registered candidate together.
   - Results are reported overall and per component.

6. **Candidates, safest first** ([PHASE2.md](../PHASE2.md)):
   - Track 1: `safe-v1`, knowledge-only constraints.
   - Track 2: `ltr-v1`, a re-ranker learned on R1-train with gene-agnostic features.
   - Track 3: `ft-v1`, the PyTorch GNN fine-tuned with a zero-initialised branch for the new inputs (ADR-0009).
   - Track 4, a gene-vocabulary update, is future work.

7. **Metrics.**
   - Primary: Δ MRR vs E0, which is production v3.0 with present terms only. It is computed over all patients, with misses counted as 0, using a paired publication-cluster bootstrap (2,000 resamples, seed 0, 95% CI).
   - Also reported:
     - harmed and helped shares;
     - top-1 and top-10 entries and exits;
     - the in-vocabulary subset;
     - the subsets where each input is known.
   - Holm correction across the confirmation reads.

8. **Knowledge masking and curation.**
   - The safe rules' knowledge (HPO 2026-02-16) masks every `r1-v1` dev, test and vault PMID, using the existing held-out mask.
   - Fresh patients are uncited there by rule 4.
   - Curation from the pinned GeneReviews and MedlinePlus snapshots (2026-10-01) may only make a rule more conservative, never stricter: it may remove a gene or lower an onset bound.
   - Curation does no web lookups.

9. **Production.**
   - A candidate that passes its confirmation gate (CI lower bound > 0, harmed ≤ 0.5%) may go to production through `diagnostic.ar-model`, after Mateo's go.
   - A learned candidate goes to staging unless it also passes the final check.

10. **Agents** follow the delegation table in the workspace `CLAUDE.md`. Only the main session runs a sealed read.

## Why
- **Reusing `r1-v1` test and vault for confirmation.**
  - It is the only real cohort large enough to confirm a gain of about 0.001 MRR.
  - Phase 2 designs only on train + dev, and the earlier reads (EXP-000, B-003, B-006, V-001) were of other systems.
  - The split into disjoint confirmation and final parts keeps one part unread until the end.
- **A post-E0 final check.**
  - It removes E0's home advantage, which Phase 1 could not remove (EVAL_PROTOCOL §4, item 5).
  - It meets Mateo's requirement of more than 400 patients.
- **New split ids instead of edits.** `r1-v1` and its ledger keep the Phase 1 history intact.

## Alternatives dropped
- **Fresh patients only (349):** too few to confirm a gain of the expected size.
- **Re-reading `r1-v1` test and vault under `r1-v1`:** the vault guard forbids it, and confirmation and final patients would mix.
- **Per-gene priors learned from R1-train:** they lowered R1-dev MRR (P2-PROBES-v1 §3).
- **Vocabulary update (Track 4):** probably the largest effect on new publications, where 48% of patients have a gene outside E0's 5,229. But it is not about the anteproyecto's new inputs, and it would change the comparison (ADR-0006). Future work.

## Consequences
- **New sources:**
  - `phenopacket_store_0_1_25` (sha256 `27ad6b98…`);
  - `hpo_annotations_2025_11_24` (sha256 `1f161ec5…`);
  - the 2026-10-20 snapshot, pinned when frozen.
- **New experiment ids:** `EXP-P-NNN` (the ledger pattern is extended).
- **New code:**
  - the `p2-v1` and `p2-fresh-v1` split builders, with the existing sealed-read guards (`DXT_SEALED_READ`, pre-registration, clean tree, ledger, vault once);
  - the `safe-v1` system.
- **Phase 1 is untouched:** documents, results and ledger rows are not edited.
