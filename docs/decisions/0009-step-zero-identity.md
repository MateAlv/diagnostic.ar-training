# ADR-0009: How new inputs enter the GNN so that the untrained extension is exactly v3.0

- **Status:** Accepted, 2026-09-29 (Mateo). **Scope: Front A only.**
  Front B does not use GinV3 or this extension; it works on the production
  model's normal output (the `genphenia_v3` ONNX distribution), as it
  always has.
- **Refines:** ADR-0001 ("zero-initialised new inputs, so that the extended
  model equals v3.0 at step 0") and PLAN §6 A3 (A-neg, A-neg2, A-cov).

## Context
- A-002/A-003/A-004 fine-tune v3.0 with negated terms, sex and age. Their
  Δ vs E0 is only attributable to the new inputs if the model **starts** at
  E0: same logits on every case, before any gradient step.
- Zero-initialised input weights are not enough for negated terms. Adding
  them as nodes changes the graph, and two things then move even with zero
  weights:
  - **message passing:** a negated node's embedding flows into the positive
    nodes it is linked to (GIN sums neighbours);
  - **pooling:** attentional pooling normalises over all nodes, so extra
    nodes take softmax weight from the positive ones.
- "Equal" must survive float32 arithmetic. A Linear widened by zero columns
  can round differently from the narrow one, which would already leave a
  ~1e-6 gap at step 0.

## Decision
`gnn.model.GinV3Extended`, warm-started with `GinV3Extended.from_v3`:

1. **Graph** (`gnn.graphs.case_graph(..., negated=True)`):
   - the positive graph is v3.0's, unchanged in order and edges;
   - each negated term the DAG knows becomes one node **appended after it**.
     It is **not expanded to its ancestors**; a term that is also in the
     positive graph still gets its own negated node;
   - a negated node gets edges **negated → its nearest positive ancestors**:
     walk up the DAG and stop at the first nodes already in the positive
     graph. That graph is closed under ancestors, so these are the most
     specific positive terms that subsume the negated one (its parents, when
     they are in). Negated nodes never receive messages.
2. **Node types** `[observed, ancestor, negated]` go through the first GIN
   layer like the embeddings and are then projected by `type_proj`
   (zero-initialised). The result is added to `conv1.nn[0]`'s output. This is
   the same function as widening that Linear by three zero columns, but
   adding an exact 0.0 keeps the output bit-identical.
3. **Negated messages** are scaled per channel by `neg_gates[k]`, one gate
   vector per GIN layer, initialised to 0. Positive-source messages are
   multiplied by exactly 1.
4. **Pooling:** the v3.0 attentional pool reads **positive nodes only**.
   - **A-neg** (`neg_readout=False`): negation reaches the output only through
     the gated messages.
   - **A-neg2** (`neg_readout=True`): negated nodes get their own attentional
     pool (gate copied from v3.0's), read by `neg_classifier`. It starts at 0
     and has no bias, so a case without negated terms adds exactly 0.
5. **Covariates**
   `[male, female, sex_unknown, log1p(age), age_known, log1p(onset), onset_known]`
   (`gnn.graphs.covariates`) → `cov_mlp` → `cov_classifier`, initialised to
   0. This is the same as concatenating the covariate features to the pooled
   vector with zero classifier columns. Unknown values are 0 with their flag
   0; prenatal onsets count as 0; `onset_term` is not used yet.

## Why this design
- **Identity is exact, not approximate**, with and without negated terms,
  single or batched (`tests/test_gnn_model.py`, ≤ 1e-6; measured 0.0). Every
  later Δ is therefore caused by training, never by the graph change.
- **Nothing is dead at step 0:** `neg_gates`, `type_proj`, `cov_classifier`
  and `neg_classifier` all get non-zero gradients on the first step (tested).
  Parameters behind a zero output (`cov_mlp`, the negated pool's gate) start
  learning from the second step.
- **The v3.0 path stays readable:** the positive graph, its pooling and its
  classifier are v3.0's tensors. A-neg vs A-neg2 is one flag.
- **ONNX:** exports with inputs `x`, `edge_index`, `node_type` and optionally
  `covariates`. Fed observed/ancestor types and neutral covariates, the
  untrained export returns production's logits bit for bit (tested).

## Alternatives dropped
- **Negated nodes pooled with the positive ones, zero features.** The pooling
  softmax still spreads weight over them, so the step-0 output changes.
- **Only a flag channel on existing nodes** (mark positive nodes that have a
  negated descendant). Loses every negated term outside the positive graph,
  and the simulator (PLAN A1) never negates a term related to a present one.
- **FiLM on the pooled vector for covariates.** Also identity at 0 (γ = β = 0),
  but it gives covariates a multiplicative route before we know whether the
  additive one helps. It remains an A-003 variant if the additive head
  underfits.
- **Widening `conv1.nn[0]` to 771 inputs.** Identical maths, but not
  bit-identical at step 0, and its state dict no longer matches v3.0's.

## Consequences
- **Identity is an eval-mode property.** In training mode, BatchNorm batch
  statistics also include negated nodes, and dropout is active. Training
  recipes should decide whether to freeze BatchNorm statistics.
- **Feature dropout** (PLAN A3) is applied to the inputs (drop negated
  terms, set covariates to unknown), not inside the model.
- `diagnostic.ar-model` will need an engine adapter `"4.0"` that builds
  `node_type` and `covariates`. Clients that send only present terms get the
  observed/ancestor types and neutral covariates.
