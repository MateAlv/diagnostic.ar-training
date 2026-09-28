# ADR-0002: A separate `diagnostic.ar-training` repo

- **Status:** Accepted, 2026-09-28.

## Context
- `GenPhenAI/` is upstream work we must never modify.
- `diagnostic.ar-model` is the release channel production pins: bundle
  tarballs, the vendored inference engine, `model-vX.Y.Z` tags.
- `rare-disease-simulator` generates synthetic patients.
- Training, re-ranking and evaluation need a home with its own lineage and
  protocol.

## Decision
- A new private repo, `MateAlv/diagnostic.ar-training`, holds:
  - the plan and the log;
  - source pins, splits and manifests;
  - the shared evaluation harness;
  - Front A (GNN) and Front B (re-ranker).
- Candidates that pass a gate are packaged and released through
  `diagnostic.ar-model`.

## Alternatives dropped
- **Put everything in `diagnostic.ar-model`.** That mixes experiments with
  the artifact production pins, and every experimental commit would sit next
  to the release history.
- **Put training in the simulator repo.** Data generation and model
  evaluation must stay separate, so that the simulator cannot be tuned against
  evaluation results by accident.

## Consequences
- Three repos to keep in sync, linked by pinned SHAs and manifests.
- The workspace `trabajo-profesional/` holds only the guardrails
  (`CLAUDE.md`, `.claude/`).
