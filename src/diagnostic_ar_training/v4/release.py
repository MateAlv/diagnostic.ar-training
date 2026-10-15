"""F3's release for diagnostic.ar-model (ADR-0020 decision 4): the network as the GenPhenia bundle
`genphenia-v4.0`, and the add-on and the hard sex rule as the numpy package `dist/v4-layer/`.

- **Network** (`to_ginv3`, `build_bundle`, `pack`): `R5x-f4-ef2f309462` has E0's architecture and encoding
  (hidden 512, 3 layers, attention pooling, edges up, no node features, no covariates), so its GinV4 state
  dict is GinV3's, key for key and tensor for tensor (`v4.model`). It exports with `gnn.export.export_v3`,
  E0's ONNX signature (x [N, 768] float32, edge_index [2, E] int64 -> logits [1, 5229]). The bundle is E0's
  `genphenia-v3.0` tarball with only `model.onnx` replaced: same spec.json, gene order, DAG, embeddings, so
  production's graph construction is unchanged. It is packed with diagnostic.ar-model's
  `scripts/package_bundle.sh` (reproducible tarball).
- **Layer** (`export_layer`): one `v4-layer-bundle/1` JSON object, read by the standalone
  `dist/v4-layer/v4_layer.py` (numpy and the standard library only):
  - the add-on `p3-addon-v1-all` (`ft-v1-bundle/2`, linear members): each member's θ on the features whose θ
    is not 0 in every member, and the per-gene arrays those features read (`p3-addon-kb-v1`), in E0's gene
    order. `neg_obligate` and `neg_embed` have θ = 0 in every member and are dropped, so production needs no
    HPO embeddings nor obligate phenotypes, and excluded terms change nothing;
  - the hard sex rule's gene lists (`sex-kb-v3`);
  - provenance.
- **Staging fixture** (`fixture_case`): known patients with their present terms, inputs, and the expected top
  genes of the network alone and of F3, through production's runtime.
"""

import importlib.util
import json
import os
import subprocess
import sys
import tarfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import ModuleType

import numpy as np

from diagnostic_ar_training import REPO_ROOT
from diagnostic_ar_training.ft import prod
from diagnostic_ar_training.ft.bundle import FEATURES, Knowledge
from diagnostic_ar_training.lineage.registry import LineageError
from diagnostic_ar_training.systems.genphenia_v3 import BUNDLE as E0_BUNDLE
from diagnostic_ar_training.systems.genphenia_v3 import CHECKPOINT
from diagnostic_ar_training.v4 import sexrule

NETWORK = "R5x-f4-ef2f309462"
ADDON = "p3-addon-v1-all"
ADDON_KB = "p3-addon-kb-v1"
SEX_KB = "sex-kb-v3"
FROZEN_SHA256 = {
    NETWORK: "22edfd7ea56510d1210111797215a9a54c22d829979ef05b4e3cc85a758004da",
    ADDON: "31299383a7dce279acdfae37248db8e7e04c62225fd892080c39758276a093b6",
    ADDON_KB: "089ccf87af2347f19ae37464a4e55629bf43ca6a08cc1a8f70dca828d632535a",
    SEX_KB: "7317a6bd5fa6b9b3fd67ae631bde203bb65fc1e5f9ebfb3f768c217ea665c971",
}
TRAINED_ON = (0, 1, 2, 3)
BUNDLE = "genphenia-v4.0"
NETWORK_DIST = REPO_ROOT / "dist" / BUNDLE
LAYER_DIST = REPO_ROOT / "dist" / "v4-layer"
STANDALONE = LAYER_DIST / "v4_layer.py"
LAYER_FILE = "v4-layer-bundle.json.gz"
FIXTURE_FILE = "staging-fixture.json"
FORMAT = "v4-layer-bundle/1"
FIXTURE_FORMAT = "v4-staging/1"
MODEL_REPO = REPO_ROOT.parent / "diagnostic.ar-model"
PACKER = MODEL_REPO / "scripts" / "package_bundle.sh"
ENGINE = MODEL_REPO / "vendor" / "genphenia_inference_engine"
TOP = 10


def load_standalone(path: Path = STANDALONE) -> ModuleType:
    return prod.load_standalone(path)


def check_e0_layout(arch, encoding) -> None:
    """Refuse a v4 configuration whose network is not E0's architecture and encoding."""
    wrong = {
        "layers": arch.layers != 3,
        "pooling": arch.pooling != "attention",
        "edges": encoding.edges != "up",
        "node features": encoding.observed_flag or encoding.ic_feature,
        "covariates": encoding.covariates,
        "drop_dash": encoding.drop_dash,
    }
    if any(wrong.values()):
        raise LineageError(f"not E0's architecture and encoding: {[k for k, v in wrong.items() if v]}")


def to_ginv3(net):
    """The GinV3 (E0's layout) computing what this GinV4 computes; its state dict loads strictly."""
    from diagnostic_ar_training.gnn.model import GinV3
    from diagnostic_ar_training.v4.model import is_new_parameter

    check_e0_layout(net.arch, net.encoding)
    state = net.state_dict()
    if any(is_new_parameter(k) for k in state):
        raise LineageError("the network has parameters GinV3 lacks")
    model = GinV3(net.in_channels, net.arch.hidden, net.out_channels, net.arch.dropout)
    model.load_state_dict(state, strict=True)
    return model.to(next(net.parameters()).device).eval()


def spec_of(bundle_dir: Path) -> dict:
    return json.loads((Path(bundle_dir) / "checkpoints" / CHECKPOINT / "spec.json").read_text())


def onnx_path(bundle_dir: Path) -> Path:
    ckpt = Path(bundle_dir) / "checkpoints" / CHECKPOINT
    return (ckpt / spec_of(bundle_dir)["onnx_path"]).resolve()


def extract_e0(e0_tarball: Path, out_dir: Path, name: str) -> Path:
    """`out_dir/name`: E0's bundle extracted with its own permission bits (the "data" filter drops group
    write), so `package_bundle.sh` repacks it into E0's tarball byte for byte."""
    target = Path(out_dir) / name
    staging = Path(out_dir) / f".{name}.extract"
    if target.exists() or staging.exists():
        raise LineageError(f"{target} or {staging} exists; a bundle is built once")
    staging.mkdir(parents=True)
    with tarfile.open(e0_tarball) as archive:
        archive.extractall(staging, filter="data")
        for member in archive.getmembers():
            os.chmod(staging / member.name, member.mode & 0o777)
    (staging / E0_BUNDLE).rename(target)
    staging.rmdir()
    return target


def build_bundle(e0_tarball: Path, model, out_dir: Path, name: str = BUNDLE) -> Path:
    """`out_dir/name`: E0's bundle with `model.onnx` replaced by `model`'s export (`gnn.export.export_v3`).

    The new file takes the old one's permission bits, so the tarball differs from E0's only in model.onnx.
    """
    from diagnostic_ar_training.gnn import export

    target = extract_e0(e0_tarball, out_dir, name)
    spec = spec_of(target)
    if (spec["in_channels"], spec["hidden_channels"]) != (model.in_channels, model.hidden_channels):
        raise LineageError("the network's sizes differ from the bundle's spec.json")
    genes = json.loads((target / "checkpoints" / CHECKPOINT / spec["genes_path"]).read_text())
    if len(genes) != model.out_channels:
        raise LineageError(f"{model.out_channels} outputs for {len(genes)} genes")
    path = onnx_path(target)
    mode = path.stat().st_mode & 0o777
    export.export_v3(model.cpu().eval(), path)
    os.chmod(path, mode)
    return target


def pack(bundle_dir: Path, out_dir: Path, packer: Path = PACKER) -> tuple[Path, Path]:
    """(tarball, its .sha256) by diagnostic.ar-model's `package_bundle.sh`."""
    subprocess.run(["bash", str(packer), str(bundle_dir), str(out_dir)], check=True, capture_output=True)
    name = Path(bundle_dir).name
    return Path(out_dir) / f"{name}.tar.gz", Path(out_dir) / f"{name}.tar.gz.sha256"


def vendored_engine(engine_dir: Path = ENGINE):
    """diagnostic.ar-model's `GenpheniaEngine`, imported under its own package name (`inference_engine`)."""
    if "inference_engine" not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            "inference_engine", Path(engine_dir) / "__init__.py", submodule_search_locations=[str(engine_dir)]
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules["inference_engine"] = module
        spec.loader.exec_module(module)
    from inference_engine.engine import GenpheniaEngine

    return GenpheniaEngine


def zero_features(bundle: Mapping) -> list[str]:
    """Features whose θ is 0 in every member (refuses non-linear members, as `ft.prod`)."""
    theta = prod.effective_theta(bundle)
    return [f for f, z in zip(FEATURES, (theta == 0).all(axis=0), strict=True) if z]


def _onsets(values: np.ndarray) -> list[float | None]:
    return [None if np.isneginf(v) else float(v) for v in values]


def export_layer(
    bundle: Mapping,
    kb: Mapping,
    sex_kb: Mapping,
    genes: Sequence[str],
    provenance: Mapping,
    standalone_features: Sequence[str],
) -> dict:
    """The `v4-layer-bundle/1` object of a linear add-on bundle on its knowledge and a `sex-kb/2` list."""
    theta = prod.effective_theta(bundle)
    dropped = zero_features(bundle)
    keep = np.array([f not in dropped for f in FEATURES])
    kept = [f for f in FEATURES if f not in dropped]
    if tuple(kept) != tuple(standalone_features):
        raise ValueError(f"active features {kept}; the standalone computes {list(standalone_features)}")
    know = Knowledge(kb, genes, None, bundle["kb_id"])
    limits = sexrule.limits(sex_kb)
    return {
        "format": FORMAT,
        "genes": list(genes),
        "addon": {
            "features": kept,
            "theta": theta[:, keep].tolist(),
            "combine": "mean over members of -θ_m · f (each member's residual, as ft-v1-bundle/2)",
            "dropped_features": {f: "θ = 0 in every member" for f in dropped},
            "arrays": {
                "male_limited": know.male.astype(int).tolist(),
                "female_limited": know.female.astype(int).tolist(),
                "xlr_only": know.xlr.astype(int).tolist(),
                "strict_onset_years": _onsets(know.strict),
                "lenient_onset_years": _onsets(know.lenient),
            },
        },
        "sex_rule": {f"{sex}_only": [g for g in genes if limits.get(g) == sex] for sex in sexrule.SEXES},
        "provenance": dict(provenance),
    }


def top(probs: np.ndarray, genes: Sequence[str], k: int = TOP) -> list[list]:
    """[[gene, probability], ...] of the k highest probabilities (ties in gene order)."""
    return [[genes[i], float(probs[i])] for i in np.argsort(-probs, kind="stable")[:k]]


def fixture_case(
    case_id: str,
    kind: str,
    gene: str,
    hpo_ids: Sequence[str],
    inputs: Mapping,
    genes: Sequence[str],
    network_probs: np.ndarray,
    f3_probs: np.ndarray,
    rank_network: int,
    rank_f3: int,
) -> dict:
    return {
        "case_id": case_id,
        "kind": kind,
        "gene": gene,
        "hpo_ids": list(hpo_ids),
        "inputs": {k: inputs.get(k) for k in ("sex", "age_years", "onset_years", "excluded")},
        "network_top": top(network_probs, genes),
        "f3_top": top(f3_probs, genes),
        "rank_network": rank_network,
        "rank_f3": rank_f3,
    }


def write_sums(paths: Sequence[Path], sums: Path) -> Path:
    from diagnostic_ar_training.lineage.hashing import sha256_file

    sums.write_text("".join(f"{sha256_file(p)}  {Path(p).name}\n" for p in paths))
    return sums


def frozen_network(ctx):
    """(net, cfg) of F3's network on `ctx.device`, refused unless its last.pt is the frozen one."""
    from diagnostic_ar_training.lineage.hashing import sha256_file
    from diagnostic_ar_training.v4 import addon
    from diagnostic_ar_training.v4.runs import load_config, run_dir

    cfg = load_config(NETWORK)
    sha = sha256_file(run_dir(NETWORK) / "last.pt")
    if sha != FROZEN_SHA256[NETWORK] or tuple(sorted(cfg.sim.real_folds)) != TRAINED_ON:
        raise LineageError(f"{NETWORK}: last.pt sha256 {sha} or real folds differ from the frozen F3")
    check_e0_layout(cfg.arch, cfg.encoding)
    return addon.load_network(NETWORK, ctx)


def frozen_layer() -> tuple[dict, dict, dict, dict[str, str]]:
    """(add-on bundle, its knowledge, sex knowledge, sha256 by id) of F3, refused unless all hashes match."""
    from diagnostic_ar_training.v4 import addon

    shas = {}
    kb, shas[ADDON_KB] = addon.load_kb(ADDON_KB)
    bundle, shas[ADDON] = addon.load_bundle(ADDON, ADDON_KB)
    sex_kb, shas[SEX_KB] = sexrule.load_kb(SEX_KB)
    wrong = {k: v for k, v in shas.items() if v != FROZEN_SHA256[k]}
    if wrong:
        raise LineageError(f"not the frozen F3: {wrong}")
    return bundle, kb, sex_kb, shas


def torch_logits(net, cfg, ctx, members) -> dict[str, np.ndarray]:
    """case id -> the network's float32 logits, batched as the research path (`v4.addon.network_logits`)."""
    from diagnostic_ar_training.v4 import addon
    from diagnostic_ar_training.v4.evaluate import PatientSet

    pset = PatientSet.build(addon.network_view(members), ctx.builder, ctx.genes)
    return addon.network_logits(net, pset, ctx.tables(cfg.encoding.ic_feature), cfg.encoding)


def flip_gap(a: np.ndarray, b: np.ndarray, target: int) -> float:
    """The largest |a_g - a_target| over the genes ranked above the target in one score vector only."""
    flipped = (a >= a[target]) != (b >= b[target])
    return float(np.abs(a[flipped].astype(np.float64) - float(a[target])).max()) if flipped.any() else 0.0


def mapping_check(net, members, onnx_system, n: int) -> dict:
    """GinV4 vs its GinV3 on the CPU, one graph per call, on the first `n` scorable patients: bit for bit."""
    import copy

    import torch

    v4 = copy.deepcopy(net).cpu().eval()
    v3 = to_ginv3(v4)
    worst, equal, done = 0.0, 0, 0
    with torch.inference_mode():
        for p in members:
            known, _ = onnx_system.inputs.known_present(p.case)
            if not known:
                continue
            _, x, edge_index = onnx_system.graph(known)
            args = (torch.from_numpy(x), torch.from_numpy(edge_index))
            a, b = v4(*args).numpy(), v3(*args).numpy()
            worst = max(worst, float(np.abs(a - b).max()))
            equal += bool(np.array_equal(a, b))
            done += 1
            if done == n:
                break
    return {"patients": done, "bit_identical": equal, "max_abs_dlogit": worst}


def network_parity(members, torch_scores: Mapping, onnx_system, engine, genes: Sequence[str]) -> dict:
    """The ONNX bundle (training repo's runtime, and diagnostic.ar-model's engine) vs the torch network.

    Ranks are pessimistic ranks of the true gene: on logits for torch and ONNX, on the engine's probabilities.
    """
    from diagnostic_ar_training.ft.bundle import softmax64
    from diagnostic_ar_training.v4.addon import rank

    lookup = {g.upper(): i for i, g in enumerate(genes)}
    out = {"patients": len(members), "scored": 0, "in_vocab": 0, "unscorable_agree": True}
    worst = {"onnx_vs_torch_max_abs_dlogit": 0.0, "engine_vs_torch_max_abs_dprob": 0.0}
    worst["onnx_vs_torch_max_rel_dlogit"] = worst["engine_vs_onnx_max_abs_dprob"] = 0.0
    differ = {"onnx": [], "engine": []}
    same = {"onnx": 0, "engine": 0, "engine_top10": 0}
    for p in members:
        known, _ = onnx_system.inputs.known_present(p.case)
        z = torch_scores.get(p.case_id)
        if (z is None) != (not known):
            out["unscorable_agree"] = False
        if z is None or not known:
            continue
        out["scored"] += 1
        onnx, _ = onnx_system.logits(known)
        probs = np.fromiter(
            engine.predict(known, top_k=TOP, return_distribution=True)["distribution"].values(), np.float64
        )
        if probs.size != len(genes):
            raise LineageError(f"the engine returned {probs.size} probabilities for {len(genes)} genes")
        torch_probs = softmax64(z)
        worst["onnx_vs_torch_max_abs_dlogit"] = max(
            worst["onnx_vs_torch_max_abs_dlogit"], float(np.abs(onnx - z).max())
        )
        rel = float((np.abs(onnx - z) / np.maximum(np.abs(z), 1.0)).max())
        worst["onnx_vs_torch_max_rel_dlogit"] = max(worst["onnx_vs_torch_max_rel_dlogit"], rel)
        worst["engine_vs_torch_max_abs_dprob"] = max(
            worst["engine_vs_torch_max_abs_dprob"], float(np.abs(probs - torch_probs).max())
        )
        worst["engine_vs_onnx_max_abs_dprob"] = max(
            worst["engine_vs_onnx_max_abs_dprob"], float(np.abs(probs - softmax64(onnx)).max())
        )
        same["engine_top10"] += bool(
            np.array_equal(np.argsort(-probs, kind="stable")[:TOP], np.argsort(-z, kind="stable")[:TOP])
        )
        idx = lookup.get(p.case.gene.upper())
        if idx is None:
            continue
        out["in_vocab"] += 1
        r = rank(z, idx)
        for name, scores in (("onnx", onnx), ("engine", probs)):
            got = rank(scores, idx)
            if got == r:
                same[name] += 1
            else:
                gap = flip_gap(z, scores, idx)
                differ[name].append({"case_id": p.case_id, "rank_torch": r, f"rank_{name}": got, "gap": gap})
    out |= worst
    out["rank_identical"] = {"onnx": same["onnx"], "engine": same["engine"]}
    out["engine_top10_same_order_as_torch"] = same["engine_top10"]
    out["rank_differs"] = differ
    return out


def research_f3(addon_model, rule, logits: np.ndarray, inputs: Mapping) -> np.ndarray:
    """F3's scores as evaluated (P4-CONFIRM, `confirm2.score`): network + add-on, then the hard sex rule."""
    return rule.apply(addon_model.scores(logits, inputs), inputs.get("sex"))


def layer_parity(
    members,
    torch_scores: Mapping,
    onnx_scores: Mapping,
    full,
    dropped,
    rule,
    layer,
    genes: Sequence[str],
) -> tuple[dict, dict[str, dict]]:
    """(summary, per case the scores at hand) of the packaged layer vs the research F3 on the same logits.

    `full` is the add-on on its knowledge with v3.0's embeddings, `dropped` the same without the θ = 0
    features and without embeddings. The packaged layer is also run on the ONNX logits (end to end).
    """
    from diagnostic_ar_training.ft.bundle import softmax64
    from diagnostic_ar_training.ft.system import case_inputs
    from diagnostic_ar_training.v4.addon import rank

    lookup = {g.upper(): i for i, g in enumerate(genes)}
    out = {
        "patients": 0,
        "in_vocab": 0,
        "dropped_equals_full": 0,
        "scores_bit_identical": 0,
        "max_abs_dscore": 0.0,
        "rank_identical_scores": 0,
        "rank_identical_probs": 0,
        "end_to_end_rank_identical": 0,
        "no_inputs_is_softmax": 0,
        "changed_by_layer": 0,
        "sex_blocked_any": 0,
    }
    differ, kept = [], {}
    for p in members:
        z = torch_scores.get(p.case_id)
        if z is None:
            continue
        out["patients"] += 1
        inputs = case_inputs(p.case)
        research = research_f3(full, rule, z, inputs)
        out["dropped_equals_full"] += bool(np.array_equal(research_f3(dropped, rule, z, inputs), research))
        got = layer.scores(z, inputs)
        out["scores_bit_identical"] += bool(np.array_equal(got, research))
        out["max_abs_dscore"] = max(out["max_abs_dscore"], float(np.abs(got - research).max()))
        out["no_inputs_is_softmax"] += bool(np.array_equal(layer.apply(z, {}), softmax64(z)))
        out["changed_by_layer"] += bool(not np.array_equal(got, np.asarray(z, dtype=np.float64)))
        out["sex_blocked_any"] += bool(layer.blocked(inputs.get("sex")).any())
        kept[p.case_id] = {"inputs": inputs, "onnx": onnx_scores[p.case_id]}
        idx = lookup.get(p.case.gene.upper())
        if idx is None:
            continue
        out["in_vocab"] += 1
        r = rank(research, idx)
        r_scores, r_probs = rank(got, idx), rank(layer.apply(z, inputs), idx)
        r_e2e = rank(layer.apply(onnx_scores[p.case_id], inputs), idx)
        out["rank_identical_scores"] += r_scores == r
        out["rank_identical_probs"] += r_probs == r
        out["end_to_end_rank_identical"] += r_e2e == r
        if not r == r_scores == r_probs == r_e2e:
            differ.append(
                {"case_id": p.case_id, "rank_research": r, "scores": r_scores, "probs": r_probs, "e2e": r_e2e}
            )
    out["rank_differs"] = differ
    return out, kept


def select_fixture(
    members, kept: Mapping[str, dict], layer, genes: Sequence[str], n: int, seed: int
) -> list[tuple[str, str, dict]]:
    """(case id, kind, inputs) of the staging fixture, seeded over the sorted case ids of in-vocabulary
    patients scored by ONNX: `n` whose sex rule blocks a gene of the network's top 10 (fewer if fewer
    exist), `n` whose top 10 the add-on changes, `n` others; then 3 of the first kind with no input."""
    import random

    from diagnostic_ar_training.ft.bundle import softmax64

    lookup = {g.upper() for g in genes}
    by_kind: dict[str, list[str]] = {"sex-rule": [], "addon": [], "other": []}
    for p in sorted(members, key=lambda p: p.case_id):
        if p.case_id not in kept or p.case.gene.upper() not in lookup:
            continue
        z, inputs = kept[p.case_id]["onnx"], kept[p.case_id]["inputs"]
        top_net = np.argsort(-softmax64(z), kind="stable")[:TOP]
        top_f3 = np.argsort(-layer.apply(z, inputs), kind="stable")[:TOP]
        if layer.blocked(inputs.get("sex"))[top_net].any():
            by_kind["sex-rule"].append(p.case_id)
        elif not np.array_equal(top_net, top_f3):
            by_kind["addon"].append(p.case_id)
        else:
            by_kind["other"].append(p.case_id)
    rng = random.Random(seed)
    picked = {k: rng.sample(v, min(n, len(v))) for k, v in by_kind.items()}
    out = [(c, kind, kept[c]["inputs"]) for kind, cases in picked.items() for c in cases]
    none = {"sex": None, "age_years": None, "onset_years": None, "excluded": []}
    out += [(c, "no-inputs", none) for c in (picked["sex-rule"] + picked["addon"])[:3]]
    return out
