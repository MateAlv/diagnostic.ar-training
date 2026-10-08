"""Optional configuration: annotation-sampled pseudo-patients and v3.0's pooled vectors.

- Pseudo-patients replay the upstream recipe on the masked knowledge, so a retrained classifier keeps every
  gene: for each gene with an annotated profile, `per_gene` cases, each a uniform subset of 1 to `max_terms`
  of the gene's profile terms that v3.0's DAG knows (size uniform in 1..min(max_terms, profile size)). Cases
  whose (gene, present set) equals an `r1-v1` patient's are dropped (EVAL_PROTOCOL §9.7).
- Pooled vectors: v3.0's attention-pooled 512-d vector, the input of its classifier. v3.0 is frozen and in
  eval mode, so a case's pooled vector is fixed and the classifier configuration trains on them directly.
"""

import random
from collections.abc import Iterable, Sequence

import numpy as np

from diagnostic_ar_training.systems.genphenia_v3 import V3Inputs

SEED = 20261008
PER_GENE = 8
MAX_TERMS = 12


def pseudo_patients(
    kb: dict,
    genes: Sequence[str],
    known: set[str],
    exclude: set[tuple[str, frozenset[str]]],
    per_gene: int = PER_GENE,
    max_terms: int = MAX_TERMS,
    seed: int = SEED,
) -> tuple[list[tuple[int, tuple[str, ...]]], dict]:
    """[(gene index, present terms)], and counts."""
    rng = random.Random(seed)
    out, dropped, genes_used = [], 0, 0
    for i, g in enumerate(genes):
        profile = [t for t in kb["genes"].get(g, {}).get("profile", ()) if t in known]
        if not profile:
            continue
        genes_used += 1
        for _ in range(per_gene):
            k = rng.randint(1, min(max_terms, len(profile)))
            terms = tuple(sorted(rng.sample(profile, k)))
            if (g.upper(), frozenset(terms)) in exclude:
                dropped += 1
                continue
            out.append((i, terms))
    stats = {
        "seed": seed,
        "per_gene": per_gene,
        "max_terms": max_terms,
        "genes": genes_used,
        "cases": len(out),
        "dropped_overlapping_r1": dropped,
    }
    return out, stats


def pooled_vectors(model, inputs: V3Inputs, presents: Iterable[Sequence[str]], device, batch_size: int = 256):
    """[n, hidden] float32: v3.0's pooled vector of each present-term list (each must have a known term)."""
    import torch

    from diagnostic_ar_training.gnn.graphs import NEUTRAL_COVARIATES, NODE_ANCESTOR, CaseGraph, collate

    model.eval()
    presents = list(presents)
    out = np.zeros((len(presents), model.hidden_channels), dtype=np.float32)
    with torch.inference_mode():
        for start in range(0, len(presents), batch_size):
            graphs = []
            for terms in presents[start : start + batch_size]:
                observed = [t for t in dict.fromkeys(terms) if t in inputs.dag.index]
                if not observed:
                    raise ValueError("a pooled vector needs at least one known present term")
                node_ids, x, edge_index = inputs.graph(observed)
                node_type = np.full(len(node_ids), NODE_ANCESTOR, dtype=np.int64)
                graphs.append(CaseGraph(node_ids, x, edge_index, node_type, NEUTRAL_COVARIATES))
            b = collate(graphs).to_torch(device)
            h = model._post(model.conv1(b["x"], b["edge_index"]), model.bn1)
            h = model._post(model.conv2(h, b["edge_index"]), model.bn2)
            h = model._post(model.conv3(h, b["edge_index"]), model.bn3)
            pooled = model.attention_pool(h, b["batch"], b["num_graphs"])
            out[start : start + len(graphs)] = pooled.cpu().numpy()
    return out
