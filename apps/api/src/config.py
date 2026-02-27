"""Application configuration using Pydantic Settings."""

import sys

from pydantic_settings import BaseSettings, SettingsConfigDict

_INSECURE_DEFAULT_SECRET = "change-me-in-production"
_MIN_SECRET_LENGTH = 32


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    # Database
    database_url: str = (
        "postgresql+asyncpg://glycemicgpt:glycemicgpt@localhost:5432/glycemicgpt"
    )

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Security
    secret_key: str = _INSECURE_DEFAULT_SECRET
    encryption_key: str = (
        ""  # Separate key for credential encryption; falls back to secret_key
    )
    jwt_algorithm: str = "HS256"
    jwt_cookie_name: str = "glycemicgpt_session"

    # Logging
    log_format: str = "json"  # 'json' or 'text'
    log_level: str = "INFO"
    service_name: str = "glycemicgpt-api"

    # CORS
    cors_origins: list[str] = ["http://localhost:3000"]

    # Session
    session_expire_hours: int = 24
    # Mobile token lifetimes (Story 16.12)
    access_token_expire_minutes: int = 60  # 1 hour for mobile access tokens
    refresh_token_expire_days: int = 30  # 30 days for mobile refresh tokens
    cookie_secure: bool = (
        True  # Set to False for plain HTTP (e.g. Docker integration tests)
    )

    # Backup Configuration (Story 1.5)
    backup_enabled: bool = True
    backup_schedule: str = "0 2 * * *"  # Cron: daily at 2 AM
    backup_path: str = "/backups"
    backup_retention_days: int = 7
    # Sync database URL for pg_dump (no asyncpg)
    database_sync_url: str = (
        "postgresql://glycemicgpt:glycemicgpt@localhost:5432/glycemicgpt"
    )

    # Data Sync Configuration (Story 3.2)
    dexcom_sync_interval_minutes: int = 5  # Sync every 5 minutes
    dexcom_sync_enabled: bool = True  # Enable/disable automatic sync
    dexcom_max_readings_per_sync: int = 12  # Max readings to fetch per sync (1 hour)

    # Tandem Sync Configuration (Story 3.4)
    tandem_sync_interval_minutes: int = 60  # Sync every hour
    tandem_sync_enabled: bool = True  # Enable/disable automatic sync
    tandem_sync_hours_back: int = 24  # Hours of history to fetch per sync

    # Predictive Alert Engine (Story 6.2)
    alert_check_interval_minutes: int = 5  # Run alert engine every 5 minutes
    alert_check_enabled: bool = True  # Enable/disable automatic alert checking

    # Alert Escalation (Story 6.7)
    escalation_check_interval_minutes: int = 1  # Check every 1 minute
    escalation_check_enabled: bool = True  # Enable/disable automatic escalation

    # Data Retention (Story 9.3)
    data_retention_enabled: bool = True
    data_retention_check_interval_hours: int = 24  # Run daily

    # Telegram Bot (Story 7.1)
    telegram_bot_token: str = ""
    telegram_polling_enabled: bool = True
    telegram_polling_interval_seconds: int = 5

    # Tandem Cloud Upload (Story 16.6)
    tandem_upload_enabled: bool = True
    tandem_upload_check_interval_minutes: int = 1  # Check for due uploads every minute
    tandem_upload_config_base: str = "https://assets.tandemdiabetes.com"

    # AI Sidecar (Story 15.2)
    ai_sidecar_url: str = "http://ai-sidecar:3456"
    ai_sidecar_api_key: str = ""  # SIDECAR_API_KEY for inter-service auth

    # SSRF Prevention (Story 28.9)
    # Default True: this is a homelab-first app where AI providers (Ollama, etc.)
    # run on the same LAN. Cloud deployments should set ALLOW_PRIVATE_AI_URLS=false.
    allow_private_ai_urls: bool = True

    # Testing
    testing: bool = False  # Set to True during tests to disable connection pooling


settings = Settings()


def validate_secret_key() -> None:
    """Validate that secret_key is safe for production use.

    Rejects the insecure default and enforces minimum length.
    Skipped during tests (TESTING=true) to avoid requiring a real secret.
    """
    if settings.testing:
        return

    if (
        settings.secret_key == _INSECURE_DEFAULT_SECRET
        or settings.secret_key.startswith("change-me")
    ):
        print(
            "FATAL: SECRET_KEY is set to an insecure default. "
            "Set a strong SECRET_KEY environment variable (>= 32 characters). "
            "Generate one with: openssl rand -hex 32",
            file=sys.stderr,
        )
        sys.exit(1)

    if len(settings.secret_key) < _MIN_SECRET_LENGTH:
        print(
            f"FATAL: SECRET_KEY must be at least {_MIN_SECRET_LENGTH} characters "
            f"(currently {len(settings.secret_key)}).",
            file=sys.stderr,
        )
        sys.exit(1)

    if settings.encryption_key and len(settings.encryption_key) < _MIN_SECRET_LENGTH:
        print(
            f"FATAL: ENCRYPTION_KEY must be at least {_MIN_SECRET_LENGTH} characters "
            f"(currently {len(settings.encryption_key)}).",
            file=sys.stderr,
        )
        sys.exit(1)

    if not settings.encryption_key:
        print(
            "WARNING: ENCRYPTION_KEY not set; falling back to SECRET_KEY for "
            "credential encryption. Set a separate ENCRYPTION_KEY for defense-in-depth.",
            file=sys.stderr,
        )
