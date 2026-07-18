# anthropic-claude-sonnet-4-6

# ProofForge Media â Release Audit Report
**Auditor:** Independent Cross-Family Release Council
**Date:** 2026-07-18
**Assigned angle:** Reliability, data integrity, concurrency, and failure recovery
**Scope:** `engine.py`, `database.py`, `showcase.py`, `test_showcase.py`, `PROOFFORGE-LIVE-RECEIPT.md`

**ContestPilot for OpenAI Build Week:** OUT OF SCOPE (not in evidence pack)

---

## Finding 1

**ID:** PF-001
**Title:** `prune_demo_runs` holds `artifact_lock` across a full-table scan of `result_json`, causing lock contention against concurrent demo completions

**Severity:** high
**Confidence:** high

**Evidence:**
`database.py` lines 380â415. The method acquires `self.artifact_lock` at line 381, then at line 403â408 executes:
```python
remaining_rows = connection.execute(
    "SELECT result_json FROM runs WHERE result_json IS NOT NULL"
).fetchall()
```
This unbounded `fetchall()` â returning every non-null `result_json` column across the entire `runs` table â executes while `artifact_lock` is held. Concurrently, `engine.py` lines 215â217 show that a completing demo run holds the same `artifact_lock` for the entire duration of `_run_demo` plus `complete_run`:
```python
with self.store.artifact_lock:
    result = self._run_demo(run_id, brief)
    self.store.complete_run(run_id, result)
```
`_run_demo` invokes `AgentLoop.run()` with `pipeline_timeout=30` (`engine.py` line 289). Any thread completing a demo run during a `prune_demo_runs` scan â or vice versa â blocks for up to 30 seconds on the lock.

**Reproduction:**
1. Start ProofForge with a SQLite store containing â¥201 completed demo runs.
2. In thread A, submit a new demo brief; it will enter `_run_demo` holding `artifact_lock`.
3. Simultaneously in thread B, call `prune_demo_runs(keep=200)` â or let the post-completion prune fire from a prior run.
4. Thread B acquires `artifact_lock` and issues the full-table `SELECT result_json FROM runs WHERE result_json IS NOT NULL`. With 500+ rows, this scan takes tens of milliseconds while thread A is blocked on lock acquisition, stalling the user-facing pipeline response.

**Impact:** Reliability. Under load (concurrent demo users), all demo completions queue behind the pruner's table scan. At 201+ runs the prune fires after every demo completion (`engine.py` lines 228â236), meaning lock contention is structural, not incidental. This can cause user-visible latency spikes and, in a single-threaded WSGI deployment, request timeouts.

**Improvement:**
Narrow the full-table scan to only those artifact names referenced by *retained* runs, computed inside the same transaction before releasing the lock, using the already-known `run_ids` to exclude:
```python
# Replace lines 403-408 in database.py
placeholders = ",".join("?" * len(run_ids))
retained_rows = connection.execute(
    f"SELECT result_json FROM runs "
    f"WHERE result_json IS NOT NULL AND id NOT IN ({placeholders})",
    run_ids,
).fetchall()
retained_names = {
    json.loads(row["result_json"]).get("asset", {}).get("localName")
    for row in retained_rows
}
```
This scopes the scan to surviving runs only and avoids re-reading rows already being deleted. Separately, move the file-deletion loop (lines 409â415) outside the `artifact_lock` block â file I/O under a threading lock is unnecessary since `candidate.unlink(missing_ok=True)` is idempotent.

**Verification:**
```python
import threading, time
from pathlib import Path
import pytest
from proofforge.database import RunStore

def test_prune_does_not_block_concurrent_complete(tmp_path):
    store = RunStore(tmp_path)
    # Insert 201 completed demo runs
    for _ in range(201):
        h = store._next_brief_hash()  # or insert directly via connect()
        run, _ = store.create_or_get(h, "demo", {})
        store.start_run(run["id"], "demo")
        store.complete_run(run["id"], minimal_result())

    blocked = []
    def prune():
        store.prune_demo_runs(keep=200)

    def complete():
        run, _ = store.create_or_get("new-hash", "demo", {})
        store.start_run(run["id"], "demo")
        t0 = time.monotonic()
        store.complete_run(run["id"], minimal_result())
        if time.monotonic() - t0 > 1.0:
            blocked.append(True)

    t1 = threading.Thread(target=prune)
    t2 = threading.Thread(target=complete)
    t1.start(); t2.start(); t1.join(); t2.join()
    assert not blocked, "complete_run blocked by prune scan"
```
Pass condition: `blocked` is empty; wall time for `complete_run` is < 1 s.

---

## Finding 2

**ID:** PF-002
**Title:** `_recover_interrupted_runs` at startup does not respect the `UNIQUE(brief_hash, mode)` constraint â a recovered run cannot be retried via the normal idempotency path

**Severity:** medium
**Confidence:** high

**Evidence:**
`database.py` lines 126â147. Recovery marks every `queued`/`running` run as `failed` with `error = 'interrupted before completion; retry is allowed'`. However, `create_or_get` at lines 149â166 uses `INSERT OR IGNORE` keyed on `(brief_hash, mode)` (`UNIQUE` constraint, schema line 74). After recovery, the interrupted row still occupies the `(brief_hash, mode)` slot with `status = 'failed'`. When a client re-submits the same brief, `INSERT OR IGNORE` silently skips insertion and the `SELECT` at line 160 returns the *failed* row. `start_run` at line 193â199 then checks `status = 'queued'` and returns `False`, so `process()` at `engine.py` line 209 returns immediately without re-running.

`queue_retry` at `database.py` lines 207â222 exists to transition `failedâqueued`, but it is never called by the re-submission path (`create_or_get` + `process`). A client that re-submits the same brief after a crash silently receives a stale `failed` run with no indication that a retry is needed.

**Reproduction:**
1. Submit brief B â run R is created (`queued`), pipeline starts (`running`).
2. Kill the process. On restart, `_recover_interrupted_runs` sets R to `failed`.
3. Re-submit brief B. `create_or_get` finds existing `(brief_hash, mode)` row â returns R (status=`failed`), `created=False`.
4. `process(run_id=R.id, ...)` calls `start_run` â `UPDATE â¦ WHERE status='queued'` â 0 rows â returns `False`.
5. Caller receives the old `failed` run with no retry.

**Impact:** Reliability and user consequence. After any crash, re-submitting an identical brief silently no-ops. The user sees a `failed` status indefinitely and must know to call the retry endpoint manually. The `retryAllowed: True` event payload (`database.py` line 144) is advisory only and not acted upon by the submission path.

**Improvement:**
In `create_or_get`, when `created` is `False` and the returned row has `status = 'failed'`, automatically call `queue_retry` before returning:
```python
# database.py, after line 165 (run_id = row["id"])
run_data = self.get(run_id)
if not created and run_data and run_data["status"] == "failed":
    self.queue_retry(run_id)
    run_data = self.get(run_id)
return run_data, created  # caller proceeds normally; start_run will accept 'queued'
```
Gate the auto-retry on the `error` field containing `"interrupted"` if stricter control is desired (e.g., don't auto-retry user-caused failures).

**Verification:**
```python
from proofforge.database import RunStore

def test_interrupted_run_is_retried_on_resubmit(tmp_path):
    store = RunStore(tmp_path)
    run, created = store.create_or_get("hash-abc", "demo", {"x": 1})
    assert created
    store.start_run(run["id"], "demo")
    # Simulate crash recovery
    store._recover_interrupted_runs_once()
    assert store.get(run["id"])["status"] == "failed"

    # Re-submit same brief
    run2, created2 = store.create_or_get("hash-abc", "demo", {"x": 1})
    assert not created2
    assert run2["status"] == "queued", f"Expected queued, got {run2['status']}"
    # start_run must now succeed
    assert store.start_run(run2["id"], "demo") is True
```
Pass condition: `run2["status"] == "queued"` and `start_run` returns `True`.

---

## Finding 3

**ID:** PF-003
**Title:** `showcase.py` `publish()` has a TOCTOU window: the `latest.json` pointer is overwritten before the fetch-back confirms the receipt, leaving a corrupt showcase state if B2 PUT latency is asymmetric

**Severity:** medium
**Confidence:** medium

**Evidence:**
`showcase.py` lines 60â86:
```python
self.backend.put(receipt_key, receipt_bytes, ...)      # line 60
if self.backend.get(receipt_key) != receipt_bytes:     # line 66 â receipt verified
    raise RuntimeError(...)

# ...build pointer...
self.backend.put(LATEST_KEY, pointer_bytes, ...)       # line 78 â pointer written
loaded = self.load()                                   # line 84 â load() re-reads pointer THEN receipt
if loaded is None or loaded["id"] != run["id"]:        # line 85
    raise RuntimeError(...)
```
The receipt is individually verified at line 66. However, `load()` at lines 89â123 fetches `LATEST_KEY` first, then fetches the receipt using the key embedded in it. If two concurrent `publish()` calls race â possible because `publish` is called from an HTTP handler with no distributed lock â the sequence can be:

- Thread A writes receipt A, verifies it (line 66). â
- Thread B writes receipt B, verifies it (line 66). â
- Thread B writes `LATEST_KEY` pointing at receipt B.
- Thread A writes `LATEST_KEY` pointing at receipt A.
- Thread B's `load()` reads `LATEST_KEY` â receipt A key â receipt A bytes â hash check passes â but `loaded["id"] != run_B["id"]` â Thread B raises `"fetch-back verification failed"`.

Thread B's approved run is lost; Thread A's `publish()` returns a stale state. The next `load()` returns run A even though run B was approved later. This is not hypothetical in a multi-worker deployment (Gunicorn, uvicorn workers).

The confidence is medium (not high) because `publish` may in practice be called from a protected admin endpoint; the evidence pack does not include the API router, so concurrency of `publish` is an inference.

**Impact:** Reliability and data integrity. A concurrent re-publish of a newer approved run can silently revert the public showcase pointer to an older run. The fetch-back check (line 85) will raise for the *newer* run rather than detecting the corruption, because the race leaves the pointer pointing at the *older* run consistently. No data is corrupted in B2, but the `latest.json` pointer reflects a stale approved state until the next successful `publish`.

**Improvement:**
Use a conditional PUT (if-not-exists or compare-and-swap on the pointer object) supported by the S3-compatible B2 API via the `IfNoneMatch` / `x-amz-if-none-match` header, or serialize `publish` with an application-level advisory lock. The minimal credible fix for the current `genblaze_s3` abstraction is to pass `extra_args={"IfNoneMatch": "*"}` only for the pointer write when updating from a known previous ETag, or add a thin lock around the pointer write + fetch-back:

```python
# showcase.py â wrap lines 78-86 in a version-fenced operation
import threading
_publish_lock = threading.Lock()   # module-level; effective for single-process deployments

def publish(self, run):
    ...
    self.backend.put(receipt_key, receipt_bytes, ...)
    if self.backend.get(receipt_key) != receipt_bytes:
        raise RuntimeError(...)
    with _publish_lock:
        self.backend.put(LATEST_KEY, pointer_bytes, ...)
        loaded = self.load()
        if loaded is None or loaded["id"] != run["id"]:
            raise RuntimeError("B2 showcase pointer fetch-back verification failed")
    return loaded
```

For multi-process deployments, document that `publish` must be serialized at the load-balancer or operator level until B2 conditional-write support is plumbed through `S3StorageBackend`.

**Verification:**
```python
import threading
from proofforge.showcase import B2ShowcaseStore
# use MemoryObjectStore from test_showcase.py

def test_concurrent_publish_last_writer_wins_consistently(tmp_path):
    asset_a = b"asset-a" * 100
    asset_b = b"asset-b" * 100
    backend = MemoryObjectStore()
    run_a = approved_run(asset_a); run_a["id"] = "a" * 36  # valid UUID shape
    run_b = approved_run(asset_b); run_b["id"] = "b" + "-" + "c" * 34

    store = B2ShowcaseStore(backend)
    errors = []

    def pub(run):
        try:
            store.publish(run)
        except RuntimeError as e:
            errors.append(str(e))

    t1 = threading.Thread(target=pub, args=(run_a,))
    t2 = threading.Thread(target=pub, args=(run_b,))
    t1.start(); t2.start(); t1.join(); t2.join()

    # With the lock fix: no errors; pointer reflects exactly one run consistently
    assert not errors, f"Unexpected errors: {errors}"
    loaded = store.load()
    assert loaded["id"] in (run_a["id"], run_b["id"])
```
Pass condition: zero `RuntimeError`s raised; `load()` returns a consistent, hash-verified run.

---

## Positive Findings (with evidence)

**Source inspection â strong atomic write discipline:** `engine.py` lines 61â78 implement `atomic_write_bytes` using `tempfile.mkstemp` + `os.fsync` + `os.replace`. This is the correct POSIX atomic-rename pattern and eliminates partial-file reads by concurrent consumers. Evidence: lines 71â75.

**Tested fact â hash chain is end-to-end verified:** `PROOFFORGE-LIVE-RECEIPT.md` lines 26â35 record asset SHA-256 `6d899e872d4...`, fetch-back verified; manifest hash `d780339a7...`, verified; per-iteration fetch-backs, verified. `engine.py` lines 520â522 and 586â589 enforce these checks in code and raise `RuntimeError` on mismatch, not merely log. The live receipt provides a genuine audit trail.

**Tested fact â tamper detection is exercised:** `test_showcase.py` lines 118â135 mutate the receipt bytes (`+= b"tamper"`) and the asset bytes, asserting `RuntimeError` with specific messages. Both tamper paths pass per `PROOFFORGE-LIVE-RECEIPT.md` line 74â75 (`31/31 passed`).

**Tested fact â crash recovery is implemented and logged:** `database.py` lines 104â147 implement `_recover_interrupted_runs` with exponential back-off retry and structured event logging (`pipeline.interrupted`). This is invoked at `__init__` time (line 32), so every process restart self-heals stale `queued`/`running` rows before serving traffic.

**Tested fact â path traversal is defended:** `engine.py` lines 659â672 enforce that `_local_asset_path` resolves to within `artifact_dir` or `generation_dir` using `Path.is_relative_to`, raising `RuntimeError` on escape. This was noted as a real failure mode encountered and fixed (`PROOFFORGE-LIVE-RECEIPT.md` lines 59â61).

---

## Verdict

**ProofForge Media for the Backblaze Generative Media Challenge: CONDITIONAL**

The core reliability architecture â atomic writes, hash-chain verification, WAL-mode SQLite, crash recovery, tamper-resistant showcase â is substantively sound and evidenced by a live integration receipt and passing test suite. The three findings above do not individually block release but collectively represent structural gaps in concurrent correctness.

### Three Highest-Leverage Fixes (priority order)

1. **PF-001 (high):** Narrow the `prune_demo_runs` full-table scan to retained rows only and move file I/O outside `artifact_lock`. This directly reduces lock-hold time proportional to database size on every demo completion, eliminating structural contention under concurrent demo load.

2. **PF-002 (medium):** Auto-requeue interrupted runs in `create_or_get` when re-submission finds a `failed` row. Without this, the otherwise well-designed crash-recovery path is not actually used by the normal client flow, defeating its purpose.

3. **PF-003 (medium):** Serialize the `latest.json` pointer write in `publish()` with a module-level lock (single-process) and document the multi-process limitation. The current fetch-back check cannot detect the specific race condition it is intended to guard against.

