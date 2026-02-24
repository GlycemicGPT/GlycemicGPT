# Docker Integration Testing

## Overview

The Docker integration test verifies the full GlycemicGPT stack works correctly when deployed as Docker containers. It builds all services, waits for health checks, exercises the full API through the container network, and validates cross-service connectivity.

## Quick Start

```bash
# Run the full integration test (build + test + teardown)
./scripts/docker-integration-test.sh

# Skip build (if containers are already running)
./scripts/docker-integration-test.sh --no-build

# Keep containers running after test (for debugging)
./scripts/docker-integration-test.sh --no-down
```

## Test Compose Configuration

The integration tests use `docker-compose.test.yml` as an override to avoid conflicts with local development services:

| Service    | Dev Port | Test Port |
|------------|----------|-----------|
| PostgreSQL | 5432     | 5433      |
| Redis      | 6379     | 6380      |
| API        | 8000     | 8001      |
| Web        | 3000     | 3001      |

The test uses `COMPOSE_PROJECT_NAME=glycemicgpt-test` to fully isolate volumes, networks, and containers from local dev. All resources are cleaned up on teardown with `docker compose ... down -v`.

## What Gets Tested

### 1. Container Health and Infrastructure
- All 4 containers start and reach healthy state
- PostgreSQL, Redis, API, and Web containers running
- API `/health` returns `{"status": "healthy", "database": "connected"}`
- Liveness and readiness probes pass
- Database migrations applied automatically (alembic_version populated)
- Frontend reachable via HTTP

### 2. Authentication Flow
- User registration through containerized API
- Login and session management
- Authenticated endpoints return 200
- Disclaimer acceptance

### 3. Settings CRUD (End-to-End)
- Read and write glucose range settings (with round-trip verification)
- Brief delivery, alert thresholds, data retention
- Emergency contacts, escalation config, profile

### 4. AI and Insights
- AI provider config endpoint
- Insights list and unread count

### 5. Integrations
- Dexcom and Tandem status endpoints

### 6. Caregiver Features
- Caregiver list and invitation endpoints

### 7. SSE Real-Time Connection
- SSE endpoint accepts streaming connections through container network
- Validates `Content-Type: text/event-stream` response header

### 8. Cross-Service Communication
- Web container can reach API via internal Docker network (`http://api:8000`)
- API container connects to PostgreSQL
- API container connects to Redis

### 9. Container Image Validation
- Both images built successfully
- Web container runs as non-root user (nextjs)

### 10. Session Cleanup
- Logout invalidates session
- Post-logout requests return 401

## CI/CD Integration

The Docker integration test runs automatically via GitHub Actions (`.github/workflows/docker-integration.yml`):

- **Triggers:** Push/PR to main when app code, Docker config, or test scripts change
- **Timeout:** 15 minutes
- **On failure:** Full container logs are captured for debugging

## Manual Docker Testing

To manually test the containerized stack:

```bash
# Start with test overlay (COMPOSE_PROJECT_NAME isolates from dev)
COMPOSE_PROJECT_NAME=glycemicgpt-test \
  docker compose -f docker-compose.yml -f docker-compose.test.yml up --build -d

# Check service health
COMPOSE_PROJECT_NAME=glycemicgpt-test \
  docker compose -f docker-compose.yml -f docker-compose.test.yml ps

# View logs
COMPOSE_PROJECT_NAME=glycemicgpt-test \
  docker compose -f docker-compose.yml -f docker-compose.test.yml logs -f api

# Tear down (removes volumes too)
COMPOSE_PROJECT_NAME=glycemicgpt-test \
  docker compose -f docker-compose.yml -f docker-compose.test.yml down -v
```

## Troubleshooting

### Build fails for web container
- Ensure `output: "standalone"` is set in `next.config.ts`
- Check that `package-lock.json` is committed (required for `npm install`)

### API container exits immediately
- Check database is healthy: `docker compose ... logs db`
- Migration failures appear in: `docker compose ... logs api`
- Verify `apps/api/scripts/start.sh` is executable

### Services never become healthy
- API has a 40s startup grace period for health checks
- Database has a 50s total startup window (5 retries x 10s)
- Check for port conflicts with local services

### Web returns 502 or can't reach API
- Verify `API_URL=http://api:8000` is set (internal Docker network name)
- `NEXT_PUBLIC_API_URL=http://localhost:8001` is for browser-side requests
- Check API container is healthy before web starts (compose dependency)
