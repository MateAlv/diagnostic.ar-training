"""GinV4: E0 parity at step 0 for every zero-initialised option, `"-"` masking, edge modes, arch knobs."""

import numpy as np
import pytest

from diagnostic_ar_training.lineage import registry

torch = pytest.importorskip("torch")

from diagnostic_ar_training.gnn.graphs import N_COVARIATES  # noqa: E402
from diagnostic_ar_training.gnn.model import GinV3  # noqa: E402
from diagnostic_ar_training.v4.config import ArchConfig, EncodingConfig  # noqa: E402
from diagnostic_ar_training.v4.model import GinV4, is_new_parameter  # noqa: E402

ALL_OPTIONS = EncodingConfig(observed_flag=True, ic_feature=True, edges="both", covariates=True)
E0_ARCH = ArchConfig(hidden=16)


def small_e0(seed: int = 0) -> GinV3:
    torch.manual_seed(seed)
    model = GinV3(8, 16, 12)
    with torch.no_grad():
        for m in model.modules():
            if isinstance(m, torch.nn.BatchNorm1d):
                m.running_mean.uniform_(-1, 1)
                m.running_var.uniform_(0.5, 2)
                m.weight.uniform_(0.5, 1.5)
                m.bias.uniform_(-0.5, 0.5)
    return model.eval()


def toy_batch(seed: int = 1):
    g = torch.Generator().manual_seed(seed)
    sizes = [5, 3, 7]
    x = torch.randn(sum(sizes), 8, generator=g)
    edges, start = [], 0
    for n in sizes:
        edges += [(start + i, start + (i - 1) // 2) for i in range(1, n)]
        start += n
    edge_index = torch.tensor(edges).T
    batch = torch.repeat_interleave(torch.arange(len(sizes)), torch.tensor(sizes))
    observed = torch.rand(sum(sizes), generator=g) > 0.5
    feats = torch.stack([observed.float(), torch.rand(sum(sizes), generator=g)], dim=1)
    cov = torch.rand(len(sizes), N_COVARIATES, generator=g)
    return x, edge_index, batch, feats, cov


def run(model, enc, data):
    x, edge_index, batch, feats, cov = data
    cols = []
    if enc.observed_flag:
        cols.append(feats[:, :1])
    if enc.ic_feature:
        cols.append(feats[:, 1:])
    nf = torch.cat(cols, dim=1) if cols else None
    with torch.no_grad():
        return model(x, edge_index, batch, 3, nf, cov if enc.covariates else None)


def e0_out(base, data):
    x, edge_index, batch, *_ = data
    with torch.no_grad():
        return base(x, edge_index, batch, 3)


def test_defaults_keep_e0s_keys_and_load_strictly():
    base = small_e0()
    model = GinV4(8, 12, ArchConfig(hidden=16))
    assert set(model.state_dict()) == set(base.state_dict())
    model.load_state_dict(base.state_dict(), strict=True)


@pytest.mark.parametrize(
    "enc",
    [
        EncodingConfig(),
        EncodingConfig(observed_flag=True),
        EncodingConfig(ic_feature=True),
        EncodingConfig(edges="both"),
        EncodingConfig(covariates=True),
        ALL_OPTIONS,
    ],
    ids=["defaults", "observed", "ic", "both", "covariates", "all"],
)
@pytest.mark.parametrize("pooling", ["attention", "attention_mean"])
def test_warm_start_is_e0_bit_for_bit_at_step_0(enc, pooling):
    base, data = small_e0(), toy_batch()
    model = GinV4.from_e0(base, enc, ArchConfig(hidden=16, pooling=pooling)).eval()
    assert torch.equal(run(model, enc, data), e0_out(base, data))
    new = [n for n, _ in model.named_parameters() if is_new_parameter(n)]
    assert bool(new) == (enc != EncodingConfig() or pooling != "attention")


def test_new_parameters_get_gradients_from_step_0():
    base, data = small_e0(), toy_batch()
    model = GinV4.from_e0(base, ALL_OPTIONS, ArchConfig(hidden=16, pooling="attention_mean")).train()
    x, edge_index, batch, feats, cov = data
    loss = torch.nn.functional.cross_entropy(
        model(x, edge_index, batch, 3, feats, cov), torch.tensor([1, 2, 3])
    )
    loss.backward()
    for name, p in model.named_parameters():
        if is_new_parameter(name) and name.endswith("weight") and not name.startswith("cov_mlp"):
            assert p.grad is not None and p.grad.abs().sum() > 0, name


def test_drop_dash_masks_class_zero():
    base, data = small_e0(), toy_batch()
    with torch.no_grad():
        base.classifier.bias[0] = 1e3
    enc = EncodingConfig(drop_dash=True)
    out = run(GinV4.from_e0(base, enc, E0_ARCH).eval(), enc, data)
    ref = e0_out(base, data)
    assert torch.isneginf(out[:, 0]).all() and (ref.argmax(1) == 0).all()
    assert torch.equal(out[:, 1:], ref[:, 1:])
    assert (out.argmax(1) != 0).all()
    loss = torch.nn.functional.cross_entropy(out, torch.tensor([1, 2, 3]))
    assert torch.isfinite(loss)


def test_edge_modes_up_reads_children_both_also_reads_parents():
    """Layer 1 at leaf 4 (parent 1): edges up ignore the parent's features; edges both read them."""
    base, (x, edge_index, *_) = small_e0(), toy_batch()
    x0, ei0 = x[:5].clone(), edge_index[:, :4]
    x1 = x0.clone()
    x1[1] += 1.0

    def first_layer(model, h):
        z = model.conv1.nn[0](model.conv1.combine(h, ei0))
        if model.down_proj is not None:
            z = z + model.down_proj[0](model._down(h, ei0))
        return z

    for edges, reads_parent in (("up", False), ("both", True)):
        model = GinV4.from_e0(base, EncodingConfig(edges=edges), E0_ARCH).eval()
        if model.down_proj is not None:
            for m in model.down_proj:
                torch.nn.init.normal_(m.weight)
        with torch.no_grad():
            a, b = first_layer(model, x0), first_layer(model, x1)
        assert (not torch.equal(a[4], b[4])) == reads_parent, edges
        assert not torch.equal(a[0], b[0])


@pytest.mark.parametrize("hidden,layers", [(16, 1), (32, 4)])
def test_architecture_knobs_from_scratch(hidden, layers):
    x, edge_index, batch, feats, cov = toy_batch()
    arch = ArchConfig(hidden=hidden, layers=layers, dropout=0.1, pooling="attention_mean")
    model = GinV4(8, 12, arch, ALL_OPTIONS)
    assert (
        sum(name.startswith("conv") and name.endswith("eps") for name, _ in model.named_parameters())
        == layers
    )
    out = model(x, edge_index, batch, 3, feats, cov)
    assert out.shape == (3, 12) and torch.isfinite(out).all()


def test_warm_start_refuses_another_shape():
    with pytest.raises(ValueError):
        GinV4.from_e0(small_e0(), EncodingConfig(), ArchConfig(hidden=16, layers=4))


bundle = pytest.mark.skipif(
    not registry.verify(registry.load_sources()["genphenia_v3"]), reason="genphenia_v3 bundle not fetched"
)


@bundle
def test_warm_start_from_the_production_checkpoint_is_ginv3():
    from diagnostic_ar_training.cohorts.schema import Case
    from diagnostic_ar_training.gnn.graphs import case_graph
    from diagnostic_ar_training.gnn.model import load_v3
    from diagnostic_ar_training.systems.genphenia_v3 import V3Inputs, unpack_bundle
    from diagnostic_ar_training.v4.graphs import GraphBuilder

    root = unpack_bundle()
    inputs, base = V3Inputs(root), load_v3(root)
    builder = GraphBuilder(inputs.dag)
    v4 = GinV4.from_e0(base, ALL_OPTIONS, ArchConfig(init="e0")).eval()
    rng = np.random.default_rng(0)
    ids = [n for n in inputs.dag.node_ids if n in inputs.emb_index]
    for _ in range(5):
        present = tuple(ids[i] for i in rng.integers(0, len(ids), 6))
        graph, _ = case_graph(inputs, Case(case_id="c", cohort="t", gene="X", present=present))
        compact = builder.build(present)
        x, ei = torch.from_numpy(graph.x), torch.from_numpy(graph.edge_index)
        feats = torch.zeros(len(graph.node_ids), 2)
        feats[: compact.n_observed, 0] = 1
        with torch.no_grad():
            assert torch.equal(v4(x, ei, None, None, feats, torch.zeros(1, N_COVARIATES)), base(x, ei))
