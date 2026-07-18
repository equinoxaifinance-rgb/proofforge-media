# ProofForge live integration receipt — 2026-07-18

This is a sanitized receipt. It contains no OpenAI key, B2 application key, operator token,
signing key, or presigned URL.

## Final approved showcase

- Application run: `c2ab959e-ecd7-4b90-b152-9f1f23bc82b6`
- Genblaze run: `e3aed0e7-16c6-4c18-86ab-7e8f8402e435`
- Runtime: `2026-07-18T05:05:59.890657Z` to `2026-07-18T05:08:45.999327Z`
- Models: GPT Image 2 with GPT Image 1.5 fallback; GPT-5.6 Terra evaluator
- Quality gate: `0.95`; observed evaluator score: `0.98`
- Evaluator response: `resp_06710f41e5129cba016a5b0a55f33881a18af87ed75ae497c5`
- Evaluator usage: 1,606 input, 238 output, 107 reasoning tokens
- Forbidden terms: none; prompt injection: false
- Generation price: unavailable from the Genblaze provider registry. The receipt records
  `null`, not a false zero-dollar claim.

The native 1024×1024 PNG was visually inspected after generation. It contains a prominent
ProofForge name, readable primary hierarchy, the “Every Asset Needs an Alibi” message,
evidence-trail/revision/verification concepts, and no prohibited sponsor logos. The evaluator's
only residual note was that small supporting copy could be enlarged slightly.

## B2 integrity chain

- Asset bytes: `1,213,775`
- Asset SHA-256: `6d899e872d4ca78dea258dbf686f615303b9b2d4eff2522f39338128d1c0417b`
- Asset key: `proofforge/assets/6d/89/6d899e872d4ca78dea258dbf686f615303b9b2d4eff2522f39338128d1c0417b.png`
- Manifest key: `proofforge/manifests/e3aed0e7-16c6-4c18-86ab-7e8f8402e435.json`
- Manifest canonical hash:
  `d780339a7a5db5b7493eea0b7c193b84b7692da41dc7be03bcf53183b4ca1c4d`
- Asset fetch-back hash: verified
- Stored manifest hash: verified
- Every-iteration fetch-back hashes: verified
- Verified operator approval recorded at `2026-07-18T05:12:44.469749Z`
- B2 application receipt fetch-back: byte-identical
- Hash-linked B2 `latest` pointer fetch-back: verified

## Real empty-state restart recovery

A second application process started with an empty data directory, zero SQLite runs, and no
local artifact. Using only the same restricted B2 credentials, it reported the showcase ready,
recovered run `c2ab959e-ecd7-4b90-b152-9f1f23bc82b6`, and streamed 1,213,775 bytes. An
independent SHA-256 calculation returned the expected
`6d899e872d4ca78dea258dbf686f615303b9b2d4eff2522f39338128d1c0417b`.

This demonstrates that an approved judge showcase survives container-local database and disk
loss. The B2 bucket remains private; the application is the hash-verifying read boundary.

## Failure history and remediation

The successful result was not produced by deleting adverse evidence:

1. The first paid run exposed Genblaze's 60-second image timeout and an application error that
   masked it as `IndexError`. ProofForge now uses a bounded 600-second image timeout and
   preserves provider failures. A regression test forces the timeout path and asserts that the
   root cause survives.
2. The retry generated and evaluated an image, then the sink rejected a Windows
   `file://C%3A%5C...` URI/out-of-allowlist source. ProofForge now stages generation under the
   OS temp allowlist, validates the resolved path, and canonicalizes it to `file:///C:/...`
   without weakening Genblaze's file-read security boundary.
3. Before another paid run, the exact 1,095,512-byte failed-run PNG traversed the real
   Genblaze→B2→fetch-back→hash→delete preflight. SHA-256
   `084f877751248e9ec4a263337d8e3f53ccd9249bfb3afa8fdbcba05dec1aa5d2` matched and the test
   object was confirmed absent after deletion.
4. The remediated run completed at 0.92, but its evaluator identified missing ProofForge
   attribution and small copy. It was deliberately not approved. The final brief raised the
   gate to 0.95 and produced the approved 0.98 asset above.

## Executed local checks

- Pytest: 31/31 passed
- Ruff: `All checks passed!`
- Tampered B2 receipt: fails closed in tests
- Tampered B2 media: fails closed in tests
- Empty-local-state B2 recovery: passes in tests and against the real bucket

Machine-readable companion:
`reports/integrations/proofforge-live-2026-07-18.json`.

## Remaining blind spots

- The durable judge host is
  `https://proofforge-media.equinoxaifinance.workers.dev`; deployment version
  `8815bef5-6e6a-4496-8182-0f243c30c22d` passed authenticated/unauthenticated API probes,
  exact showcase-byte readback, disabled-live-mode checks, malformed/oversized/injection
  rejection, and Lighthouse 1.0/1.0/1.0/1.0. See
  `reports/qa/proofforge-cloudflare-deployment-8815bef5-2026-07-18.json`.
- The approved live run passed on its first 0.98 iteration, so the real provider did not need a
  revision. The deterministic public demo separately executes a failing first iteration and a
  passing revision; this is not represented as proof of a paid-provider revision.
- Genblaze did not expose an image price for this model, so generation cost remains unknown.
- The completed Lighthouse run is a single controlled mobile-profile measurement, not a
  long-duration uptime or global load guarantee.
