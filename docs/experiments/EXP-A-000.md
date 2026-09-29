# EXP-A-000: v3.0 through our PyTorch re-implementation (parity)

- **Front:** A
- **Registered:** 2026-09-29, by the Front A agent for Mateo Alvarez
- **Status:** planned

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
(filled after running)

## Verdict

## Addenda
