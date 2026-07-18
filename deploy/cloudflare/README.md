# Cloudflare Containers deployment

This wrapper routes traffic to one named ProofForge container and puts the live judge lane
behind the `JudgeLedger` Durable Object. The container filesystem is ephemeral on Cloudflare;
Backblaze B2 is the durable store for verified live media and manifests. Judge session hashes,
login throttles, idempotent reservations, one-active-run state, and quotas survive container
restarts in the ledger.

Cloudflare Containers require the Workers Paid plan. Do not upgrade or deploy without the
account owner's explicit approval. Sensitive values belong in Wrangler secrets only; never add
them to `wrangler.jsonc`, a committed environment file, or logs.

```powershell
npm ci
npm run check
npx wrangler secret put PROOFFORGE_ENABLE_LIVE
npx wrangler secret put PROOFFORGE_ENABLE_JUDGE_SANDBOX
npx wrangler secret put PROOFFORGE_OPERATOR_TOKEN
npx wrangler secret put PROOFFORGE_SIGNING_KEY
npx wrangler secret put PROOFFORGE_JUDGE_CAPABILITY_KEY
npx wrangler secret put PROOFFORGE_JUDGE_USERNAME
npx wrangler secret put PROOFFORGE_JUDGE_PASSWORD
npx wrangler secret put OPENAI_API_KEY
npx wrangler secret put B2_KEY_ID
npx wrangler secret put B2_APP_KEY
npx wrangler secret put B2_BUCKET
npx wrangler secret put B2_REGION
npm run deploy
```

The Worker checks the temporary judge username/password at the edge and stores only a SHA-256
session hash in the Durable Object. It enforces five failed logins per IP per 15 minutes, a
short session TTL, three runs per session, six runs per ledger lifetime, one active run, and
idempotent replay protection. The operator credential is injected only on the internal
container hop and is never returned to the browser. These are application spend guards; a
provider-side dollar hard stop is not claimed because provider budgets and pricing must be
verified separately.

`PROOFFORGE_ENABLE_LIVE` and `PROOFFORGE_ENABLE_JUDGE_SANDBOX` must be `true` only on the
isolated judge deployment after the full release gate, public login, live generation, B2
fetch-back, restart, replay, concurrency, and failure-path checks pass. The route remains
fail-closed for live requests without a valid judge session.
