"""E0: the production GenPhenia v3.0 bundle, run exactly as production runs it.

Graph construction reproduces diagnostic.ar-model@654736f
vendor/genphenia_inference_engine/preprocess.py (HPODag.ancestors,
GraphPreprocessor._build_structure, EmbeddingStore.lookup_many) and
engine.py (softmax over ONNX logits). Unknown ids are left out and counted, as
diagnostic.ar-api@19610bf services/genphenai/app/main.py (split_known_ids)
does; a case with no known id is unscorable, where the API answers 422.
Parity with production is checked in tests/test_genphenia_v3.py.
"""

import json
import tarfile
from collections import deque
from pathlib import Path

import numpy as np

from diagnostic_ar_training import INTERIM_DIR
from diagnostic_ar_training.cohorts.schema import Case
from diagnostic_ar_training.lineage.registry import LineageError, Purpose, load_sources, open_source
from diagnostic_ar_training.systems import Scored

SOURCE = "genphenia_v3"
BUNDLE = "genphenia-v3.0"
CHECKPOINT = "graphens_best_model"


def unpack_bundle() -> Path:
    """Extract the pinned tarball once; a stamp ties the directory to its sha256."""
    source = load_sources()[SOURCE]
    target = INTERIM_DIR / BUNDLE
    stamp = target / ".source-sha256"
    if stamp.exists() and stamp.read_text().strip() == source.sha256:
        return target
    if target.exists():
        raise LineageError(f"{target} exists without a matching stamp; delete it and retry")
    tarball = open_source(SOURCE, Purpose.BASELINE)
    INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tarball) as archive:
        archive.extractall(INTERIM_DIR, filter="data")
    stamp.write_text(source.sha256 + "\n")
    return target


class HpoDag:
    def __init__(self, npz_path: Path, index_path: Path) -> None:
        archive = np.load(npz_path, allow_pickle=False)
        self.node_ids = tuple(str(x) for x in archive["node_ids"].tolist())
        self.offsets = archive["parent_offsets"].astype(np.int64)
        self.parent_idx = archive["parent_indices"].astype(np.int64)
        self.index = {str(k): int(v) for k, v in json.loads(index_path.read_text()).items()}

    def parents(self, hpo_id: str) -> tuple[str, ...]:
        i = self.index.get(hpo_id)
        if i is None:
            return ()
        return tuple(self.node_ids[int(j)] for j in self.parent_idx[self.offsets[i] : self.offsets[i + 1]])

    def ancestors(self, hpo_id: str) -> set[str]:
        if hpo_id not in self.index:
            return set()
        seen, result, queue = {hpo_id}, set(), deque([hpo_id])
        while queue:
            for parent in self.parents(queue.popleft()):
                if parent not in seen:
                    seen.add(parent)
                    result.add(parent)
                    queue.append(parent)
        return result


class V3Inputs:
    """What v3.0 sees of a case: bundle spec, gene vocabulary, HPO DAG, embeddings, graph.

    Shared by every system built on the v3.0 bundle, so graph construction cannot drift.
    """

    def __init__(self, root: Path) -> None:
        ckpt = root / "checkpoints" / CHECKPOINT
        spec = json.loads((ckpt / "spec.json").read_text())
        if spec["include_reverse_edges"] or not spec["include_ancestors"]:
            raise LineageError("bundle spec differs from the v3.0 production settings")
        self.root = root
        self.spec = spec
        self.genes = tuple(json.loads((ckpt / spec["genes_path"]).read_text()))
        artifacts = root / "artifacts" / CHECKPOINT
        self.dag = HpoDag(artifacts / "hpo_graph_compact.npz", artifacts / "hpo_graph_index.json")

        emb_index = json.loads((ckpt / spec["embeddings_index_path"]).read_text())
        self.emb_index = {str(k): int(v) for k, v in emb_index.items()}
        raw = np.memmap(ckpt / spec["embeddings_data_path"], dtype="float32", mode="r")
        self.dim = spec["in_channels"]
        self.vectors = raw.reshape(max(self.emb_index.values()) + 1, self.dim)

    def embed(self, node_ids: tuple[str, ...]) -> np.ndarray:
        """Terms without an embedding get a zero vector."""
        x = np.zeros((len(node_ids), self.dim), dtype=np.float32)
        for i, n in enumerate(node_ids):
            row = self.emb_index.get(n)
            if row is not None:
                x[i] = self.vectors[row]
        return x

    def graph(self, observed: list[str]) -> tuple[tuple[str, ...], np.ndarray, np.ndarray]:
        expanded = set(observed)
        for hpo_id in observed:
            expanded |= self.dag.ancestors(hpo_id)
        node_ids = tuple(observed) + tuple(sorted(expanded - set(observed)))
        position = {n: i for i, n in enumerate(node_ids)}
        edges = [
            (i, position[p]) for i, n in enumerate(node_ids) for p in self.dag.parents(n) if p in position
        ]
        edge_index = np.asarray(edges, dtype=np.int64).T if edges else np.zeros((2, 0), dtype=np.int64)
        return node_ids, self.embed(node_ids), edge_index

    def known_present(self, case: Case) -> tuple[list[str], dict]:
        """Present terms the DAG knows, in first-seen order, and the coverage counts reported per case."""
        observed = list(dict.fromkeys(case.present))
        known = [t for t in observed if t in self.dag.index]
        info = {
            "n_present": len(observed),
            "n_unknown": len(observed) - len(known),
            "n_zero_embedded_observed": sum(1 for t in known if t not in self.emb_index),
        }
        return known, info


def softmax64(logits: np.ndarray) -> np.ndarray:
    logits = np.asarray(logits, dtype=np.float64).reshape(-1)
    exp = np.exp(logits - logits.max())
    return exp / exp.sum()


class GenPheniaV3:
    name = "genphenia-v3.0"

    def __init__(self, bundle_dir: Path | None = None) -> None:
        import onnxruntime as ort

        self.inputs = V3Inputs(bundle_dir or unpack_bundle())
        self.spec = self.inputs.spec
        self.genes = self.inputs.genes
        ckpt = self.inputs.root / "checkpoints" / CHECKPOINT
        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        self.session = ort.InferenceSession(
            str(ckpt / self.spec["onnx_path"]), options, providers=["CPUExecutionProvider"]
        )
        self.input_names = {i.name for i in self.session.get_inputs()}

    def lineage_inputs(self) -> list[dict]:
        return [load_sources()[SOURCE].as_input()]

    def graph(self, observed: list[str]) -> tuple[tuple[str, ...], np.ndarray, np.ndarray]:
        return self.inputs.graph(observed)

    def logits(self, observed: list[str]) -> tuple[np.ndarray, tuple[str, ...]]:
        node_ids, x, edge_index = self.graph(observed)
        feeds = {"x": x, "edge_index": edge_index, "batch": np.zeros(len(node_ids), dtype=np.int64)}
        out = self.session.run(None, {k: v for k, v in feeds.items() if k in self.input_names})[0]
        return np.asarray(out).reshape(-1), node_ids

    def probabilities(self, observed: list[str]) -> tuple[np.ndarray, int, int]:
        logits, node_ids = self.logits(observed)
        zero_embedded = sum(1 for n in node_ids if n not in self.inputs.emb_index)
        return softmax64(logits), len(node_ids), zero_embedded

    def score(self, case: Case) -> Scored:
        known, info = self.inputs.known_present(case)
        if not known:
            return Scored(None, info)
        probs, n_nodes, zero_nodes = self.probabilities(known)
        info.update(n_nodes=n_nodes, n_zero_embedded_nodes=zero_nodes)
        return Scored(probs, info)
