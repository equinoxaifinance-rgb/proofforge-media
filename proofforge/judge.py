from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass

TOKEN_PREFIX = "pfj1"  # noqa: S105 - public protocol version, not a credential
MAX_TOKEN_BYTES = 4096


class JudgeTokenError(ValueError):
    """A judge capability/session token is malformed, expired, or invalid."""


@dataclass(frozen=True)
class JudgeClaims:
    kind: str
    token_id: str
    issued_at: int
    expires_at: int
    max_runs: int
    scope: str
    label: str = "judge"


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    if not value or len(value) > MAX_TOKEN_BYTES:
        raise JudgeTokenError("token encoding is invalid")
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, UnicodeError) as error:
        raise JudgeTokenError("token encoding is invalid") from error


def _sign(payload: str, key: str) -> str:
    return _b64(hmac.new(key.encode("utf-8"), payload.encode("ascii"), hashlib.sha256).digest())


def _encode(claims: JudgeClaims, key: str) -> str:
    body = _b64(
        json.dumps(
            {
                "v": 1,
                "kind": claims.kind,
                "jti": claims.token_id,
                "iat": claims.issued_at,
                "exp": claims.expires_at,
                "max": claims.max_runs,
                "scope": claims.scope,
                "label": claims.label,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )
    signed = f"{TOKEN_PREFIX}.{body}"
    return f"{signed}.{_sign(signed, key)}"


def _decode(token: str, key: str, expected_kind: str, now: int | None = None) -> JudgeClaims:
    if not isinstance(token, str) or len(token.encode("utf-8")) > MAX_TOKEN_BYTES:
        raise JudgeTokenError("token is invalid")
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != TOKEN_PREFIX:
        raise JudgeTokenError("token is invalid")
    signed = ".".join(parts[:2])
    expected = _sign(signed, key)
    if not hmac.compare_digest(parts[2], expected):
        raise JudgeTokenError("token signature is invalid")
    try:
        payload = json.loads(_unb64(parts[1]))
        claims = JudgeClaims(
            kind=str(payload["kind"]),
            token_id=str(payload["jti"]),
            issued_at=int(payload["iat"]),
            expires_at=int(payload["exp"]),
            max_runs=int(payload["max"]),
            scope=str(payload["scope"]),
            label=str(payload.get("label", "judge")),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise JudgeTokenError("token claims are invalid") from error
    current = int(time.time()) if now is None else now
    if claims.kind != expected_kind or claims.scope != "judge-sandbox":
        raise JudgeTokenError("token scope is invalid")
    if not (1 <= claims.max_runs <= 3):
        raise JudgeTokenError("token quota is invalid")
    if claims.expires_at <= current or claims.issued_at > current + 60:
        raise JudgeTokenError("token is expired")
    if len(claims.token_id) < 32 or len(claims.token_id) > 128:
        raise JudgeTokenError("token identifier is invalid")
    return claims


def issue_capability(
    key: str, *, ttl_seconds: int, max_runs: int, label: str
) -> tuple[str, JudgeClaims]:
    if len(key) < 32:
        raise JudgeTokenError("judge capability key is not configured")
    if not 60 <= ttl_seconds <= 1800:
        raise JudgeTokenError("judge capability TTL must be between 60 and 1800 seconds")
    if not 1 <= max_runs <= 3:
        raise JudgeTokenError("judge capability quota must be between 1 and 3 runs")
    now = int(time.time())
    claims = JudgeClaims(
        kind="capability",
        token_id=secrets.token_urlsafe(24),
        issued_at=now,
        expires_at=now + ttl_seconds,
        max_runs=max_runs,
        scope="judge-sandbox",
        label=label[:80] or "judge",
    )
    return _encode(claims, key), claims


def redeem_capability(token: str, key: str, now: int | None = None) -> JudgeClaims:
    return _decode(token, key, "capability", now)


def issue_session(
    key: str, capability: JudgeClaims, *, now: int | None = None
) -> tuple[str, JudgeClaims]:
    current = int(time.time()) if now is None else now
    session = JudgeClaims(
        kind="session",
        token_id=secrets.token_urlsafe(24),
        issued_at=current,
        expires_at=min(capability.expires_at, current + 1800),
        max_runs=capability.max_runs,
        scope=capability.scope,
        label=capability.label,
    )
    return _encode(session, key), session


def verify_session(token: str, key: str, now: int | None = None) -> JudgeClaims:
    return _decode(token, key, "session", now)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
