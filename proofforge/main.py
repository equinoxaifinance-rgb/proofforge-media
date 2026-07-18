from __future__ import annotations

import hashlib
import hmac
import io
import ipaddress
import json
import logging
import re
import secrets
import threading
import time
import zipfile
from collections import deque
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request, Response, status
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .config import load_settings
from .database import RunStore
from .engine import PIPELINE_VERSION, ProofForgeEngine, bounded_asset_bytes, brief_hash
from .judge import (
    JudgeTokenError,
    issue_capability,
    issue_session,
    redeem_capability,
    token_hash,
    verify_session,
)
from .models import JudgeExchangeRequest, JudgeIssueRequest, ReviewRequest, RunRequest
from .showcase import B2ShowcaseStore

APP_ROOT = Path(__file__).resolve().parents[1]
IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{20,128}$")
SAFE_ASSET_NAME_RE = re.compile(r"^[a-f0-9]{64}\.[a-z0-9]{1,10}$")
MAX_RATE_LIMIT_CLIENTS = 4096
BUILD_ID = "proofforge-2026-07-18.2-schema-v2"
logger = logging.getLogger("proofforge")


def create_app(
    data_dir: Path | None = None,
    showcase_store: B2ShowcaseStore | None = None,
) -> FastAPI:
    settings = load_settings(data_dir)
    store = RunStore(settings.data_dir)
    engine = ProofForgeEngine(settings, store)
    durable_showcase = showcase_store
    if durable_showcase is None and settings.b2_ready:
        durable_showcase = B2ShowcaseStore.from_settings(settings)
    application = FastAPI(
        title="ProofForge Media",
        version="0.2.0",
        description="Evidence-first generative media orchestration with Genblaze and Backblaze B2.",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    application.state.settings = settings
    application.state.store = store
    application.state.engine = engine
    application.state.showcase_store = durable_showcase
    application.mount("/static", StaticFiles(directory=APP_ROOT / "static"), name="static")
    demo_requests: dict[str, deque[float]] = {}
    demo_rate_lock = threading.Lock()

    @application.middleware("http")
    async def security_boundary(request: Request, call_next):
        content_length = request.headers.get("content-length")
        if request.method in {"POST", "PUT", "PATCH"} and content_length is None:
            return JSONResponse({"detail": "Content-Length is required"}, status_code=411)
        if content_length:
            try:
                declared_length = int(content_length)
            except ValueError:
                return JSONResponse({"detail": "invalid Content-Length"}, status_code=400)
            if declared_length < 0:
                return JSONResponse({"detail": "invalid Content-Length"}, status_code=400)
            if declared_length > 32_768:
                return JSONResponse({"detail": "request body exceeds 32 KiB"}, status_code=413)
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' blob: data:; connect-src 'self'; object-src 'none'; "
            "base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def run_access_token(run_id: str) -> str:
        return hmac.new(settings.signing_key.encode(), run_id.encode(), hashlib.sha256).hexdigest()

    def is_operator(key: str | None) -> bool:
        return bool(
            settings.operator_token and key and secrets.compare_digest(key, settings.operator_token)
        )

    def judge_claims(session_token: str | None):
        if not settings.judge_sandbox_ready or not session_token:
            raise HTTPException(status_code=401, detail="valid judge session required")
        try:
            return verify_session(session_token, settings.judge_capability_key)
        except JudgeTokenError as error:
            raise HTTPException(status_code=401, detail="valid judge session required") from error

    def judge_status_error(result: str) -> HTTPException:
        if result in {"invalid", "expired", "redeemed"}:
            return HTTPException(status_code=401, detail="judge capability is invalid or expired")
        if result == "active":
            return HTTPException(status_code=409, detail="judge session already has an active run")
        if result == "quota":
            return HTTPException(status_code=429, detail="judge session run quota exhausted")
        return HTTPException(status_code=409, detail="judge capability could not be redeemed")

    def demo_client_key(request: Request) -> str:
        if settings.trust_edge_client_ip:
            edge_value = request.headers.get("x-proofforge-client-ip", "").strip()
            try:
                if not edge_value or "," in edge_value:
                    raise ValueError("edge client IP must contain exactly one address")
                return f"edge:{ipaddress.ip_address(edge_value).compressed}"
            except ValueError:
                # The Worker overwrites this header. If deployment wiring is
                # malformed, collapse to one bounded failure-safe bucket rather
                # than accepting attacker-controlled or unbounded identities.
                return "edge:invalid"
        transport = request.client.host if request.client else "unknown"
        return f"transport:{transport}"

    def require_run_access(
        run: dict,
        run_key: str | None,
        operator_key: str | None,
        judge_session: str | None = None,
    ) -> bool:
        operator = is_operator(operator_key)
        if run["mode"] == "live":
            if operator:
                return True
            claims = judge_claims(judge_session)
            authorization = store.judge_session_authorizes_run(
                claims.token_id, run["id"], int(time.time())
            )
            if authorization != "ok":
                raise HTTPException(
                    status_code=401, detail="judge session is not authorized for run"
                )
            return False
        expected = run_access_token(run["id"])
        if not run_key or not secrets.compare_digest(run_key, expected):
            if not operator:
                raise HTTPException(status_code=401, detail="valid run access key required")
        return operator

    def verified_asset_payload(run: dict) -> tuple[bytes, str, str]:
        with store.artifact_lock:
            if run["status"] != "completed" or not run["result"]:
                raise HTTPException(status_code=409, detail="verified asset is not available yet")
            asset = run["result"].get("asset") or {}
            local_name = asset.get("localName")
            expected_hash = asset.get("sha256")
            media_type = asset.get("mediaType")
            if not all(isinstance(value, str) for value in (local_name, expected_hash, media_type)):
                raise HTTPException(status_code=409, detail="verified asset metadata is invalid")
            if not SAFE_ASSET_NAME_RE.fullmatch(local_name):
                raise HTTPException(status_code=409, detail="verified asset filename is invalid")
            artifact_root = store.artifact_dir.resolve()
            candidate = (artifact_root / local_name).resolve()
            if not candidate.is_relative_to(artifact_root):
                raise HTTPException(status_code=409, detail="verified asset path is invalid")
            try:
                data = bounded_asset_bytes(candidate)
            except (OSError, RuntimeError) as error:
                raise HTTPException(
                    status_code=409, detail="verified asset bytes are unavailable"
                ) from error
            actual_hash = hashlib.sha256(data).hexdigest()
            if not secrets.compare_digest(actual_hash, expected_hash):
                raise HTTPException(status_code=409, detail="asset integrity verification failed")
            return data, media_type, local_name

    @application.get("/", include_in_schema=False)
    def home() -> FileResponse:
        return FileResponse(APP_ROOT / "static" / "index.html")

    @application.get("/favicon.ico", include_in_schema=False)
    def favicon() -> FileResponse:
        # Some browsers request the conventional fallback even when the HTML
        # advertises the SVG icon explicitly. Serve the same checked-in asset
        # instead of generating a production 404.
        return FileResponse(APP_ROOT / "static" / "favicon.svg", media_type="image/svg+xml")

    @application.get("/api/health")
    def health() -> dict:
        if not store.health_check():
            raise HTTPException(status_code=503, detail="database integrity check failed")
        return {
            "status": "ok",
            "service": "proofforge",
            "version": "0.2.0",
            "buildId": BUILD_ID,
            "pipelineVersion": PIPELINE_VERSION,
            "database": "ok",
        }

    @application.get("/api/capabilities")
    def capabilities() -> dict:
        if durable_showcase is not None:
            try:
                showcase_ready = durable_showcase.load() is not None
            except Exception:
                logger.exception("durable showcase verification failed")
                showcase_ready = False
        else:
            showcase_ready = False
        return {
            "demoReady": True,
            "pipelineVersion": PIPELINE_VERSION,
            "liveEnabled": settings.live_enabled,
            "liveReady": settings.live_ready,
            "judgeSandboxEnabled": settings.judge_sandbox_enabled,
            "judgeSandboxReady": settings.judge_sandbox_ready,
            "judgeSandbox": {
                "scope": "judge-sandbox",
                "ttlSeconds": settings.judge_capability_ttl_seconds,
                "maxRuns": settings.judge_capability_max_runs,
                "oneActiveRun": True,
                "operatorApprovalRequired": True,
                "dollarCap": "not claimed; provider pricing is not assumed",
            },
            "b2Ready": settings.b2_ready,
            "showcaseReady": showcase_ready,
            "runAccess": (
                "persistent HMAC-scoped demo keys; operator key or one-time bounded judge session "
                "for live reads"
            ),
            "provider": "OpenAI via Genblaze",
            "models": [
                settings.image_model,
                f"{settings.image_fallback_model} fallback",
                f"{settings.judge_model} evaluator",
            ],
            "storage": "Backblaze B2 via genblaze-s3",
        }

    def public_showcase_run() -> dict:
        if durable_showcase is not None:
            try:
                run = durable_showcase.load()
            except Exception as error:
                logger.exception("durable showcase verification failed")
                raise HTTPException(
                    status_code=503,
                    detail="durable showcase failed integrity verification",
                ) from error
        else:
            raise HTTPException(
                status_code=503,
                detail="durable B2 showcase storage is unavailable",
            )
        if run is None:
            raise HTTPException(status_code=404, detail="no verified live showcase is published")
        return run

    @application.get("/api/showcase")
    def showcase() -> dict:
        run = public_showcase_run()
        result = run["result"]
        # Do not expose provider-private URLs in the judge-facing receipt. Content-addressed
        # object keys and hashes remain useful provenance without leaking bucket topology.
        public_storage = {
            key: value
            for key, value in result["storage"].items()
            if not key.lower().endswith("url")
        }
        if isinstance(public_storage.get("iterations"), list):
            public_storage["iterations"] = [
                {key: value for key, value in item.items() if not key.lower().endswith("url")}
                for item in public_storage["iterations"]
                if isinstance(item, dict)
            ]
        return {
            "runId": run["id"],
            "createdAt": run["createdAt"],
            "updatedAt": run["updatedAt"],
            "campaign": run["brief"]["campaign_name"],
            "models": result["models"],
            "asset": {
                "previewPath": "/api/showcase/asset",
                "sha256": result["asset"]["sha256"],
                "mediaType": result["asset"]["mediaType"],
                "bytes": result["asset"]["bytes"],
            },
            "manifestCanonicalHash": result["manifest"]["canonicalHash"],
            "orchestration": {
                "engine": result["orchestration"]["engine"],
                "iterations": result["orchestration"]["iterations"],
                "passed": result["orchestration"]["passed"],
            },
            "storage": public_storage,
            "checks": result["checks"],
            "approval": next(
                review
                for review in reversed(run["reviews"])
                if review["approved"] and review["verified"]
            ),
        }

    @application.get("/api/showcase/asset")
    def showcase_asset() -> Response:
        run = public_showcase_run()
        media_type = run["result"]["asset"]["mediaType"]
        try:
            asset_bytes, media_type, _ = verified_asset_payload(run)
        except HTTPException as local_error:
            if durable_showcase is None:
                raise
            try:
                asset_bytes = durable_showcase.fetch_asset(run)
            except Exception as error:
                logger.exception("durable showcase asset verification failed")
                raise HTTPException(
                    status_code=503,
                    detail="durable showcase asset failed integrity verification",
                ) from error
            logger.info("served showcase asset from B2 after local miss: %s", local_error.detail)
            return Response(content=asset_bytes, media_type=media_type)
        return Response(content=asset_bytes, media_type=media_type)

    @application.post("/api/judge/issue")
    def issue_judge(
        request: JudgeIssueRequest,
        x_proofforge_key: str | None = Header(default=None),
    ) -> dict:
        if not is_operator(x_proofforge_key):
            raise HTTPException(status_code=401, detail="operator authorization required")
        if not settings.judge_sandbox_ready:
            raise HTTPException(status_code=409, detail="judge sandbox is disabled or incomplete")
        try:
            token, claims = issue_capability(
                settings.judge_capability_key,
                ttl_seconds=min(request.ttl_seconds, settings.judge_capability_ttl_seconds),
                max_runs=min(request.max_runs, settings.judge_capability_max_runs),
                label=request.label,
            )
            store.register_judge_capability(
                claims.token_id,
                token_hash(token),
                claims.expires_at,
                claims.max_runs,
                claims.label,
            )
        except (JudgeTokenError, ValueError) as error:
            raise HTTPException(
                status_code=409, detail="judge capability could not be issued"
            ) from error
        return {
            "capability": token,
            "scope": claims.scope,
            "expiresAt": claims.expires_at,
            "maxRuns": claims.max_runs,
            "redemption": "one-time",
        }

    @application.post("/api/judge/exchange")
    def exchange_judge(request: JudgeExchangeRequest) -> dict:
        if not settings.judge_sandbox_ready:
            raise HTTPException(status_code=409, detail="judge sandbox is disabled or incomplete")
        try:
            capability = redeem_capability(request.capability, settings.judge_capability_key)
            session_token, session = issue_session(settings.judge_capability_key, capability)
            result = store.redeem_judge_capability(
                capability.token_id,
                token_hash(request.capability),
                session.token_id,
                session.expires_at,
                session.max_runs,
                int(time.time()),
            )
        except JudgeTokenError as error:
            raise HTTPException(
                status_code=401, detail="judge capability is invalid or expired"
            ) from error
        if result != "ok":
            raise judge_status_error(result)
        return {
            "session": session_token,
            "scope": session.scope,
            "expiresAt": session.expires_at,
            "maxRuns": session.max_runs,
            "oneActiveRun": True,
        }

    @application.post("/api/runs", status_code=status.HTTP_202_ACCEPTED)
    def create_run(
        request: RunRequest,
        background_tasks: BackgroundTasks,
        http_request: Request,
        x_proofforge_key: str | None = Header(default=None),
        x_proofforge_idempotency_key: str | None = Header(default=None),
        x_proofforge_judge_session: str | None = Header(default=None),
    ) -> dict:
        if request.mode == "demo":
            client_key = demo_client_key(http_request)
            now = time.monotonic()
            with demo_rate_lock:
                if client_key not in demo_requests:
                    stale_clients = [
                        key
                        for key, requests in demo_requests.items()
                        if not requests or requests[-1] <= now - 60
                    ]
                    for stale_client in stale_clients:
                        demo_requests.pop(stale_client, None)
                    if len(demo_requests) >= MAX_RATE_LIMIT_CLIENTS:
                        raise HTTPException(
                            status_code=503,
                            detail="demo capacity is temporarily full; retry in one minute",
                        )
                    demo_requests[client_key] = deque()
                window = demo_requests[client_key]
                while window and window[0] <= now - 60:
                    window.popleft()
                if len(window) >= 12:
                    raise HTTPException(
                        status_code=429,
                        detail="demo rate limit reached; retry after one minute",
                    )
                window.append(now)
        judge_session_id: str | None = None
        if request.mode == "live":
            if not settings.live_enabled:
                raise HTTPException(status_code=409, detail="live mode is disabled")
            if not settings.live_ready:
                raise HTTPException(
                    status_code=409, detail="live provider or B2 configuration is incomplete"
                )
            if not is_operator(x_proofforge_key):
                claims = judge_claims(x_proofforge_judge_session)
                judge_session_id = claims.token_id
        digest = brief_hash(request.brief)
        storage_digest = digest
        if request.mode == "demo":
            idempotency_key = x_proofforge_idempotency_key or secrets.token_urlsafe(32)
            if not IDEMPOTENCY_KEY_RE.fullmatch(idempotency_key):
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "X-Proofforge-Idempotency-Key must contain 20-128 URL-safe "
                        "letters, digits, underscores, or hyphens"
                    ),
                )
            tenant_scope = hmac.new(
                settings.signing_key.encode(),
                idempotency_key.encode(),
                hashlib.sha256,
            ).hexdigest()
            storage_digest = hashlib.sha256(f"{digest}:{tenant_scope}".encode()).hexdigest()
        elif judge_session_id:
            storage_digest = hashlib.sha256(
                f"{digest}:judge:{judge_session_id}".encode()
            ).hexdigest()
        run, created = store.create_or_get(
            storage_digest, request.mode, request.brief.model_dump(mode="json")
        )
        retried = False
        if not created and run["status"] == "completed":
            try:
                verified_asset_payload(run)
                if run["result"].get("pipelineVersion") != PIPELINE_VERSION:
                    raise HTTPException(status_code=409, detail="stale pipeline receipt")
            except HTTPException:
                store.fail_run(
                    run["id"],
                    "completed receipt failed integrity or schema verification",
                    "IntegrityError",
                )
                run = store.get(run["id"])
        if not created and run["status"] == "failed":
            retried = store.queue_retry(run["id"])
        if judge_session_id:
            reservation = store.reserve_judge_run(judge_session_id, run["id"], int(time.time()))
            if reservation not in {"reserved", "existing"}:
                if created:
                    store.fail_run(
                        run["id"], "judge quota denied before provider dispatch", "JudgeQuota"
                    )
                raise judge_status_error(reservation)
        if created or retried:
            event_type = "run.queued" if created else "run.requeued"
            store.add_event(
                run["id"],
                event_type,
                {"briefHash": digest, "mode": request.mode, "idempotencyScoped": True},
            )
            background_tasks.add_task(engine.process, run["id"], request.brief, request.mode)
        return {
            "run": store.get(run["id"]),
            "created": created,
            "retried": retried,
            "accessToken": run_access_token(run["id"]) if request.mode == "demo" else None,
        }

    @application.get("/api/runs")
    def list_runs(x_proofforge_key: str | None = Header(default=None)) -> dict:
        if not is_operator(x_proofforge_key):
            raise HTTPException(status_code=401, detail="operator authorization required")
        return {"runs": store.list()}

    @application.get("/api/runs/{run_id}")
    def get_run(
        run_id: str,
        x_proofforge_run_key: str | None = Header(default=None),
        x_proofforge_key: str | None = Header(default=None),
        x_proofforge_judge_session: str | None = Header(default=None),
    ) -> dict:
        run = store.get(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        require_run_access(run, x_proofforge_run_key, x_proofforge_key, x_proofforge_judge_session)
        return run

    @application.get("/api/runs/{run_id}/manifest")
    def manifest(
        run_id: str,
        x_proofforge_run_key: str | None = Header(default=None),
        x_proofforge_key: str | None = Header(default=None),
        x_proofforge_judge_session: str | None = Header(default=None),
    ) -> dict:
        run = store.get(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        require_run_access(run, x_proofforge_run_key, x_proofforge_key, x_proofforge_judge_session)
        if run["status"] != "completed" or not run["result"]:
            raise HTTPException(status_code=409, detail="manifest is not available yet")
        return run["result"]["manifest"]

    @application.post("/api/runs/{run_id}/review", status_code=status.HTTP_201_CREATED)
    def review(
        run_id: str,
        request: ReviewRequest,
        x_proofforge_run_key: str | None = Header(default=None),
        x_proofforge_key: str | None = Header(default=None),
        x_proofforge_judge_session: str | None = Header(default=None),
    ) -> dict:
        run = store.get(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        operator = require_run_access(
            run, x_proofforge_run_key, x_proofforge_key, x_proofforge_judge_session
        )
        if run["mode"] == "live" and not operator:
            raise HTTPException(status_code=403, detail="operator approval is required")
        if run["status"] != "completed":
            raise HTTPException(status_code=409, detail="only completed runs can be reviewed")
        verified = bool(operator and run["mode"] == "live")
        if request.approved and verified and durable_showcase is None:
            raise HTTPException(
                status_code=503,
                detail="durable B2 showcase storage is unavailable",
            )
        review_record = store.add_review(
            run_id,
            request.approved,
            request.reviewer,
            request.notes,
            verified=verified,
            publication_status=("pending" if request.approved and verified else "not_requested"),
        )
        if review_record["approved"] and review_record["verified"]:
            try:
                publication_candidate = store.get(run_id)
                candidate_review = next(
                    item
                    for item in reversed(publication_candidate["reviews"])
                    if item["createdAt"] == review_record["createdAt"]
                )
                candidate_review["publicationStatus"] = "published"
                candidate_review["publicationError"] = None
                durable_showcase.publish(publication_candidate)
            except Exception as error:
                logger.exception("durable showcase publication failed")
                store.set_review_publication(
                    run_id,
                    review_record["createdAt"],
                    "failed",
                    type(error).__name__,
                )
                raise HTTPException(
                    status_code=502,
                    detail="operator approval was retained as unpublished after B2 failure",
                ) from error
            review_record = store.set_review_publication(
                run_id,
                review_record["createdAt"],
                "published",
            )
        return review_record

    @application.get("/api/runs/{run_id}/evidence.zip")
    def evidence_bundle(
        run_id: str,
        x_proofforge_run_key: str | None = Header(default=None),
        x_proofforge_key: str | None = Header(default=None),
        x_proofforge_judge_session: str | None = Header(default=None),
    ) -> StreamingResponse:
        with store.artifact_lock:
            run = store.get(run_id)
            if run is None:
                raise HTTPException(status_code=404, detail="run not found")
            require_run_access(
                run, x_proofforge_run_key, x_proofforge_key, x_proofforge_judge_session
            )
            if run["status"] != "completed" or not run["result"]:
                raise HTTPException(status_code=409, detail="evidence is not available yet")
            asset_bytes, _, local_name = verified_asset_payload(run)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("brief.json", json.dumps(run["brief"], indent=2))
            archive.writestr("receipt.json", json.dumps(run, indent=2))
            archive.writestr("manifest.json", json.dumps(run["result"]["manifest"], indent=2))
            archive.writestr(f"asset/{local_name}", asset_bytes)
        buffer.seek(0)
        return StreamingResponse(
            buffer,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="proofforge-{run_id}.zip"'},
        )

    @application.get("/api/runs/{run_id}/asset")
    def asset(
        run_id: str,
        x_proofforge_run_key: str | None = Header(default=None),
        x_proofforge_key: str | None = Header(default=None),
        x_proofforge_judge_session: str | None = Header(default=None),
    ) -> Response:
        with store.artifact_lock:
            run = store.get(run_id)
            if run is None:
                raise HTTPException(status_code=404, detail="run not found")
            require_run_access(
                run, x_proofforge_run_key, x_proofforge_key, x_proofforge_judge_session
            )
            asset_bytes, media_type, _ = verified_asset_payload(run)
        return Response(content=asset_bytes, media_type=media_type)

    @application.get("/robots.txt", include_in_schema=False)
    def robots() -> Response:
        return Response("User-agent: *\nDisallow: /api/\n", media_type="text/plain")

    return application


app = create_app()
