# Real Data Pipeline Verification

## Overview

This document describes how to verify the complete GlycemicGPT data pipeline with real Dexcom G7 and Tandem t:connect data. The verification script exercises every stage from credential configuration through data ingestion, dashboard display, and AI analysis.

## Prerequisites

1. **Backend running** with database and Redis (Docker Compose or local dev)
2. **Registered user** with accepted safety disclaimer
3. **Dexcom G7 credentials** (Share username and password)
4. **AI API key** (Anthropic or OpenAI) for AI analysis verification
5. (Optional) **Tandem t:connect credentials** for pump data verification

## Quick Start

```bash
# 1. Start backend services
docker compose up -d db redis
cd apps/api && uv run uvicorn src.main:app --host 0.0.0.0 --port 8000 &

# 2. Start frontend
cd apps/web && npm run dev &

# 3. Configure integrations via the web UI:
#    - Navigate to /dashboard/settings/integrations
#    - Enter Dexcom G7 credentials and test connection
#    - (Optional) Enter Tandem credentials
#    - Navigate to /dashboard/settings/ai-provider
#    - Configure Claude or OpenAI with API key

# 4. Run the automated verification
./scripts/verify-data-pipeline.sh --email your@email.com --password yourpassword
```

## What Gets Verified

### Stage 1: Authentication
- Login with real user credentials
- Verify user role and session

### Stage 2: Integration Status
- Dexcom G7 connection status (connected/error/unconfigured)
- Tandem t:connect connection status

### Stage 3: Data Sync
- Trigger manual Dexcom sync and verify readings are fetched
- Trigger manual Tandem sync and verify pump events are fetched
- Report counts: readings fetched vs. stored (deduplication)

### Stage 4: Dashboard Data
- **Current glucose**: Value, trend direction, freshness (minutes ago)
- **Glucose history**: Number of readings in last 3 hours
- **Staleness check**: Warns if reading is > 10 minutes old
- **Target range**: Confirms low/high threshold configuration

### Stage 5: Insulin on Board (Tandem only)
- IoB projection from pump data
- Staleness check on IoB data

### Stage 6: Control-IQ Activity (Tandem only)
- 24-hour activity summary
- Automated vs. manual event counts

### Stage 7: Real-Time SSE Stream
- Connect to SSE endpoint and verify data events arrive
- Parse glucose value from first event

### Stage 8: AI Provider
- Confirm AI provider is configured (Claude or OpenAI)

### Stage 9: AI Chat
- Send a test message asking about glucose status
- Verify AI responds with contextual analysis

### Stage 10: Daily Brief Generation
- Generate a 24-hour daily brief with AI
- Verify time-in-range, average glucose, and AI summary

### Stage 11: Insights Feed
- Verify insights (briefs + analyses) appear in the feed
- Report unread count

### Stage 12: Alert System
- Verify alert thresholds are configured
- Check for active alerts

## Data Flow Diagram

```
Dexcom G7 Cloud                 Tandem t:connect Cloud
     |                                |
     v                                v
  POST /api/integrations/dexcom/sync   POST /api/integrations/tandem/sync
     |                                      |
     v                                      v
  glucose_readings table              pump_events table
     |                                      |
     +------------- merged --------------->+
                      |
                      v
         GET /api/integrations/glucose/current   (Dashboard: GlucoseHero)
         GET /api/integrations/glucose/history   (Dashboard: TrendArrow, TimeInRange)
         GET /api/v1/glucose/stream              (Dashboard: Real-time SSE)
                      |
                      v
         POST /api/ai/briefs/generate            (AI: Daily Brief)
         POST /api/ai/chat                       (AI: Chat with context)
         POST /api/ai/meals/analyze              (AI: Meal patterns)
         POST /api/ai/corrections/analyze        (AI: Correction factors)
                      |
                      v
         GET /api/ai/insights                    (Insights Feed)
```

## Manual Verification Checklist

After running the automated script, verify visually via the web UI:

### Dashboard (/dashboard)
- [ ] GlucoseHero card shows current glucose value and trend arrow
- [ ] Value updates in real-time via SSE (watch for ~60 seconds)
- [ ] TimeInRangeBar shows percentage based on real data
- [ ] FreshnessIndicator shows "X minutes ago"
- [ ] No "Live updates paused" banner (SSE connected)

### Daily Briefs (/dashboard/briefs)
- [ ] AI Insights page shows generated briefs
- [ ] Clicking a brief shows full AI analysis
- [ ] Unread badge appears on sidebar "Daily Briefs" link
- [ ] Filter tabs work (All Insights / Daily Briefs)

### AI Chat (/dashboard/ai-chat)
- [ ] Chat interface loads with input field
- [ ] Sending "How am I doing today?" returns contextual response
- [ ] AI references actual glucose data in its analysis
- [ ] "Not medical advice" disclaimer visible

### Alerts (/dashboard/alerts)
- [ ] Alert feed shows any triggered alerts
- [ ] Alerts reflect real glucose threshold crossings

### Settings (/dashboard/settings)
- [ ] Integrations page shows Dexcom as "Connected"
- [ ] AI Provider page shows configured provider
- [ ] Glucose Range settings persist after save

## Troubleshooting

### Dexcom sync returns 0 readings
- Dexcom Share may have a delay (5-15 minutes after CGM reading)
- Verify credentials work on the Dexcom Clarity app
- Check the Dexcom account has Share enabled

### AI chat returns empty response
- Verify API key is valid (test in Settings > AI Provider)
- Check backend logs for AI provider errors
- Ensure there is glucose data available for context

### SSE stream shows no data events
- SSE sends heartbeats every 30 seconds (verify those arrive first)
- If only heartbeats: sync Dexcom first, then reconnect SSE
- Browser DevTools > Network > EventSource shows live events

### Dashboard shows stale data
- The scheduled sync runs every 5 minutes by default
- Trigger manual sync: `curl -X POST http://localhost:8000/api/integrations/dexcom/sync`
- Check backend logs for sync errors

### Time-in-range shows 0%
- Need at least a few readings to calculate meaningful TIR
- Default range is 70-180 mg/dL (configurable in Settings > Glucose Range)
