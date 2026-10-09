# Documentation index

This repo holds what was built and measured on top of GenPhenAI to add sex, age and negated symptoms to gene
prioritisation. In short: a question agent (Q2b selection) that adds confirmed and ruled-out findings to each case, a re-ranker
that uses the ruled-out findings, onset age in the doctor's final output, a literature-enriched patient simulator,
and an evaluation infrastructure with sealed splits and pre-registration. Q2b goes into production; the re-ranking on
missing symptoms (`rerank-v1.0.0`) stays in staging only. The summary with numbers is at the top of [STATE.md](STATE.md); the final decisions are in
[ADR-0016](decisions/0016-final-deployment-and-close-out.md).

**Phase 2 (2026-10-07 to 10-08):** `ft-v1.1` is production-ready ([ADR-0018](decisions/0018-ft-v11-production-ready.md)): +0.00138 [+0.00070, +0.00232] on 3,587 and +0.00054 [+0.00005, +0.00129] on 1,072 sealed real patients. Phase 2 was a restart on real patients toward a pre-registered gain from sex, age, onset and absent
symptoms, with a final check on publications GenPhenAI never saw. Plan and status: [PHASE2.md](PHASE2.md); decision:
[ADR-0017](decisions/0017-phase-2-real-patient-restart.md).

| If you need… | Read |
|---|---|
| **Where things stand right now; open decisions; next steps** | [STATE.md](STATE.md) |
| **Phase 2 plan, tracks, gates and schedule** | [PHASE2.md](PHASE2.md) |
| The goal, the two fronts, phases and dates, guardrails | [PLAN.md](PLAN.md) |
| What was done, when, with which numbers, and what worked or didn't | [BITACORA.md](BITACORA.md) (newest entry at the bottom) |
| How data may flow; sources, manifests, known gaps | [DATA_LINEAGE.md](DATA_LINEAGE.md) |
| Splits, sealing, pre-registration, gates, reporting | [EVAL_PROTOCOL.md](EVAL_PROTOCOL.md) |
| Every read of a sealed split | [TEST_LEDGER.md](TEST_LEDGER.md) |
| Analyses (why results look the way they do; dataset realism) | [analyses/](analyses/) |
| Actions only Mateo or the team can take (licenses, billing) | [TODO.md](TODO.md) |
| Why things are the way they are | [decisions/](decisions/README.md) |
| An experiment's hypothesis, gate, configs tried, results | `experiments/<EXP-id>.md` ([template](experiments/TEMPLATE.md)) |
| How a shard agent extracts literature facts (ADR-0013) | [lit/EXTRACTION_GUIDE.md](lit/EXTRACTION_GUIDE.md) |
| How extracted rows become `hpoa-lit` / `hpoa-enriched` / `presentation-ages` (`dxt lit build`) | [DATA_LINEAGE.md §8](DATA_LINEAGE.md) |
| Agent rules (Claude, Codex, …) | [../CLAUDE.md](../CLAUDE.md) (`AGENTS.md` is a symlink to it) |

## Decisions (ADRs)

Status and outcomes: [decisions/README.md](decisions/README.md).

| ADR | One line |
|---|---|
| [0001](decisions/0001-pytorch-for-retraining.md) | Retrain in PyTorch, warm-started from v3.0 |
| [0002](decisions/0002-separate-training-repo.md) | A separate training repo |
| [0003](decisions/0003-publication-grouped-sealed-split.md) | R1 split by publication, sealed test and vault |
| [0004](decisions/0004-two-fronts-one-harness.md) | Two fronts judged by one harness |
| [0005](decisions/0005-release-assets-not-dvc.md) | Manifests in git and release assets instead of DVC |
| [0006](decisions/0006-gene-vocabulary-stays-frozen.md) | Gene vocabulary stays v3.0's 5,229 genes |
| [0007](decisions/0007-frequency-estimation.md) | How HPOA frequencies are read |
| [0008](decisions/0008-gene-profiles.md) | Gene profiles from open sources; disease weighting |
| [0009](decisions/0009-step-zero-identity.md) | New GNN inputs start as an exact identity on v3.0 |
| [0010](decisions/0010-front-a-frozen-base.md) | Front A freezes v3.0 and trains only the new inputs |
| [0011](decisions/0011-simulator-v04.md) | Simulator v0.4, realism-first rebuild |
| [0012](decisions/0012-data-quality-gate.md) | No retraining until simulated data passes the gate (closed without passing) |
| [0013](decisions/0013-literature-enrichment.md) | Enrich profiles from GeneReviews and open-access cohorts |
| [0014](decisions/0014-reranker-v11-and-s3-v2.md) | Re-ranker v1.1 and better questions on S3 v2 |
| [0015](decisions/0015-onset-follow-up-s3-v3.md) | Does onset age help the re-ranker; S3 v3 and v3b |
| [0016](decisions/0016-final-deployment-and-close-out.md) | Final deployment (Q2b + `rerank-v1.0.0`), `rerank-v1.1.0` not released, no more model experiments (superseded by 0017) |
| [0017](decisions/0017-phase-2-real-patient-restart.md) | Phase 2: restart on real patients; `p2-v1` confirmation and a post-E0 final check |
| [0018](decisions/0018-ft-v11-production-ready.md) | `ft-v1.1-c1-lin-all-ens` is the production-ready model; integration later |

## Experiments

| Experiment | One line |
|---|---|
| [EXP-000](experiments/EXP-000.md) | E0 baseline on every cohort |
| [EXP-A-000](experiments/EXP-A-000.md) | v3.0 through our PyTorch re-implementation (parity) |
| [EXP-A-001](experiments/EXP-A-001.md) | Fine-tune v3.0 on simulator positives; R1-dev Δ vs E0 −0.0913 to −0.2075 |
| [EXP-A-002f](experiments/EXP-A-002f.md) | Negated answers into frozen v3.0; R1-dev Δ vs E0 0 (c1 to c3) to −0.2788 |
| [EXP-A-003f](experiments/EXP-A-003f.md) | Sex, age, onset into frozen v3.0; R1-dev Δ vs E0 −0.2090 to −0.2348 |
| [EXP-A-004f](experiments/EXP-A-004f.md) | Negation plus covariates in frozen v3.0 (not run) |
| [EXP-B-001](experiments/EXP-B-001.md) | rr-v1 feature grid searched on R1-dev |
| [EXP-B-002](experiments/EXP-B-002.md) | rr-v2 weights learned on R1-train |
| [EXP-S3-001](experiments/EXP-S3-001.md) | Negation as the app produces it, on simulated interviews |
| [EXP-B-003](experiments/EXP-B-003.md) | Gate for rr-v1[neg=0.5]; passed, released as `rerank-v1.0.0` |
| [EXP-B-004](experiments/EXP-B-004.md) | Re-ranker v1.1 on S3 v2 (descriptive) |
| [EXP-Q-001](experiments/EXP-Q-001.md) | Better questions on S3 v2; Q2b vs Q0 +0.0049 [+0.0027, +0.0069] |
| [EXP-B-005](experiments/EXP-B-005.md) | Onset in the re-ranker on S3 v3b; P1 passed |
| [EXP-B-006](experiments/EXP-B-006.md) | rr-v1 + onset 0.25 (`rerank-v1.1.0`), one R1-test read; gate passed, vs rr-v1 −0.0003 [−0.0019, +0.0008] |
| [EXP-V-001](experiments/EXP-V-001.md) | The one R1-vault read: E0 vs `rerank-v1.0.0` vs `rerank-v1.1.0` (descriptive) |
| [EXP-P-001](experiments/EXP-P-001.md) | Phase 2 Track 1: `safe-v1` (`safe-kb-v1`) on `p2-v1` test; registered 2026-10-08 |
| [EXP-P-004](experiments/EXP-P-004.md) | Withdrawn before its read (X-linked feature flaws found on train) |
| [EXP-P-005](experiments/EXP-P-005.md) | Phase 2 Track 3: `ft-v1.1-c1-lin-all-ens` on `p2-v1` test (confirmation read 2 of 3) |
| [EXP-P-006](experiments/EXP-P-006.md) | Phase 2 final check: `safe-v1[sex+onset]` (H1), `ft-v1.1` (H2) and the rest, on post-E0 patients; read once, 2026-10-08 |
| [EXP-P-003](experiments/EXP-P-003.md) | Phase 2 Track 3: `ft-v1` residual, dev grid of 8 × 3 seeds; selected `c1-lin-all` (dev +0.00313) |
| [EXP-P-007](experiments/EXP-P-007.md) | Phase 2 Track 4: new-row training, leave-genes-out standards test on dev (registered 2026-10-08) |

## Analyses (`analyses/`)

| Analysis | One line |
|---|---|
| [ANALYSIS-001](analyses/ANALYSIS-001-dataset-realism.md) | How realistic the simulated patients are |
| [ANALYSIS-002](analyses/ANALYSIS-002-noise-structure-and-e0-contamination.md) | Structure of real noise; the E0 difficulty target |
| [ANALYSIS-003](analyses/ANALYSIS-003-why-simulated-patients-are-hard.md) | Why simulated patients are too hard for E0 |
| [ANALYSIS-004](analyses/ANALYSIS-004-noise-signal-and-candidate-3.md) | Gene signal in real noise; what candidate 3 taught |
| [ANALYSIS-005](analyses/ANALYSIS-005-what-separates-candidate-5.md) | What still separates candidate 5 from real patients |
| [ANALYSIS-006](analyses/ANALYSIS-006-candidate-6a.md) | Candidate 6a and the last two gaps |
| [SOURCES-SCOPING-001](analyses/SOURCES-SCOPING-001.md) | Would better sources improve the profiles |
| [SOURCES-ACQUISITION-001](analyses/SOURCES-ACQUISITION-001.md) | Tier-1 curated sources and extraction lists |
| [LITPANEL-v2](analyses/LITPANEL-v2.md) | The literature evaluation panel (G4) |
| [LIT-CROSSCHECK-v1](analyses/LIT-CROSSCHECK-v1.md) | Blind re-extraction of 10% of literature rows |
| [LIT-AUDIT-v1](analyses/LIT-AUDIT-v1.md) | Codex re-read of 98 sources: row error, recall |
| [ONSET-INFORMATIVE-TERMS-v1](analyses/ONSET-INFORMATIVE-TERMS-v1.md) | Which symptoms get the onset selector; dev tertiles Δ low +0.0069, mid +0.0040, high +0.0017 |
| [P2-PROBES-v1](analyses/P2-PROBES-v1.md) | Phase 2 sizing on R1 train + dev: sex + strict onset +0.00088 [+0.00039, +0.00151], 0 harmed; E0 MRR 0.612 on cited vs 0.066 on post-E0 publications |

## Evidence for the informe (`evidence/`)

| File | One line |
|---|---|
| [evidence/EVIDENCE_INDEX.md](evidence/EVIDENCE_INDEX.md) | Where each claimable result lives, with split, source and status |
| [evidence/TABLES.md](evidence/TABLES.md) | The same results as full-precision tables, generated |

Figures and data files are in `evidence/figures/` and `evidence/data/`.

## Glossary

| Term | Meaning |
|---|---|
| **E0** | Production GenPhenia v3.0 (`model-v3.0.0`) measured by our harness; the reference for every claim |
| **R1** | phenopacket-store 0.1.27, split `r1-v1` into train / dev / test / vault by publication |
| **R2, R3** | MCRD (229) and DDD (1,048); eval-only external benchmarks |
| **S1, S2** | Our simulator's held-out cases; upstream-style simulated patients |
| **Front A** | Simulator + GNN retraining with sex, age and negated inputs |
| **Front B** | Re-ranker over v3.0's gene distribution using the same inputs |
| **Views** | The same cases evaluated as: present only / + excluded / + sex / + age / all |
| **Harmed rate** | Share of cases whose true gene ranks worse than under E0 |
| **Held-out PMIDs** | Publications of R1 dev/test/vault; masked from every KB and simulator profile |
| **Sealed** | Readable only through a pre-registered experiment, from a clean tree, with a ledger row |
| **Harmed share** | Same as harmed rate; in sealed tables, the share of cases where the system's rank of the true gene is worse than the reference's (cap 5% for Front B candidates) |
| **S3** | Simulated interviewed patients: a case, a question-asking session and the answers (including "no"), used to evaluate Front B; v1, v2, v3b differ in generator and split |
| **kb-vN** | A versioned knowledge base for the re-ranker (kb-v3 ships in `rerank-v1.0.0`; kb-v6 and v7 drop annot-split half B) |
| **annot-split half B** | The 30% of (disease, term) pairs held out of every system's knowledge, kept for the generator, so simulated patients carry facts the system has not seen |
| **rr-v1** | The released re-ranker, `rerank-v1.0.0`: E0's ranking plus a negation penalty (neg = 0.5) |
| **F** | The EXP-B-004 re-ranker (kb-v6, propagated negation, neg 0.5); the bar for the onset experiments |
| **Q0 / Q1 / Q2 / Q2b** | Question strategies of EXP-Q-001: Q0 E0 information gain, non-adaptive; Q1 the previous production selector; Q2 re-ranker-aware adaptive; Q2b Q2 without diversity, now the production default |
| **Onset** | Age at which a symptom (or the disease) began; the re-ranker feature of ADR-0015 and the web «Precisar» age selector |
| **Sealed read, ledger** | One load of a sealed split under a pre-registered experiment, from a clean tree; each is a row in [TEST_LEDGER.md](TEST_LEDGER.md) |
| **DXT_SEALED_READ** | Environment variable that must equal the experiment id for a sealed split to load; set on that one command only |
| **Post-E0** | A publication group with at least one PMID, none in phenopacket-store 0.1.25 and none cited in HPO 2025-11-24 (E0's training annotations); ADR-0017 |
| **EXP-P-NNN** | Phase 2 experiment ids, accepted by the ledger like EXP-A/B/V |
| **p2-v1, p2-fresh-v1** | Phase 2 splits: `r1-v1` train/dev for development, R1 test+vault split into confirmation (not post-E0) and final (post-E0), plus fresh post-E0 patients from phenopacket-store `main` at 2026-10-08 (Amendment 2) |
| **safe-v1, ltr-v1, ft-v1** | Phase 2 candidates: knowledge-only constraints; a re-ranker learned on R1-train; the fine-tuned GNN |

## Related locations

| Location | What |
|---|---|
| `/home/mate/FIUBA/trabajo-profesional/CLAUDE.md` | Workspace guardrails (GenPhenAI lock) |
| `/home/mate/FIUBA/trabajo-profesional/.claude/` | Guard hook and its tests |
| `/home/mate/diagnostic.ar/informe/` | Informe draft, rúbrica, reglamento (written by the team) |
| `/home/mate/diagnostic.ar/qa-agente-claude/docs/EVALUACION.md` | Prior re-ranking evaluation (Mariano's repo; read-only) |
