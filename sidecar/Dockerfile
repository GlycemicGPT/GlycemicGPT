# AI Sidecar Container
# Bundles Claude Code CLI + Codex CLI + Express proxy server
#
# Build: docker build -t glycemicgpt-ai-sidecar .
# Run:   docker run -p 3456:3456 glycemicgpt-ai-sidecar

FROM node:22-slim AS base

# Install curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Install Claude Code CLI and Codex CLI globally
# claude-code 2.x provides the `claude` binary for subscription proxy
# codex 0.x provides the `codex` binary for ChatGPT subscription proxy
RUN npm install -g @anthropic-ai/claude-code@latest @openai/codex@latest

# Create non-root user
RUN groupadd --gid 1001 sidecar && \
    useradd --uid 1001 --gid sidecar --create-home --shell /bin/bash sidecar

# Build stage
FROM base AS builder
WORKDIR /app
COPY package.json ./
RUN npm install
COPY tsconfig.json ./
COPY src/ src/
RUN npx tsc

# Production stage
FROM base AS production
WORKDIR /app

COPY package.json ./
RUN npm install --omit=dev

COPY --from=builder /app/dist/ dist/

# Create token storage directory (will be volume-mounted)
RUN mkdir -p /home/sidecar/.config/sidecar /home/sidecar/.codex && \
    chown -R sidecar:sidecar /home/sidecar /app

USER sidecar

# Surface the build commit so Sentry can tag the release (no-op when unset/"unknown").
# CI passes GIT_SHA as a build-arg; see src/observability.ts and PRIVACY.md.
ARG GIT_SHA=unknown
ENV GLYCEMICGPT_SIDECAR_SENTRY_RELEASE=${GIT_SHA}
ENV NODE_ENV=production
ENV SIDECAR_PORT=3456
ENV TOKEN_DIR=/home/sidecar/.config/sidecar
ENV HOME=/home/sidecar

EXPOSE 3456

HEALTHCHECK --interval=15s --timeout=5s --retries=3 --start-period=10s \
  CMD curl -f http://localhost:3456/health || exit 1

CMD ["node", "dist/server.js"]
