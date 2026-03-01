"""GlycemicGPT FastAPI Application."""

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
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
    meal_analysis,
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
)

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


@app.get("/")
async def root() -> dict[str, Any]:
    """Root endpoint."""
    return {
        "name": "GlycemicGPT API",
        "docs": "/docs",
    }
