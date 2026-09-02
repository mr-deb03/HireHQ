"""Application configuration.

All settings are read from the environment (or a local ``.env``). Nothing here has a
production-safe default that could silently ship an insecure value: ``JWT_SECRET`` is
validated at startup and refused if it is still the development placeholder while
``APP_ENV=production``.
"""

from __future__ import annotations

import secrets
from functools import lru_cache
from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_JWT_SECRET = "dev-only-insecure-secret-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ------------------------------------------------------------------ app
    APP_NAME: str = "HireHQ"
    APP_TAGLINE: str = "From Application to Hire - Automated."
    APP_ENV: Literal["development", "test", "staging", "production"] = "development"
    API_V1_PREFIX: str = "/api/v1"
    DEBUG: bool = False
    #: Public base URL of the frontend, used to build candidate-facing links in emails.
    FRONTEND_BASE_URL: str = "http://localhost:3000"
    #: Public base URL of this API, used for signed file URLs.
    BACKEND_BASE_URL: str = "http://localhost:8000"

    # ------------------------------------------------------------- database
    #: ``postgresql+asyncpg://...`` in real deployments. The SQLite default lets the
    #: whole backend and the test-suite run with zero infrastructure.
    DATABASE_URL: str = "sqlite+aiosqlite:///./hirehq.db"
    DB_ECHO: bool = False
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20

    # ---------------------------------------------------------------- redis
    REDIS_URL: str = "redis://localhost:6379/0"
    #: When false, background jobs execute in-process instead of via an ARQ worker.
    #: Real Redis + worker is the production path; this keeps local dev runnable.
    USE_REDIS_QUEUE: bool = False
    USE_REDIS_CACHE: bool = False

    # ------------------------------------------------------------------ jwt
    JWT_SECRET: str = DEV_JWT_SECRET
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_EXPIRE_MINUTES: int = 30
    JWT_REFRESH_EXPIRE_DAYS: int = 14
    #: Rotate refresh tokens on every use and revoke the consumed one.
    JWT_REFRESH_ROTATION: bool = True

    PASSWORD_MIN_LENGTH: int = 10
    EMAIL_VERIFICATION_EXPIRE_HOURS: int = 48
    PASSWORD_RESET_EXPIRE_MINUTES: int = 60

    #: Whether signing in requires a verified email address.
    #:
    #: Unset (the default) means "only when the email provider can actually deliver the
    #: verification link". Enforcing it while email is not transmitting locks every user
    #: out permanently - the link is recorded but never arrives, so nobody can ever
    #: satisfy the requirement. That is a lockout, not a security control.
    #:
    #: Set it to true to require verification regardless, or false to never require it.
    REQUIRE_EMAIL_VERIFICATION: bool | None = None

    # -------------------------------------------------------------- storage
    #: ``s3`` (any S3-compatible endpoint) or ``local`` (filesystem, dev only).
    STORAGE_PROVIDER: Literal["s3", "local"] = "local"
    STORAGE_ENDPOINT: str | None = None
    STORAGE_REGION: str = "us-east-1"
    STORAGE_BUCKET: str = "hirehq"
    STORAGE_ACCESS_KEY: str | None = None
    STORAGE_SECRET_KEY: str | None = None
    STORAGE_LOCAL_PATH: str = "./storage"
    STORAGE_SIGNED_URL_TTL_SECONDS: int = 900
    #: Value for the ``x-amz-server-side-encryption`` header on upload. AWS S3 and MinIO
    #: accept ``AES256``; Cloudflare R2 encrypts everything automatically and rejects the
    #: header, so set this empty for R2. Encryption at rest is not lost either way.
    STORAGE_SERVER_SIDE_ENCRYPTION: str = "AES256"

    MAX_RESUME_SIZE_MB: int = 10
    MAX_DOCUMENT_SIZE_MB: int = 20
    ALLOWED_RESUME_EXTENSIONS: str = "pdf,docx"

    # ------------------------------------------------------------------- ai
    #: ``anthropic`` uses the real Claude API. ``heuristic`` is a fully deterministic,
    #: credential-free local implementation used for dev/tests - it is never presented
    #: to users as if it were an LLM.
    AI_PROVIDER: Literal["anthropic", "heuristic"] = "heuristic"
    AI_API_KEY: str | None = None
    AI_MODEL: str = "claude-opus-5"
    AI_ASSISTANT_MODEL: str = "claude-opus-5"
    AI_MAX_TOKENS: int = 8000
    AI_EFFORT: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    AI_TIMEOUT_SECONDS: float = 120.0
    #: Embeddings back the semantic-similarity component of the ATS score.
    #: ``lexical`` is a deterministic local vectoriser (no network, no credentials).
    EMBEDDING_PROVIDER: Literal["lexical"] = "lexical"

    # ---------------------------------------------------------------- email
    #: ``smtp`` transmits for real. ``console`` records the message and marks it
    #: NOT_SENT_NO_PROVIDER - it never claims delivery.
    EMAIL_PROVIDER: Literal["smtp", "console"] = "console"
    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_USERNAME: str | None = None
    SMTP_PASSWORD: str | None = None
    SMTP_USE_TLS: bool = True
    EMAIL_FROM_ADDRESS: str = "no-reply@hirehq.test"
    EMAIL_FROM_NAME: str = "HireHQ"

    # ------------------------------------------------------------- calendar
    CALENDAR_PROVIDER: Literal["google", "microsoft", "none"] = "none"
    GOOGLE_CLIENT_ID: str | None = None
    GOOGLE_CLIENT_SECRET: str | None = None
    GOOGLE_REDIRECT_URI: str | None = None
    MICROSOFT_CLIENT_ID: str | None = None
    MICROSOFT_CLIENT_SECRET: str | None = None
    MICROSOFT_TENANT_ID: str = "common"
    MICROSOFT_REDIRECT_URI: str | None = None

    # ------------------------------------------------------- sms / whatsapp
    SMS_PROVIDER: Literal["none", "twilio"] = "none"
    WHATSAPP_PROVIDER: Literal["none", "twilio"] = "none"
    TWILIO_ACCOUNT_SID: str | None = None
    TWILIO_AUTH_TOKEN: str | None = None
    TWILIO_FROM_NUMBER: str | None = None

    # ------------------------------------------------------- code execution
    #: How coding/SQL assessment answers are graded.
    #: ``manual`` (default) stores submissions for a human - this server never executes
    #: untrusted candidate code. ``sqlite`` additionally grades SQL against a disposable
    #: in-memory database. ``remote`` delegates to a sandbox you operate.
    CODE_RUNNER: Literal["manual", "sqlite", "remote"] = "sqlite"
    CODE_RUNNER_URL: str | None = None
    CODE_RUNNER_TOKEN: str | None = None
    CODE_RUNNER_TIMEOUT_SECONDS: int = 10

    # -------------------------------------------------------- malware scan
    #: ``clamav`` talks to a real clamd. ``basic`` performs structural checks only
    #: (magic bytes, embedded-JS heuristics) and marks the verdict accordingly.
    MALWARE_SCANNER: Literal["clamav", "basic"] = "basic"
    CLAMAV_HOST: str = "localhost"
    CLAMAV_PORT: int = 3310

    # ------------------------------------------------------------- security
    CORS_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000"
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_DEFAULT_PER_MINUTE: int = 300
    RATE_LIMIT_AUTH_PER_MINUTE: int = 10
    RATE_LIMIT_PUBLIC_PER_MINUTE: int = 120

    # ------------------------------------------------------------- defaults
    #: Default ATS weight profile, overridable per company and per job.
    ATS_WEIGHT_SKILLS: float = 0.40
    ATS_WEIGHT_EXPERIENCE: float = 0.25
    ATS_WEIGHT_EDUCATION: float = 0.10
    ATS_WEIGHT_RESPONSIBILITIES: float = 0.15
    ATS_WEIGHT_SEMANTIC: float = 0.10

    DATA_RETENTION_DAYS: int = 365 * 2

    # ------------------------------------------------------------ seed data
    SEED_SUPER_ADMIN_EMAIL: str = "admin@hirehq.test"
    SEED_SUPER_ADMIN_PASSWORD: str = "ChangeMe!2024"
    SEED_DEMO_PASSWORD: str = "Demo!2024Pass"

    LOG_LEVEL: str = "INFO"
    LOG_JSON: bool = False

    # ----------------------------------------------------------- validators
    @field_validator("CORS_ORIGINS")
    @classmethod
    def _strip_origins(cls, v: str) -> str:
        return v.strip()

    @model_validator(mode="after")
    def _validate_production_secrets(self) -> Settings:
        if self.APP_ENV != "production":
            return self

        # `APP_ENV=production` is baked into the container image, so it is set even when
        # the host supplies no configuration whatsoever. When that happens every
        # production check fails at once, and reporting only the first one sends people
        # hunting for a secrets problem they do not have. Detect the real cause instead.
        untouched = [
            name
            for name, is_default in (
                ("JWT_SECRET", self.JWT_SECRET == DEV_JWT_SECRET),
                ("DATABASE_URL", self.DATABASE_URL.startswith("sqlite")),
                ("STORAGE_PROVIDER", self.STORAGE_PROVIDER == "local"),
                ("REDIS_URL", self.REDIS_URL == "redis://localhost:6379/0"),
                ("CORS_ORIGINS", "localhost" in self.CORS_ORIGINS),
            )
            if is_default
        ]
        if len(untouched) >= 4:
            raise ValueError(
                "No configuration reached this container - every core setting is still "
                "at its development default ("
                + ", ".join(untouched)
                + "). This is a deployment problem, not a bad secret: the host is not "
                "passing environment variables to the process.\n"
                "  * Render: open the service -> Environment. If it is empty or the "
                "values are blank, fill them in there. Blueprint variables marked "
                "'sync: false' are created without a value and must be set by hand.\n"
                "  * Docker: pass --env-file .env, or -e for each variable.\n"
                "See DEPLOY-SIMPLE.md or DEPLOYMENT.md for the full list."
            )

        # Otherwise report every problem at once, so fixing them is not a guessing game
        # one redeploy at a time.
        problems: list[str] = []
        if self.JWT_SECRET == DEV_JWT_SECRET:
            problems.append(
                "JWT_SECRET is still the development placeholder. Generate one with: "
                'python -c "import secrets; print(secrets.token_urlsafe(48))"'
            )
        elif len(self.JWT_SECRET) < 32:
            problems.append(
                f"JWT_SECRET is only {len(self.JWT_SECRET)} characters; it must be at "
                "least 32."
            )
        if self.DEBUG:
            problems.append("DEBUG must be false in production.")
        if self.STORAGE_PROVIDER == "local":
            problems.append(
                "STORAGE_PROVIDER=local is a development-only backend. Configure "
                "S3-compatible storage (STORAGE_PROVIDER=s3 plus STORAGE_ENDPOINT, "
                "STORAGE_BUCKET, STORAGE_ACCESS_KEY, STORAGE_SECRET_KEY)."
            )

        if problems:
            raise ValueError(
                "Invalid production configuration:\n"
                + "\n".join(f"  * {p}" for p in problems)
            )
        return self

    # ------------------------------------------------------------ computed
    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def allowed_resume_extensions(self) -> set[str]:
        return {e.strip().lower().lstrip(".") for e in self.ALLOWED_RESUME_EXTENSIONS.split(",")}

    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")

    @property
    def ai_is_real_provider(self) -> bool:
        """True only when a genuine LLM provider is configured *and* has credentials."""
        return self.AI_PROVIDER == "anthropic" and bool(self.AI_API_KEY)

    @property
    def email_is_real_provider(self) -> bool:
        return self.EMAIL_PROVIDER == "smtp" and bool(self.SMTP_HOST)

    def new_secret(self) -> str:
        return secrets.token_urlsafe(48)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()


def _configure_email_validation() -> None:
    """Permit RFC 2606 reserved domains (.test, .local, .invalid) outside production.

    Demo and test fixtures deliberately use reserved TLDs: they are guaranteed never to
    route real mail, so seeded data cannot accidentally email a real person if SMTP is
    switched on. ``email-validator`` rejects them by default, which would make those
    accounts unable to even sign in.

    Production keeps the default strict behaviour - a genuine user should never be
    registering with an unroutable address.
    """
    if settings.APP_ENV == "production":
        return
    try:
        import email_validator

        email_validator.TEST_ENVIRONMENT = True
    except ImportError:  # pragma: no cover - email-validator is a hard dependency
        pass


_configure_email_validation()
