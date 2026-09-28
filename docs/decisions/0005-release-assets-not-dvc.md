# ADR-0005: Manifests in git + GitHub release assets instead of DVC

- **Status:** Accepted, 2026-09-28.

## Context
- `diagnostic.ar-model` has DVC configured, but its `nvme` remote points to an
  unmounted path.
- About 14 GB of disk is free.
- Artifacts are moderate: datasets of a few hundred MB, checkpoints of about
  55 MB, KBs of tens of MB.
- Production already consumes models as GitHub release assets.

## Decision
- Lineage manifests (inputs, code SHA, params, output sha256) are committed in
  `data/manifests/`.
- Artifact bytes are uploaded as GitHub release assets of this private repo,
  one release per artifact id.
- Raw sources are fetched from immutable URLs and verified against
  `data/sources.yaml`.

## Alternatives dropped
- **DVC with a local remote.** It duplicates bytes on a nearly full disk, and
  the remote would live on the same machine.
- **Git LFS.** Quota limits, and it adds a second storage mechanism.
- **Committing binaries.** It bloats the repo history.

## Consequences
- `gh` must be authenticated to upload and fetch artifacts.
- Reproducing an artifact needs only: the manifest, the code SHA, and the
  sources.
