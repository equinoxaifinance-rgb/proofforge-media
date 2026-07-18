# Cloudflare Containers deployment

This wrapper routes all public traffic to one named ProofForge container. It intentionally
sets `max_instances` to one to match the application's documented single-replica topology.
The container filesystem is ephemeral on Cloudflare; Backblaze B2 remains the durable store
for verified live media and manifests. Public demo runs are short-lived and do not promise
cross-restart retention.

Cloudflare Containers require the Workers Paid plan. Do not upgrade or deploy without the
account owner's explicit approval. Once approved, set each sensitive value with
`wrangler secret put`; never add values to `wrangler.jsonc` or a committed environment file.

```powershell
npm ci
npm run check
npx wrangler secret put PROOFFORGE_ENABLE_LIVE
npx wrangler secret put PROOFFORGE_OPERATOR_TOKEN
npx wrangler secret put PROOFFORGE_SIGNING_KEY
npx wrangler secret put OPENAI_API_KEY
npx wrangler secret put B2_KEY_ID
npx wrangler secret put B2_APP_KEY
npx wrangler secret put B2_BUCKET
npx wrangler secret put B2_REGION
npm run deploy
```

The deployment must then pass public health, demo pipeline, asset, manifest, evidence-bundle,
restart/cold-start, security-header, and mobile-browser checks before it is a judge URL.
