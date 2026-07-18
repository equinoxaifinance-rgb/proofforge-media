# Backblaze Generative Media Hackathon

- Contest: https://backblaze-generative-media.devpost.com/
- Official rules: https://backblaze-generative-media.devpost.com/rules
- Deadline: 2026-08-03T17:00:00-04:00
- Mode: online
- Current release state: Review — live OpenAI/B2 receipt, conflict attestation, and public assets pending

## Requirements

- Build a generative AI media application using both Backblaze B2 and Genblaze.
- Provide a working app URL.
- Provide a repository with setup instructions.
- List AI providers/models and explain meaningful B2 and Genblaze usage.
- Provide an approximately three-minute demo video.

## Judging evidence map

| Criterion | Weight | Judge-visible evidence | Current implementation |
|---|---:|---|---|
| Real-World Utility | 25 | Submit a real campaign brief, inspect revision feedback, record a review, and export an evidence bundle. | Complete local synthetic workflow with scoped preview/manifest/review/export; real marketing/compliance user study not yet claimed. |
| Production Readiness | 25 | Restart the service, force dependency failure, corrupt an asset, retry the same brief, and inspect health/security boundaries. | SQLite WAL recovery, idempotent state machine, persistent scoped tokens, rate/body/asset limits, corruption refusal/repair, pinned non-root read-only container. |
| B2 Storage and Data Orchestration | 25 | Show content-addressed object/manifest keys and fetch the stored object back to reproduce the SHA-256. | B2 sink, manifest read/verify, key recovery, and fetch-back comparison implemented; real B2 receipt remains a hard release gate. |
| Use of Genblaze | 25 | Force a weak first iteration, show evaluator feedback entering the next run, then show parent/run lineage and fallback-capable configuration. | Genblaze AgentLoop reaches 58% → 95% in deterministic demo; live path uses GPT Image 2, 1.5 fallback, and GPT-5.6 Terra evaluator. |

## Winning thesis

ProofForge is not another image generator: it makes quality gates, lineage, durable storage, reviewer decisions, and byte-level proof part of the media workflow itself.
