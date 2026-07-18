# Cloudflare Containers deployment

This wrapper routes all public traffic to one named ProofForge container. It intentionally
sets `max_instances` to one to match the application's documented single-replica topology.
The container filesystem is ephemeral on Cloudflare; Backblaze B2 remains the durable store
for verified live media and manifests. Public demo runs are short-lived and do not promise
cross-restart retention.

Cloudflare Containers require the Workers Paid plan. Do not upgrade or deploy without the
account owner's explicit approval. Once approved, set each sensitive value with
`wrangler secret put`; never add values to `wrangler.jsonc` or a committed environment file.
The public judge host is intentionally read-only: live generation is disabled, no OpenAI key
is installed, and its B2 key is separately limited to `listFiles`/`readFiles` for the
`proofforge/` prefix.

```powershell
npm ci
npm run check
npx wrangler secret put PROOFFORGE_ENABLE_LIVE
npx wrangler secret put PROOFFORGE_ENABLE_JUDGE_SANDBOX
npx wrangler secret put PROOFFORGE_OPERATOR_TOKEN
npx wrangler secret put PROOFFORGE_SIGNING_KEY
npx wrangler secret put PROOFFORGE_JUDGE_CAPABILITY_KEY
npx wrangler secret put B2_KEY_ID
npx wrangler secret put B2_APP_KEY
npx wrangler secret put B2_BUCKET
npx wrangler secret put B2_REGION
npm run deploy
```

Set `PROOFFORGE_ENABLE_LIVE` and `PROOFFORGE_ENABLE_JUDGE_SANDBOX` to the literal value
`false` on the public host. The operator, signing, and judge capability values must be
independent random secrets even though live generation is disabled. Do not reuse or install
the write/delete pipeline key on this host. A judge sandbox requires a separate Worker with
an externally durable redemption store; this single-replica container's disk is not sufficient
for a public one-time-token guarantee.

The deployment must then pass public health, demo pipeline, asset, manifest, evidence-bundle,
restart/cold-start, security-header, and mobile-browser checks before it is a judge URL.
