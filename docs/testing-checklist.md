# GlycemicGPT Local Dev Server Testing Checklist

## Prerequisites

1. **Docker and Docker Compose** installed
2. **Node.js 20+** and npm installed
3. **Python 3.12+** and uv package manager installed (for backend dev)
4. **Ports available:** 5432 (PostgreSQL), 6379 (Redis), 8000 (API), 3000 (Web)

## Quick Start

```bash
# 1. Start backend services (database, redis, API)
docker compose up -d db redis
cd apps/api && uv run alembic upgrade head && uv run uvicorn src.main:app --host 0.0.0.0 --port 8000

# 2. Start frontend (in a separate terminal)
cd apps/web && npm run dev

# 3. Run automated smoke test (in a separate terminal)
./scripts/smoke-test.sh
```

Alternatively, start everything via Docker:

```bash
docker compose up --build
```

## Automated Tests

### Backend Unit Tests (pytest)

```bash
cd apps/api
DATABASE_URL="postgresql+asyncpg://glycemicgpt:glycemicgpt@localhost:5432/glycemicgpt_test" \
TESTING=true \
uv run pytest --tb=short -q
```

- 42 test files, 200+ test cases
- Covers auth, RBAC, integrations, AI, alerts, telegram, caregivers, settings

### Frontend Unit Tests (Jest)

```bash
cd apps/web
npm test
```

- 20+ test suites, 480+ test cases
- Covers all pages, settings, sidebar, briefs, AI chat

### API Smoke Test

```bash
./scripts/smoke-test.sh
```

- Automated end-to-end check of all API endpoints
- Registers a test user, logs in, exercises all settings/features, logs out
- Verifies health probes, auth flow, settings CRUD, integrations, AI, caregivers

## Manual Testing Checklist

Use this checklist to verify all features work end-to-end in the browser.

### 1. Infrastructure

- [ ] `docker compose up -d db redis` starts PostgreSQL and Redis
- [ ] API starts without errors: `cd apps/api && uv run uvicorn src.main:app --port 8000`
- [ ] Frontend starts without errors: `cd apps/web && npm run dev`
- [ ] `curl http://localhost:8000/health` returns `{"status": "healthy", "database": "connected"}`
- [ ] `http://localhost:3000` loads the landing page

### 2. User Registration and Login

- [ ] Navigate to `/register` and create a new account
- [ ] Verify safety disclaimer appears on first login
- [ ] Accept disclaimer and proceed to dashboard
- [ ] Navigate to `/login`, log in with created credentials
- [ ] Dashboard loads with glucose overview widgets
- [ ] Sidebar shows: Dashboard, Daily Briefs, Alerts, AI Chat, Settings
- [ ] Logout works (Account dropdown > Logout)
- [ ] After logout, accessing `/dashboard` redirects to login

### 3. Dashboard

- [ ] Glucose Hero card renders (with mock/placeholder data if no real data)
- [ ] Time in Range bar renders
- [ ] Trend arrow component renders
- [ ] "Live updates paused" banner shows when SSE disconnects (expected without real data)
- [ ] No JavaScript errors in browser console (network errors are expected)

### 4. Settings Pages (no 404s)

Navigate to each settings page and verify it loads:

- [ ] `/dashboard/settings` - Settings index with all cards
- [ ] `/dashboard/settings/profile` - Profile page with email, display name, role
- [ ] `/dashboard/settings/integrations` - Dexcom and Tandem sections
- [ ] `/dashboard/settings/ai-provider` - AI provider selection (Claude/OpenAI)
- [ ] `/dashboard/settings/glucose-range` - Low/high threshold sliders
- [ ] `/dashboard/settings/brief-delivery` - Time, timezone, channel settings
- [ ] `/dashboard/settings/alerts` - Alert threshold configuration
- [ ] `/dashboard/settings/emergency-contacts` - Contact list with add/remove
- [ ] `/dashboard/settings/caregivers` - Caregiver invitation management
- [ ] `/dashboard/settings/communications` - Telegram and future channels
- [ ] `/dashboard/settings/data` - Retention periods, purge, export

### 5. Settings Save Flow

For each settings page with a Save button:

- [ ] Page loads with current values (or defaults when backend returns data)
- [ ] Changing a value enables the Save Changes button
- [ ] Clicking Save sends the API request
- [ ] Success shows a confirmation message
- [ ] Reloading the page shows the saved value
- [ ] Offline state shows warning banner when API is unavailable

### 6. AI Provider Configuration

- [ ] Navigate to `/dashboard/settings/ai-provider`
- [ ] Select Claude or OpenAI as provider
- [ ] Enter an API key (masked input, show/hide toggle works)
- [ ] Test Connection button sends a validation request
- [ ] Valid key shows success message
- [ ] Invalid key shows error message
- [ ] Save persists the configuration

### 7. AI Chat

- [ ] Navigate to `/dashboard/ai-chat`
- [ ] Without AI configured: shows "No AI Provider Configured" with link to settings
- [ ] With AI configured: shows chat interface with input field
- [ ] Typing a message and sending shows it in the conversation
- [ ] AI response appears with typing indicator while loading
- [ ] "Not medical advice" disclaimer visible
- [ ] Multiple messages maintain conversation history

### 8. Daily Briefs

- [ ] Navigate to `/dashboard/briefs`
- [ ] Page shows "AI Insights" heading
- [ ] Filter tabs appear when insights exist (All Insights / Daily Briefs)
- [ ] Clicking "Daily Briefs" tab filters to only daily briefs
- [ ] Pending badge shows count of unread briefs
- [ ] Empty state shows when no insights exist
- [ ] Sidebar "Daily Briefs" shows unread badge when there are pending insights

### 9. Alerts

- [ ] Navigate to `/dashboard/alerts`
- [ ] Alert feed loads (empty state is OK with no real data)
- [ ] Alert cards show severity, message, timestamp
- [ ] Alerts can be acknowledged/dismissed

### 10. Integrations

- [ ] Navigate to `/dashboard/settings/integrations`
- [ ] Dexcom section shows email/password fields and Test Connection button
- [ ] Tandem section shows email/password fields and Test Connection button
- [ ] Connection status indicators show connected/disconnected state

### 11. Communications (Telegram)

- [ ] Navigate to `/dashboard/settings/communications`
- [ ] Telegram section visible with setup status
- [ ] Bot token configuration field available
- [ ] Account linking section shows verification code flow
- [ ] Future channels section shows "coming soon" placeholder

### 12. Caregiver Access

- [ ] Navigate to `/dashboard/settings/caregivers`
- [ ] Can invite a caregiver by email
- [ ] Invitation list shows pending invitations
- [ ] Can revoke pending invitations

### 13. Data Management

- [ ] Navigate to `/dashboard/settings/data`
- [ ] Retention period settings load and can be modified
- [ ] Data purge section with confirmation dialog
- [ ] Export section with download button

### 14. Accessibility

- [ ] All pages have proper heading hierarchy (h1, h2, h3)
- [ ] Tab navigation works through all interactive elements
- [ ] ARIA labels present on icons, buttons, and form fields
- [ ] Color contrast meets WCAG AA standards
- [ ] Screen reader can navigate all major sections

### 15. Mobile Responsiveness

- [ ] Sidebar collapses to hamburger menu on mobile viewport
- [ ] All settings pages render correctly on narrow screens
- [ ] Dashboard cards stack vertically on mobile
- [ ] Navigation menu opens/closes correctly on mobile

## Troubleshooting

### API won't start
- Check PostgreSQL is running: `docker compose ps db`
- Check Redis is running: `docker compose ps redis`
- Verify DATABASE_URL environment variable
- Run migrations: `cd apps/api && uv run alembic upgrade head`

### Frontend shows "Failed to fetch" everywhere
- Backend API must be running on port 8000
- Check that the web container can reach the API (API_URL env var, default http://api:8000)
- Browser requests are proxied through the web server via Next.js rewrites -- no direct API access needed

### Tests fail with database errors
- Ensure a test database exists
- Set TESTING=true environment variable
- Run migrations on the test database first

### Settings Save button stays disabled
- This was fixed in a previous release
- If it persists, check browser console for API errors
- Verify the backend endpoint returns expected schema
