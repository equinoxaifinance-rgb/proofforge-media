from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

LOCK_RETRY_ATTEMPTS = 20
LOCK_RETRY_BASE_SECONDS = 0.025
logger = logging.getLogger("proofforge.database")


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class RunStore:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.db_path = data_dir / "proofforge.sqlite3"
        self.artifact_dir = data_dir / "artifacts"
        self.artifact_lock = threading.RLock()
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        self._initialize()
        self._recover_interrupted_runs()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        for attempt in range(LOCK_RETRY_ATTEMPTS):
            try:
                self._initialize_once()
                return
            except sqlite3.OperationalError as error:
                if "locked" not in str(error).lower() or attempt == LOCK_RETRY_ATTEMPTS - 1:
                    raise
                time.sleep(min(LOCK_RETRY_BASE_SECONDS * (2**attempt), 0.25))

    def _initialize_once(self) -> None:
        with self.connect() as connection:
            # WAL is a database-wide setting. Enabling it during first boot needs the
            # retry boundary above because concurrent processes can both observe a
            # brand-new database before either one acquires SQLite's schema lock.
            connection.execute("PRAGMA journal_mode = WAL").fetchone()
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    brief_hash TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    brief_json TEXT NOT NULL,
                    result_json TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(brief_hash, mode)
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL REFERENCES runs(id),
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS reviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL REFERENCES runs(id),
                    approved INTEGER NOT NULL,
                    reviewer TEXT NOT NULL,
                    notes TEXT NOT NULL,
                    verified INTEGER NOT NULL DEFAULT 0,
                    publication_status TEXT NOT NULL DEFAULT 'not_requested',
                    publication_error TEXT,
                    created_at TEXT NOT NULL
                );
                """
            )
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(reviews)")}
            if "verified" not in columns:
                try:
                    connection.execute(
                        "ALTER TABLE reviews ADD COLUMN verified INTEGER NOT NULL DEFAULT 0"
                    )
                except sqlite3.OperationalError as error:
                    if "duplicate column name" not in str(error).lower():
                        raise
            if "publication_status" not in columns:
                try:
                    connection.execute(
                        "ALTER TABLE reviews ADD COLUMN publication_status "
                        "TEXT NOT NULL DEFAULT 'not_requested'"
                    )
                except sqlite3.OperationalError as error:
                    if "duplicate column name" not in str(error).lower():
                        raise
            if "publication_error" not in columns:
                try:
                    connection.execute(
                        "ALTER TABLE reviews ADD COLUMN publication_error TEXT"
                    )
                except sqlite3.OperationalError as error:
                    if "duplicate column name" not in str(error).lower():
                        raise

    def _recover_interrupted_runs(self) -> None:
        for attempt in range(LOCK_RETRY_ATTEMPTS):
            try:
                self._recover_interrupted_runs_once()
                return
            except sqlite3.OperationalError as error:
                if attempt == LOCK_RETRY_ATTEMPTS - 1:
                    logger.error(
                        "interrupted-run recovery failed after %d attempts: %s",
                        LOCK_RETRY_ATTEMPTS,
                        error,
                    )
                    raise
                delay = min(LOCK_RETRY_BASE_SECONDS * (2**attempt), 0.25)
                logger.warning(
                    "interrupted-run recovery attempt %d failed; retrying in %.3fs: %s",
                    attempt + 1,
                    delay,
                    error,
                )
                time.sleep(delay)

    def _recover_interrupted_runs_once(self) -> None:
        now = utc_now()
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT id FROM runs WHERE status IN ('queued', 'running')"
            ).fetchall()
            for row in rows:
                connection.execute(
                    "UPDATE runs SET status = 'failed', result_json = NULL, "
                    "error = ?, updated_at = ? WHERE id = ?",
                    ("interrupted before completion; retry is allowed", now, row["id"]),
                )
                connection.execute(
                    "INSERT INTO events "
                    "(run_id, event_type, payload_json, created_at) VALUES (?, ?, ?, ?)",
                    (
                        row["id"],
                        "pipeline.interrupted",
                        json.dumps({"retryAllowed": True}),
                        now,
                    ),
                )

    def create_or_get(
        self, brief_hash: str, mode: str, brief: dict[str, Any]
    ) -> tuple[dict[str, Any], bool]:
        now = utc_now()
        run_id = str(uuid.uuid4())
        with self.connect() as connection:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO runs VALUES (?, ?, ?, 'queued', ?, NULL, NULL, ?, ?)",
                (run_id, brief_hash, mode, json.dumps(brief), now, now),
            )
            created = cursor.rowcount == 1
            row = connection.execute(
                "SELECT id FROM runs WHERE brief_hash = ? AND mode = ?", (brief_hash, mode)
            ).fetchone()
            if row is None:
                raise RuntimeError("idempotent run creation did not produce a readable row")
            run_id = row["id"]
        return self.get(run_id), created

    def set_status(
        self,
        run_id: str,
        status: str,
        *,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE runs SET status = ?, "
                "result_json = COALESCE(?, result_json), error = ?, updated_at = ? "
                "WHERE id = ?",
                (
                    status,
                    json.dumps(result) if result is not None else None,
                    error,
                    utc_now(),
                    run_id,
                ),
            )

    def start_run(self, run_id: str, mode: str) -> bool:
        now = utc_now()
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE runs SET status = 'running', error = NULL, updated_at = ? "
                "WHERE id = ? AND status = 'queued'",
                (now, run_id),
            )
            if cursor.rowcount != 1:
                return False
            connection.execute(
                "INSERT INTO events "
                "(run_id, event_type, payload_json, created_at) VALUES (?, ?, ?, ?)",
                (run_id, "pipeline.started", json.dumps({"mode": mode}), now),
            )
        return True

    def queue_retry(self, run_id: str) -> bool:
        now = utc_now()
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE runs SET status = 'queued', result_json = NULL, error = NULL, "
                "updated_at = ? WHERE id = ? AND status = 'failed'",
                (now, run_id),
            )
            if cursor.rowcount != 1:
                return False
            connection.execute(
                "INSERT INTO events "
                "(run_id, event_type, payload_json, created_at) VALUES (?, ?, ?, ?)",
                (run_id, "pipeline.retry_queued", "{}", now),
            )
        return True

    def complete_run(self, run_id: str, result: dict[str, Any]) -> None:
        now = utc_now()
        manifest_hash = result["manifest"]["canonicalHash"]
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE runs SET status = 'completed', result_json = ?, error = NULL, "
                "updated_at = ? WHERE id = ? AND status = 'running'",
                (json.dumps(result), now, run_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("run cannot transition to completed from its current state")
            connection.execute(
                "INSERT INTO events "
                "(run_id, event_type, payload_json, created_at) VALUES (?, ?, ?, ?)",
                (
                    run_id,
                    "pipeline.completed",
                    json.dumps({"manifestHash": manifest_hash}),
                    now,
                ),
            )

    def fail_run(self, run_id: str, error: str, error_type: str) -> None:
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                "UPDATE runs SET status = 'failed', result_json = NULL, error = ?, "
                "updated_at = ? WHERE id = ?",
                (error, now, run_id),
            )
            connection.execute(
                "INSERT INTO events "
                "(run_id, event_type, payload_json, created_at) VALUES (?, ?, ?, ?)",
                (
                    run_id,
                    "pipeline.failed",
                    json.dumps({"errorType": error_type}),
                    now,
                ),
            )

    def add_event(self, run_id: str, event_type: str, payload: dict[str, Any]) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO events (run_id, event_type, payload_json, created_at) "
                "VALUES (?, ?, ?, ?)",
                (run_id, event_type, json.dumps(payload), utc_now()),
            )

    def add_review(
        self,
        run_id: str,
        approved: bool,
        reviewer: str,
        notes: str,
        *,
        verified: bool,
        publication_status: str = "not_requested",
    ) -> dict[str, Any]:
        if publication_status not in {"not_requested", "pending", "published", "failed"}:
            raise ValueError("invalid review publication status")
        created_at = utc_now()
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO reviews "
                "(run_id, approved, reviewer, notes, verified, publication_status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    int(approved),
                    reviewer,
                    notes,
                    int(verified),
                    publication_status,
                    created_at,
                ),
            )
            connection.execute(
                "INSERT INTO events "
                "(run_id, event_type, payload_json, created_at) VALUES (?, ?, ?, ?)",
                (
                    run_id,
                    "review.recorded",
                    json.dumps(
                        {
                            "approved": approved,
                            "reviewer": reviewer,
                            "verified": verified,
                            "publicationStatus": publication_status,
                        }
                    ),
                    created_at,
                ),
            )
        return {
            "approved": approved,
            "reviewer": reviewer,
            "notes": notes,
            "verified": verified,
            "publicationStatus": publication_status,
            "publicationError": None,
            "createdAt": created_at,
        }

    def set_review_publication(
        self,
        run_id: str,
        created_at: str,
        publication_status: str,
        error: str | None = None,
    ) -> dict[str, Any]:
        if publication_status not in {"published", "failed"}:
            raise ValueError("publication status must be published or failed")
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE reviews SET publication_status = ?, publication_error = ? "
                "WHERE run_id = ? AND created_at = ? AND publication_status = 'pending'",
                (publication_status, error, run_id, created_at),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("pending review publication state was not found")
            connection.execute(
                "INSERT INTO events "
                "(run_id, event_type, payload_json, created_at) VALUES (?, ?, ?, ?)",
                (
                    run_id,
                    f"showcase.publication.{publication_status}",
                    json.dumps({"reviewCreatedAt": created_at, "error": error}),
                    utc_now(),
                ),
            )
            row = connection.execute(
                "SELECT approved, reviewer, notes, verified, publication_status, "
                "publication_error, created_at FROM reviews "
                "WHERE run_id = ? AND created_at = ?",
                (run_id, created_at),
            ).fetchone()
        if row is None:
            raise RuntimeError("review publication state disappeared")
        return {
            "approved": bool(row["approved"]),
            "reviewer": row["reviewer"],
            "notes": row["notes"],
            "verified": bool(row["verified"]),
            "publicationStatus": row["publication_status"],
            "publicationError": row["publication_error"],
            "createdAt": row["created_at"],
        }

    def get(self, run_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
            if row is None:
                return None
            events = connection.execute(
                "SELECT event_type, payload_json, created_at FROM events "
                "WHERE run_id = ? ORDER BY id",
                (run_id,),
            ).fetchall()
            reviews = connection.execute(
                "SELECT approved, reviewer, notes, verified, publication_status, "
                "publication_error, created_at FROM reviews "
                "WHERE run_id = ? ORDER BY id",
                (run_id,),
            ).fetchall()
        return {
            "id": row["id"],
            "mode": row["mode"],
            "status": row["status"],
            "brief": json.loads(row["brief_json"]),
            "result": json.loads(row["result_json"]) if row["result_json"] else None,
            "error": row["error"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
            "events": [
                {
                    "type": event["event_type"],
                    "payload": json.loads(event["payload_json"]),
                    "createdAt": event["created_at"],
                }
                for event in events
            ],
            "reviews": [
                {
                    "approved": bool(review["approved"]),
                    "reviewer": review["reviewer"],
                    "notes": review["notes"],
                    "verified": bool(review["verified"]),
                    "publicationStatus": review["publication_status"],
                    "publicationError": review["publication_error"],
                    "createdAt": review["created_at"],
                }
                for review in reviews
            ],
        }

    def list(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT id FROM runs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self.get(row["id"]) for row in rows]

    def health_check(self) -> bool:
        with self.connect() as connection:
            row = connection.execute("PRAGMA quick_check").fetchone()
        return bool(row and row[0] == "ok")

    def latest_verified_live(self) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT runs.id FROM runs JOIN reviews ON reviews.run_id = runs.id "
                "WHERE runs.mode = 'live' AND runs.status = 'completed' "
                "AND reviews.approved = 1 AND reviews.verified = 1 "
                "AND reviews.publication_status = 'published' "
                "ORDER BY reviews.created_at DESC, reviews.id DESC LIMIT 1"
            ).fetchone()
        return self.get(row["id"]) if row else None

    def prune_demo_runs(self, keep: int = 200, *, exclude_run_id: str | None = None) -> int:
        with self.artifact_lock:
            excluded = exclude_run_id or ""
            with self.connect() as connection:
                rows = connection.execute(
                    "SELECT id, result_json FROM runs WHERE mode = 'demo' "
                    "AND status IN ('completed', 'failed') AND id != ? "
                    "ORDER BY created_at DESC LIMIT -1 OFFSET ?",
                    (excluded, keep),
                ).fetchall()
                if not rows:
                    return 0
                run_ids = [row["id"] for row in rows]
                removed_names = {
                    json.loads(row["result_json"]).get("asset", {}).get("localName")
                    for row in rows
                    if row["result_json"]
                }
                identifiers = [(run_id,) for run_id in run_ids]
                connection.executemany("DELETE FROM reviews WHERE run_id = ?", identifiers)
                connection.executemany("DELETE FROM events WHERE run_id = ?", identifiers)
                connection.executemany("DELETE FROM runs WHERE id = ?", identifiers)
                remaining_rows = connection.execute(
                    "SELECT result_json FROM runs WHERE result_json IS NOT NULL"
                ).fetchall()
                retained_names = {
                    json.loads(row["result_json"]).get("asset", {}).get("localName")
                    for row in remaining_rows
                }
            for local_name in removed_names - retained_names - {None}:
                candidate = (self.artifact_dir / local_name).resolve()
                if candidate.parent == self.artifact_dir.resolve():
                    try:
                        candidate.unlink(missing_ok=True)
                    except OSError as error:
                        logger.warning("artifact prune deferred for %s: %s", candidate, error)
            return len(run_ids)
