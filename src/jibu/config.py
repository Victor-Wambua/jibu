"""Runtime settings, read from environment variables (see .env.example)."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path


class ConfigError(ValueError):
    pass


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _rate(value: str | None, default: tuple[int, float]) -> tuple[int, float]:
    if not value:
        return default
    try:
        count, window = value.split("/")
        parsed = (int(count), float(window))
    except ValueError as exc:
        raise ConfigError("JIBU_RATE_LIMIT must look like '30/60' (requests/seconds)") from exc
    if parsed[0] < 1 or parsed[1] <= 0:
        raise ConfigError("JIBU_RATE_LIMIT values must be positive")
    return parsed


@dataclass(frozen=True)
class Settings:
    kb_dir: Path = Path("kb")
    default_kb: str | None = None
    threshold: float | None = None
    rate_limit: tuple[int, float] = (30, 60.0)
    trust_proxy: bool = False
    cors_origins: tuple[str, ...] = ()
    admin_token: str | None = None
    store_unanswered_text: bool = False  # opt-in: keep (redacted) text of unanswered questions
    unanswered_file: Path | None = None
    feedback_file: Path | None = None
    session_ttl: float = 600.0
    wa_verify_token: str | None = None
    wa_app_secret: str | None = None
    wa_access_token: str | None = None
    wa_phone_number_id: str | None = None
    wa_kb: str | None = None
    wa_send: bool = False  # False: log replies only. True: call the (unverified) Cloud API
    hash_secret: bytes = field(default_factory=lambda: os.urandom(32))

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        e = os.environ if env is None else env
        threshold = e.get("JIBU_THRESHOLD")
        try:
            thr = float(threshold) if threshold else None
        except ValueError as exc:
            raise ConfigError("JIBU_THRESHOLD must be a number between 0 and 1") from exc
        if thr is not None and not 0 < thr < 1:
            raise ConfigError("JIBU_THRESHOLD must be between 0 and 1")

        def path(name: str) -> Path | None:
            v = e.get(name)
            return Path(v) if v else None

        secret = e.get("JIBU_HASH_SECRET")
        return cls(
            kb_dir=Path(e.get("JIBU_KB_DIR", "kb")),
            default_kb=e.get("JIBU_DEFAULT_KB") or None,
            threshold=thr,
            rate_limit=_rate(e.get("JIBU_RATE_LIMIT"), (30, 60.0)),
            trust_proxy=_bool(e.get("JIBU_TRUST_PROXY")),
            cors_origins=tuple(
                o.strip() for o in e.get("JIBU_CORS_ORIGINS", "").split(",") if o.strip()
            ),
            admin_token=e.get("JIBU_ADMIN_TOKEN") or None,
            store_unanswered_text=_bool(e.get("JIBU_STORE_UNANSWERED_TEXT")),
            unanswered_file=path("JIBU_UNANSWERED_FILE"),
            feedback_file=path("JIBU_FEEDBACK_FILE"),
            session_ttl=float(e.get("JIBU_SESSION_TTL", "600")),
            wa_verify_token=e.get("JIBU_WA_VERIFY_TOKEN") or None,
            wa_app_secret=e.get("JIBU_WA_APP_SECRET") or None,
            wa_access_token=e.get("JIBU_WA_ACCESS_TOKEN") or None,
            wa_phone_number_id=e.get("JIBU_WA_PHONE_NUMBER_ID") or None,
            wa_kb=e.get("JIBU_WA_KB") or None,
            wa_send=_bool(e.get("JIBU_WA_SEND")),
            hash_secret=secret.encode() if secret else os.urandom(32),
        )
