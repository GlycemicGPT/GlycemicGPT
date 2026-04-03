"""GlycemicGPT FastAPI Application."""

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded

from src.config import settings, validate_secret_key
from src.database import close_database
from src.logging_config import get_logger, setup_logging
from src.middleware import CorrelationIdMiddleware
from src.middleware.csrf import CSRFMiddleware
from src.middleware.rate_limit import limiter, rate_limit_exceeded_handler
from src.middleware.security_headers import SecurityHeadersMiddleware
from src.routers import (
    ai,
    alert_api,
    alert_stream,
    alerts,
    api_keys,
    auth,
    briefs,
    caregivers,
    correction_analysis,
    device_registration,
    disclaimer,
    emergency_contacts,
    escalation,
    glucose_stream,
    health,
    insights,
    integrations,
    knowledge,
    meal_analysis,
    research,
    safety,
    system,
    telegram,
    treatment,
)
from src.routers import (
    settings as settings_router,
)
from src.services.scheduler import start_scheduler, stop_scheduler

# Configure structured logging (Story 1.5)
setup_logging(
    log_format=settings.log_format,
    log_level=settings.log_level,
    service_name=settings.service_name,
)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    validate_secret_key()
    # Note: Migrations are run by scripts/start.sh before uvicorn starts
    logger.info("GlycemicGPT API started")

    # Start background scheduler (Story 3.2)
    start_scheduler()
    logger.info("Background scheduler started")

    # Preload embedding model for RAG retrieval (Story 35.9)
    # Model downloads ~500MB on first run, then caches in Docker volume.
    try:
        from src.services.embedding import preload_model

        preload_model()
    except Exception:
        logger.warning("Embedding model preload failed", exc_info=True)

    yield

    # Shutdown
    logger.info("Shutting down GlycemicGPT API...")
    stop_scheduler()
    logger.info("Background scheduler stopped")
    await close_database()
    logger.info("GlycemicGPT API shutdown complete")


app = FastAPI(
    title="GlycemicGPT API",
    description="AI-powered diabetes management API",
    lifespan=lifespan,
    docs_url=None,  # Disabled: custom self-hosted route below
    redoc_url=None,  # Disabled: custom self-hosted route below
)

# Mount static files for self-hosted API docs assets (Swagger UI, ReDoc).
# Eliminates CDN dependency and resolves CSP/SRI/cross-domain findings.
_static_dir = Path(__file__).resolve().parent / "static"
if _static_dir.is_dir():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

# Rate limiting (Story 16.12)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

# Middleware (order matters: last added = first executed on incoming requests)
# Add security response headers (Story 28.13)
app.add_middleware(SecurityHeadersMiddleware)

# Add correlation ID middleware for request tracing (Story 1.5)
app.add_middleware(CorrelationIdMiddleware)

# Add CSRF protection middleware (Story 28.4)
app.add_middleware(CSRFMiddleware)

# Add CORS middleware as outermost (added last) so all responses carry CORS
# headers -- including CSRF 403 rejections that short-circuit inner middleware.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "Accept",
        "X-CSRF-Token",
        "X-Correlation-ID",
        "X-API-Key",
    ],
)

# Include routers
app.include_router(health.router)
app.include_router(disclaimer.router)
app.include_router(auth.router)
app.include_router(system.router)
app.include_router(integrations.router)
app.include_router(glucose_stream.router)
app.include_router(ai.router)
app.include_router(briefs.router)
app.include_router(meal_analysis.router)
app.include_router(correction_analysis.router)
app.include_router(safety.router)
app.include_router(insights.router)
app.include_router(settings_router.router)
app.include_router(alerts.router)
app.include_router(emergency_contacts.router)
app.include_router(escalation.router)
app.include_router(telegram.router)
app.include_router(caregivers.router)
app.include_router(device_registration.router)
app.include_router(api_keys.router)
app.include_router(alert_stream.router)
app.include_router(alert_api.router)
app.include_router(treatment.router)
app.include_router(research.router)
app.include_router(knowledge.router)


@app.get("/")
async def root() -> dict[str, Any]:
    """Root endpoint."""
    return {
        "name": "GlycemicGPT API",
        "docs": "/docs",
    }


# Self-hosted API documentation routes.
# Assets are vendored in the Docker image (downloaded at build time from pinned
# CDN versions). This eliminates cross-domain script loading, adds CSP headers,
# and removes the CDN supply chain dependency.
# CSP for /docs and /redoc pages. FastAPI's get_swagger_ui_html() generates an
# inline <script> block to initialize SwaggerUIBundle, requiring 'unsafe-inline'.
# All directives are explicit (no fallback to default-src) per ZAP best practice.
_CSP_DOCS = (
    "default-src 'none'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "form-action 'self'; "
    "base-uri 'self'"
)


@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui():
    """Swagger UI with self-hosted assets and CSP header."""
    response = get_swagger_ui_html(
        openapi_url=app.openapi_url or "/openapi.json",
        title=f"{app.title} - Swagger UI",
        swagger_js_url="/static/swagger-ui/swagger-ui-bundle.js",
        swagger_css_url="/static/swagger-ui/swagger-ui.css",
    )
    response.headers["Content-Security-Policy"] = _CSP_DOCS
    return response


@app.get("/redoc", include_in_schema=False)
async def custom_redoc():
    """ReDoc with self-hosted assets and CSP header."""
    response = get_redoc_html(
        openapi_url=app.openapi_url or "/openapi.json",
        title=f"{app.title} - ReDoc",
        redoc_js_url="/static/redoc/redoc.standalone.js",
        with_google_fonts=False,
    )
    response.headers["Content-Security-Policy"] = _CSP_DOCS
    return response
