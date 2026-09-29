# TODO: actions only Mateo (or the team) can take

The newest items are at the top. Mark them done with the date, and log the
outcome in `BITACORA.md`.

## [ ] GeneCards: ask LifeMap Sciences for written permission (optional)
- **Why:** the GeneCards terms forbid training or validating AI models with
  its data, and forbid scraping, without express written permission.
  https://www.lifemapsc.com/genecards-suite-terms-of-use/ (read 2026-09-29).
  Until permission exists, gene profiles come from open sources (HGNC,
  Orphanet, ClinGen, ClinVar).
- **Who sends it:** Mateo or the director (Damián Martinelli), from an
  institutional (fi.uba.ar) address. The academic license is granted to
  academic non-profit institutions.
- **What to ask for** (all three):
  1. The academic data license (data dumps).
  2. Explicit permission to use the data to train and validate ML models in
     a university thesis project.
  3. Permission to use models trained with it in a free, non-commercial web
     tool (diagnostic.ar, hosted at FCEN-UBA).
- **Where:** the GeneCards data access page,
  https://www.genecards.org/Guide/Datasets, or LifeMap Sciences' licensing
  contact.
- **Draft** (edit before sending):

  > Subject: Academic data license and ML-use permission — FIUBA thesis project (diagnostic.ar)
  >
  > Dear LifeMap Sciences team,
  >
  > We are a student team at the Faculty of Engineering, University of Buenos
  > Aires (FIUBA), supervised by Eng. Damián Martinelli, developing a
  > non-commercial rare-disease gene prioritisation tool (diagnostic.ar,
  > hosted at FCEN-UBA). We would like to request (1) the GeneCards academic
  > data license, and (2) written permission to use GeneCards data to train
  > and validate machine-learning models within this academic project,
  > including (3) serving those models in a free, non-commercial web tool.
  > We would cite GeneCards in all outputs. We are happy to provide any
  > further details or sign the required agreement.
  >
  > Kind regards,
  > Mateo Alvarez — FIUBA, legajo 108666
- **If granted:** register the dump in `data/sources.yaml` like any other
  source, with its version, sha256 and the permission letter's reference in
  `notes`. Then decide whether gene profiles `genes-v2` use it.

## [ ] GitHub Actions billing
CI jobs on `MateAlv/diagnostic.ar-training` are refused for billing or
spending-limit reasons. Until this is fixed, `scripts/hooks/pre-push` runs the
same checks locally. See `BITACORA.md` (2026-09-28).
