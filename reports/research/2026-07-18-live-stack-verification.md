# Live stack verification — 2026-07-18

Checked against current primary sources before the release build:

- Genblaze `0.4.3` is the latest umbrella release on PyPI (released 2026-07-17).
- Genblaze Core `0.3.6`, OpenAI adapter `0.3.2`, and S3 adapter `0.3.5` are the
  versions resolved in the hashed lock. The installed runtime contract was inspected directly,
  then exercised by the every-iteration object-store round-trip test.
- The official Genblaze package description identifies Backblaze B2/S3 durable storage,
  SHA-256 provenance manifests, `AgentLoop`, `ObjectStorageSink`, and content-addressable keys
  as supported first-class paths.
- Backblaze's official S3-compatible API guidance requires a non-master Application Key ID,
  Application Key, bucket, endpoint/region, and SigV4. Bucket-restricted keys may also need
  `listAllBucketNames` for SDK compatibility. ProofForge uses a bucket-scoped application key
  and does not request or store the master key.
- B2 buckets are versioned by default. ProofForge therefore uses immutable run manifests and
  SHA-256 content-addressed asset keys, reads each stored manifest, fetches each asset back,
  and compares every fetched digest before setting `b2Persisted=true`.

Primary sources:

- https://pypi.org/project/genblaze/
- https://pypi.org/project/genblaze-core/
- https://pypi.org/project/genblaze-openai/
- https://pypi.org/project/genblaze-s3/
- https://github.com/backblaze-labs/genblaze
- https://help.backblaze.com/hc/en-us/articles/360047425453-Getting-Started-with-the-S3-Compatible-API
- https://postman.backblaze.com/
- https://www.backblaze.com/docs/cloud-storage-use-backblaze-b2-terraform
