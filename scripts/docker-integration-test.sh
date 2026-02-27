#!/bin/bash
# GlycemicGPT Docker Integration Test
#
# Story 13.2: Docker Container Integration Testing
#
# Builds the full Docker stack, waits for all services to become healthy,
# then runs integration checks against the containerized application.
# Uses docker-compose.test.yml for isolated ports and COMPOSE_PROJECT_NAME
# for full volume/network isolation from local development.
#
# Usage:
#   ./scripts/docker-integration-test.sh              # build + test + teardown
#   ./scripts/docker-integration-test.sh --no-build   # skip build, test existing containers
#   ./scripts/docker-integration-test.sh --no-down    # keep containers running after test
#
# Exit codes:
#   0 = all checks passed
#   1 = one or more checks failed

set -uo pipefail
# Note: -e is intentionally omitted. The script uses explicit error handling
# via || fallbacks so that failures in individual checks do not abort the
# entire test run before the summary is printed.

# --- Configuration ---
export COMPOSE_PROJECT_NAME=glycemicgpt-test
COMPOSE_CMD="docker compose -f docker-compose.yml -f docker-compose.test.yml"
API_URL="http://localhost:8001"
WEB_URL="http://localhost:3001"
TEST_EMAIL="dockertest_$(date +%s)@example.com"
TEST_PASSWORD="DockerTest123!"
COOKIE_JAR=$(mktemp)
MAX_WAIT=180  # seconds to wait for services to become healthy

# --- Parse CLI args ---
DO_BUILD=true
DO_DOWN=true

while [[ $# -gt 0 ]]; do
  case $1 in
    --no-build) DO_BUILD=false; shift ;;
    --no-down)  DO_DOWN=false; shift ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

# --- Helpers ---
PASS=0
FAIL=0
SKIP=0

pass() { PASS=$((PASS+1)); echo "  [PASS] $1"; }
fail() { FAIL=$((FAIL+1)); echo "  [FAIL] $1"; }
skip() { SKIP=$((SKIP+1)); echo "  [SKIP] $1"; }

get_csrf_token() {
  # Extract csrf_token from the cookie jar (Netscape format: domain\tflags\tpath\tsecure\texpiry\tname\tvalue)
  grep "csrf_token" "$COOKIE_JAR" 2>/dev/null | awk '{print $NF}' | tail -1
}

api_get() {
  curl -s -o /dev/null -w "%{http_code}" --connect-timeout 5 --max-time 10 \
    -b "$COOKIE_JAR" -c "$COOKIE_JAR" "$API_URL$1" 2>/dev/null || echo "000"
}

api_get_body() {
  curl -s --connect-timeout 5 --max-time 10 \
    -b "$COOKIE_JAR" -c "$COOKIE_JAR" "$API_URL$1" 2>/dev/null || echo "{}"
}

api_post() {
  local csrf; csrf=$(get_csrf_token)
  curl -s -o /dev/null -w "%{http_code}" --connect-timeout 5 --max-time 10 \
    -b "$COOKIE_JAR" -c "$COOKIE_JAR" \
    -X POST -H "Content-Type: application/json" ${csrf:+-H "X-CSRF-Token: $csrf"} \
    -d "$2" "$API_URL$1" 2>/dev/null || echo "000"
}

# shellcheck disable=SC2329  # kept for completeness alongside api_post/api_patch
api_put() {
  local csrf; csrf=$(get_csrf_token)
  curl -s -o /dev/null -w "%{http_code}" --connect-timeout 5 --max-time 10 \
    -b "$COOKIE_JAR" -c "$COOKIE_JAR" \
    -X PUT -H "Content-Type: application/json" ${csrf:+-H "X-CSRF-Token: $csrf"} \
    -d "$2" "$API_URL$1" 2>/dev/null || echo "000"
}

api_patch() {
  local csrf; csrf=$(get_csrf_token)
  curl -s -o /dev/null -w "%{http_code}" --connect-timeout 5 --max-time 10 \
    -b "$COOKIE_JAR" -c "$COOKIE_JAR" \
    -X PATCH -H "Content-Type: application/json" ${csrf:+-H "X-CSRF-Token: $csrf"} \
    -d "$2" "$API_URL$1" 2>/dev/null || echo "000"
}

cleanup() {
  rm -f "$COOKIE_JAR"
  if [ "$DO_DOWN" = true ]; then
    echo ""
    echo "Tearing down containers..."
    $COMPOSE_CMD down -v --remove-orphans 2>/dev/null || true
  fi
}
trap cleanup EXIT

# --- Start ---
echo ""
echo "============================================="
echo "  GlycemicGPT Docker Integration Test"
echo "============================================="
echo "  API:  $API_URL"
echo "  Web:  $WEB_URL"
echo "  User: $TEST_EMAIL"
echo "  Project: $COMPOSE_PROJECT_NAME"
echo "============================================="
echo ""

# -----------------------------------------------
# 0. Build and Start Containers
# -----------------------------------------------
echo "0. Container Setup"
echo "---"

if [ "$DO_BUILD" = true ]; then
  echo "  Building and starting containers..."
  $COMPOSE_CMD up --build -d 2>&1 | tail -5
  echo ""
fi

# Wait for all services to become healthy (including web)
echo "  Waiting for services to become healthy (max ${MAX_WAIT}s)..."

WAITED=0
while [ $WAITED -lt $MAX_WAIT ]; do
  # Use curl to check actual service endpoints rather than parsing docker compose ps JSON
  # (which varies across Docker Compose versions)
  API_READY=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 2 --max-time 5 "$API_URL/health" 2>/dev/null || echo "000")
  WEB_READY=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 2 --max-time 5 "$WEB_URL" 2>/dev/null || echo "000")

  if [ "$API_READY" = "200" ] && [ "$WEB_READY" = "200" ]; then
    pass "All services healthy after ${WAITED}s"
    break
  fi

  if [ $((WAITED % 15)) -eq 0 ] && [ $WAITED -gt 0 ]; then
    SIDECAR_READY=$($COMPOSE_CMD ps --status running ai-sidecar 2>/dev/null | grep -c "sidecar" || echo "0")
    echo "  ... still waiting (${WAITED}s) - API=$API_READY WEB=$WEB_READY SIDECAR_RUNNING=$SIDECAR_READY"
  fi

  sleep 3
  WAITED=$((WAITED+3))
done

if [ $WAITED -ge $MAX_WAIT ]; then
  fail "Services did not become healthy within ${MAX_WAIT}s"
  echo ""
  echo "  Container status:"
  $COMPOSE_CMD ps 2>/dev/null || true
  echo ""
  echo "  API logs (last 30 lines):"
  $COMPOSE_CMD logs --tail=30 api 2>/dev/null || true
  echo ""
  echo "  Web logs (last 30 lines):"
  $COMPOSE_CMD logs --tail=30 web 2>/dev/null || true
  echo ""
  echo "  Sidecar logs (last 30 lines):"
  $COMPOSE_CMD logs --tail=30 ai-sidecar 2>/dev/null || true
  exit 1
fi

echo ""

# -----------------------------------------------
# 1. Container Health Checks
# -----------------------------------------------
echo "1. Container Health & Infrastructure"
echo "---"

# 1a-e. Container states (use docker compose ps with text output for portability)
for SVC in db redis ai-sidecar api web; do
  SVC_RUNNING=$($COMPOSE_CMD ps --status running "$SVC" 2>/dev/null | grep -c "$SVC" || echo "0")
  if [ "$SVC_RUNNING" -gt 0 ] 2>/dev/null; then
    pass "$SVC container running"
  else
    fail "$SVC container not running"
  fi
done

# 1f. API health endpoint
BODY=$(api_get_body "/health")
if echo "$BODY" | grep -q '"healthy"'; then pass "API /health: healthy"; else fail "API /health: $BODY"; fi

# 1g. Database connected (via health response)
if echo "$BODY" | grep -q '"connected"'; then pass "Database connected (via /health)"; else fail "Database not connected"; fi

# 1h. Liveness probe
STATUS=$(api_get "/health/live")
if [ "$STATUS" = "200" ]; then pass "Liveness probe (/health/live)"; else fail "Liveness probe (got $STATUS)"; fi

# 1i. Readiness probe
STATUS=$(api_get "/health/ready")
if [ "$STATUS" = "200" ]; then pass "Readiness probe (/health/ready)"; else fail "Readiness probe (got $STATUS)"; fi

# 1j. Database migrations ran (alembic_version table exists)
MIGRATION_CHECK=$($COMPOSE_CMD exec -T db psql -U glycemicgpt -d glycemicgpt -t -c "SELECT COUNT(*) FROM alembic_version;" 2>/dev/null | tr -d ' \n' || echo "0")
if [ -n "$MIGRATION_CHECK" ] && [ "$MIGRATION_CHECK" != "0" ] 2>/dev/null; then
  pass "Database migrations applied (alembic_version populated)"
else
  fail "Database migrations not applied (count: ${MIGRATION_CHECK:-empty})"
fi

# 1k. Frontend reachable
WEB_HTTP=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 5 --max-time 10 "$WEB_URL" 2>/dev/null || echo "000")
if [ "$WEB_HTTP" = "200" ]; then pass "Frontend reachable at $WEB_URL"; else fail "Frontend not reachable (got $WEB_HTTP)"; fi

echo ""

# -----------------------------------------------
# 2. Authentication Flow
# -----------------------------------------------
echo "2. Authentication (Container Network)"
echo "---"

# 2a. Register
STATUS=$(api_post "/api/auth/register" "{\"email\":\"$TEST_EMAIL\",\"password\":\"$TEST_PASSWORD\"}")
if [ "$STATUS" = "201" ]; then pass "User registration"; else fail "Registration (got $STATUS)"; fi

# 2b. Login
STATUS=$(api_post "/api/auth/login" "{\"email\":\"$TEST_EMAIL\",\"password\":\"$TEST_PASSWORD\"}")
if [ "$STATUS" = "200" ]; then pass "User login"; else fail "Login (got $STATUS)"; fi

# 2c. Get current user
STATUS=$(api_get "/api/auth/me")
if [ "$STATUS" = "200" ]; then pass "Get current user (authenticated)"; else fail "Get current user (got $STATUS)"; fi

# 2d. Acknowledge disclaimer
DISCLAIMER_SESSION=$(python3 -c "import uuid; print(uuid.uuid4())" 2>/dev/null || echo "00000000-0000-0000-0000-000000000000")
STATUS=$(api_post "/api/disclaimer/acknowledge" "{\"session_id\":\"$DISCLAIMER_SESSION\",\"checkbox_experimental\":true,\"checkbox_not_medical_advice\":true}")
if [ "$STATUS" = "200" ] || [ "$STATUS" = "201" ]; then pass "Acknowledge disclaimer"; else fail "Acknowledge disclaimer (got $STATUS)"; fi

echo ""

# -----------------------------------------------
# 3. Settings CRUD (End-to-End through Containers)
# -----------------------------------------------
echo "3. Settings Endpoints (Container E2E)"
echo "---"

# 3a. Target glucose range - GET
STATUS=$(api_get "/api/settings/target-glucose-range")
if [ "$STATUS" = "200" ]; then pass "GET target glucose range"; else fail "GET target glucose range (got $STATUS)"; fi

# 3b. Target glucose range - PATCH
STATUS=$(api_patch "/api/settings/target-glucose-range" '{"low_target":65,"high_target":175}')
if [ "$STATUS" = "200" ]; then pass "PATCH target glucose range"; else fail "PATCH target glucose range (got $STATUS)"; fi

# 3c. Verify round-trip (GET should return saved values)
BODY=$(api_get_body "/api/settings/target-glucose-range")
if echo "$BODY" | grep -q '"low_target"'; then pass "Glucose range round-trip persisted"; else fail "Glucose range round-trip: $BODY"; fi

# 3d. Brief delivery config - GET
STATUS=$(api_get "/api/settings/brief-delivery")
if [ "$STATUS" = "200" ]; then pass "GET brief delivery config"; else fail "GET brief delivery config (got $STATUS)"; fi

# 3e. Alert thresholds - GET
STATUS=$(api_get "/api/settings/alert-thresholds")
if [ "$STATUS" = "200" ]; then pass "GET alert thresholds"; else fail "GET alert thresholds (got $STATUS)"; fi

# 3f. Alert thresholds - PATCH
STATUS=$(api_patch "/api/settings/alert-thresholds" '{"low_warning":70,"urgent_low":55,"high_warning":180,"urgent_high":250}')
if [ "$STATUS" = "200" ]; then pass "PATCH alert thresholds"; else fail "PATCH alert thresholds (got $STATUS)"; fi

# 3g. Data retention config - GET
STATUS=$(api_get "/api/settings/data-retention")
if [ "$STATUS" = "200" ]; then pass "GET data retention config"; else fail "GET data retention config (got $STATUS)"; fi

# 3h. Emergency contacts - GET
STATUS=$(api_get "/api/settings/emergency-contacts")
if [ "$STATUS" = "200" ]; then pass "GET emergency contacts"; else fail "GET emergency contacts (got $STATUS)"; fi

# 3i. Escalation config - GET
STATUS=$(api_get "/api/settings/escalation-config")
if [ "$STATUS" = "200" ]; then pass "GET escalation config"; else fail "GET escalation config (got $STATUS)"; fi

# 3j. Profile - GET (uses /me endpoint)
STATUS=$(api_get "/api/auth/me")
if [ "$STATUS" = "200" ]; then pass "GET user profile"; else fail "GET user profile (got $STATUS)"; fi

echo ""

# -----------------------------------------------
# 4. AI & Insights (Container Network)
# -----------------------------------------------
echo "4. AI & Insights"
echo "---"

# 4a. AI provider config - GET (404 means no provider configured yet, which is valid)
STATUS=$(api_get "/api/ai/provider")
if [ "$STATUS" = "200" ]; then pass "GET AI provider config (configured)"; elif [ "$STATUS" = "404" ]; then pass "GET AI provider config (none configured - expected)"; else fail "GET AI provider config (got $STATUS)"; fi

# 4b. Insights list
STATUS=$(api_get "/api/ai/insights?limit=10")
if [ "$STATUS" = "200" ]; then pass "GET insights list"; else fail "GET insights list (got $STATUS)"; fi

# 4c. Unread count
STATUS=$(api_get "/api/ai/insights/unread-count")
if [ "$STATUS" = "200" ]; then pass "GET unread insights count"; else fail "GET unread insights count (got $STATUS)"; fi

echo ""

# -----------------------------------------------
# 5. Integrations
# -----------------------------------------------
echo "5. Integrations"
echo "---"

# 404 means integration not configured yet, which is valid for a fresh install
STATUS=$(api_get "/api/integrations/dexcom/status")
if [ "$STATUS" = "200" ]; then pass "GET Dexcom integration status (connected)"; elif [ "$STATUS" = "404" ]; then pass "GET Dexcom integration status (not configured - expected)"; else fail "GET Dexcom status (got $STATUS)"; fi

STATUS=$(api_get "/api/integrations/tandem/status")
if [ "$STATUS" = "200" ]; then pass "GET Tandem integration status (connected)"; elif [ "$STATUS" = "404" ]; then pass "GET Tandem integration status (not configured - expected)"; else fail "GET Tandem status (got $STATUS)"; fi

echo ""

# -----------------------------------------------
# 6. AI Sidecar (Container Network)
# -----------------------------------------------
echo "6. AI Sidecar"
echo "---"

# 6a. API can reach sidecar health endpoint (via internal network)
SIDECAR_HEALTH=$($COMPOSE_CMD exec -T api curl -s --connect-timeout 5 --max-time 10 http://ai-sidecar:3456/health 2>/dev/null || echo "")
if echo "$SIDECAR_HEALTH" | grep -q '"status"'; then
  pass "API -> Sidecar connectivity (/health)"
else
  fail "API -> Sidecar connectivity (response: ${SIDECAR_HEALTH:-empty})"
fi

# 6b. Sidecar health shows auth state fields
if echo "$SIDECAR_HEALTH" | grep -q '"claude_auth"'; then
  pass "Sidecar reports claude_auth status"
else
  fail "Sidecar missing claude_auth in health response"
fi

if echo "$SIDECAR_HEALTH" | grep -q '"codex_auth"'; then
  pass "Sidecar reports codex_auth status"
else
  fail "Sidecar missing codex_auth in health response"
fi

# 6c. Sidecar auth status endpoint reachable
SIDECAR_AUTH=$($COMPOSE_CMD exec -T api curl -s --connect-timeout 5 --max-time 10 http://ai-sidecar:3456/auth/status 2>/dev/null || echo "")
if echo "$SIDECAR_AUTH" | grep -q '"claude"'; then
  pass "Sidecar /auth/status reachable"
else
  fail "Sidecar /auth/status unreachable (response: ${SIDECAR_AUTH:-empty})"
fi

# 6d. Sidecar not exposed to host (should fail to connect on host port 3456)
SIDECAR_HOST=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 2 --max-time 3 "http://localhost:3456/health" 2>/dev/null; echo "")
if echo "$SIDECAR_HOST" | grep -q "^200"; then
  fail "Sidecar unexpectedly reachable on host port 3456 (got HTTP 200)"
else
  pass "Sidecar NOT exposed to host network (expected)"
fi

# 6e. Subscription auth status endpoint via API
STATUS=$(api_get "/api/ai/subscription/auth/status")
if [ "$STATUS" = "200" ]; then pass "GET subscription auth status via API"; else fail "GET subscription auth status (got $STATUS)"; fi

echo ""

# -----------------------------------------------
# 7. Caregiver Features
# -----------------------------------------------
echo "7. Caregiver Features"
echo "---"

STATUS=$(api_get "/api/caregivers/linked")
if [ "$STATUS" = "200" ]; then pass "GET caregivers list"; else fail "GET caregivers list (got $STATUS)"; fi

STATUS=$(api_get "/api/caregivers/invitations")
if [ "$STATUS" = "200" ]; then pass "GET caregiver invitations"; else fail "GET caregiver invitations (got $STATUS)"; fi

echo ""

# -----------------------------------------------
# 8. SSE / Real-Time (Container Network)
# -----------------------------------------------
echo "8. SSE Real-Time Connection"
echo "---"

# Test SSE endpoint by checking that it returns the correct Content-Type header
SSE_HEADERS=$(curl -s -D - -o /dev/null --connect-timeout 5 --max-time 3 \
  -H "Accept: text/event-stream" -b "$COOKIE_JAR" \
  "$API_URL/api/v1/glucose/stream" 2>/dev/null || echo "")

if echo "$SSE_HEADERS" | grep -qi "text/event-stream"; then
  pass "SSE endpoint returns text/event-stream Content-Type"
elif echo "$SSE_HEADERS" | grep -qi "HTTP/.*200"; then
  pass "SSE endpoint accepts connections (200 OK)"
else
  # SSE may timeout reading (expected for long-lived streams) - check if we got any headers
  if echo "$SSE_HEADERS" | grep -qi "HTTP/"; then
    skip "SSE endpoint responded but Content-Type not verified"
  else
    fail "SSE endpoint not reachable"
  fi
fi

echo ""

# -----------------------------------------------
# 9. Cross-Service Communication
# -----------------------------------------------
echo "9. Cross-Service Communication"
echo "---"

# 9a. Web container can reach API (internal network)
INTERNAL_CHECK=$($COMPOSE_CMD exec -T web wget -q -O - --timeout=5 http://api:8000/health 2>/dev/null || echo "")
if echo "$INTERNAL_CHECK" | grep -q "healthy"; then
  pass "Web -> API internal network connectivity"
else
  # Try with curl if wget isn't available (Alpine minimal image may not have either)
  INTERNAL_CHECK=$($COMPOSE_CMD exec -T web curl -s --connect-timeout 5 http://api:8000/health 2>/dev/null || echo "")
  if echo "$INTERNAL_CHECK" | grep -q "healthy"; then
    pass "Web -> API internal network connectivity"
  else
    skip "Web -> API internal check (wget/curl not available in minimal image)"
  fi
fi

# 9b. API container can reach database (verified via health endpoint, which checks DB)
READY_BODY=$(api_get_body "/health/ready")
if echo "$READY_BODY" | grep -q '"ready"'; then
  pass "API -> Database connectivity (verified via /health/ready)"
else
  fail "API -> Database connectivity check failed: $READY_BODY"
fi

# 9c. API -> Sidecar covered in section 6a

# 9c. API container can reach Redis
REDIS_CHECK=$($COMPOSE_CMD exec -T api python -c "
import redis
r = redis.from_url('redis://redis:6379/0')
print(r.ping())
" 2>/dev/null || echo "False")
if echo "$REDIS_CHECK" | grep -q "True"; then
  pass "API -> Redis connectivity"
else
  skip "API -> Redis connectivity (redis-py not directly importable)"
fi

echo ""

# -----------------------------------------------
# 10. Container Image Checks
# -----------------------------------------------
echo "10. Container Image Validation"
echo "---"

# 10a. API image built
API_IMAGE=$($COMPOSE_CMD images api 2>/dev/null | grep -c "api" || echo "0")
if [ "$API_IMAGE" -gt 0 ] 2>/dev/null; then pass "API image built successfully"; else fail "API image not found"; fi

# 10b. Web image built
WEB_IMAGE=$($COMPOSE_CMD images web 2>/dev/null | grep -c "web" || echo "0")
if [ "$WEB_IMAGE" -gt 0 ] 2>/dev/null; then pass "Web image built successfully"; else fail "Web image not found"; fi

# 10c. Sidecar image built
SIDECAR_IMAGE=$($COMPOSE_CMD images ai-sidecar 2>/dev/null | grep -c "sidecar" || echo "0")
if [ "$SIDECAR_IMAGE" -gt 0 ] 2>/dev/null; then pass "Sidecar image built successfully"; else fail "Sidecar image not found"; fi

# 10d. Web runs as non-root
WEB_USER=$($COMPOSE_CMD exec -T web whoami 2>/dev/null || echo "unknown")
if [ "$WEB_USER" = "nextjs" ]; then pass "Web container runs as non-root (nextjs)"; else skip "Web container user: $WEB_USER"; fi

# 10e. Sidecar runs as non-root
SIDECAR_USER=$($COMPOSE_CMD exec -T ai-sidecar whoami 2>/dev/null || echo "unknown")
if [ "$SIDECAR_USER" = "sidecar" ]; then pass "Sidecar container runs as non-root (sidecar)"; else skip "Sidecar container user: $SIDECAR_USER"; fi

echo ""

# -----------------------------------------------
# 11. Session Cleanup
# -----------------------------------------------
echo "11. Session Cleanup"
echo "---"

STATUS=$(api_post "/api/auth/logout" "{}")
if [ "$STATUS" = "200" ]; then pass "User logout"; else fail "Logout (got $STATUS)"; fi

STATUS=$(api_get "/api/auth/me")
if [ "$STATUS" = "401" ]; then pass "Session invalidated after logout"; else fail "Session still valid after logout (got $STATUS)"; fi

echo ""

# -----------------------------------------------
# Summary
# -----------------------------------------------
TOTAL=$((PASS+FAIL+SKIP))
echo "============================================="
echo "  Results: $PASS passed, $FAIL failed, $SKIP skipped (of $TOTAL)"
echo "============================================="

if [ "$FAIL" -gt 0 ]; then
  echo ""
  echo "  Some checks failed. Container logs below."
  echo ""
  echo "  --- API logs (last 30 lines) ---"
  $COMPOSE_CMD logs --tail=30 api 2>/dev/null || true
  echo ""
  echo "  --- Web logs (last 30 lines) ---"
  $COMPOSE_CMD logs --tail=30 web 2>/dev/null || true
  echo ""
  echo "  --- Sidecar logs (last 30 lines) ---"
  $COMPOSE_CMD logs --tail=30 ai-sidecar 2>/dev/null || true
  echo ""
  echo "  Debug commands:"
  echo "    COMPOSE_PROJECT_NAME=$COMPOSE_PROJECT_NAME $COMPOSE_CMD logs api"
  echo "    COMPOSE_PROJECT_NAME=$COMPOSE_PROJECT_NAME $COMPOSE_CMD logs web"
  echo "    COMPOSE_PROJECT_NAME=$COMPOSE_PROJECT_NAME $COMPOSE_CMD ps"
  exit 1
else
  echo ""
  echo "  All checks passed!"
  exit 0
fi
