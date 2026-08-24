import { HttpResponse, delay, http, sse } from "msw";

import type { GlucoseHistoryReading, PredictiveAlert } from "@/lib/api";
import type { Schemas } from "@/lib/wire-types";

import { getMissingMockApiHandlerDetail } from "./guard";
import {
  buildActiveAlerts,
  buildAlertThresholds,
  buildBolusReview,
  buildCgmSources,
  buildForecast,
  buildGlookoAvailability,
  buildGlookoStatus,
  buildGlucoseHistoryResponse,
  buildGlucosePercentiles,
  buildGlucoseStats,
  buildInsulinSummary,
  buildIntegrations,
  buildMedtronicAvailability,
  buildMedtronicConnectStatus,
  buildMockInsightDetail,
  buildMockInsights,
  buildMockKnowledgeDocuments,
  buildMockUnreadInsightCount,
  buildMockDataSnapshot,
  buildNightscoutConnections,
  buildNightscoutSyncResponse,
  buildNightscoutTestResult,
  buildPumpEventHistoryResponse,
  buildPumpProfile,
  buildPumpStatus,
  buildSyncResponse,
  buildTandemAvailability,
  buildTandemSyncStatus,
  buildTargetRange,
  buildTimeInRangeDetail,
  buildUser,
  findMockDailyBrief,
  generateAndStoreMockDailyBrief,
  recordMockInsightResponse,
} from "./data";
import { getMockRuntimeState, setMockRuntimeState } from "./state";
import {
  MOCK_FORECAST_SOURCE_PREFERENCES,
  type MockCgmSource,
  type MockPumpSource,
} from "./types";

const API = "*/api";

function requestParams(request: Request): URLSearchParams {
  return new URL(request.url).searchParams;
}

const SNAPSHOT_CACHE_BUCKET_MS = 5 * 60_000;

// Tracks the single live `/v1/glucose/stream` connection so a reconnect (a
// mock scenario switch remounts the app content, which races the browser's
// `abort` delivery for the old connection against the new connection's
// resolver) can force-close the stale connection's interval and controller
// before it enqueues onto a controller the browser has moved on from -- see
// GLY-270. Assumes one consumer per page: a second real EventSource against
// this same mock worker (e.g. two dashboard tabs) would fight over this
// singleton, and only the most recently opened connection survives --
// acceptable for mock/dev-only tooling.
//
// Residual leak: if a connection is torn down without a successor AND
// without `request.signal` ever firing `abort` (e.g. a frozen/suspended
// tab), the `setInterval` below has nothing left to clear it -- msw exposes
// no "the browser gave up on this stream" signal independent of that abort
// event. Not attempting a speculative tick-based self-close for that case:
// it would also terminate legitimately long-running dev sessions.
let closeActiveGlucoseStreamConnection: (() => void) | null = null;

let snapshotCache: {
  key: string;
  data: ReturnType<typeof buildMockDataSnapshot>;
} | null = null;

function snapshot() {
  const state = getMockRuntimeState();
  // Regenerating the full backfill costs ~55 ms at 30 days and ~680 ms at 365
  // days, so cache it per runtime state and five-minute reading bucket (any
  // panel change bumps state.updatedAt; new readings only exist per bucket).
  const bucket = Math.floor(Date.now() / SNAPSHOT_CACHE_BUCKET_MS);
  const key = `${JSON.stringify(state)}|${bucket}`;
  if (snapshotCache?.key !== key) {
    snapshotCache = { key, data: buildMockDataSnapshot(state) };
  }
  return {
    state,
    data: snapshotCache.data,
  };
}

function connectCgmSource(source: MockCgmSource): void {
  const state = getMockRuntimeState();
  setMockRuntimeState({
    cgmSources: [...new Set([...state.cgmSources, source])],
    enabled: true,
  });
}

function disconnectCgmSource(source: MockCgmSource): void {
  const state = getMockRuntimeState();
  const cgmSources = state.cgmSources.filter(
    (candidate) => candidate !== source,
  );
  setMockRuntimeState({
    cgmSources,
    enabled: true,
  });
}

function connectPumpSource(source: MockPumpSource): void {
  const state = getMockRuntimeState();
  setMockRuntimeState({
    pumpSources: [...new Set([...state.pumpSources, source])],
    enabled: true,
  });
}

function disconnectPumpSource(source: MockPumpSource): void {
  const state = getMockRuntimeState();
  setMockRuntimeState({
    pumpSources: state.pumpSources.filter((candidate) => candidate !== source),
    enabled: true,
  });
}

function ok(body: Parameters<typeof HttpResponse.json>[0]) {
  return HttpResponse.json(body);
}

function nowIso(): string {
  return new Date().toISOString();
}

function futureIso(minutes: number): string {
  return new Date(Date.now() + minutes * 60_000).toISOString();
}

// Typed against the generated SSE payload schemas (GLY-181) so a backend
// contract change to a stream payload fails `tsc` here instead of the mock
// silently drifting from what `use-glucose-stream.ts` actually parses.
function buildMockGlucosePayload(
  latest: GlucoseHistoryReading,
  iob: Schemas["SseGlucosePayload"]["iob"],
): Schemas["SseGlucosePayload"] {
  return {
    event: "glucose",
    value: latest.value,
    trend: latest.trend,
    trend_rate: latest.trend_rate,
    reading_timestamp: latest.reading_timestamp,
    minutes_ago: 0,
    is_stale: false,
    iob,
    timestamp: nowIso(),
  };
}

function buildMockHeartbeatPayload(): Schemas["SseHeartbeatPayload"] {
  return { event: "heartbeat", timestamp: nowIso() };
}

function buildMockGlucoseAlertPayload(
  alert: PredictiveAlert,
  id: string,
): Schemas["SseGlucoseAlertPayload"] {
  return {
    event: "alert",
    id,
    alert_type: alert.alert_type,
    severity: alert.severity,
    current_value: alert.current_value,
    predicted_value: alert.predicted_value,
    prediction_minutes: alert.prediction_minutes,
    iob_value: alert.iob_value,
    message: alert.message,
    trend_rate: alert.trend_rate,
    source: alert.source,
    created_at: alert.created_at,
    expires_at: alert.expires_at,
  };
}

// NOTE: `GET /api/v1/alerts/stream` is deliberately NOT mocked. Nothing in the
// web client consumes it (it exists for the mobile apps), and the cycle-1 stub
// diverged from the real router -- no per-alert dedupe, a synthetic non-UUID
// id, and `patient_name: null` where the router omits the key outside a
// caregiver stream. A mock that lies is worse than a missing one: the fallback
// handler below returns an explicit "no mock handler" 501 instead. Bring it
// back WITH its first consumer, faithful to `routers/alert_stream.py` and
// covered by a test; `contracts/fixtures/live_alert_event*.json` already pin
// the payload shape for whoever does.

async function jsonBody<TBody extends Record<string, unknown>>(
  request: Request,
): Promise<TBody> {
  return (await request.json().catch(() => ({}))) as TBody;
}

function mockPermissions() {
  return {
    can_view_glucose: true,
    can_view_history: true,
    can_view_iob: true,
    can_view_ai_suggestions: true,
    can_receive_alerts: true,
  };
}

function mockEmergencyContact(position = 1) {
  return {
    id: `mock-emergency-contact-${position}`,
    name: position === 1 ? "Mock Primary Contact" : "Mock Backup Contact",
    telegram_username: position === 1 ? "mock_primary" : "mock_backup",
    priority: position === 1 ? "primary" : "secondary",
    position,
    created_at: nowIso(),
    updated_at: nowIso(),
  };
}

function mockResearchSource(id = "mock-research-source") {
  return {
    id,
    url: "https://example.test/glycemic-research",
    name: "Mock Glycemic Research Source",
    category: "clinical",
    is_active: true,
    last_researched_at: nowIso(),
    created_at: nowIso(),
  };
}

function mockFoodRecord(id = "mock-food-record") {
  const timestamp = nowIso();
  return {
    id,
    meal_timestamp: timestamp,
    food_description: "Grilled chicken bowl with rice and vegetables",
    carbs_low: 42,
    carbs_high: 58,
    confidence: "medium",
    safety_qualifier:
      "Development mock estimate only. Do not use this value for dosing decisions.",
    nutrition_json: {
      protein_grams: 34,
      fat_grams: 18,
      fiber_grams: 7,
      calories: 560,
    },
    assumptions: "One medium bowl with cooked rice and mixed vegetables.",
    source: "ai_estimate",
    corrected_carbs_low: null,
    corrected_carbs_high: null,
    corrected_nutrition_json: null,
    corrected_at: null,
    common_food_id: null,
    ai_model: "mock-meal-v1",
    ai_provider: "msw",
    confirmed_food_name: null,
    identity_confirmed: false,
    suggested_identity: "chicken rice bowl",
    grounding_source: null,
    grounding_source_url: null,
    grounding_trust_tier: null,
    nutrition_facts: {
      portion: "One medium bowl",
      macros: [
        {
          key: "protein_grams",
          label: "Protein",
          value: 34,
          unit: "g",
          glucose_note:
            "Protein can slow digestion and extend the glucose curve.",
        },
        {
          key: "fat_grams",
          label: "Fat",
          value: 18,
          unit: "g",
          glucose_note: "Fat can delay glucose rise after the meal.",
        },
      ],
      net_carbs: {
        low: 35,
        high: 51,
        caveat: "Net carbs are estimated from visible ingredients.",
      },
      disclaimer:
        "Nutrition details are descriptive estimates for development testing.",
    },
    comorbidity_nutrition: null,
    created_at: timestamp,
  };
}

function mockCommonFood(id = "mock-common-food") {
  return {
    id,
    name: "Chicken rice bowl",
    carbs_low: 42,
    carbs_high: 58,
    nutrition_json: {
      protein_grams: 34,
      fat_grams: 18,
      fiber_grams: 7,
      calories: 560,
    },
    created_at: nowIso(),
    updated_at: nowIso(),
  };
}

function mockAIProvider() {
  return {
    provider_type: "openai_api",
    status: "connected",
    model_name: "mock-model",
    base_url: null,
    max_response_tokens: 1200,
    sidecar_provider: null,
    masked_api_key: "mock-key",
    last_validated_at: nowIso(),
    last_error: null,
    created_at: nowIso(),
    updated_at: nowIso(),
  };
}

function mockAIProviderResponse() {
  const { aiChatScenario } = getMockRuntimeState();

  if (aiChatScenario === "not-configured") {
    return HttpResponse.json(
      { detail: "No AI provider configured" },
      { status: 404 },
    );
  }

  if (aiChatScenario === "server-unavailable") {
    return HttpResponse.json(
      { detail: "AI service is unavailable" },
      { status: 503 },
    );
  }

  return ok(mockAIProvider());
}

function isMockGlucoseUnit(value: unknown): value is "mgdl" | "mmol" {
  return value === "mgdl" || value === "mmol";
}

export const handlers = [
  http.all(`${API}/*`, () => {
    if (!getMockRuntimeState().apiUnavailable) {
      return;
    }

    return HttpResponse.json(
      { detail: "The mock API is unavailable." },
      { status: 503 },
    );
  }),

  http.get(`${API}/auth/me`, () => {
    return ok(buildUser(new Date(), getMockRuntimeState()));
  }),

  http.post(`${API}/auth/login`, () => {
    return ok({
      message: "Mock login complete",
      user: buildUser(new Date(), getMockRuntimeState()),
      disclaimer_required: false,
    });
  }),

  http.post(`${API}/auth/register`, () => {
    return ok({
      id: "mock-user",
      email: "mock.patient@glycemicgpt.local",
      role: "diabetic",
      message: "Mock registration complete",
      disclaimer_required: false,
    });
  }),

  http.post(`${API}/auth/logout`, () => {
    return ok({ message: "Mock logout complete" });
  }),

  http.patch(`${API}/auth/profile`, async ({ request }) => {
    const body = await jsonBody<{ display_name?: unknown }>(request);
    const currentState = getMockRuntimeState();
    const nextState =
      typeof body.display_name === "string" || body.display_name === null
        ? setMockRuntimeState({ displayName: body.display_name })
        : currentState;

    return ok(buildUser(new Date(), nextState));
  }),

  http.post(`${API}/auth/change-password`, () => {
    return ok({ message: "Mock password changed" });
  }),

  http.get(`${API}/disclaimer/content`, () => {
    return ok({
      version: "dev-mock",
      title: "Development mock disclaimer",
      warnings: [],
      checkboxes: [],
      button_text: "Continue",
    });
  }),

  http.get(`${API}/disclaimer/status`, () => {
    return ok({
      acknowledged: true,
      acknowledged_at: nowIso(),
      disclaimer_version: "dev-mock",
    });
  }),

  http.post(`${API}/disclaimer/acknowledge`, () => {
    return ok({
      success: true,
      acknowledged_at: nowIso(),
      message: "Mock disclaimer acknowledged",
    });
  }),

  http.post(`${API}/disclaimer/acknowledge-auth`, () => {
    return ok({
      success: true,
      message: "Mock disclaimer acknowledged",
    });
  }),

  http.post(`${API}/caregivers/invitations`, () => {
    return ok({
      id: "mock-caregiver-invitation",
      token: "mock-invite-token",
      expires_at: futureIso(7 * 24 * 60),
      invite_url: "http://localhost:3003/invite/mock-invite-token",
    });
  }),

  http.get(`${API}/caregivers/invitations`, () => {
    return ok({
      invitations: [
        {
          id: "mock-caregiver-invitation",
          status: "pending",
          created_at: nowIso(),
          expires_at: futureIso(7 * 24 * 60),
          accepted_by_email: null,
        },
      ],
      count: 1,
    });
  }),

  http.get(`${API}/caregivers/invitations/:token/details`, () => {
    return ok({
      patient_email: "mock.patient@glycemicgpt.local",
      status: "pending",
      expires_at: futureIso(7 * 24 * 60),
    });
  }),

  http.delete(`${API}/caregivers/invitations/:id`, () => {
    return new HttpResponse(null, { status: 204 });
  }),

  http.post(`${API}/caregivers/accept`, () => {
    return ok({
      message: "Mock invitation accepted",
      user_id: "mock-caregiver",
    });
  }),

  http.get(`${API}/caregivers/patients`, () => {
    return ok({
      patients: [
        {
          patient_id: "mock-patient",
          patient_email: "mock.patient@glycemicgpt.local",
          linked_at: nowIso(),
        },
      ],
      count: 1,
    });
  }),

  http.get(`${API}/caregivers/patients/:patientId/status`, ({ params }) => {
    const { state, data } = snapshot();
    const latest = data.glucoseHistory.at(-1);
    return ok({
      patient_id: String(params.patientId),
      patient_email: "mock.patient@glycemicgpt.local",
      glucose: latest
        ? {
            value: latest.value,
            trend: latest.trend,
            trend_rate: latest.trend_rate,
            reading_timestamp: latest.reading_timestamp,
            minutes_ago: 0,
            is_stale: false,
          }
        : null,
      iob: {
        current_iob: data.iobValue,
        projected_30min: 1.2,
        confirmed_at: nowIso(),
        is_stale: false,
      },
      permissions: mockPermissions(),
      glucose_unit: state.glucoseUnit,
    });
  }),

  http.get(
    `${API}/caregivers/patients/:patientId/glucose/history`,
    ({ params, request }) => {
      const { data } = snapshot();
      const history = buildGlucoseHistoryResponse(data, requestParams(request));
      return ok({
        patient_id: String(params.patientId),
        readings: history.readings.map((reading) => ({
          value: reading.value,
          trend: reading.trend,
          trend_rate: reading.trend_rate,
          reading_timestamp: reading.reading_timestamp,
        })),
        count: history.count,
      });
    },
  ),

  http.post(
    `${API}/caregivers/patients/:patientId/chat`,
    async ({ request }) => {
      const body = await jsonBody<{ message?: unknown }>(request);
      return ok({
        response: `Mock caregiver response to: ${
          typeof body.message === "string" ? body.message : "message"
        }`,
        disclaimer:
          "Development mock only. Not medical advice and not suitable for dosing decisions.",
      });
    },
  ),

  http.get(`${API}/caregivers/linked`, () => {
    return ok({
      caregivers: [
        {
          link_id: "mock-caregiver-link",
          caregiver_id: "mock-caregiver",
          caregiver_email: "mock.caregiver@glycemicgpt.local",
          linked_at: nowIso(),
          permissions: mockPermissions(),
        },
      ],
      count: 1,
    });
  }),

  http.get(`${API}/caregivers/linked/:linkId/permissions`, ({ params }) => {
    return ok({
      link_id: String(params.linkId),
      permissions: mockPermissions(),
    });
  }),

  http.patch(
    `${API}/caregivers/linked/:linkId/permissions`,
    async ({ request, params }) => {
      const body = await jsonBody<Record<string, unknown>>(request);
      return ok({
        link_id: String(params.linkId),
        permissions: { ...mockPermissions(), ...body },
      });
    },
  ),

  http.get(`${API}/escalation/alerts/:alertId/timeline`, ({ params }) => {
    return ok({
      alert_id: String(params.alertId),
      events: [
        {
          id: "mock-escalation-event",
          alert_id: String(params.alertId),
          tier: "reminder",
          triggered_at: nowIso(),
          message_content: "Mock escalation reminder.",
          notification_status: "sent",
          contacts_notified: ["mock_primary"],
          created_at: nowIso(),
        },
      ],
      count: 1,
    });
  }),

  http.get(`${API}/telegram/bot-config`, () => {
    return ok({
      configured: true,
      can_manage: true,
      bot_username: "mock_glycemicgpt_bot",
      configured_at: nowIso(),
    });
  }),

  http.post(`${API}/telegram/bot-config`, () => {
    return ok({ valid: true, bot_username: "mock_glycemicgpt_bot" });
  }),

  http.delete(`${API}/telegram/bot-config`, () => {
    return new HttpResponse(null, { status: 204 });
  }),

  http.get(`${API}/telegram/status`, () => {
    return ok({
      linked: true,
      link: {
        id: "mock-telegram-link",
        chat_id: 123456,
        username: "mock_patient",
        is_verified: true,
        linked_at: nowIso(),
      },
      bot_username: "mock_glycemicgpt_bot",
    });
  }),

  http.post(`${API}/telegram/link`, () => {
    return ok({
      code: "123456",
      expires_at: futureIso(10),
      bot_username: "mock_glycemicgpt_bot",
    });
  }),

  http.delete(`${API}/telegram/link`, () => {
    return ok({ success: true, message: "Mock Telegram link removed" });
  }),

  http.post(`${API}/telegram/test`, () => {
    return ok({ success: true, message: "Mock Telegram test sent" });
  }),

  http.get(`${API}/integrations`, () => {
    const { state } = snapshot();
    return ok(buildIntegrations(state, new Date()));
  }),

  http.post(`${API}/integrations/dexcom`, () => {
    connectCgmSource("dexcom");
    const { state } = snapshot();
    return ok({
      message: "Mock Dexcom connected",
      integration: buildIntegrations(state, new Date()).integrations.find(
        (integration) => integration.integration_type === "dexcom",
      ),
    });
  }),

  http.delete(`${API}/integrations/dexcom`, () => {
    disconnectCgmSource("dexcom");
    return new HttpResponse(null, { status: 204 });
  }),

  http.post(`${API}/integrations/tandem`, () => {
    connectPumpSource("tandem");
    const { state } = snapshot();
    return ok({
      message: "Mock Tandem connected",
      integration: buildIntegrations(state, new Date()).integrations.find(
        (integration) => integration.integration_type === "tandem",
      ),
    });
  }),

  http.delete(`${API}/integrations/tandem`, () => {
    disconnectPumpSource("tandem");
    return new HttpResponse(null, { status: 204 });
  }),

  http.get(`${API}/integrations/nightscout`, () => {
    const { state } = snapshot();
    return ok(buildNightscoutConnections(state, new Date()));
  }),

  http.post(`${API}/integrations/nightscout`, async ({ request }) => {
    const body = (await request.json().catch(() => ({}))) as { name?: string };
    connectCgmSource("nightscout-loop");
    connectPumpSource("loop-nightscout");
    const { state } = snapshot();
    const connection = buildNightscoutConnections(state, new Date())
      .connections[0];
    return ok({
      connection: {
        ...connection,
        name: body.name || connection.name,
      },
      test: buildNightscoutTestResult(),
    });
  }),

  http.patch(`${API}/integrations/nightscout/:connectionId`, () => {
    const { state } = snapshot();
    return ok({
      connection: buildNightscoutConnections(state, new Date()).connections[0],
      test: buildNightscoutTestResult(),
    });
  }),

  http.delete(`${API}/integrations/nightscout/:connectionId`, () => {
    const state = getMockRuntimeState();
    setMockRuntimeState({
      cgmSources: state.cgmSources.filter(
        (source) => !source.startsWith("nightscout"),
      ),
      pumpSources: state.pumpSources.filter(
        (source) => !source.endsWith("nightscout"),
      ),
      enabled: true,
    });
    return new HttpResponse(null, { status: 204 });
  }),

  http.post(`${API}/integrations/nightscout/:connectionId/test`, () => {
    return ok(buildNightscoutTestResult());
  }),

  http.post(`${API}/integrations/nightscout/:connectionId/sync`, () => {
    const { state } = snapshot();
    return ok(buildNightscoutSyncResponse(state));
  }),

  http.post(`${API}/integrations/nightscout/:connectionId/evaluate`, () => {
    return ok({
      status_ok: true,
      server_version: "15.0.0-mock",
      earliest_entry_at: new Date(
        Date.now() - 30 * 24 * 60 * 60_000,
      ).toISOString(),
      entry_count_estimate: 8_640,
      recent_entry_count_7d: 2_016,
      uploaders_detected: ["loop"],
      has_treatments: true,
      treatment_count_estimate: 120,
      has_devicestatus: true,
      has_profile: true,
      profile_summary: {
        target_low: 90,
        target_high: 120,
        dia_hours: 5,
        units: "mg/dl",
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
        carb_ratio_schedule: [{ time: "00:00", value: 11 }],
        isf_schedule: [{ time: "00:00", value: 44 }],
        basal_schedule: [{ time: "00:00", value: 0.72 }],
        target_low_schedule: [{ time: "00:00", value: 90 }],
        target_high_schedule: [{ time: "00:00", value: 120 }],
        is_malformed: false,
      },
      active_pump_loop: "loop",
      partial_resources: [],
      evaluated_at: nowIso(),
      error: null,
    });
  }),

  http.get(
    `${API}/integrations/nightscout/:connectionId/onboarding-derivation`,
    () => {
      return ok({
        has_profile: true,
        units_converted: false,
        units_unknown: false,
        target_low: {
          field: "target_low",
          current_value: 90,
          proposed_value: 90,
          default_checked: true,
        },
        target_high: {
          field: "target_high",
          current_value: 120,
          proposed_value: 120,
          default_checked: true,
        },
        dia_hours: {
          field: "dia_hours",
          current_value: 5,
          proposed_value: 5,
          default_checked: true,
        },
        carb_ratio_schedule: {
          field: "carb_ratio_schedule",
          current_segments: [{ start_minutes: 0, value: 11 }],
          proposed_segments: [{ start_minutes: 0, value: 11 }],
          default_checked: true,
        },
        isf_schedule: {
          field: "isf_schedule",
          current_segments: [{ start_minutes: 0, value: 44 }],
          proposed_segments: [{ start_minutes: 0, value: 44 }],
          default_checked: true,
        },
        basal_schedule: {
          field: "basal_schedule",
          current_segments: [{ start_minutes: 0, value: 0.72 }],
          proposed_segments: [{ start_minutes: 0, value: 0.72 }],
          default_checked: true,
        },
      });
    },
  ),

  http.post(
    `${API}/integrations/nightscout/:connectionId/apply-onboarding`,
    ({ params }) => {
      const { state } = snapshot();
      return ok({
        connection_id: String(params.connectionId),
        applied: {
          target_low: true,
          target_high: true,
          dia_hours: true,
          basal_schedule: true,
          carb_ratio_schedule: true,
          isf_schedule: true,
        },
        target_glucose_range: buildTargetRange(new Date()),
        insulin_config: {
          insulin_type: "rapid_acting",
          dia_hours: 5,
          onset_minutes: 15,
        },
        pump_profile_id: "mock-pump-profile",
        first_sync_status: "ok",
        first_sync_error: null,
        sync_result: buildNightscoutSyncResponse(state),
      });
    },
  ),

  http.get(`${API}/integrations/glucose/history`, ({ request }) => {
    const { data } = snapshot();
    return ok(buildGlucoseHistoryResponse(data, requestParams(request)));
  }),

  http.get(`${API}/integrations/glucose/stats`, ({ request }) => {
    const { data } = snapshot();
    return ok(buildGlucoseStats(data, requestParams(request)));
  }),

  http.get(`${API}/integrations/glucose/time-in-range`, ({ request }) => {
    const { data } = snapshot();
    return ok(buildTimeInRangeDetail(data, requestParams(request)));
  }),

  http.get(`${API}/integrations/glucose/percentiles`, ({ request }) => {
    const { data } = snapshot();
    return ok(buildGlucosePercentiles(data, requestParams(request)));
  }),

  http.get(`${API}/integrations/pump/history`, ({ request }) => {
    const { data } = snapshot();
    return ok(buildPumpEventHistoryResponse(data, requestParams(request)));
  }),

  http.get(`${API}/integrations/pump/status`, () => {
    const { state, data } = snapshot();
    return ok(buildPumpStatus(state, data));
  }),

  http.get(`${API}/integrations/forecast`, () => {
    const { state, data } = snapshot();
    return ok(buildForecast(state, data));
  }),

  http.put(`${API}/integrations/forecast/source`, async ({ request }) => {
    const body = (await request.json().catch(() => ({}))) as {
      source?: string;
    };
    if (
      !body.source ||
      !MOCK_FORECAST_SOURCE_PREFERENCES.includes(
        body.source as (typeof MOCK_FORECAST_SOURCE_PREFERENCES)[number],
      )
    ) {
      return HttpResponse.json(
        { detail: "Invalid forecast source preference" },
        { status: 422 },
      );
    }

    const state = setMockRuntimeState({
      forecastSourcePreference:
        body.source as (typeof MOCK_FORECAST_SOURCE_PREFERENCES)[number],
    });
    return ok({ source_preference: state.forecastSourcePreference });
  }),

  http.get(`${API}/integrations/cgm`, () => {
    const { state } = snapshot();
    return ok(buildCgmSources(state));
  }),

  http.put(`${API}/integrations/cgm/source`, async ({ request }) => {
    const body = (await request.json().catch(() => ({}))) as {
      source?: string;
    };
    return ok({ primary_source: body.source ?? null });
  }),

  http.get(`${API}/integrations/insulin/summary`, ({ request }) => {
    const { data } = snapshot();
    return ok(buildInsulinSummary(data, requestParams(request)));
  }),

  http.get(`${API}/integrations/bolus/review`, ({ request }) => {
    const { state, data } = snapshot();
    return ok(buildBolusReview(state, data, requestParams(request)));
  }),

  http.get(`${API}/integrations/tandem/sync/status`, () => {
    const { state } = snapshot();
    return ok(buildTandemSyncStatus(state, new Date()));
  }),

  http.put(`${API}/integrations/tandem/sync/settings`, async ({ request }) => {
    const body = await jsonBody<{
      enabled?: unknown;
      sync_interval_minutes?: unknown;
    }>(request);
    const current = getMockRuntimeState();
    if (!current.pumpSources.includes("tandem")) {
      return HttpResponse.json(
        { detail: "Tandem integration not configured" },
        { status: 404 },
      );
    }
    if (
      typeof body.enabled !== "boolean" ||
      typeof body.sync_interval_minutes !== "number" ||
      !Number.isInteger(body.sync_interval_minutes) ||
      body.sync_interval_minutes < 15 ||
      body.sync_interval_minutes > 1440
    ) {
      return HttpResponse.json(
        { detail: "Invalid Tandem sync settings" },
        { status: 422 },
      );
    }

    const state = setMockRuntimeState({
      tandemSyncEnabled: body.enabled,
      tandemSyncIntervalMinutes: body.sync_interval_minutes,
    });
    return ok(buildTandemSyncStatus(state, new Date()));
  }),

  http.post(`${API}/integrations/tandem/sync`, () => {
    const { data, state } = snapshot();
    if (state.tandemSyncShouldFail) {
      return HttpResponse.json(
        {
          detail: "Unable to connect to Tandem. Please try again later.",
        },
        { status: 503 },
      );
    }
    return ok(buildSyncResponse(data));
  }),

  http.get(`${API}/integrations/tandem/sync/availability`, () => {
    return ok(buildTandemAvailability(new Date()));
  }),

  http.post(`${API}/integrations/tandem/sync/import`, () => {
    const { data } = snapshot();
    return ok(buildSyncResponse(data));
  }),

  http.post(`${API}/integrations/medtronic/availability`, () => {
    return ok(buildMedtronicAvailability(new Date()));
  }),

  http.post(`${API}/integrations/medtronic/import`, () => {
    const { data } = snapshot();
    return ok({
      message: "Mock Medtronic import complete",
      glucose_fetched: data.glucoseHistory.length,
      glucose_stored: data.glucoseHistory.length,
      events_fetched: data.pumpEvents.length,
      events_stored: data.pumpEvents.length,
    });
  }),

  http.get(`${API}/integrations/medtronic/connect/status`, () => {
    const { state } = snapshot();
    return ok(buildMedtronicConnectStatus(state, new Date()));
  }),

  http.post(`${API}/integrations/medtronic/connect/install`, () => {
    return ok({
      handle: "mock-medtronic",
      pairing_token: "mock-pairing-token",
      expires_at: new Date(Date.now() + 15 * 60_000).toISOString(),
    });
  }),

  http.get(
    `${API}/integrations/medtronic/connect/install/:file`,
    ({ params }) => {
      return new HttpResponse(
        `mock install bundle for ${String(params.file)}`,
        {
          status: 200,
          headers: { "Content-Type": "text/plain" },
        },
      );
    },
  ),

  http.put(`${API}/integrations/medtronic/connect/settings`, () => {
    const { state } = snapshot();
    return ok(buildMedtronicConnectStatus(state, new Date()));
  }),

  http.post(`${API}/integrations/medtronic/connect/disconnect`, () => {
    disconnectPumpSource("medtronic-connect");
    return new HttpResponse(null, { status: 204 });
  }),

  http.post(`${API}/integrations/medtronic/connect/sync`, () => {
    const { data } = snapshot();
    return ok({
      message: "Mock Medtronic sync complete",
      glucose_fetched: data.glucoseHistory.length,
      glucose_stored: data.glucoseHistory.length,
      events_fetched: data.pumpEvents.length,
      events_stored: data.pumpEvents.length,
    });
  }),

  http.post(`${API}/integrations/glooko`, () => {
    connectPumpSource("omnipod-glooko");
    const { state } = snapshot();
    return ok(buildGlookoStatus(state, new Date()));
  }),

  http.get(`${API}/integrations/glooko/status`, () => {
    const { state } = snapshot();
    return ok(buildGlookoStatus(state, new Date()));
  }),

  http.delete(`${API}/integrations/glooko`, () => {
    disconnectPumpSource("omnipod-glooko");
    return new HttpResponse(null, { status: 204 });
  }),

  http.post(`${API}/integrations/glooko/sync`, () => {
    const { data } = snapshot();
    return ok({
      message: "Mock Glooko sync complete",
      glucose_fetched: data.glucoseHistory.length,
      glucose_stored: data.glucoseHistory.length,
      events_fetched: data.pumpEvents.length,
      events_stored: data.pumpEvents.length,
    });
  }),

  http.put(`${API}/integrations/glooko/sync/settings`, () => {
    const { state } = snapshot();
    return ok(buildGlookoStatus(state, new Date()));
  }),

  http.get(`${API}/integrations/glooko/sync/availability`, () => {
    const { state } = snapshot();
    return ok(buildGlookoAvailability(state, new Date()));
  }),

  http.post(`${API}/integrations/glooko/sync/import`, () => {
    const { data } = snapshot();
    return ok({
      message: "Mock Glooko backfill complete",
      glucose_fetched: data.glucoseHistory.length,
      glucose_stored: data.glucoseHistory.length,
      events_fetched: data.pumpEvents.length,
      events_stored: data.pumpEvents.length,
    });
  }),

  http.get(`${API}/settings/target-glucose-range`, () => {
    return ok(buildTargetRange(new Date()));
  }),

  http.patch(`${API}/settings/target-glucose-range`, () => {
    return ok(buildTargetRange(new Date()));
  }),

  http.get(`${API}/settings/glucose-unit`, () => {
    return ok({ glucose_unit: getMockRuntimeState().glucoseUnit });
  }),

  http.patch(`${API}/settings/glucose-unit`, async ({ request }) => {
    const body = await jsonBody<{ glucose_unit?: unknown }>(request);
    const nextUnit = isMockGlucoseUnit(body.glucose_unit)
      ? body.glucose_unit
      : getMockRuntimeState().glucoseUnit;
    const nextState = setMockRuntimeState({ glucoseUnit: nextUnit });
    return ok({
      glucose_unit: nextState.glucoseUnit,
    });
  }),

  http.post(`${API}/settings/glucose-unit/acknowledge`, () => {
    return ok({ glucose_unit: getMockRuntimeState().glucoseUnit });
  }),

  http.patch(`${API}/settings/meal-intelligence`, async ({ request }) => {
    const body = await jsonBody<{ enabled?: unknown }>(request);
    return ok({
      enabled: typeof body.enabled === "boolean" ? body.enabled : true,
    });
  }),

  http.get(`${API}/settings/insulin-config`, () => {
    return ok({
      id: "mock-insulin-config",
      insulin_type: "rapid_acting",
      dia_hours: 5,
      onset_minutes: 15,
      updated_at: nowIso(),
    });
  }),

  http.patch(`${API}/settings/insulin-config`, async ({ request }) => {
    const body = await jsonBody<Record<string, unknown>>(request);
    return ok({
      id: "mock-insulin-config",
      insulin_type:
        typeof body.insulin_type === "string"
          ? body.insulin_type
          : "rapid_acting",
      dia_hours: typeof body.dia_hours === "number" ? body.dia_hours : 5,
      onset_minutes:
        typeof body.onset_minutes === "number" ? body.onset_minutes : 15,
      updated_at: nowIso(),
    });
  }),

  http.get(`${API}/settings/insulin-config/defaults`, () => {
    return ok({
      insulin_type: "rapid_acting",
      dia_hours: 5,
      onset_minutes: 15,
      presets: {
        rapid_acting: { dia_hours: 5, onset_minutes: 15 },
        fiasp: { dia_hours: 4, onset_minutes: 10 },
      },
    });
  }),

  http.get(`${API}/settings/alert-thresholds`, () => {
    return ok(buildAlertThresholds(new Date()));
  }),

  http.patch(`${API}/settings/alert-thresholds`, () => {
    return ok(buildAlertThresholds(new Date()));
  }),

  http.get(`${API}/settings/safety-limits`, () => {
    return ok({
      id: "mock-safety-limits",
      min_glucose_mgdl: 55,
      max_glucose_mgdl: 350,
      max_basal_rate_milliunits: 5_000,
      max_bolus_dose_milliunits: 12_000,
      updated_at: nowIso(),
    });
  }),

  http.patch(`${API}/settings/safety-limits`, () => {
    return ok({
      id: "mock-safety-limits",
      min_glucose_mgdl: 55,
      max_glucose_mgdl: 350,
      max_basal_rate_milliunits: 5_000,
      max_bolus_dose_milliunits: 12_000,
      updated_at: nowIso(),
    });
  }),

  http.get(`${API}/settings/safety-limits/defaults`, () => {
    return ok({
      min_glucose_mgdl: 55,
      max_glucose_mgdl: 350,
      max_basal_rate_milliunits: 5_000,
      max_bolus_dose_milliunits: 12_000,
    });
  }),

  http.get(`${API}/settings/emergency-contacts`, () => {
    const contacts = [mockEmergencyContact(1), mockEmergencyContact(2)];
    return ok({ contacts, count: contacts.length });
  }),

  http.post(`${API}/settings/emergency-contacts`, async ({ request }) => {
    const body = await jsonBody<Record<string, unknown>>(request);
    return ok({
      ...mockEmergencyContact(1),
      name: typeof body.name === "string" ? body.name : "Mock Primary Contact",
      telegram_username:
        typeof body.telegram_username === "string"
          ? body.telegram_username
          : "mock_primary",
      priority: body.priority === "secondary" ? "secondary" : "primary",
    });
  }),

  http.patch(
    `${API}/settings/emergency-contacts/:contactId`,
    async ({ request, params }) => {
      const body = await jsonBody<Record<string, unknown>>(request);
      return ok({
        ...mockEmergencyContact(1),
        id: String(params.contactId),
        name:
          typeof body.name === "string" ? body.name : "Mock Primary Contact",
        telegram_username:
          typeof body.telegram_username === "string"
            ? body.telegram_username
            : "mock_primary",
        priority: body.priority === "secondary" ? "secondary" : "primary",
        updated_at: nowIso(),
      });
    },
  ),

  http.delete(`${API}/settings/emergency-contacts/:contactId`, () => {
    return new HttpResponse(null, { status: 204 });
  }),

  http.get(`${API}/settings/escalation-config`, () => {
    return ok({
      id: "mock-escalation-config",
      reminder_delay_minutes: 10,
      primary_contact_delay_minutes: 15,
      all_contacts_delay_minutes: 30,
      updated_at: nowIso(),
    });
  }),

  http.patch(`${API}/settings/escalation-config`, async ({ request }) => {
    const body = await jsonBody<Record<string, unknown>>(request);
    return ok({
      id: "mock-escalation-config",
      reminder_delay_minutes:
        typeof body.reminder_delay_minutes === "number"
          ? body.reminder_delay_minutes
          : 10,
      primary_contact_delay_minutes:
        typeof body.primary_contact_delay_minutes === "number"
          ? body.primary_contact_delay_minutes
          : 15,
      all_contacts_delay_minutes:
        typeof body.all_contacts_delay_minutes === "number"
          ? body.all_contacts_delay_minutes
          : 30,
      updated_at: nowIso(),
    });
  }),

  http.get(`${API}/settings/pump-profile`, () => {
    return ok(buildPumpProfile(new Date()));
  }),

  http.get(`${API}/settings/analytics-config`, () => {
    return ok({
      id: "mock-analytics-config",
      day_boundary_hour: 4,
      display_labels: null,
      category_labels: null,
      updated_at: nowIso(),
    });
  }),

  http.patch(`${API}/settings/analytics-config`, () => {
    return ok({
      id: "mock-analytics-config",
      day_boundary_hour: 4,
      display_labels: null,
      category_labels: null,
      updated_at: nowIso(),
    });
  }),

  http.get(`${API}/settings/plugin-declarations`, () => {
    const { state } = snapshot();
    if (!state.pumpSources.includes("mobile-plugin")) {
      return new HttpResponse(null, { status: 404 });
    }
    return ok({
      id: "mock-plugin-declaration",
      plugin_id: "mock-mobile-plugin",
      plugin_name: "Mock Mobile Plugin",
      plugin_version: "1.0.0",
      declared_categories: ["basal", "bolus", "correction"],
      category_mappings: {},
      updated_at: nowIso(),
    });
  }),

  http.get(`${API}/alerts/active`, () => {
    const { data } = snapshot();
    return ok(buildActiveAlerts(data));
  }),

  http.patch(`${API}/alerts/:alertId/acknowledge`, ({ params }) => {
    return ok({
      id: String(params.alertId),
      acknowledged: true,
      acknowledged_at: nowIso(),
    });
  }),

  http.get(`${API}/ai/provider`, () => {
    return mockAIProviderResponse();
  }),

  http.post(`${API}/ai/provider`, () => {
    setMockRuntimeState({ aiChatScenario: "connected", enabled: true });
    return ok(mockAIProvider());
  }),

  http.post(`${API}/ai/provider/test`, () => {
    return ok({
      success: true,
      message: "Mock provider test succeeded",
    });
  }),

  http.delete(`${API}/ai/provider`, () => {
    setMockRuntimeState({ aiChatScenario: "not-configured", enabled: true });
    return ok({ message: "Mock AI provider deleted" });
  }),

  http.post(`${API}/ai/subscription/configure`, async ({ request }) => {
    const body = await jsonBody<{ sidecar_provider?: unknown }>(request);
    setMockRuntimeState({ aiChatScenario: "connected", enabled: true });
    return ok({
      ...mockAIProvider(),
      provider_type: "claude_subscription",
      sidecar_provider:
        typeof body.sidecar_provider === "string"
          ? body.sidecar_provider
          : "claude",
    });
  }),

  http.post(`${API}/ai/subscription/auth/start`, async ({ request }) => {
    const body = await jsonBody<{ provider?: unknown }>(request);
    const provider =
      typeof body.provider === "string" ? body.provider : "claude";
    return ok({
      provider,
      auth_method: "manual_token",
      instructions: `Mock ${provider} subscription auth started.`,
    });
  }),

  http.post(`${API}/ai/subscription/auth/token`, async ({ request }) => {
    const body = await jsonBody<{ provider?: unknown }>(request);
    return ok({
      success: true,
      provider: typeof body.provider === "string" ? body.provider : "claude",
    });
  }),

  http.get(`${API}/ai/subscription/auth/status`, () => {
    return ok({
      sidecar_available: true,
      claude: { authenticated: true },
      codex: { authenticated: true },
      copilot: { authenticated: true },
    });
  }),

  http.post(`${API}/ai/subscription/auth/revoke`, () => {
    return ok({ success: true });
  }),

  http.get(`${API}/ai/subscription/sidecar/health`, () => {
    return ok({
      available: true,
      status: "mock",
      claude_auth: true,
      codex_auth: true,
      copilot_auth: true,
    });
  }),

  http.post(`${API}/ai/chat`, async ({ request }) => {
    const { aiChatScenario } = getMockRuntimeState();
    if (
      aiChatScenario === "not-configured" ||
      aiChatScenario === "disconnect-on-send"
    ) {
      return HttpResponse.json(
        { detail: "No AI provider configured" },
        { status: 404 },
      );
    }
    if (aiChatScenario === "server-unavailable") {
      return HttpResponse.json(
        { detail: "AI service is unavailable" },
        { status: 503 },
      );
    }
    if (aiChatScenario === "provider-error") {
      return HttpResponse.json(
        { detail: "Unable to get a response from the AI provider" },
        { status: 502 },
      );
    }
    if (aiChatScenario === "empty-response") {
      return HttpResponse.json(
        { detail: "The AI returned an empty response" },
        { status: 502 },
      );
    }
    if (aiChatScenario === "slow-response") {
      await delay(5_000);
    }

    const body = await jsonBody<{ message?: unknown }>(request);
    const message =
      typeof body.message === "string" ? body.message : "your mock message";
    return ok({
      response: `Mock response to: ${message}`,
      disclaimer:
        "Development mock only. Not medical advice and not suitable for dosing decisions.",
      conversation_id: "mock-conversation",
      message_id: `mock-message-${Date.now()}`,
    });
  }),

  http.get(`${API}/ai/chat/history`, () => {
    return ok({
      conversation_id: "mock-conversation",
      messages: [
        {
          id: "mock-chat-1",
          role: "assistant",
          content: "Mock chat history is ready.",
          timestamp: nowIso(),
          model: "mock-model",
          disclaimer:
            "Development mock only. Not medical advice and not suitable for dosing decisions.",
        },
      ],
      total: 1,
    });
  }),

  http.delete(`${API}/ai/chat/history`, () => {
    return new HttpResponse(null, { status: 204 });
  }),

  http.get(`${API}/ai/research/sources`, () => {
    const sources = [mockResearchSource()];
    return ok({ sources, total: sources.length });
  }),

  http.post(`${API}/ai/research/sources`, async ({ request }) => {
    const body = await jsonBody<Record<string, unknown>>(request);
    return ok({
      ...mockResearchSource(`mock-research-source-${Date.now()}`),
      url:
        typeof body.url === "string"
          ? body.url
          : "https://example.test/glycemic-research",
      name:
        typeof body.name === "string"
          ? body.name
          : "Mock Glycemic Research Source",
      category: typeof body.category === "string" ? body.category : "clinical",
    });
  }),

  http.delete(`${API}/ai/research/sources/:sourceId`, () => {
    return new HttpResponse(null, { status: 204 });
  }),

  http.post(`${API}/ai/research/run`, () => {
    return ok({ sources: 1, updated: 1, new: 0, unchanged: 0, errors: 0 });
  }),

  http.get(`${API}/ai/research/suggestions`, () => {
    return ok({
      suggestions: [
        {
          url: "https://example.test/glycemic-guidelines",
          name: "Mock Glycemic Guidelines",
          category: "clinical",
        },
      ],
      based_on: { source: "mock" },
    });
  }),

  http.get(`${API}/knowledge/documents`, ({ request }) => {
    const params = requestParams(request);
    const page = Math.max(1, Number(params.get("page")) || 1);
    const pageSize = Math.max(
      1,
      Math.min(100, Number(params.get("page_size")) || 20),
    );
    const trustTier = params.get("trust_tier");
    const search = params.get("search")?.trim().toLocaleLowerCase();
    const documents = buildMockKnowledgeDocuments(getMockRuntimeState()).filter(
      (document) =>
        (!trustTier || document.trust_tier === trustTier) &&
        (!search || document.source_name.toLocaleLowerCase().includes(search)),
    );
    const offset = (page - 1) * pageSize;

    return ok({
      documents: documents.slice(offset, offset + pageSize),
      total_documents: documents.length,
      total_chunks: documents.reduce(
        (total, document) => total + document.chunk_count,
        0,
      ),
      page,
      page_size: pageSize,
    });
  }),

  http.get(`${API}/knowledge/documents/chunks`, ({ request }) => {
    const params = requestParams(request);
    const sourceName = params.get("source_name") ?? "Mock Clinical Reference";
    const document = buildMockKnowledgeDocuments(getMockRuntimeState()).find(
      (candidate) => candidate.source_name === sourceName,
    );
    const chunkCount = document?.chunk_count ?? 1;

    return ok({
      chunks: Array.from({ length: chunkCount }, (_, index) => {
        const content = `${sourceName} mock excerpt ${index + 1} for development testing only.`;
        return {
          id: `mock-knowledge-chunk-${index + 1}`,
          content: content,
          content_preview: content,
          content_length: content.length,
          source_url: document?.source_url ?? null,
          retrieved_at: nowIso(),
          created_at: nowIso(),
          injection_risk: false,
        };
      }),
      total: chunkCount,
      source_name: sourceName,
    });
  }),

  http.delete(`${API}/knowledge/documents`, () => {
    return ok({ message: "Mock document deleted", chunks_invalidated: 1 });
  }),

  http.get(`${API}/knowledge/stats`, () => {
    const documents = buildMockKnowledgeDocuments(getMockRuntimeState());
    const byTier = documents.reduce<Record<string, number>>(
      (counts, document) => {
        counts[document.trust_tier] =
          (counts[document.trust_tier] ?? 0) + document.chunk_count;
        return counts;
      },
      {},
    );

    return ok({
      total_documents: documents.length,
      total_chunks: documents.reduce(
        (total, document) => total + document.chunk_count,
        0,
      ),
      by_tier: byTier,
    });
  }),

  http.get(`${API}/ai/insights/unread-count`, () => {
    const { state, data } = snapshot();
    return ok(buildMockUnreadInsightCount(state, data));
  }),

  http.get(`${API}/ai/insights`, ({ request }) => {
    const { state, data } = snapshot();
    return ok(buildMockInsights(state, data, requestParams(request)));
  }),

  http.get(`${API}/ai/insights/:analysisType/:analysisId`, ({ params }) => {
    if (params.analysisType !== "daily_brief") {
      return HttpResponse.json(
        { detail: "Mock insight type not found" },
        { status: 404 },
      );
    }

    const { state, data } = snapshot();
    const detail = buildMockInsightDetail(
      state,
      data,
      String(params.analysisId),
    );
    if (!detail) {
      return HttpResponse.json(
        { detail: "Mock insight not found" },
        { status: 404 },
      );
    }

    return ok(detail);
  }),

  http.post(
    `${API}/ai/insights/:analysisType/:analysisId/respond`,
    async ({ request, params }) => {
      if (params.analysisType !== "daily_brief") {
        return HttpResponse.json(
          { detail: "Mock insight type not found" },
          { status: 404 },
        );
      }

      const body = (await request.json().catch(() => ({}))) as {
        response?: "acknowledged" | "dismissed";
        reason?: string | null;
      };
      if (body.response !== "acknowledged" && body.response !== "dismissed") {
        return HttpResponse.json(
          { detail: "Response must be acknowledged or dismissed" },
          { status: 422 },
        );
      }

      return HttpResponse.json(
        recordMockInsightResponse(
          String(params.analysisId),
          body.response,
          body.reason ?? null,
        ),
        { status: 201 },
      );
    },
  ),

  http.post(`${API}/ai/briefs/generate`, async ({ request }) => {
    const body = (await request.json().catch(() => ({}))) as { hours?: number };
    const hours = Number(body.hours ?? 24);
    if (!Number.isFinite(hours) || hours < 1 || hours > 72) {
      return HttpResponse.json(
        { detail: "hours must be between 1 and 72" },
        { status: 422 },
      );
    }

    const { state, data } = snapshot();
    return HttpResponse.json(
      generateAndStoreMockDailyBrief(state, data, hours),
      { status: 201 },
    );
  }),

  http.get(`${API}/ai/briefs`, ({ request }) => {
    const { state, data } = snapshot();
    const params = requestParams(request);
    const limit = Math.max(
      1,
      Math.min(50, Number(params.get("limit") ?? "10")),
    );
    const offset = Math.max(0, Number(params.get("offset") ?? "0"));
    const briefs = buildMockInsights(
      state,
      data,
      new URLSearchParams("limit=100"),
    )
      .insights.map((insight) => findMockDailyBrief(state, data, insight.id))
      .filter((brief) => brief !== null);

    return ok({
      briefs: briefs.slice(offset, offset + limit),
      total: briefs.length,
    });
  }),

  http.get(`${API}/ai/briefs/:briefId`, ({ params }) => {
    const { state, data } = snapshot();
    const brief = findMockDailyBrief(state, data, String(params.briefId));
    if (!brief) {
      return HttpResponse.json(
        { detail: "Mock brief not found" },
        { status: 404 },
      );
    }

    return ok(brief);
  }),

  http.get(`${API}/settings/brief-delivery`, () => {
    return ok({
      id: "mock-brief-delivery",
      enabled: true,
      delivery_time: "07:00:00",
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
      channel: "web_only",
      updated_at: nowIso(),
    });
  }),

  http.patch(`${API}/settings/brief-delivery`, async ({ request }) => {
    const body = (await request.json().catch(() => ({}))) as Record<
      string,
      unknown
    >;
    return ok({
      id: "mock-brief-delivery",
      enabled: typeof body.enabled === "boolean" ? body.enabled : true,
      delivery_time:
        typeof body.delivery_time === "string"
          ? body.delivery_time
          : "07:00:00",
      timezone:
        typeof body.timezone === "string"
          ? body.timezone
          : Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
      channel: typeof body.channel === "string" ? body.channel : "web_only",
      updated_at: nowIso(),
    });
  }),

  http.get(`${API}/settings/data-retention`, () => {
    return ok({
      id: "mock-data-retention",
      glucose_retention_days: 365,
      analysis_retention_days: 365,
      audit_retention_days: 180,
      updated_at: nowIso(),
    });
  }),

  http.patch(`${API}/settings/data-retention`, () => {
    return ok({
      id: "mock-data-retention",
      glucose_retention_days: 365,
      analysis_retention_days: 365,
      audit_retention_days: 180,
      updated_at: nowIso(),
    });
  }),

  http.get(`${API}/settings/data-retention/usage`, () => {
    const { data } = snapshot();
    const glucoseRecords = data.glucoseHistory.length;
    const pumpRecords = data.pumpEvents.length;
    return ok({
      glucose_records: glucoseRecords,
      pump_records: pumpRecords,
      analysis_records: 3,
      audit_records: 8,
      total_records: glucoseRecords + pumpRecords + 11,
    });
  }),

  http.post(`${API}/settings/data-retention/purge`, () => {
    return ok({
      success: true,
      deleted_records: {
        glucose_records: 0,
        pump_records: 0,
        analysis_records: 0,
        audit_records: 0,
      },
      total_deleted: 0,
      message: "Mock purge complete",
    });
  }),

  http.post(`${API}/settings/export`, () => {
    return ok({
      export_data: {
        user: buildUser(new Date(), getMockRuntimeState()),
        generated_at: nowIso(),
        source: "mock",
      },
    });
  }),

  http.get(`${API}/food-records`, ({ request }) => {
    const params = requestParams(request);
    const limit = Math.max(
      1,
      Math.min(100, Number(params.get("limit") ?? "50")),
    );
    const records = [mockFoodRecord()].slice(0, limit);
    return ok({ records, total: records.length });
  }),

  http.post(`${API}/food-records`, () => {
    return HttpResponse.json(mockFoodRecord(`mock-food-record-${Date.now()}`), {
      status: 201,
    });
  }),

  http.get(`${API}/food-records/:recordId/audit`, ({ params }) => {
    return ok({
      food_record_id: String(params.recordId),
      samples: [
        {
          carbs_low: 42,
          carbs_high: 58,
          identity: "chicken rice bowl",
          parse_ok: true,
        },
      ],
      dispersion: {
        confidence: "medium",
        coefficient_of_variation: 0.18,
        samples_requested: 3,
        samples_used: 3,
        identity_agreement: true,
        distinct_identities: ["chicken rice bowl"],
        wide_spread: false,
      },
      precedence: {
        outcome: "vision_only",
        chosen_source: null,
        trust_tier: null,
        source_url: null,
        identity_used: "chicken rice bowl",
        identity_confirmed: false,
        reason: "Mock vision estimate used for development.",
        ladder: ["user_corrected", "common_food", "grounded", "vision"],
      },
      created_at: nowIso(),
      updated_at: nowIso(),
    });
  }),

  http.get(`${API}/food-records/:recordId/photo`, () => {
    return new HttpResponse(
      `<svg xmlns="http://www.w3.org/2000/svg" width="320" height="200"><rect width="320" height="200" fill="#e5f3ef"/><text x="24" y="104" font-family="Arial" font-size="18" fill="#14332b">Mock meal photo</text></svg>`,
      {
        status: 200,
        headers: { "Content-Type": "image/svg+xml" },
      },
    );
  }),

  http.post(
    `${API}/food-records/:recordId/correct`,
    async ({ request, params }) => {
      const body = await jsonBody<Record<string, unknown>>(request);
      return ok({
        ...mockFoodRecord(String(params.recordId)),
        corrected_carbs_low:
          typeof body.corrected_carbs_low === "number"
            ? body.corrected_carbs_low
            : 40,
        corrected_carbs_high:
          typeof body.corrected_carbs_high === "number"
            ? body.corrected_carbs_high
            : 55,
        corrected_at: nowIso(),
        source: "user_corrected",
      });
    },
  ),

  http.post(
    `${API}/food-records/:recordId/confirm-identity`,
    async ({ request, params }) => {
      const body = await jsonBody<{ confirmed_food_name?: unknown }>(request);
      return ok({
        ...mockFoodRecord(String(params.recordId)),
        confirmed_food_name:
          typeof body.confirmed_food_name === "string"
            ? body.confirmed_food_name
            : "Chicken rice bowl",
        identity_confirmed: true,
        grounding_source: "Mock Food Database",
        grounding_source_url: "https://example.test/mock-food",
        grounding_trust_tier: "reference",
        comorbidity_nutrition: {
          facts: [
            {
              key: "sodium_mg",
              label: "Sodium",
              value: 720,
              unit: "mg",
              note: "Mock sodium value for cardiovascular awareness.",
            },
          ],
          sugar_note: null,
          source: "Mock Food Database",
          source_url: "https://example.test/mock-food",
          trust_tier: "reference",
          disclaimer:
            "Grounded nutrition facts are mock values for development testing.",
        },
      });
    },
  ),

  http.post(
    `${API}/food-records/:recordId/save-as-common-food`,
    async ({ request }) => {
      const body = await jsonBody<{ name?: unknown }>(request);
      return ok({
        ...mockCommonFood(`mock-common-food-${Date.now()}`),
        name: typeof body.name === "string" ? body.name : "Chicken rice bowl",
      });
    },
  ),

  http.post(
    `${API}/food-records/:recordId/link-common-food`,
    async ({ request, params }) => {
      const body = await jsonBody<{ common_food_id?: unknown }>(request);
      return ok({
        ...mockFoodRecord(String(params.recordId)),
        common_food_id:
          typeof body.common_food_id === "string"
            ? body.common_food_id
            : "mock-common-food",
      });
    },
  ),

  http.get(`${API}/food-records/:recordId`, ({ params }) => {
    return ok(mockFoodRecord(String(params.recordId)));
  }),

  http.delete(`${API}/food-records/:recordId`, () => {
    return new HttpResponse(null, { status: 204 });
  }),

  http.get(`${API}/common-foods`, ({ request }) => {
    const params = requestParams(request);
    const limit = Math.max(
      1,
      Math.min(100, Number(params.get("limit") ?? "50")),
    );
    const common_foods = [mockCommonFood()].slice(0, limit);
    return ok({ common_foods, total: common_foods.length });
  }),

  http.patch(
    `${API}/common-foods/:commonFoodId`,
    async ({ request, params }) => {
      const body = await jsonBody<Record<string, unknown>>(request);
      return ok({
        ...mockCommonFood(String(params.commonFoodId)),
        name: typeof body.name === "string" ? body.name : "Chicken rice bowl",
        carbs_low: typeof body.carbs_low === "number" ? body.carbs_low : 42,
        carbs_high: typeof body.carbs_high === "number" ? body.carbs_high : 58,
        updated_at: nowIso(),
      });
    },
  ),

  http.delete(`${API}/common-foods/:commonFoodId`, () => {
    return new HttpResponse(null, { status: 204 });
  }),

  sse<{
    glucose: string;
    heartbeat: string;
    alert: string;
  }>(`${API}/v1/glucose/stream`, ({ client, request }) => {
    // Force-close any still-live connection before opening this one -- see
    // the singleton comment on `closeActiveGlucoseStreamConnection` above.
    if (closeActiveGlucoseStreamConnection) {
      console.warn(
        "[mock] Force-closing a stale /v1/glucose/stream connection before opening a new one (GLY-270).",
      );
      closeActiveGlucoseStreamConnection();
    }

    const sendGlucose = () => {
      const { state, data } = snapshot();
      const latest = data.glucoseHistory.at(-1);
      if (!latest) return;
      const primaryPumpSource = state.pumpSources[0];
      const iob: Schemas["SseGlucosePayload"]["iob"] =
        primaryPumpSource && primaryPumpSource !== "mdi"
          ? { current: data.iobValue, is_stale: false }
          : null;
      client.send({
        event: "glucose",
        data: JSON.stringify(buildMockGlucosePayload(latest, iob)),
      });
      client.send({
        event: "heartbeat",
        data: JSON.stringify(buildMockHeartbeatPayload()),
      });
      const alert = buildActiveAlerts(data).alerts[0];
      if (alert) {
        const id = `${alert.id}-${state.glucoseEvent}-${state.updatedAt ?? latest.reading_timestamp}`;
        client.send({
          event: "alert",
          data: JSON.stringify(buildMockGlucoseAlertPayload(alert, id)),
        });
      }
    };

    sendGlucose();

    // Bare (not `window.`) so this resolver also runs under
    // `handlers.test.ts`'s `@jest-environment node`, where `window` is
    // undefined.
    const interval = setInterval(
      sendGlucose,
      getMockRuntimeState().liveMode ? 5_000 : 30_000,
    );

    let isClosed = false;
    const close = () => {
      if (isClosed) {
        return;
      }
      isClosed = true;
      clearInterval(interval);
      client.close();
      if (closeActiveGlucoseStreamConnection === close) {
        closeActiveGlucoseStreamConnection = null;
      }
    };
    closeActiveGlucoseStreamConnection = close;

    request.signal.addEventListener("abort", close, { once: true });
  }),

  http.all(`${API}/*`, ({ request }) => {
    return HttpResponse.json(
      { detail: getMissingMockApiHandlerDetail(request) },
      { status: 501 },
    );
  }),
];
