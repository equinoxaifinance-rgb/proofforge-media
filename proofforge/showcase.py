from __future__ import annotations

import hashlib
import json
import re
import threading
from typing import Any

from genblaze_core.storage import StorageBackend

from .config import Settings
from .engine import MAX_ASSET_BYTES

LATEST_KEY = "proofforge/showcase/latest.json"
MAX_RECEIPT_BYTES = 2 * 1024 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
RUN_ID_RE = re.compile(r"^[0-9a-f-]{36}$")


def canonical_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


class B2ShowcaseStore:
    """Durable, hash-linked public showcase state stored in Backblaze B2."""

    def __init__(self, backend: StorageBackend):
        self.backend = backend
        self._publish_lock = threading.Lock()

    @classmethod
    def from_settings(cls, settings: Settings) -> B2ShowcaseStore:
        from genblaze_s3 import S3StorageBackend

        return cls(
            S3StorageBackend.for_backblaze(
                settings.b2_bucket,
                region=settings.b2_region,
                public_url_base=settings.b2_public_url_base or None,
            )
        )

    def publish(self, run: dict[str, Any]) -> dict[str, Any]:
        self._validate_run(run)
        receipt = {
            "id": run["id"],
            "mode": run["mode"],
            "status": run["status"],
            "brief": run["brief"],
            "result": run["result"],
            "reviews": run["reviews"],
            "createdAt": run["createdAt"],
            "updatedAt": run["updatedAt"],
            "error": None,
            "errorType": None,
        }
        receipt_bytes = canonical_bytes(receipt)
        if len(receipt_bytes) > MAX_RECEIPT_BYTES:
            raise RuntimeError("showcase receipt exceeds the safety limit")
        receipt_hash = hashlib.sha256(receipt_bytes).hexdigest()
        # Receipts are immutable and content-addressed. A new approval/review for the
        # same run must never overwrite the bytes referenced by the current pointer.
        receipt_key = f"proofforge/showcase/runs/{run['id']}/{receipt_hash}.json"
        pointer = {
            "schemaVersion": "2",
            "runId": run["id"],
            "receiptKey": receipt_key,
            "receiptSha256": receipt_hash,
            "assetSha256": run["result"]["asset"]["sha256"],
            "manifestCanonicalHash": run["result"]["manifest"]["canonicalHash"],
        }
        pointer_bytes = canonical_bytes(pointer)
        # Serialize the entire receipt + pointer publication. The object PUT is
        # atomic, and preserving the last verified pointer ensures a failed
        # publication cannot replace a working public showcase.
        with self._publish_lock:
            previous_pointer = (
                self.backend.get(LATEST_KEY) if self.backend.exists(LATEST_KEY) else None
            )
            try:
                self.backend.put(
                    receipt_key,
                    receipt_bytes,
                    content_type="application/json",
                    extra_args={"CacheControl": "no-store"},
                )
                if self.backend.get(receipt_key) != receipt_bytes:
                    raise RuntimeError("B2 showcase receipt fetch-back verification failed")
                self.backend.put(
                    LATEST_KEY,
                    pointer_bytes,
                    content_type="application/json",
                    extra_args={"CacheControl": "no-store"},
                )
                loaded = self.load()
                if loaded is None or loaded["id"] != run["id"]:
                    raise RuntimeError("B2 showcase pointer fetch-back verification failed")
            except Exception:
                if previous_pointer is None:
                    self.backend.delete(LATEST_KEY)
                else:
                    self.backend.put(
                        LATEST_KEY,
                        previous_pointer,
                        content_type="application/json",
                        extra_args={"CacheControl": "no-store"},
                    )
                raise
        return loaded

    def load(self) -> dict[str, Any] | None:
        if not self.backend.exists(LATEST_KEY):
            return None
        pointer_bytes = self.backend.get(LATEST_KEY)
        if len(pointer_bytes) > 16 * 1024:
            raise RuntimeError("B2 showcase pointer exceeds the safety limit")
        pointer = json.loads(pointer_bytes)
        if not isinstance(pointer, dict) or pointer.get("schemaVersion") not in {"1", "2"}:
            raise RuntimeError("B2 showcase pointer schema is invalid")
        schema_version = pointer["schemaVersion"]
        run_id = pointer.get("runId")
        receipt_key = pointer.get("receiptKey")
        receipt_hash = pointer.get("receiptSha256")
        expected_key = (
            f"proofforge/showcase/runs/{run_id}.json"
            if schema_version == "1"
            else f"proofforge/showcase/runs/{run_id}/{receipt_hash}.json"
        )
        if (
            not isinstance(run_id, str)
            or not RUN_ID_RE.fullmatch(run_id)
            or receipt_key != expected_key
            or not isinstance(receipt_hash, str)
            or not SHA256_RE.fullmatch(receipt_hash)
        ):
            raise RuntimeError("B2 showcase pointer fields are invalid")
        receipt_bytes = self.backend.get(receipt_key)
        if len(receipt_bytes) > MAX_RECEIPT_BYTES:
            raise RuntimeError("B2 showcase receipt exceeds the safety limit")
        if hashlib.sha256(receipt_bytes).hexdigest() != receipt_hash:
            raise RuntimeError("B2 showcase receipt hash verification failed")
        run = json.loads(receipt_bytes)
        self._validate_run(run)
        if run["id"] != run_id:
            raise RuntimeError("B2 showcase run identity verification failed")
        if run["result"]["asset"]["sha256"] != pointer.get("assetSha256"):
            raise RuntimeError("B2 showcase asset pointer verification failed")
        if run["result"]["manifest"]["canonicalHash"] != pointer.get("manifestCanonicalHash"):
            raise RuntimeError("B2 showcase manifest pointer verification failed")
        return run

    def fetch_asset(self, run: dict[str, Any]) -> bytes:
        self._validate_run(run)
        result = run["result"]
        object_key = result["storage"].get("objectKey")
        if not isinstance(object_key, str) or not object_key.startswith("proofforge/assets/"):
            raise RuntimeError("B2 showcase asset key is invalid")
        data = self.backend.get(object_key)
        if len(data) > MAX_ASSET_BYTES:
            raise RuntimeError("B2 showcase asset exceeds the safety limit")
        expected_size = result["asset"].get("bytes")
        expected_hash = result["asset"].get("sha256")
        if len(data) != expected_size:
            raise RuntimeError("B2 showcase asset size verification failed")
        if hashlib.sha256(data).hexdigest() != expected_hash:
            raise RuntimeError("B2 showcase asset hash verification failed")
        return data

    @staticmethod
    def _validate_run(run: Any) -> None:
        if not isinstance(run, dict):
            raise RuntimeError("showcase receipt must be an object")
        run_id = run.get("id")
        if not isinstance(run_id, str) or not RUN_ID_RE.fullmatch(run_id):
            raise RuntimeError("showcase run ID is invalid")
        if run.get("mode") != "live" or run.get("status") != "completed":
            raise RuntimeError("only completed live runs can be showcased")
        result = run.get("result")
        if not isinstance(result, dict):
            raise RuntimeError("showcase result is missing")
        checks = result.get("checks") or {}
        required_checks = (
            "assetHashVerified",
            "allIterationHashesVerified",
            "storedManifestHashVerified",
            "qualityThresholdMet",
        )
        if not all(checks.get(name) is True for name in required_checks):
            raise RuntimeError("showcase integrity checks are incomplete")
        asset_hash = (result.get("asset") or {}).get("sha256")
        manifest_hash = (result.get("manifest") or {}).get("canonicalHash")
        if not isinstance(asset_hash, str) or not SHA256_RE.fullmatch(asset_hash):
            raise RuntimeError("showcase asset hash is invalid")
        if not isinstance(manifest_hash, str) or not SHA256_RE.fullmatch(manifest_hash):
            raise RuntimeError("showcase manifest hash is invalid")
        reviews = run.get("reviews")
        if not isinstance(reviews, list) or not any(
            review.get("approved") is True and review.get("verified") is True
            for review in reviews
            if isinstance(review, dict)
        ):
            raise RuntimeError("verified operator approval is required")
