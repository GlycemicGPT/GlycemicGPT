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
LABEL org.opencontainers.image.source="https://github.com/GlycemicGPT/GlycemicGPT"
LABEL org.opencontainers.image.licenses="MIT"

WORKDIR /app

# Install system dependencies
# build-essential + cargo needed for fastembed's Rust-based tokenizers dependency
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    cargo \
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

# Vendored API docs assets -- self-hosted for CSP compliance and supply chain integrity.
# Versions tracked by Renovate (regex manager in .github/renovate.json5).
# When Renovate bumps a version, the SHA-256 hash will mismatch and the build
# will fail. To fix: download the new file, compute sha256sum, update the hash below.
RUN mkdir -p src/static/swagger-ui src/static/redoc && \
    curl -sfL -o src/static/swagger-ui/swagger-ui-bundle.js \
      "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.18.2/swagger-ui-bundle.js" && \
    echo "c50b94bbc4f02394326fb7aed1f4fb693b3677f4b3d3344e0d6131808cbf281f  src/static/swagger-ui/swagger-ui-bundle.js" | sha256sum -c - && \
    curl -sfL -o src/static/swagger-ui/swagger-ui.css \
      "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.18.2/swagger-ui.css" && \
    echo "8f33d996025317049d4a9864f421eab2b2a247872f388026fa94c654913259e7  src/static/swagger-ui/swagger-ui.css" | sha256sum -c - && \
    curl -sfL -o src/static/redoc/redoc.standalone.js \
      "https://cdn.jsdelivr.net/npm/redoc@2.2.0/bundles/redoc.standalone.js" && \
    echo "582ba875436fd6a561d285b97e39c90f06f90303ae7bbde3287748f73f2218a5  src/static/redoc/redoc.standalone.js" | sha256sum -c -

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
