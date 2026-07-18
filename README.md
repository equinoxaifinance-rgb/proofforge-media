# ProofForge Media

ProofForge Media is an evidence-first generative media workflow. Genblaze coordinates
generation, rubric evaluation, and revision; operator-locked live mode persists every
iteration asset and manifest to Backblaze B2 and fetches every object back before claiming
byte integrity.

The default public path is deliberately synthetic and local. It requires no cloud credentials,
spends no API credits, and never claims B2 persistence.

## Architecture

1. FastAPI validates a bounded campaign brief and creates an idempotent SQLite run.
2. `Genblaze AgentLoop` generates, evaluates, and revises for at most three iterations.
3. The demo uses `MockProvider`; live mode uses GPT Image 2 with GPT Image 1.5 fallback.
4. GPT-5.6 Terra evaluates live images against a strict JSON schema.
5. Completed assets are limited to 20 MiB and stored under their SHA-256.
6. Live mode writes each iteration through `genblaze-s3` to B2, reads each stored manifest,
   fetches each B2 object, and compares its bytes with Genblaze's recorded digest.
7. A verified approval publishes a hash-linked application receipt and `latest` pointer to B2.
8. A fresh container with no SQLite rows or local artifact recovers the approved showcase from
   B2 and verifies the receipt, manifest pointer, media size, and media SHA-256 before serving.
9. Access-controlled endpoints expose preview, manifest, review events, and evidence.zip.

## Local demo

Requires Python 3.11.

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements-dev-lock.txt
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m uvicorn proofforge.main:app --host 127.0.0.1 --port 8000
```

macOS/Linux:

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements-dev-lock.txt
PYTHONPATH=. .venv/bin/python -m uvicorn proofforge.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`. The app creates a persistent demo signing key in the configured
data directory with mode `0600` when the platform supports POSIX modes.

## Tests and lint

```powershell
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest -W error -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pip check
```

The hostile suite covers authorization, invalid and chunked/oversized input, rate limits,
restart recovery, tenant-scoped idempotency, duplicate concurrency, migration concurrency,
provider failure, the full mocked live Genblaze-to-object-store contract, every-iteration
fetch-back verification, invalid transitions, pruning races, review atomicity, path escape,
corruption, missing/oversized assets, evidence contents, SVG text bounds, B2 receipt/media
tampering, and recovery of an approved showcase with an empty local database and disk cache.

## Reproducible container

```bash
docker build --pull --no-cache -t proofforge-media .
docker run --rm --read-only --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  -v proofforge-data:/app/data -p 127.0.0.1:8000:8000 proofforge-media
```

The Dockerfile pins the full base-image digest, installs the hashed transitive lock, runs as
UID 10001, and includes `/api/health` as its healthcheck.

The current SQLite/background-task topology intentionally runs as one application replica.
Starting a second replica against the same data volume is unsupported because interrupted-run
recovery is process-local; horizontal scaling requires a leased external job queue first.

## Judge hosting target

`deploy/cloudflare` contains the pinned Cloudflare Containers wrapper. It routes every request
to one named instance, passes live credentials only from encrypted Worker secrets, and has a
Wrangler dry-run/config test. Cloudflare container disks are ephemeral. Public demo rows remain
intentionally disposable; an approved live showcase is recovered from a hash-linked receipt
and media object in B2. The
deployment requires the Workers Paid plan and must not be activated without owner approval.

## Operator-locked live mode

Copy `.env.example` into your secret manager; do not commit the populated file. Required:

- `PROOFFORGE_ENABLE_LIVE=true`
- `PROOFFORGE_OPERATOR_TOKEN`: at least 32 random characters
- `PROOFFORGE_SIGNING_KEY`: independent value of at least 32 random characters
- `OPENAI_API_KEY`
- `B2_KEY_ID`, `B2_APP_KEY`, `B2_BUCKET`, and the correct `B2_REGION`
- optional `B2_PUBLIC_URL_BASE`

Live generation is accepted only with `X-Proofforge-Key`. Demo run tokens cannot authorize a
live run or verified approval. Never expose the operator token or B2 application key in the
browser. Judges use the public local workflow plus sanitized receipts from an operator-created
live run; they are never given an unlimited paid-generation credential.

## Providers and models

- Orchestrator: Genblaze 0.4.3
- Image generation: OpenAI GPT Image 2
- Fallback image generation: OpenAI GPT Image 1.5
- Vision evaluator: OpenAI GPT-5.6 Terra
- Object storage: Backblaze B2 through genblaze-s3 0.3.5
- Public deterministic demo: Genblaze MockProvider

## Current release gates

The local demo, hostile suite, browser QA, container QA, paid OpenAI generation, real B2
round-trip, verified approval, and empty-local-state B2 recovery have receipts in
`../../../reports/qa/RUNTIME-RECEIPTS.md` and
`../../../reports/integrations/PROOFFORGE-LIVE-RECEIPT.md`. Durable public hosting, repository
publication, final video publication, rule acceptance, and final Devpost submission remain.
