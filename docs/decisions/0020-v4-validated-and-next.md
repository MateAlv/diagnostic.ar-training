# ADR-0020: the v4 candidate passed its vault read; production comes with a deterministic sex and age layer

- **Status:** Proposed, 2026-10-15 (main session for Mateo). Mateo's direction, 2026-10-15: wrap up v4, build sex and
  age features on top of it ("tiny gain is gold"), then deploy once.
- **Context:** Phase 3 ([ADR-0019](0019-phase-3-v4-retraining.md), [PHASE3.md](../PHASE3.md) §2f).

## What Phase 3 established
- **The v4 candidate** is `R5x-f4-ef2f309462` + `p3-addon-v1-all` (frozen in [P3-CONFIRM](../analyses/P3-CONFIRM.md) §1).
  - The network, `R5x-f4-ef2f309462`, is R1c (E0's architecture, trained from scratch on `sim4`) fine-tuned with
    4,369 real phenopacket-store patients of `p3-v1` train folds 0–3, each gene drawn as the simulator draws it.
  - The add-on, `p3-addon-v1-all`, is `ft-v1.1`'s residual refit on the network's out-of-fold scores, with E0's
    knowledge. It can only lower a gene.
- **Evidence:**

  | Reading | Uncited patients | Capped Δ MRR vs E0 [95% CI] |
  |---|---|---|
  | Folds 0–3, out of fold (network) | 2,316 | +0.071 [+0.049, +0.096] |
  | CONFIRM, read once ([P3-CONFIRM](../analyses/P3-CONFIRM.md)) | 406 | +0.072 [+0.033, +0.120] |
  | **Vault, read once ([EXP-V-002](../experiments/EXP-V-002.md))** | **2,678** | **+0.065 [+0.047, +0.083]** |

- On the vault, uncited patients' right gene is first 16.0% of the time (E0 11.7%) and in the top 10 34.5% of the
  time (29.5%). Cited patients gain +0.060.
- **Where the gain comes from:** real training patients. On the vault it is +0.137 for genes with real training
  patients and +0.001 for the others (EXP-V-002 Addendum 1). The simulator rungs, the memory, the add-on and the
  earlier re-rankers add about 0 on top of the network ([P3-ADDON](../analyses/P3-ADDON.md)).
- **Limits, stated with any claim:**
  - Moving every term to its parent keeps 35% of the gain on the vault (none at CONFIRM): the gain is largest for
    curator-coded HPO terms.
  - The newest publications (`p2-fresh-v1`) show no gain: few of their genes have training patients.
  - Under phenotype swap there is a raw-rank lean toward genes with training patients, deep in the list (reported
    control, Mateo 2026-10-14).
  - `rerank-v1.0.0` lowers the network on publication negatives (−0.0030 [−0.0065, −0.0001], folds 0–3).

## Decision
1. **v4 is the next production base model, after the sex and age layer below.** E0 stays in production until then.
   `rerank-v1.0.0` is not stacked on v4.
2. **Sex and age layer (Phase 4, `docs/analyses/P4-*`):** deterministic rules on top of the v4 candidate.
   - **Sex:** a gene a patient of the other sex cannot have is moved to the bottom. The list must be certain:
     every disease of the gene is limited to one sex. The knowledge is E0's plus HGNC location, declared.
   - **Age:** only rules that are certain and harm no development patient. A rule that cannot get there is
     dropped.
   - Unknown sex or age changes nothing.
3. **Evidence for the layer.** The vault is spent and is never reopened, so the layer is checked in two ways:
   - on folds 0–3 with the network's out-of-fold scores: the gain, and **zero harmed** as the bar;
   - by a second CONFIRM read (fold 4), with its own protocol and ledger row, disclosed. No model was ever fitted on
     fold 4. Its earlier read scored a different system and tuned nothing.
4. **Production** goes through `diagnostic.ar-model`, staging first, once the layer is fixed. The network ships as
   ONNX with E0's input contract. The add-on and the rules ship as numpy code, as `ft-v1.1` was designed to ship.
   E0's behaviour with no new input is checked on staging.
5. **A later, cleaner check:** phenopacket-store publications released after the `p3-v1` freeze (0.1.28+) form the
   next untouched set.

## Consequences
- The informe can report v4's gain, its source (real patients) and its limits from EXP-V-002, P3-CONFIRM and this
  ADR. The prose is the students'.
- Retraining as phenopacket-store grows is the main lever: the gain follows the genes that have real patients.
