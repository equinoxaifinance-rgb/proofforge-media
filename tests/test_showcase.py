import copy
import hashlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import BinaryIO

import pytest
from fastapi.testclient import TestClient
from genblaze_core.storage import StorageBackend

from proofforge.main import create_app
from proofforge.showcase import LATEST_KEY, B2ShowcaseStore


class MemoryObjectStore(StorageBackend):
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(
        self,
        key: str,
        data: bytes | BinaryIO,
        *,
        content_type: str | None = None,
        metadata: dict[str, str] | None = None,
        extra_args: dict | None = None,
    ) -> str:
        del content_type, metadata, extra_args
        self.objects[key] = bytes(data) if isinstance(data, bytes) else data.read()
        return key

    def get(self, key: str) -> bytes:
        return self.objects[key]

    def exists(self, key: str) -> bool:
        return key in self.objects

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)

    def get_url(self, key: str, *, expires_in: int = 3600) -> str:
        del expires_in
        return self.get_durable_url(key)

    def get_durable_url(self, key: str) -> str:
        return f"https://objects.test/{key}"

    def key_from_url(self, url: str) -> str | None:
        return url.removeprefix("https://objects.test/")


def approved_run(asset_bytes: bytes) -> dict:
    asset_hash = hashlib.sha256(asset_bytes).hexdigest()
    return {
        "id": "c2ab959e-ecd7-4b90-b152-9f1f23bc82b6",
        "mode": "live",
        "status": "completed",
        "brief": {"campaign_name": "ProofForge"},
        "result": {
            "models": ["gpt-image-2", "gpt-5.6-terra evaluator"],
            "asset": {
                "sha256": asset_hash,
                "bytes": len(asset_bytes),
                "mediaType": "image/png",
                "localName": f"{asset_hash}.png",
            },
            "manifest": {"canonicalHash": "d" * 64},
            "orchestration": {
                "engine": "Genblaze AgentLoop",
                "iterations": [{"index": 0, "score": 0.98, "passed": True}],
                "passed": True,
            },
            "storage": {
                "b2Persisted": True,
                "objectKey": f"proofforge/assets/{asset_hash}.png",
            },
            "checks": {
                "assetHashVerified": True,
                "allIterationHashesVerified": True,
                "storedManifestHashVerified": True,
                "qualityThresholdMet": True,
            },
        },
        "reviews": [
            {
                "approved": True,
                "verified": True,
                "reviewer": "Operator",
                "notes": "Inspected and approved",
                "createdAt": "2026-07-18T05:10:00+00:00",
            }
        ],
        "createdAt": "2026-07-18T05:05:59+00:00",
        "updatedAt": "2026-07-18T05:10:00+00:00",
    }


def test_b2_showcase_round_trip_and_container_restart_recovery(tmp_path) -> None:
    asset_bytes = b"verified-proof-forge-png"
    backend = MemoryObjectStore()
    run = approved_run(asset_bytes)
    backend.objects[run["result"]["storage"]["objectKey"]] = asset_bytes
    showcase_store = B2ShowcaseStore(backend)

    published = showcase_store.publish(run)
    assert published["id"] == run["id"]
    assert showcase_store.fetch_asset(published) == asset_bytes

    # A fresh app has an empty SQLite DB and no local artifact. It must recover
    # both the public receipt and verified media bytes from B2.
    with TestClient(create_app(tmp_path, showcase_store=showcase_store)) as client:
        assert client.get("/api/capabilities").json()["showcaseReady"] is True
        response = client.get("/api/showcase")
        assert response.status_code == 200
        assert response.json()["runId"] == run["id"]
        asset = client.get("/api/showcase/asset")
        assert asset.status_code == 200
        assert asset.content == asset_bytes


def test_b2_showcase_fails_closed_on_receipt_or_asset_tampering() -> None:
    asset_bytes = b"verified-proof-forge-png"
    backend = MemoryObjectStore()
    run = approved_run(asset_bytes)
    asset_key = run["result"]["storage"]["objectKey"]
    backend.objects[asset_key] = asset_bytes
    showcase_store = B2ShowcaseStore(backend)
    showcase_store.publish(run)

    receipt_key = f"proofforge/showcase/runs/{run['id']}.json"
    backend.objects[receipt_key] += b"tamper"
    with pytest.raises(RuntimeError, match="receipt hash verification failed"):
        showcase_store.load()

    showcase_store.publish(run)
    backend.objects[asset_key] = b"tampered-media"
    with pytest.raises(RuntimeError, match="asset (size|hash) verification failed"):
        showcase_store.fetch_asset(showcase_store.load())

    assert LATEST_KEY in backend.objects


def test_concurrent_operator_publications_are_serialized() -> None:
    class ObservedObjectStore(MemoryObjectStore):
        def __init__(self) -> None:
            super().__init__()
            self.guard = threading.Lock()
            self.active_pointer_writes = 0
            self.max_active_pointer_writes = 0

        def put(self, key, data, **kwargs):
            if key != LATEST_KEY:
                return super().put(key, data, **kwargs)
            with self.guard:
                self.active_pointer_writes += 1
                self.max_active_pointer_writes = max(
                    self.max_active_pointer_writes,
                    self.active_pointer_writes,
                )
            try:
                time.sleep(0.05)
                return super().put(key, data, **kwargs)
            finally:
                with self.guard:
                    self.active_pointer_writes -= 1

    backend = ObservedObjectStore()
    first_asset = b"first-approved-asset"
    second_asset = b"second-approved-asset"
    first = approved_run(first_asset)
    second = copy.deepcopy(approved_run(second_asset))
    second["id"] = "e3aed0e7-16c6-4c18-86ab-7e8f8402e435"
    for run, asset in ((first, first_asset), (second, second_asset)):
        backend.objects[run["result"]["storage"]["objectKey"]] = asset

    store = B2ShowcaseStore(backend)
    with ThreadPoolExecutor(max_workers=2) as pool:
        published = list(pool.map(store.publish, (first, second)))

    assert {run["id"] for run in published} == {first["id"], second["id"]}
    assert backend.max_active_pointer_writes == 1
    assert store.load()["id"] in {first["id"], second["id"]}
