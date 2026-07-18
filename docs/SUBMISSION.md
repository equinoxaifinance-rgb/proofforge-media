# Submission draft: Backblaze Generative Media Hackathon

This copy reflects the approved live Genblaze/OpenAI/B2 run and the current hardened release.
The durable judge URL, final video, owner attestations, and Devpost receipt remain publication
gates and must be inserted only after their checks pass.

## Project name

ProofForge Media

## Tagline (140 characters maximum)

Generate, evaluate, revise, and prove every AI media asset with reproducible lineage and B2-backed evidence.

## Inspiration

Generating an image is easy. Answering production questions later is hard: Which brief made
this asset? Which model ran? Did it pass the quality bar? Was it revised? Are the stored bytes
still the bytes we approved? Can a reviewer reconstruct the decision without trusting a
screenshot?

ProofForge Media turns those questions into the product. It treats the media file and its
evidence trail as one deliverable.

## What it does

A user submits a campaign brief, audience, channel, message, visual direction, forbidden
terms, and quality threshold. Genblaze runs a generate/evaluate/revise loop for up to three
iterations. Each evaluation records score, pass/fail state, feedback, run identity, and parent
lineage. A completed run exposes an access-controlled preview, manifest, reviewer event, and
downloadable evidence bundle containing the exact verified asset.

The public demo uses Genblaze's deterministic provider and clearly labels its output local and
synthetic. Operator-locked live mode uses OpenAI image generation, GPT-5.6 Terra vision
evaluation, content-addressed Backblaze B2 persistence for every iteration, stored-manifest
verification, and a B2 fetch-back byte hash for every asset before it can claim persistence.

## How we built it

ProofForge is a FastAPI application backed by SQLite WAL storage. Genblaze's `AgentLoop`
coordinates generation and rubric evaluation, passing revision feedback into the next parented
run. Demo SVGs are parsed with defusedxml. Live assets are bounded to 20 MiB, hashed in chunks,
stored under SHA-256-derived names, written to B2 through `genblaze-s3`, then fetched back and
compared with Genblaze's digest. Each parented iteration receives its own immutable manifest
and asset receipt, while content-addressing deduplicates identical bytes.

Every public run is idempotent only within a cryptographically scoped browser session, so two
people submitting an identical brief cannot share a run or review history. State transitions
are atomic, interrupted queued/running work fails closed on restart, scoped HMAC tokens protect
demo evidence, and only an operator can start live runs or record a verified approval.

## Challenges

The difficult work was failure behavior, not the success animation. We found and fixed stale
schema collisions, restart-invalidated tokens, unauthenticated evidence access, missing assets
inside exported bundles, corrupted completed-run reuse, path escape risk, unbounded request
bodies, whole-file hashing, migration races, and inaccessible loading/validation state.

The browser was also tested with the API process intentionally stopped. A new action failed,
but the previous verified result remained visible instead of being destroyed by the error.

## Accomplishments

- 47 adversarial Python tests pass under warnings-as-errors, plus Ruff, dependency consistency,
  and vulnerability checks.
- A forced weak first pass scores 58%, revision scores 95%, and the final local asset hash is verified.
- One-byte corruption changes asset access to 409; retry exposes queued → running → completed and repairs the same idempotent run.
- Tokens survive restart through a persistent signing key; short configured keys are rejected.
- Failed B2 pointer publication remains explicitly unpublished, restores the prior verified
  pointer, and can be retried without becoming a false public approval.
- The public-host design uses a separate read-only, `proofforge/`-scoped B2 credential and
  keeps paid generation disabled for judges.
- The pinned container runs non-root with a read-only root filesystem and a real healthcheck.
- Desktop and 375px mobile browser layouts have no horizontal overflow.
- Independent audits found cross-user deduplication, model-markup injection, incomplete
  iteration storage, and unsafe pruning behavior; each finding now has a regression test.

## What we learned

Provenance is a runtime property, not a JSON file placed beside an image. A useful manifest has
to survive retries, corruption, restart, authorization boundaries, and export. Storage claims
also require read-after-write verification: an upload response alone does not prove that the
durable bytes match the approved local asset.

## What's next

The owner-authorized live run is complete. It produced a real GPT Image asset, GPT-5.6 Terra
evaluation, Genblaze lineage, B2 asset and manifest objects, per-iteration fetch-back checks,
and empty-local-state recovery. The remaining gates are the exact Cloudflare container
deployment with a read-only B2 key, hostile remote verification, the final accurate video,
owner attestations, and the Devpost submitted-state receipt.

## Built with

Python 3.11, FastAPI, Uvicorn, Genblaze 0.4.3, genblaze-openai 0.3.2,
genblaze-s3 0.3.5, Backblaze B2, OpenAI GPT Image 2 with GPT Image 1.5 fallback,
GPT-5.6 Terra, SQLite WAL, Pydantic, defusedxml, Docker, pytest, and Ruff.

## Links

- Durable demo: [DEPLOYMENT GATE - insert only after hostile remote verification]
- Repository: https://github.com/equinoxaifinance-rgb/proofforge-media
- Final public video: [VIDEO GATE - record only after the durable deployment is green]
- Live B2 receipt: `../../reports/integrations/PROOFFORGE-LIVE-RECEIPT.md`
