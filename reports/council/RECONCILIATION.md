# Cross-family council reconciliation — 2026-07-18

The council's job is to attack a checkable surface, not issue taste-based scores. A critique
counts only when it contains exact evidence, deterministic reproduction, impact, a concrete
improvement, and an exact verification. Raw outputs are preserved before validation. Agreement
is not proof; accepted findings must become code plus an executed check.

## Closure-audit raw receipts

| Model family | Raw report | SHA-256 | Bytes |
| --- | --- | --- | ---: |
| Anthropic Claude Sonnet 4.6 | `post-verification/anthropic-claude-sonnet-4-6.raw.md` | `f65f267abf6722edf4c3a0fecc51b6f1929c2ba1fe0ca04c0a109232fab42d23` | 16,136 |
| Google Gemini 3.1 Pro Preview | `post-verification/google-gemini-3.1-pro-preview.raw.md` | `bf90fca58b2b48c48d0f77a1df2391944f26d4647a2a3ec666dbc2e35a173d96` | 1,957 |
| DeepSeek V4 Pro | `post-verification/deepseek-v4-pro.raw.md` | `ea204e564b17b9f9e4d66fa8268f86f0af7cc8f3cb2c212ff1391337eb741b9e` | 5,752 |
| xAI Grok 4.3 | `post-verification/xai-grok-4.3.raw.md` | `af9d503a8e9632dd38a5f5ba6aa86e051c34bd8ff4abc272458dc5063a659761` | 3,870 |

The harness retained and rejected malformed reports rather than silently counting them. DeepSeek
initially failed transport/format validation; ASCII-safe UTF-8 transport and a Unicode-tolerant
section validator were added, then the family completed. Anthropic and Grok were likewise rerun
after their substantive reports failed overly narrow section-format regexes.

## Accepted findings and receipts

| Finding | Repair | Executed verification |
| --- | --- | --- |
| Bounded asset reads had a size-check/read TOCTOU window. | Replaced stat-then-read with one incrementally bounded file handle. | Oversize-at-read regression; ProofForge suite green. |
| Pruning could race a deferred asset response. | Added one artifact `RLock`; read and hash bytes before returning a response; pruning holds the same lock through row and file deletion. | Forced prune-vs-read interleaving proves pruning blocks until the read finishes. |
| Demo and live canonical artifact publication were non-atomic. | Added same-directory `mkstemp` + flush + `fsync` + `os.replace`; both paths use it. | Replacement-boundary test proves old-or-complete bytes only and no temp leak; mock live contract passes. |
| Demo publication could still race pruning before its completed DB receipt existed. | `_run_demo` plus `complete_run` now share the pruning lock as one critical section. | Forced write/pause/prune interleaving leaves every retained completed run's asset present. |
| Interrupted-run recovery lacked bounded retry. | Added logged exponential retry around recovery. | Two injected SQLite failures followed by success; health check passes. |
| Generation prompts relied too heavily on a short injection blacklist. | Delimited JSON brief/evaluator data, explicit untrusted-data authority boundary, and broader injection-pattern rejection. | Prompt-boundary test and three injection variants pass; strict evaluator JSON remains enabled. |
| Evidence archive names lacked an explicit allowlist. | Require exactly a 64-hex content hash plus a short lowercase extension before any read/export. | Nested and traversal metadata are rejected with 409 for both asset and zip paths. |
| Failed live generation left provider staging files. | Wrapped the live pipeline in unconditional staging-directory cleanup. | Provider-timeout regression proves the root cause is preserved and the run directory is absent. |
| Screen-reader state changes were incomplete. | Persistent ContestPilot live region, disclosure `aria-controls`, ProofForge busy guard without focus removal, live download status, and assertive pipeline-error region. | Production SSR assertions, ProofForge static assertion, build/lint, and runtime browser checks. |
| Concurrent operator publications could make one fetch-back validate another publication's pointer. | Serialized pointer PUT plus fetch-back on the singleton showcase store. | Forced two-thread publication test proves one active pointer write and both callers receive their own verified run. |
| ContestPilot receipt links shared a generic accessible name. | Added receipt labels to each link's accessible name. | Production SSR requires a contextual `aria-label`; build and lint pass. |

## Rejected, scoped, or deferred critiques

| Critique | Decision and evidence |
| --- | --- |
| A Python `RLock` does not make SQLite/files safe across multiple replicas. | Correct in general, outside the declared topology. Docker starts one Uvicorn process; the README forbids shared-volume multi-replica use; the Cloudflare wrapper uses one named container with `max_instances: 1`. This remains an explicit limitation, not a hidden production claim. |
| Quality-gate failure leaves B2 iteration orphans. | Rejected: the cited `if not output.passed: raise` occurs before `S3StorageBackend` and `ObjectStorageSink` creation. Temp staging leakage was real and fixed separately. |
| Arbitrary `brand_colors` can inject SVG attributes. | Rejected: `CampaignBrief.validate_colors` requires exactly `#RRGGBB` and parses the hex digits before `demo_svg` runs. The report's malicious value cannot construct a brief. |
| Two API requests schedule duplicate `engine.process` calls and silently strand a run. | Rejected for the shipped route: background work is scheduled only when `create_or_get` created the row or a failed row was explicitly requeued. Duplicate in-progress requests receive the existing run and do not schedule a second task. |
| Stale rate-limit clients block the 4,097th client. | Rejected: the new-client branch removes every expired deque before checking the 4,096-client cap—the reproduction reverses the cited execution order. |
| Proxy-aware rate limiting is universally broken. | Deployment-dependent and still yellow until a durable host is chosen. Uvicorn 0.51 has proxy-header support, but trusted-peer configuration must match the final host; blindly trusting public `X-Forwarded-For` would create a bypass. The final-host adversarial test must prove distinct trusted client buckets. |
| Post-generation B2 verification is unbounded. | Partly scoped. The shipped server has no Gunicorn worker timeout assumed by the reproduction, and the observed SDK config is 30-second connect, 300-second read, adaptive retry with four total attempts. Long latency is still an operational risk to test on the durable host. Interrupted runs recover to failed on restart. |
| ProofForge preview/showcase images lack alt text after JavaScript assigns `src`. | Rejected: both `<img>` elements already have descriptive static `alt` attributes in `index.html`; assigning `src` does not remove them. |
| A transient read failure after a B2 pointer PUT permanently corrupts the pointer. | Rejected: B2 object PUT is whole-object and the newly written pointer references a receipt that was already byte-verified. A transient GET can make that request return 502, but the next load reads the valid new pointer. Concurrent operator PUT/fetch-back ambiguity was a separate real issue and is now serialized. |

## External gates the council correctly kept yellow

- OpenAI Build Week still needs the real Codex `/feedback` Session ID, owner conflict-exclusion
  attestation, public repository access, final public judge video, and Devpost rule acceptance.
- ProofForge still needs a durable judge URL. Its Quick Tunnel is deliberately labeled temporary.
- Final videos remain last because the approved live B2 showcase and current UI must be the footage.
- No model claims or guarantees a contest win. The receipts support quality and compliance claims,
  not the judges' future decision.

## Current machine closure

The current canonical machine closure is generated by `npm run release:verify` and stored in
`reports/qa/release-verify.receipt.json` beside its hash-bound transcript. The same two files are
embedded byte-for-byte in both generated release repositories after the gate completes.
