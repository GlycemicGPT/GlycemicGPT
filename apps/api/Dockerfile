# GlycemicGPT API Dockerfile
ARG VERSION=0.0.0
ARG BUILD_DATE=unknown
ARG GIT_SHA=unknown

FROM python:3.14-slim

# Labels
LABEL org.opencontainers.image.title="GlycemicGPT API"
LABEL org.opencontainers.image.description="FastAPI backend for GlycemicGPT diabetes management platform"
LABEL org.opencontainers.image.version="${VERSION}"
LABEL org.opencontainers.image.created="${BUILD_DATE}"
LABEL org.opencontainers.image.revision="${GIT_SHA}"
LABEL org.opencontainers.image.source="https://github.com/jlengelbrecht/GlycemicGPT"
LABEL org.opencontainers.image.licenses="MIT"

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast package management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency files and README for package metadata
COPY pyproject.toml README.md ./

# Copy source code (needed for package install)
COPY src/ ./src/

# Install dependencies using uv
# Verify pkg_resources is importable (required by tconnectsync at runtime,
# provided by setuptools <82 — removed in 82+)
RUN uv pip install --system --no-cache . && \
    python -c "import pkg_resources"

# Copy remaining files
COPY migrations/ ./migrations/
COPY alembic.ini ./
COPY scripts/ ./scripts/

# Make start script executable
RUN chmod +x ./scripts/start.sh

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run migrations and start the application
CMD ["./scripts/start.sh"]
