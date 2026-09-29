# EXP-A-000: v3.0 through our PyTorch re-implementation (parity)

- **Front:** A
- **Registered:** 2026-09-29, by the Front A agent for Mateo Alvarez
- **Status:** done (2026-09-29)

## Hypothesis
`GinV3` (`gnn/model.py`) loaded from the production `best_model.pt` is
production v3.0. On the same graphs it gives the same logits as the
production ONNX up to float32 rounding, the same top-10 and the same rank of
the true gene. Every later Front A model starts from it, so a failure here
would contaminate every A-00x Δ.

## Systems compared
| System | Artifact ids / code | Notes |
|---|---|---|
| E0 | source `genphenia_v3` (model-v3.0.0) via `systems/genphenia_v3.py` (ONNX Runtime, CPU, 1 thread) | reference |
| candidate | `ginv3-torch`: `systems/ginv3_torch.py` → `gnn.model.load_v3` (same bundle, same graphs via `V3Inputs`) | PyTorch 2.14.0+cu130; CPU (1 thread) and CUDA (RTX 4070 Ti) |

## Data
- **No training, no tuning.** Weights are loaded as released.
- **R1-train, seeded sample:** 1,000 cases with at least one known present
  term, drawn with `random.Random(20260929).sample` from the case-id-sorted
  scorable cases (`dxt gnn parity --n 1000 --seed 20260929`).
- **R1-dev, all 1,883 cases:** `dxt eval run --system ginv3-torch --cohort
  r1-v1/dev --exp EXP-A-000`, view `all`, compared rank by rank with
  `results/EXP-000/r1-v1-dev__genphenia-v3.0__all.ranks.jsonl`
  (`dxt eval compare`).
- **Sealed reads:** none.

## Primary metric and gate
The gate is on the CPU run. Written before any R1 run:

1. **Logits:** max |Δlogit| ≤ 1e-4 over all 1,000 × 5,229 logits of the
   R1-train sample.
2. **Top-10:** the same 10 genes in the same order in 1,000 of 1,000 cases.
3. **R1-dev ranks:** the true gene's rank identical to EXP-000 in 1,883 of
   1,883 cases, so ΔMRR = 0 exactly.

Also reported, without being part of the gate:
- **Stricter bounds:** the count of cases over 1e-5 (the PLAN §6 A3 figure)
  and over 1e-4.
- **Float64 reference:** each case scored with a float64 copy of the same
  weights, and each float32 runtime's distance from it.
- **Re-exported ONNX vs production ONNX:** `gnn.export.export_v3` run
  through ONNX Runtime on the 1,000 cases.
- **Batching:** batched (128) vs single-case torch logits.
- **Timings:**
  - network-only latency per case: ONNX CPU 1 thread, torch CPU 1 thread,
    torch GPU;
  - batch throughput;
  - the harness's end-to-end latency on R1-dev.
- **GPU, recorded separately with no gate:**
  - `dxt gnn parity --device cuda` on the same sample;
  - an R1-dev run with `--device cuda`.

  Report max |Δlogit|, top-10 agreement and every rank change.

**Known before registration** (the 3 production reference cases in
`tests/fixtures/`, not R1):
- torch CPU vs ONNX max |Δlogit| was 4.6e-5, 1.2e-4 and 5.3e-5. That is at
  most 8 float32 ulps, at logits of magnitude 95–170.
- Against a float64 evaluation, ONNX was off by up to 1.0e-4 and torch by
  up to 4.7e-5. The difference is therefore rounding in two different GEMM
  libraries, not a model difference.
- Criterion 1 sits at the float32 floor and may fail on cases whose logits
  are large in magnitude.
- **If it fails** while criteria 2 and 3 hold, the verdict will say so
  literally: ⚠️, with the float64 comparison. Adopting the implementation
  anyway is Mateo's call, not this file's.
- The ONNX re-export already matched production bit for bit on those cases.

## Dev search
None: nothing is tuned. Budget 0 configurations.

## Results
Everything was run from commit `26760d3` (code and this registration),
PyTorch 2.14.0+cu130, ONNX Runtime 1.30.0, RTX 4070 Ti.
- **Files:** `results/EXP-A-000/`, with manifests
  `data/manifests/results-EXP-A-000-*` and `compare-EXP-A-000-*`.
- **Commands:**
  - `dxt gnn parity --device cpu|cuda` (seed 20260929, n = 1,000);
  - `dxt eval run --system ginv3-torch [--device cuda] --cohort r1-v1/dev`;
  - `dxt eval compare`.

**R1-train sample, 1,000 cases:**

| | Torch CPU (gated) | Torch GPU (no gate) |
|---|---|---|
| Max \|Δlogit\| vs production ONNX | **4.9e-4** ❌ (gate 1e-4) | 4.3e-4 |
| Cases with max \|Δlogit\| > 1e-4 / > 1e-5 | 671 / 999 | 631 / 997 |
| Max relative Δlogit (÷ max(\|logit\|, 1)) | 1.2e-6 | 1.2e-6 |
| Max \|Δp\| after softmax | 2.6e-5 | 2.4e-5 |
| Top-10, same genes, same order | **1,000 / 1,000** ✅ | 1,000 / 1,000 |
| True-gene rank identical | 1,000 / 1,000 | 999 / 1,000 (1) |
| Batched (128) vs single-case torch, max \|Δlogit\| | 4.9e-4 | 5.5e-4 |
| Max \|Δlogit\| vs a float64 evaluation of the same weights | torch 2.6e-4; ONNX 4.5e-4 | torch 1.9e-4; ONNX 4.5e-4 |
| Cases where torch is at least as close to float64 as ONNX | 920 / 1,000 | 956 / 1,000 |
| Re-exported ONNX (`export_v3`) vs production ONNX, max \|Δlogit\| | 0.0 on all 1,000 cases | same file |

(1) One GPU rank change: `PMID_33674768_Patient_15_This_study`, true gene
at rank 194 under ONNX and 193 under torch GPU (max \|Δlogit\| 1.1e-4).

**R1-dev, all 1,883 cases, vs EXP-000's per-case ranks:**

| | Torch CPU (gated) | Torch GPU |
|---|---|---|
| Identical ranks | **1,883 / 1,883** ✅ | 1,883 / 1,883 |
| MRR (EXP-000: 0.448) | 0.4485, Δ = 0 exactly, harmed 0, helped 0 | same |
| Other record fields (coverage, n_nodes, unknown and zero-embedded counts) | identical | identical |
| Max \|Δ true-gene probability\| | 4.1e-5 | 3.0e-5 |

The ΔMRR CI shows `resample_unit: case` because EXP-000's rank files
predate publication groups. With Δ = 0 on every case the CI is [0, 0]
either way.

**Timings:**

| | ONNX CPU, 1 thread (E0) | Torch CPU, 1 thread | Torch GPU |
|---|---|---|---|
| Network only, per case, p50 / p95 (R1-train sample) | 1.55 / 3.87 ms | 2.39 / 4.34 ms | 0.64 / 0.84 ms |
| Harness end to end, graph included, p50 / p95 (R1-dev) | 1.56 / 4.00 ms (EXP-000) | 2.08 / 4.23 ms | 0.69 / 1.08 ms |
| Batch of 128 (collate + forward), throughput | n/a | 486 cases/s | 15,350 cases/s |

## Verdict
⚠️ **Gate not met as written: criterion 1 failed; criteria 2 and 3 passed.**

- **Criterion 1 (max |Δlogit| ≤ 1e-4) failed:** 4.9e-4 on CPU, with 671 of
  1,000 cases above 1e-4. The PLAN's 1e-5 fails in 999 of 1,000.
- **Criterion 2 (top-10) passed:** 1,000 of 1,000, same genes in the same
  order.
- **Criterion 3 (R1-dev ranks) passed:** 1,883 of 1,883 identical to EXP-000,
  so ΔMRR = 0 exactly.

What the numbers show:
- **The failure is float32 rounding, not a model difference:**
  - the relative error is ≤ 1.2e-6, a few float32 ulps at logits of magnitude
    in the hundreds;
  - torch is at least as close to a float64 evaluation as production's own
    ONNX Runtime in 92% of cases (CPU) and 96% (GPU);
  - its worst distance from float64 (2.6e-4) is below ONNX's (4.5e-4).
- **The absolute 1e-4 bound is only a few float32 ulps at these
  magnitudes** (one ulp is 3.1e-5 for |logit| in 256–512). A runtime whose
  GEMM kernels differ from ONNX Runtime's (MLAS) cannot be held to it.
- **The same weights exported by `gnn.export.export_v3` reproduce production
  bit for bit** on all 1,000 cases. So the weights, graph construction,
  aggregation and pooling are production's, and the export path, which is
  what a release ships, is exact.

Evidence for a decision (Mateo's, by a dated addendum):
- `GinV3` can be accepted as v3.0 for Front A, since every rank and top-10
  matched on CPU.
- Future parity gates could use a relative bound (e.g. ≤ 2e-6 of
  max(|logit|, 1)) or "no farther from float64 than production", plus
  identical ranks, instead of an absolute bound.
- GPU runs differ from CPU at the same rounding level: 1 rank change in
  1,000 train cases, none on dev. Front A evaluations should state their
  device.

## Addenda

### 2026-09-29, Addendum (decision): GinV3 accepted as v3.0
Mateo accepted GinV3 as production v3.0 for Front A: "I'm ok with rebuilding
if we proved it's the same."

What was proved:
- identical top-10 on 1,000 R1-train cases;
- identical ranks on all 1,883 R1-dev cases;
- relative logit error ≤ 1.2e-6;
- our ONNX export equals production's exactly.

The pre-registered absolute bound (1e-4) stays recorded as **missed**; it is
not rewritten. From now on, parity gates are "relative |Δlogit| ≤ 1e-5 **and**
identical ranks". The reason is that an absolute bound is below float32
resolution at these logit magnitudes (EXP-A-000 Verdict).

