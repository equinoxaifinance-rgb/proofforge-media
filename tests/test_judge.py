from __future__ import annotations

from pathlib import Path

import pytest

from proofforge.database import RunStore
from proofforge.judge import (
    JudgeTokenError,
    issue_capability,
    issue_session,
    redeem_capability,
    token_hash,
    verify_session,
)

KEY = "judge-key-000000000000000000000000000000"


def test_capability_is_signed_and_session_is_scoped() -> None:
    token, capability = issue_capability(KEY, ttl_seconds=600, max_runs=3, label="Judge")
    assert token.startswith("pfj1.")
    assert redeem_capability(token, KEY, now=capability.issued_at + 1) == capability
    session_token, session = issue_session(KEY, capability, now=capability.issued_at + 1)
    assert verify_session(session_token, KEY, now=session.issued_at + 1) == session
    assert session.kind == "session"
    assert session.scope == "judge-sandbox"
    assert token_hash(token) != token_hash(session_token)


def test_tamper_expiry_and_wrong_key_fail_closed() -> None:
    token, claims = issue_capability(KEY, ttl_seconds=60, max_runs=1, label="Judge")
    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
    for candidate, key, now in (
        (tampered, KEY, claims.issued_at + 1),
        (token, "other-key-000000000000000000000000000", claims.issued_at + 1),
        (token, KEY, claims.expires_at),
    ):
        with pytest.raises(JudgeTokenError):
            redeem_capability(candidate, key, now=now)


def test_token_bounds_reject_unsafe_quotas() -> None:
    with pytest.raises(JudgeTokenError):
        issue_capability(KEY, ttl_seconds=59, max_runs=1, label="Judge")
    with pytest.raises(JudgeTokenError):
        issue_capability(KEY, ttl_seconds=60, max_runs=4, label="Judge")


def test_redemption_and_run_quota_survive_store_restart(tmp_path: Path) -> None:
    token, capability = issue_capability(KEY, ttl_seconds=600, max_runs=1, label="Judge")
    first = RunStore(tmp_path)
    first.register_judge_capability(
        capability.token_id,
        token_hash(token),
        capability.expires_at,
        capability.max_runs,
        capability.label,
    )
    session_token, session = issue_session(KEY, capability, now=capability.issued_at + 1)
    assert (
        first.redeem_judge_capability(
            capability.token_id,
            token_hash(token),
            session.token_id,
            session.expires_at,
            session.max_runs,
            capability.issued_at + 1,
        )
        == "ok"
    )
    assert first.redeem_judge_capability(
        capability.token_id,
        token_hash(token),
        "another-session",
        session.expires_at,
        session.max_runs,
        capability.issued_at + 1,
    ) == "redeemed"
    run, _ = first.create_or_get("a" * 64, "live", {"campaign_name": "Judge"})
    assert (
        first.reserve_judge_run(session.token_id, run["id"], capability.issued_at + 1)
        == "reserved"
    )
    restarted = RunStore(tmp_path)
    assert restarted.judge_session_authorizes_run(
        session.token_id, run["id"], capability.issued_at + 2
    ) == "ok"
    # Restart recovery fails an interrupted queued run, but the spent quota remains.
    assert (
        restarted.reserve_judge_run(session.token_id, "another-run", capability.issued_at + 2)
        == "quota"
    )
