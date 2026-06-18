"""Application configuration using Pydantic Settings."""

import sys

from pydantic import Field
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
    # The scheduler now ticks on `tandem_sync_tick_interval_minutes`; on each
    # tick it scans connected Tandem users and runs the sync for any whose
    # per-user `sync_interval_minutes` (TandemSyncState, default below) has
    # elapsed since the credential's last_sync_at. `tandem_sync_enabled`
    # gates the whole job; `tandem_sync_interval_minutes` is the default
    # per-user cadence applied when a user has no TandemSyncState row.
    # Bounded at parse time: these feed APScheduler's IntervalTrigger, which
    # misbehaves on 0/negative/huge values. Default per-user cadence matches
    # the TandemSyncState column bounds (15-1440).
    tandem_sync_tick_interval_minutes: int = Field(default=15, ge=1, le=60)
    tandem_sync_interval_minutes: int = Field(default=60, ge=15, le=1440)
    tandem_sync_enabled: bool = True  # Enable/disable the whole job
    tandem_sync_hours_back: int = Field(default=24, ge=1, le=168)

    # Medtronic CareLink CarePartner (Connect) autonomous sync.
    # Operator kill switch for the background sync job, mirroring
    # dexcom/tandem/nightscout_sync_enabled (all default True, all gate only the
    # scheduler tick -- not the UI or endpoints). Set False via env to stop just
    # the Medtronic background sync (e.g. if it floods errors or hammers
    # CareLink) without a redeploy; users retain per-connection enable/disconnect
    # regardless. When enabled, the scheduler ticks every
    # `medtronic_connect_tick_interval_minutes` and runs the follower sync for
    # any connected user whose per-user `sync_interval_minutes`
    # (MedtronicConnectState) has elapsed. Bounded at parse time (feeds
    # APScheduler's IntervalTrigger).
    medtronic_connect_enabled: bool = True  # Enable/disable the whole job
    medtronic_connect_tick_interval_minutes: int = Field(default=15, ge=1, le=60)

    # Glooko (Omnipod Cloud Sync) autonomous sync. Operator kill switch for the
    # background sync job, mirroring the dexcom/tandem/medtronic flags (all default
    # True, all gate only the scheduler tick -- not the UI or endpoints). Set False
    # via env to stop just the Glooko background sync (e.g. if it floods errors or
    # hammers Glooko) without a redeploy; users retain per-connection
    # enable/disconnect regardless. The tick no-ops safely until a user connects.
    # When enabled, the scheduler ticks every `glooko_sync_tick_interval_minutes`
    # and runs the sync for any connected user whose per-user `sync_interval_minutes`
    # (GlookoSyncState) has elapsed. Bounded at parse time (feeds APScheduler's
    # IntervalTrigger).
    glooko_sync_enabled: bool = True  # Enable/disable the whole job
    glooko_sync_tick_interval_minutes: int = Field(default=15, ge=1, le=60)

    # Nightscout Sync Configuration (Story 43.4)
    # The scheduler ticks on a fixed interval; on each tick it scans
    # nightscout_connections and runs the per-connection sync for any
    # row whose `last_synced_at + sync_interval_minutes <= now()`.
    # Per-connection cadence is honored via the column on the connection
    # row, not via the global tick.
    nightscout_sync_enabled: bool = True
    # Bounded so a misconfigured env var (0 / negative / absurdly
    # large) can't crash APScheduler at startup or starve the
    # scheduler entirely. 1 minute = the per-connection minimum the
    # connection model already enforces; 60 minutes ceiling on the
    # global tick is generous (per-connection cadence is what users
    # actually tune).
    nightscout_sync_tick_interval_minutes: int = Field(default=1, ge=1, le=60)

    # Predictive Alert Engine (Story 6.2)
    alert_check_interval_minutes: int = 5  # Run alert engine every 5 minutes
    alert_check_enabled: bool = True  # Enable/disable automatic alert checking

    # Alert Escalation (Story 6.7)
    escalation_check_interval_minutes: int = 1  # Check every 1 minute
    escalation_check_enabled: bool = True  # Enable/disable automatic escalation

    # Daily brief auto-generation (issue #741)
    # Bounded like the sync-tick intervals: the value feeds IntervalTrigger, which
    # starves/crashes on zero/negative/absurd values.
    brief_check_interval_minutes: int = Field(default=5, ge=1, le=60)
    brief_scheduler_enabled: bool = True  # Enable/disable automatic daily briefs

    # Data Retention (Story 9.3)
    data_retention_enabled: bool = True
    data_retention_check_interval_hours: int = 24  # Run daily

    # Telegram Bot (Story 7.1)
    telegram_bot_token: str = ""
    telegram_polling_enabled: bool = True
    telegram_polling_interval_seconds: int = 5

    # AI Sidecar (Story 15.2)
    ai_sidecar_url: str = "http://ai-sidecar:3456"
    ai_sidecar_api_key: str = ""  # SIDECAR_API_KEY for inter-service auth

    # Food-photo uploads (meal-photo carb estimation)
    # Private, owner-scoped storage volume for meal photos. Never web-served;
    # files are re-encoded on upload (EXIF stripped). 5 MB cap mirrors the
    # sidecar's image limit. Vision carb estimation is opt-in behind this flag.
    upload_dir: str = "/uploads"
    food_image_max_bytes: int = Field(default=5 * 1024 * 1024, ge=1)
    meal_intelligence_enabled: bool = False
    # Timeout (seconds) for the sidecar vision call; longer than the text
    # timeout because a CLI vision provider can take tens of seconds.
    vision_request_timeout_seconds: float = Field(default=120.0, gt=0)
    # Multi-sample estimation (Story 50.H1). One photo is sampled this many times
    # in a single request; the confidence/range come from the observed spread,
    # not the model's (discredited) self-reported confidence. Cost guardrail:
    # ~N x vision tokens/estimate, so capped low (1 disables multi-sampling and
    # yields a single, necessarily low-confidence draw). 50.H4's variance harness
    # tunes the value against the accuracy-vs-cost curve.
    meal_estimate_sample_count: int = Field(default=3, ge=1, le=7)

    # Nutrition grounding (Story 50.E1). Estimates are grounded against the
    # user's own logged history (RAG) and published nutrition facts. The external
    # sources below are cacheable/redistributable (USDA = CC0/public domain; Open
    # Food Facts = ODbL) and fail open: a lookup error falls back to vision-only.
    # USDA FoodData Central needs a free data.gov API key, per-deployment (BYO or
    # bundled). Empty key -> USDA grounding is skipped (no error). 1k req/hr per
    # IP is plenty for a self-hoster.
    usda_fdc_api_key: str = ""
    usda_fdc_base_url: str = "https://api.nal.usda.gov/fdc/v1"
    # Open Food Facts needs no key (ODbL). Disable to opt out entirely.
    open_food_facts_enabled: bool = True
    open_food_facts_base_url: str = "https://world.openfoodfacts.org"
    # Hard per-call timeout for an external nutrition lookup; kept short so a slow
    # source never stalls the estimate path (it falls back to vision-only).
    nutrition_grounding_timeout_seconds: float = Field(default=6.0, gt=0)

    # Restaurant / fast-food grounding (Story 50.E2). A confirmed branded-chain
    # item (e.g. a McDonald's Quarter Pounder) is grounded against that chain's
    # OWN published nutrition, fetched on demand for that one item -- no
    # pre-crawl, no bulk mirror -- via the per-chain fetcher registry in
    # ``services/restaurant_nutrition.py``. Compliance mitigations (robots.txt,
    # rate-limit + back-off, descriptive User-Agent, user-action-triggered, and
    # OWNER-SCOPED caching -- never the shared mirror USDA/OFF use) are
    # non-negotiable. Disable to opt out of every restaurant fetch (falls back to
    # vision-only).
    restaurant_grounding_enabled: bool = True
    # Minimum seconds between successive fetches to the same chain host (a simple
    # per-host rate limit; a 429/503 adds exponential back-off on top).
    restaurant_min_seconds_between_fetches: float = Field(default=2.0, ge=0)
    # How long an owner-scoped restaurant cache entry stays fresh. Chain facts
    # change rarely, so a re-log inside this window reuses the cached value rather
    # than re-fetching. Owner-scoped only -- never pooled into a shared mirror.
    restaurant_cache_ttl_hours: float = Field(default=24 * 30, gt=0)

    # Optional FatSecret BYO-key add-on (Story 50.E2, AC5). Broader *commercial*
    # restaurant coverage via the operator's OWN FatSecret Platform credentials
    # (self-serve free tier). Empty -> disabled; no shared key is ever shipped.
    # FatSecret's terms cap value caching at 24 h, so FatSecret-sourced results are
    # cached owner-scoped for at most ``fatsecret_cache_ttl_hours`` and otherwise
    # queried fresh.
    fatsecret_consumer_key: str = ""
    fatsecret_consumer_secret: str = ""
    fatsecret_token_url: str = "https://oauth.fatsecret.com/connect/token"
    fatsecret_api_url: str = "https://platform.fatsecret.com/rest/server.api"
    # FatSecret's value-cache ToS limit (hours). Hard-capped at 24 h by intent.
    fatsecret_cache_ttl_hours: float = Field(default=24.0, gt=0, le=24.0)

    # Device & API key limits (Story 28.7)
    max_devices_per_user: int = Field(default=10, ge=1)
    debug_device_limit: int = Field(default=50, ge=1)
    debug_rate_limit_multiplier: int = Field(default=5, ge=1)

    # SSRF Prevention (Story 28.9)
    # Default True: this is a homelab-first app where AI providers (Ollama, etc.)
    # run on the same LAN. Cloud deployments should set ALLOW_PRIVATE_AI_URLS=false.
    allow_private_ai_urls: bool = True

    # Proxy Trust (Story 28.11 -- rate limit XFF bypass prevention)
    # Only trust X-Forwarded-For from these CIDR ranges.
    # Default: loopback only. Production deployments should add their load
    # balancer / reverse proxy CIDRs (e.g. "127.0.0.0/8,10.0.1.0/24").
    # Docker Compose: set TRUSTED_PROXY_CIDRS to include the Docker bridge
    # network (e.g. "127.0.0.0/8,172.16.0.0/12").
    trusted_proxy_cidrs: str = "127.0.0.0/8"

    # AI Research Pipeline (Story 35.12)
    research_pipeline_interval_hours: int = Field(default=168, ge=1)  # Weekly default
    research_pipeline_enabled: bool = True

    # Knowledge seed (issue #563 follow-up): set to True for air-gapped or
    # firewalled deployments so the seed does not trigger an embedding-model
    # download at startup. The model cache (~500 MB) must be pre-populated
    # in this mode (mount it at /home/glycemicgpt/.cache/fastembed). Seed
    # is skipped cleanly with an explicit log line; AI chat works without
    # bootstrap RAG augmentation.
    embedding_offline_only: bool = False

    # Sentry error monitoring (Sentry for Good). DISABLED by default: with no
    # DSN the SDK is a no-op and the running platform sends nothing. The DSN is
    # supplied only in the project's own dev/CI/staging via a runtime env var
    # and is never baked into a distributed build; self-hosters may set their
    # own DSN to send errors to their own Sentry. See PRIVACY.md.
    glycemicgpt_sentry_dsn: str = ""
    glycemicgpt_sentry_environment: str = "development"
    # Tracing off by default (errors only); bounded 0.0-1.0.
    glycemicgpt_sentry_traces_sample_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    # Release identifier (commit SHA), injected at build time via the Dockerfile
    # GIT_SHA build arg -> env. "unknown"/"" => no release tag.
    glycemicgpt_sentry_release: str = ""

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
