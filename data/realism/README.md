# Realism reference data

## `literature-panel-v1.tsv`
Literature prevalence of 37 features of the 8 ANALYSIS-001 diseases that have
published per-feature numbers (NF1, FBN1, PTPN11, KMT2D, TBX5, UMOD, FBXL4,
ITPR1). `dxt sim realism` scores simulated emission against it (ADR-0011,
ADR-0012 G2a).

- **Origin:** compiled on 2026-09-30 from the two literature reports behind
  ANALYSIS-001 §4 (GeneReviews chapters and cohort papers). Every row keeps
  its citation in `source`.
- **HPO ids:** checked against the pinned `hpo_ontology` (2026-02-16). All
  37 draft ids are current terms, and none was changed. `hpo_label` is the
  pinned label. Three draft labels paraphrase their term:
  - "Freckling (skinfold)" is `HP:0001480` *Freckling*, the parent of the
    axillary and inguinal terms;
  - "Neurofibroma (cutaneous)" is `HP:0001067` *Neurofibroma*; HPO has no
    cutaneous-neurofibroma term;
  - "Increased serum lactate" is `HP:0002151`, now labelled *Increased
    circulating lactate concentration*.
- **`sex`:** a row applies only to simulated patients of that sex
  (cryptorchidism: males).
- **Prevalences are lifetime or cohort figures.** `age_note` says where they
  depend on age. They are compared in aggregate, never used to fit anything.
- **No `source_kind` column.** No row is sourced from Orphanet, so every row
  counts in the G2a primary error.
- **Registered** as the artifact `literature-panel-v1` (`dxt knowledge
  panel`, which re-checks the ids and labels).

The ADR-0012 evaluation panel (`literature-panel-v2`, ≥ 50 diseases) is
built separately.
