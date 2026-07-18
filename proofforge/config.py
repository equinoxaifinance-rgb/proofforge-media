from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    live_enabled: bool
    operator_token: str
    openai_key_present: bool
    b2_key_id_present: bool
    b2_app_key_present: bool
    b2_bucket: str
    b2_region: str
    b2_public_url_base: str
    signing_key: str
    signing_key_persistent: bool
    trust_edge_client_ip: bool
    image_model: str
    image_fallback_model: str
    judge_model: str

    @property
    def b2_ready(self) -> bool:
        return all(
            [
                self.b2_key_id_present,
                self.b2_app_key_present,
                bool(self.b2_bucket),
            ]
        )

    @property
    def live_ready(self) -> bool:
        return all(
            [
                self.live_enabled,
                len(self.operator_token) >= 32,
                self.openai_key_present,
                self.b2_ready,
                self.signing_key_persistent,
            ]
        )


def _load_or_create_signing_key(data_dir: Path) -> tuple[str, bool]:
    configured_key = os.getenv("PROOFFORGE_SIGNING_KEY", "").strip()
    if configured_key:
        if len(configured_key) < 32:
            raise RuntimeError("configured signing key must be at least 32 characters")
        return configured_key, True

    key_path = data_dir / ".signing-key"
    try:
        descriptor = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(secrets.token_urlsafe(48))
            handle.write("\n")
    key = key_path.read_text(encoding="utf-8").strip()
    if len(key) < 32:
        raise RuntimeError("persisted signing key is missing or too short")
    return key, True


def load_settings(data_dir: Path | None = None) -> Settings:
    configured_dir = data_dir or Path(os.getenv("PROOFFORGE_DATA_DIR", "data"))
    configured_dir.mkdir(parents=True, exist_ok=True)
    signing_key, signing_key_persistent = _load_or_create_signing_key(configured_dir)
    return Settings(
        data_dir=configured_dir.resolve(),
        live_enabled=os.getenv("PROOFFORGE_ENABLE_LIVE", "false").lower() == "true",
        operator_token=os.getenv("PROOFFORGE_OPERATOR_TOKEN", ""),
        openai_key_present=bool(os.getenv("OPENAI_API_KEY")),
        b2_key_id_present=bool(os.getenv("B2_KEY_ID")),
        b2_app_key_present=bool(os.getenv("B2_APP_KEY")),
        b2_bucket=os.getenv("B2_BUCKET", ""),
        b2_region=os.getenv("B2_REGION", "us-west-004"),
        b2_public_url_base=os.getenv("B2_PUBLIC_URL_BASE", ""),
        signing_key=signing_key,
        signing_key_persistent=signing_key_persistent,
        trust_edge_client_ip=(
            os.getenv("PROOFFORGE_TRUST_EDGE_CLIENT_IP", "false").lower() == "true"
        ),
        image_model=os.getenv("PROOFFORGE_IMAGE_MODEL", "gpt-image-2"),
        image_fallback_model=os.getenv("PROOFFORGE_IMAGE_FALLBACK_MODEL", "gpt-image-1.5"),
        judge_model=os.getenv("PROOFFORGE_JUDGE_MODEL", "gpt-5.6-terra"),
    )
