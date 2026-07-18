# Runtime QA receipts — 2026-07-18

These receipts separate executed checks from source inspection. They do not prove a contest
result or Devpost acceptance. A paid OpenAI generation and real Backblaze B2 write/recovery are
now separately receipted in `reports/integrations/PROOFFORGE-LIVE-RECEIPT.md`.

## Dependency-clean matrix

The source was copied to an isolated `<qa-cold>/devpost-autopilot-20260718-v5` directory with Git metadata, installed dependencies, Python caches, test caches, databases, and persisted ProofForge data excluded. Before installation, the copy contained 204 files, zero forbidden dependency/cache directories, and no ProofForge persisted data.

- Root: `npm ci --ignore-scripts` audited one package with zero vulnerabilities; `npm test`
  passed 15/15 tests.
- ContestPilot site: `npm ci --ignore-scripts` installed 332 packages and audited 333 with
  zero vulnerabilities; the Vinext production build passed two render/asset tests and ESLint.
- Repeated site builds produced identical hashes for every client artifact. Exactly three
  server artifacts changed: `server/index.js`, `server/ssr/vinext-server.json`, and
  `server/vinext-server.json`. Diff inspection showed only Vinext's intentionally rotated
  prerender/draft secrets, UUID build ID, and deployment version.
- ProofForge: a new Python 3.11 virtual environment installed
  `requirements-dev-lock.txt` with `--require-hashes`; pytest passed 22/22 tests in 4.00s and
  Ruff returned `All checks passed!`.
- The formerly failing concurrent legacy migration test then passed in the clean copy. In the
  source environment it also passed 30/30 consecutive eight-worker stress iterations.

## ContestPilot browser and production behavior

- Public URL: https://contestpilot-evidence-2026.therealbortega.chatgpt.site
- Production HTML and all six hydration assets returned HTTP 200. Security responses include
  CSP, `X-Content-Type-Options: nosniff`, and `Referrer-Policy`.
- A fresh public browser tab produced no console entries. After hydration, Ready showed its
  explicit empty state; Review selected Backblaze; its evidence plan expanded; Reset restored
  All and announced the reset through a status region.
- Layout measurements showed no horizontal overflow at desktop (`1308 == 1308`) or mobile
  (`375 == 375`). Receipts: `contestpilot-desktop-1308x890.jpg` and
  `contestpilot-mobile-375x812.jpg`.

## ProofForge Media runtime behavior

- Durable public URL: https://proofforge-media.equinoxaifinance.workers.dev. Cloudflare
  deployment version `8815bef5-6e6a-4496-8182-0f243c30c22d` serves the current container
  image; exact deployment, recovery, API, and Lighthouse evidence is retained in
  `reports/qa/proofforge-cloudflare-deployment-8a3da01e-2026-07-18.json`.
- Public browser QA forced a 58% first iteration and reached 95% on iteration two. Integrity
  displayed `VERIFIED`, the output was explicitly labeled local/synthetic, pipeline version
  was `2026-07-17.4`, and the browser console remained empty.
- A whitespace-only reviewer was rejected while the prior evidence and preview remained.
  With the API deliberately stopped in local QA, a new run reported
  `New action failed; prior evidence preserved.` and kept the last verified preview.
- Desktop and 375px mobile layouts had no horizontal overflow. Receipts:
  `proofforge-preview-desktop-1308x890.jpg`, `proofforge-desktop-1308x890.jpg`, and
  `proofforge-mobile-375x812.jpg`.
- A no-cache Docker build produced image digest
  `sha256:2329188e6567c857de832bd88f90ad2ca194ca23b76075358a9f0b1091fc02fb`.
  The container ran as the non-root `proofforge` user, with a read-only root filesystem, and
  reached Docker health `healthy`.
- Container API adversary: unauthenticated run/asset/review access returned 401; authorized
  asset and bundle access returned 200; the same scoped token remained valid after restart;
  one-byte asset corruption changed access to 409; retry reused the run, exposed
  `queued -> queued -> completed`, repaired the artifact, and restored verified 200 access.
- The production and dev dependency locks are hash pinned. A deliberately all-zero SHA-256
  fixture was rejected with pip's `THESE PACKAGES DO NOT MATCH THE HASHES` message.

## Current unified release and release-repository gate

- The canonical current gate is `reports/qa/release-verify.receipt.json`, produced by
  `npm run release:verify` after 20/20 bounded steps, completed at
  `2026-07-18T09:56:45.149Z` with transcript SHA-256
  `bf315e168a48c5fc30b71ec414bb4748c5af43af0d8fe00dfd461bfeb0c23422`:
  31 ContestPilot engine/control-plane tests; the ContestPilot production build and three
  render/asset/release-identity tests; ContestPilot lint and npm audit; 48 ProofForge tests
  with warnings treated as errors;
  Ruff; `pip check`; `pip-audit`; Cloudflare wrapper audit, dry-run build, and three config
  tests; clean release generation and layout verification; secret scanning; packaged import and
  packaged tests; final clean regeneration, layout re-verification, and a second secret scan;
  a pinned ProofForge container build; and the container judge-path smoke.
  The receipt binds the transcript SHA-256. The log and receipt are copied byte-identically into
  the root, ContestPilot release, and ProofForge release.
- The container smoke returned health 200, completed the demo pipeline with
  `assetHashVerified=true`, and retrieved asset, manifest, and evidence bundle (3/3).
- Clean allowlisted release directories were regenerated. A secret scanner passed both
  directories and its negative-control fixture correctly failed on a populated fake B2 key.
- Clean-room install from the generated ContestPilot directory passed 28 engine/control-plane tests,
  installed/audited 333 site packages with zero vulnerabilities, passed its production
  build and three render/asset/release-identity tests, and passed ESLint.
- The generated ProofForge directory imported successfully, passed the same 48 tests, built as
  a container, and passed the protected judge-path smoke. The packaged B2 client then loaded the
  real approved run `c2ab959e-ecd7-4b90-b152-9f1f23bc82b6`, fetched 1,213,775 media bytes, and
  independently matched SHA-256
  `6d899e872d4ca78dea258dbf686f615303b9b2d4eff2522f39338128d1c0417b` plus manifest hash
  `d780339a7a5db5b7493eea0b7c193b84b7692da41dc7be03bcf53183b4ca1c4d`.
- CycloneDX inventories were regenerated. ProofForge SBOM SHA-256:
  `3c9f777eeddf54f61ab1fe2dfe3bd7d52aec54ee1bcec54fb69d21afe662333c`;
  ContestPilot site SBOM SHA-256:
  `08c2467a6dec593b709c7efc7ba80eb8a32268782e9a75e4f4ccb7f89374faa1`;
  ProofForge Cloudflare wrapper SBOM SHA-256:
  `cb4ce065739c6ba7b43b14895272d4b95d0fb14a1964258706f1f9e73d82e266`.

## Independent council receipts

Raw reports and their SHA-256 digests are indexed in `reports/council/RECONCILIATION.md`.
The council used Anthropic Claude Sonnet 4.6, Google Gemini 3.1 Pro Preview, DeepSeek V4 Pro,
and xAI Grok 4.3. Findings are not accepted by vote: every accepted item maps to a change and
an executed check; rejected advice includes an explicit failure-mode analysis.

## Open gates and blind spots

- The approved live ProofForge run scored 0.98, persisted its asset and manifest to B2, and
  recovered from an empty local database/disk cache with a matching 1,213,775-byte SHA-256.
  Exact receipts are in `reports/integrations/PROOFFORGE-LIVE-RECEIPT.md`.
- The durable ProofForge deployment passed direct recovery after one recorded rollout
  transient, public positive and negative API checks, exact B2 showcase-byte readback, and
  Lighthouse scores of 1.0 for performance, accessibility, best practices, and SEO. The
  Lighthouse process serialized complete reports before a Windows temporary-profile cleanup
  error; the report contents and hashes were independently validated.
- Existing private videos predate the approved live B2 showcase and durable recovery layer;
  they are stale and are not final judge artifacts. Videos remain last.
- Both public MIT repositories exist. Their final post-deployment deltas must be pushed and
  verified from clean public checkouts before video production. Final Devpost receipts do not
  exist yet.
- Sponsor/judge/employment/conflict exclusions still require explicit owner attestation.
- Final rule acceptance and Devpost submission remain owner actions.
