/**
 * API client configuration and utilities.
 *
 * Story 1.3: First-Run Safety Disclaimer
 * Story 15.1: Authentication API functions
 * Story 15.4: Global 401 handling via apiFetch wrapper
 * Glucose unit preference on the current user + update endpoint
 */

import type { GlucoseUnit } from "./glucose-units";

/**
 * Resolve the API base URL.
 *
 * Client-side: returns "" (empty string) so all /api/* requests hit the same
 * origin. Next.js rewrites proxy them to the backend (see next.config.ts).
 * This eliminates CORS and works behind any reverse proxy.
 *
 * Server-side (SSR): uses API_URL env var for container-to-container calls.
 * Defaults to http://localhost:8000 for local dev outside Docker.
 */
export function getApiBaseUrl(): string {
  if (typeof window !== "undefined") {
    return "";
  }
  return process.env.API_URL || "http://localhost:8000";
}

const API_BASE_URL = getApiBaseUrl();

// Auth endpoints that legitimately return 401 (should NOT trigger redirect)
const AUTH_ENDPOINTS = [
  "/api/auth/login",
  "/api/auth/register",
  "/api/auth/me",
  "/api/auth/logout",
];

/**
 * Read a cookie value by name (client-side only).
 */
function getCookie(name: string): string | undefined {
  if (typeof document === "undefined") return undefined;
  const match = document.cookie.match(
    new RegExp("(?:^|; )" + name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "=([^;]*)")
  );
  if (!match) return undefined;
  try {
    return decodeURIComponent(match[1]);
  } catch {
    return undefined;
  }
}

/**
 * Authenticated fetch wrapper with automatic 401 handling and CSRF protection.
 *
 * Defaults credentials to "include" and redirects to /login?expired=true
 * when a 401 response is received from non-auth endpoints. Returns a
 * never-resolving promise after redirect to prevent callers from
 * processing the stale response.
 *
 * For state-changing requests (POST, PATCH, PUT, DELETE), automatically
 * reads the csrf_token cookie and sends it as X-CSRF-Token header.
 */
export async function apiFetch(
  url: string,
  options?: RequestInit
): Promise<Response> {
  const headers = new Headers(options?.headers);
  const method = (options?.method || "GET").toUpperCase();

  // Add CSRF token for state-changing requests (Story 28.4)
  if (["POST", "PATCH", "PUT", "DELETE"].includes(method)) {
    const csrfToken = getCookie("csrf_token");
    if (csrfToken && !headers.has("X-CSRF-Token")) {
      headers.set("X-CSRF-Token", csrfToken);
    }
  }

  const response = await fetch(url, {
    ...options,
    headers,
    credentials: "include",
  });

  if (response.status === 401 && typeof window !== "undefined") {
    const urlPath = new URL(url, window.location.origin).pathname;
    if (!AUTH_ENDPOINTS.some((ep) => urlPath === ep)) {
      window.location.href = "/login?expired=true";
      return new Promise<Response>(() => {});
    }
  }

  return response;
}

// ============================================================================
// Story 15.1: Authentication
// ============================================================================

export interface LoginResponse {
  message: string;
  user: CurrentUserResponse;
  disclaimer_required: boolean;
}

export interface RegisterResponse {
  id: string;
  email: string;
  role: string;
  message: string;
  disclaimer_required: boolean;
}

/**
 * Log in with email and password. Sets httpOnly session cookie on success.
 */
export async function loginUser(
  email: string,
  password: string
): Promise<LoginResponse> {
  const response = await fetch(`${API_BASE_URL}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ email, password }),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `Login failed: ${response.status}`);
  }

  return response.json();
}

/**
 * Register a new user account.
 */
export async function registerUser(
  email: string,
  password: string
): Promise<RegisterResponse> {
  const response = await fetch(`${API_BASE_URL}/api/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Registration failed: ${response.status}`
    );
  }

  return response.json();
}

/**
 * Log out the current user. Clears session cookie.
 */
export async function logoutUser(): Promise<void> {
  const response = await apiFetch(`${API_BASE_URL}/api/auth/logout`, {
    method: "POST",
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `Logout failed: ${response.status}`);
  }
}

/**
 * Disclaimer API types
 */
export interface DisclaimerStatusResponse {
  acknowledged: boolean;
  acknowledged_at: string | null;
  disclaimer_version: string;
}

export interface DisclaimerAcknowledgeRequest {
  session_id: string;
  checkbox_experimental: boolean;
  checkbox_not_medical_advice: boolean;
  checkbox_ai_data_flow: boolean;
}

export interface DisclaimerAcknowledgeResponse {
  success: boolean;
  acknowledged_at: string;
  message: string;
}

export interface DisclaimerWarning {
  icon: string;
  title: string;
  text: string;
}

export interface DisclaimerCheckbox {
  id: string;
  label: string;
}

export interface DisclaimerContent {
  version: string;
  title: string;
  warnings: DisclaimerWarning[];
  checkboxes: DisclaimerCheckbox[];
  button_text: string;
}

/**
 * Check if the disclaimer has been acknowledged for a session.
 * Public endpoint (session_id based, not cookie auth) - uses raw fetch intentionally.
 */
export async function getDisclaimerStatus(
  sessionId: string
): Promise<DisclaimerStatusResponse> {
  const response = await fetch(
    `${API_BASE_URL}/api/disclaimer/status?session_id=${encodeURIComponent(sessionId)}`
  );

  if (!response.ok) {
    throw new Error(`Failed to check disclaimer status: ${response.status}`);
  }

  return response.json();
}

/**
 * Acknowledge the disclaimer.
 * Public endpoint (session_id based, not cookie auth) - uses raw fetch intentionally.
 */
export async function acknowledgeDisclaimer(
  data: DisclaimerAcknowledgeRequest
): Promise<DisclaimerAcknowledgeResponse> {
  const response = await fetch(`${API_BASE_URL}/api/disclaimer/acknowledge`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(data),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `Failed to acknowledge disclaimer: ${response.status}`);
  }

  return response.json();
}

/**
 * Get the disclaimer content to display.
 * Public endpoint (no auth required) - uses raw fetch intentionally.
 */
export async function getDisclaimerContent(): Promise<DisclaimerContent> {
  const response = await fetch(`${API_BASE_URL}/api/disclaimer/content`);

  if (!response.ok) {
    throw new Error(`Failed to get disclaimer content: ${response.status}`);
  }

  return response.json();
}

/**
 * Acknowledge the disclaimer for the authenticated user.
 * Story 15.5: Sets disclaimer_acknowledged=true on the user record.
 */
export async function acknowledgeDisclaimerAuth(): Promise<{
  success: boolean;
  message: string;
}> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/disclaimer/acknowledge-auth`,
    { method: "POST" }
  );

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to acknowledge disclaimer: ${response.status}`
    );
  }

  return response.json();
}

/**
 * AI Insights API types (Story 5.7)
 */
export interface InsightSummary {
  id: string;
  analysis_type: "daily_brief" | "meal_analysis" | "correction_analysis";
  title: string;
  content: string;
  created_at: string;
  status: "pending" | "acknowledged" | "dismissed";
}

export interface InsightsListResponse {
  insights: InsightSummary[];
  total: number;
}

export interface SuggestionResponseResponse {
  id: string;
  analysis_type: string;
  analysis_id: string;
  response: string;
  reason: string | null;
  created_at: string;
}

export interface ModelInfo {
  model: string;
  provider: string;
  input_tokens: number;
  output_tokens: number;
}

export interface SafetyInfo {
  status: string;
  has_dangerous_content: boolean;
  flagged_items: Record<string, unknown>[];
  validated_at: string;
}

export interface UserResponseInfo {
  response: string;
  reason: string | null;
  responded_at: string;
}

export interface InsightDetail {
  id: string;
  analysis_type: "daily_brief" | "meal_analysis" | "correction_analysis";
  title: string;
  content: string;
  created_at: string;
  status: "pending" | "acknowledged" | "dismissed";
  period_start: string;
  period_end: string;
  data_context: Record<string, unknown>;
  model_info: ModelInfo;
  safety: SafetyInfo | null;
  user_response: UserResponseInfo | null;
}

/**
 * Fetch detailed view of a single AI insight
 */
export async function getInsightDetail(
  analysisType: string,
  analysisId: string
): Promise<InsightDetail> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/ai/insights/${encodeURIComponent(analysisType)}/${encodeURIComponent(analysisId)}`
  );

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `Failed to fetch insight detail: ${response.status}`);
  }

  return response.json();
}

/**
 * Fetch AI insights for the current user
 */
export async function getInsights(
  limit: number = 10
): Promise<InsightsListResponse> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/ai/insights?limit=${limit}`
  );

  if (!response.ok) {
    throw new Error(`Failed to fetch insights: ${response.status}`);
  }

  return response.json();
}

/**
 * Fetch unread (pending) insights count for sidebar badge
 */
export async function getUnreadInsightsCount(): Promise<number> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/ai/insights/unread-count`
  );

  if (!response.ok) {
    throw new Error(`Failed to fetch unread count: ${response.status}`);
  }

  const data = await response.json();
  return data.unread_count;
}

/**
 * Record a response to an AI insight
 */
export async function respondToInsight(
  analysisType: string,
  analysisId: string,
  response: "acknowledged" | "dismissed",
  reason?: string
): Promise<SuggestionResponseResponse> {
  const res = await apiFetch(
    `${API_BASE_URL}/api/ai/insights/${analysisType}/${analysisId}/respond`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ response, reason }),
    }
  );

  if (!res.ok) {
    const error = await res.json().catch(() => ({}));
    throw new Error(error.detail || `Failed to respond to insight: ${res.status}`);
  }

  return res.json();
}

/**
 * Alert Threshold API types (Story 6.1)
 */
export interface AlertThresholdResponse {
  id: string;
  low_warning: number;
  urgent_low: number;
  high_warning: number;
  urgent_high: number;
  iob_warning: number;
  updated_at: string;
}

export interface AlertThresholdUpdate {
  low_warning?: number;
  urgent_low?: number;
  high_warning?: number;
  urgent_high?: number;
  iob_warning?: number;
}

/**
 * Fetch current alert thresholds
 */
export async function getAlertThresholds(): Promise<AlertThresholdResponse> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/settings/alert-thresholds`
  );

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `Failed to fetch thresholds: ${response.status}`);
  }

  return response.json();
}

/**
 * Update alert thresholds
 */
export async function updateAlertThresholds(
  updates: AlertThresholdUpdate
): Promise<AlertThresholdResponse> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/settings/alert-thresholds`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(updates),
    }
  );

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `Failed to update thresholds: ${response.status}`);
  }

  return response.json();
}

/**
 * Predictive Alert API types (Story 6.2)
 */
export interface PredictiveAlert {
  id: string;
  alert_type: string;
  severity: string;
  current_value: number;
  predicted_value: number | null;
  prediction_minutes: number | null;
  iob_value: number | null;
  message: string;
  trend_rate: number | null;
  source: string;
  acknowledged: boolean;
  acknowledged_at: string | null;
  created_at: string;
  expires_at: string;
}

export interface ActiveAlertsResponse {
  alerts: PredictiveAlert[];
  count: number;
}

export interface AlertAcknowledgeResponse {
  id: string;
  acknowledged: boolean;
  acknowledged_at: string | null;
}

/**
 * Fetch active (unacknowledged, non-expired) alerts
 */
export async function getActiveAlerts(): Promise<ActiveAlertsResponse> {
  const response = await apiFetch(`${API_BASE_URL}/api/alerts/active`);

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to fetch alerts: ${response.status}`
    );
  }

  return response.json();
}

/**
 * Acknowledge an alert by ID
 */
export async function acknowledgeAlert(
  alertId: string
): Promise<AlertAcknowledgeResponse> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/alerts/${encodeURIComponent(alertId)}/acknowledge`,
    { method: "PATCH" }
  );

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to acknowledge alert: ${response.status}`
    );
  }

  return response.json();
}

/**
 * Emergency Contact API types (Story 6.5)
 */
export interface EmergencyContact {
  id: string;
  name: string;
  telegram_username: string;
  priority: "primary" | "secondary";
  position: number;
  created_at: string;
  updated_at: string;
}

export interface EmergencyContactListResponse {
  contacts: EmergencyContact[];
  count: number;
}

export interface EmergencyContactCreate {
  name: string;
  telegram_username: string;
  priority: "primary" | "secondary";
}

export interface EmergencyContactUpdate {
  name?: string;
  telegram_username?: string;
  priority?: "primary" | "secondary";
}

/**
 * Fetch all emergency contacts
 */
export async function getEmergencyContacts(): Promise<EmergencyContactListResponse> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/settings/emergency-contacts`
  );

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to fetch emergency contacts: ${response.status}`
    );
  }

  return response.json();
}

/**
 * Create a new emergency contact
 */
export async function createEmergencyContact(
  data: EmergencyContactCreate
): Promise<EmergencyContact> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/settings/emergency-contacts`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }
  );

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to create emergency contact: ${response.status}`
    );
  }

  return response.json();
}

/**
 * Update an existing emergency contact
 */
export async function updateEmergencyContact(
  contactId: string,
  data: EmergencyContactUpdate
): Promise<EmergencyContact> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/settings/emergency-contacts/${encodeURIComponent(contactId)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }
  );

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to update emergency contact: ${response.status}`
    );
  }

  return response.json();
}

/**
 * Delete an emergency contact
 */
export async function deleteEmergencyContact(
  contactId: string
): Promise<void> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/settings/emergency-contacts/${encodeURIComponent(contactId)}`,
    { method: "DELETE" }
  );

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to delete emergency contact: ${response.status}`
    );
  }
}

/**
 * Escalation Config API types (Story 6.6)
 */
export interface EscalationConfigResponse {
  id: string;
  reminder_delay_minutes: number;
  primary_contact_delay_minutes: number;
  all_contacts_delay_minutes: number;
  updated_at: string;
}

export interface EscalationConfigUpdate {
  reminder_delay_minutes?: number;
  primary_contact_delay_minutes?: number;
  all_contacts_delay_minutes?: number;
}

/**
 * Fetch escalation timing configuration
 */
export async function getEscalationConfig(): Promise<EscalationConfigResponse> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/settings/escalation-config`
  );

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail ||
        `Failed to fetch escalation config: ${response.status}`
    );
  }

  return response.json();
}

/**
 * Update escalation timing configuration
 */
export async function updateEscalationConfig(
  data: EscalationConfigUpdate
): Promise<EscalationConfigResponse> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/settings/escalation-config`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }
  );

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail ||
        `Failed to update escalation config: ${response.status}`
    );
  }

  return response.json();
}

/**
 * Escalation Event types (Story 6.7)
 */
export interface EscalationEvent {
  id: string;
  alert_id: string;
  tier: string;
  triggered_at: string;
  message_content: string;
  notification_status: string;
  contacts_notified: string[];
  created_at: string;
}

export interface EscalationTimelineResponse {
  alert_id: string;
  events: EscalationEvent[];
  count: number;
}

/**
 * Telegram Bot API types (Story 7.1)
 */
export interface TelegramLink {
  id: string;
  chat_id: number;
  username: string | null;
  is_verified: boolean;
  linked_at: string;
}

export interface TelegramStatusResponse {
  linked: boolean;
  link: TelegramLink | null;
  bot_username: string;
}

export interface TelegramVerificationCodeResponse {
  code: string;
  expires_at: string;
  bot_username: string;
}

export interface TelegramUnlinkResponse {
  success: boolean;
  message: string;
}

export interface TelegramTestMessageResponse {
  success: boolean;
  message: string;
}

/**
 * Telegram Bot Configuration types (Story 12.3)
 */
export interface TelegramBotConfigResponse {
  configured: boolean;
  bot_username: string | null;
  configured_at: string | null;
}

export interface TelegramBotValidateResponse {
  valid: boolean;
  bot_username: string;
}

/**
 * Get Telegram bot configuration status
 */
export async function getTelegramBotConfig(): Promise<TelegramBotConfigResponse> {
  const response = await apiFetch(`${API_BASE_URL}/api/telegram/bot-config`);

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to fetch bot config: ${response.status}`
    );
  }

  return response.json();
}

/**
 * Validate and save a Telegram bot token
 */
export async function saveTelegramBotToken(
  token: string
): Promise<TelegramBotValidateResponse> {
  const response = await apiFetch(`${API_BASE_URL}/api/telegram/bot-config`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token }),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to save bot token: ${response.status}`
    );
  }

  return response.json();
}

/**
 * Remove the configured Telegram bot token
 */
export async function removeTelegramBotToken(): Promise<void> {
  const response = await apiFetch(`${API_BASE_URL}/api/telegram/bot-config`, {
    method: "DELETE",
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to remove bot token: ${response.status}`
    );
  }
}

/**
 * Get Telegram link status for the current user
 */
export async function getTelegramStatus(): Promise<TelegramStatusResponse> {
  const response = await apiFetch(`${API_BASE_URL}/api/telegram/status`);

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to fetch Telegram status: ${response.status}`
    );
  }

  return response.json();
}

/**
 * Generate a Telegram verification code for account linking
 */
export async function generateTelegramCode(): Promise<TelegramVerificationCodeResponse> {
  const response = await apiFetch(`${API_BASE_URL}/api/telegram/link`, {
    method: "POST",
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to generate Telegram code: ${response.status}`
    );
  }

  return response.json();
}

/**
 * Unlink the user's Telegram account
 */
export async function unlinkTelegram(): Promise<TelegramUnlinkResponse> {
  const response = await apiFetch(`${API_BASE_URL}/api/telegram/link`, {
    method: "DELETE",
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to unlink Telegram: ${response.status}`
    );
  }

  return response.json();
}

/**
 * Send a test message to the user's linked Telegram account
 */
export async function sendTelegramTestMessage(): Promise<TelegramTestMessageResponse> {
  const response = await apiFetch(`${API_BASE_URL}/api/telegram/test`, {
    method: "POST",
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to send test message: ${response.status}`
    );
  }

  return response.json();
}

/**
 * Get escalation timeline for a specific alert
 */
export async function getAlertEscalationTimeline(
  alertId: string
): Promise<EscalationTimelineResponse> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/escalation/alerts/${encodeURIComponent(alertId)}/timeline`
  );

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail ||
        `Failed to fetch escalation timeline: ${response.status}`
    );
  }

  return response.json();
}

/**
 * Caregiver Invitation API types (Story 8.1)
 */
export interface CaregiverInvitation {
  id: string;
  token: string;
  expires_at: string;
  invite_url: string;
}

export interface CaregiverInvitationListItem {
  id: string;
  status: string;
  created_at: string;
  expires_at: string;
  accepted_by_email: string | null;
}

export interface CaregiverInvitationListResponse {
  invitations: CaregiverInvitationListItem[];
  count: number;
}

export interface InvitationDetail {
  patient_email: string;
  status: string;
  expires_at: string;
}

export interface AcceptInvitationResponse {
  message: string;
  user_id: string;
}

export interface LinkedPatient {
  patient_id: string;
  patient_email: string;
  linked_at: string;
}

export interface LinkedPatientsListResponse {
  patients: LinkedPatient[];
  count: number;
}

/**
 * Create a new caregiver invitation
 */
export async function createCaregiverInvitation(): Promise<CaregiverInvitation> {
  const response = await apiFetch(`${API_BASE_URL}/api/caregivers/invitations`, {
    method: "POST",
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to create invitation: ${response.status}`
    );
  }

  return response.json();
}

/**
 * List all caregiver invitations for the current patient
 */
export async function listCaregiverInvitations(): Promise<CaregiverInvitationListResponse> {
  const response = await apiFetch(`${API_BASE_URL}/api/caregivers/invitations`);

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to list invitations: ${response.status}`
    );
  }

  return response.json();
}

/**
 * Revoke a pending caregiver invitation
 */
export async function revokeCaregiverInvitation(id: string): Promise<void> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/caregivers/invitations/${encodeURIComponent(id)}`,
    { method: "DELETE" }
  );

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to revoke invitation: ${response.status}`
    );
  }
}

/**
 * Get public invitation details.
 * Public endpoint (no auth required) - uses raw fetch intentionally.
 */
export async function getInvitationDetails(
  token: string
): Promise<InvitationDetail> {
  const response = await fetch(
    `${API_BASE_URL}/api/caregivers/invitations/${encodeURIComponent(token)}/details`
  );

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to fetch invitation details: ${response.status}`
    );
  }

  return response.json();
}

/**
 * Accept a caregiver invitation.
 * Public endpoint (no auth required) - uses raw fetch intentionally.
 */
export async function acceptCaregiverInvitation(
  token: string,
  email: string,
  password: string
): Promise<AcceptInvitationResponse> {
  const response = await fetch(`${API_BASE_URL}/api/caregivers/accept`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token, email, password }),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to accept invitation: ${response.status}`
    );
  }

  return response.json();
}

/**
 * List linked patients for the current caregiver
 */
export async function listLinkedPatients(): Promise<LinkedPatientsListResponse> {
  const response = await apiFetch(`${API_BASE_URL}/api/caregivers/patients`);

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to list linked patients: ${response.status}`
    );
  }

  return response.json();
}

/**
 * Caregiver Permissions API types (Story 8.2)
 */
export interface CaregiverPermissions {
  can_view_glucose: boolean;
  can_view_history: boolean;
  can_view_iob: boolean;
  can_view_ai_suggestions: boolean;
  can_receive_alerts: boolean;
}

export interface LinkedCaregiverItem {
  link_id: string;
  caregiver_id: string;
  caregiver_email: string;
  linked_at: string;
  permissions: CaregiverPermissions;
}

export interface LinkedCaregiversResponse {
  caregivers: LinkedCaregiverItem[];
  count: number;
}

export interface PermissionsUpdateResponse {
  link_id: string;
  permissions: CaregiverPermissions;
}

/**
 * List all caregivers linked to the current patient, with permissions
 */
export async function listLinkedCaregivers(): Promise<LinkedCaregiversResponse> {
  const response = await apiFetch(`${API_BASE_URL}/api/caregivers/linked`);

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to list linked caregivers: ${response.status}`
    );
  }

  return response.json();
}

/**
 * Get permissions for a specific caregiver link
 */
export async function getCaregiverPermissions(
  linkId: string
): Promise<PermissionsUpdateResponse> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/caregivers/linked/${encodeURIComponent(linkId)}/permissions`
  );

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to fetch caregiver permissions: ${response.status}`
    );
  }

  return response.json();
}

/**
 * Update permissions for a specific caregiver link
 */
export async function updateCaregiverPermissions(
  linkId: string,
  permissions: Partial<CaregiverPermissions>
): Promise<PermissionsUpdateResponse> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/caregivers/linked/${encodeURIComponent(linkId)}/permissions`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(permissions),
    }
  );

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to update caregiver permissions: ${response.status}`
    );
  }

  return response.json();
}

/**
 * Current User API types (Story 8.3)
 */
export interface CurrentUserResponse {
  id: string;
  email: string;
  display_name: string | null;
  role: "diabetic" | "caregiver" | "admin";
  is_active: boolean;
  email_verified: boolean;
  // Version-aware: the API reports `false` when the stored acknowledgment is for
  // an older disclaimer version, so the gate re-prompts on a version bump.
  disclaimer_acknowledged: boolean;
  disclaimer_version: string | null;
  /**
   * Preferred glucose display unit. Read from /api/auth/me.
   * Optional so a transient deploy skew (web bundle hitting an older API that
   * predates the glucose-unit backend) is type-safe; callers default to "mgdl" (see
   * `useGlucoseUnit`) so existing mg/dL behavior is preserved.
   */
  glucose_unit?: GlucoseUnit;
  created_at: string;
}

/**
 * Get the currently authenticated user's profile
 */
export async function getCurrentUser(): Promise<CurrentUserResponse> {
  const response = await fetch(`${API_BASE_URL}/api/auth/me`, {
    credentials: "include",
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to fetch current user: ${response.status}`
    );
  }

  return response.json();
}

/**
 * Return the HTTP status of `/api/auth/me` without throwing on 4xx/5xx.
 * Used by the login page to detect deployment misconfigs (session cookie
 * dropped by the browser, network failure, etc.) and surface a specific
 * error instead of silently redirecting.
 */
export async function verifySessionCookie(): Promise<number> {
  const response = await fetch(`${API_BASE_URL}/api/auth/me`, {
    credentials: "include",
  });
  return response.status;
}

/**
 * Update user profile (Story 10.2)
 */
export async function updateProfile(data: {
  display_name?: string | null;
}): Promise<CurrentUserResponse> {
  const response = await apiFetch(`${API_BASE_URL}/api/auth/profile`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `Failed to update profile: ${response.status}`);
  }

  return response.json();
}

/**
 * Update the current user's glucose display unit preference.
 *
 * Persists via the dedicated PATCH /api/settings/glucose-unit endpoint
 * (the backend field owner). Web-only: no profile-payload change. Callers
 * refresh the user context afterward so dashboard display switches units.
 */
export async function updateGlucoseUnit(
  glucose_unit: GlucoseUnit
): Promise<{ glucose_unit: GlucoseUnit }> {
  const response = await apiFetch(`${API_BASE_URL}/api/settings/glucose-unit`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ glucose_unit }),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to update glucose unit: ${response.status}`
    );
  }

  return response.json();
}

/**
 * Change password (Story 10.2)
 */
export async function changePassword(data: {
  current_password: string;
  new_password: string;
}): Promise<{ message: string }> {
  const response = await apiFetch(`${API_BASE_URL}/api/auth/change-password`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `Failed to change password: ${response.status}`);
  }

  return response.json();
}

/**
 * Caregiver Dashboard API types (Story 8.3)
 */
export interface CaregiverGlucoseData {
  value: number;
  trend: string;
  trend_rate: number | null;
  reading_timestamp: string;
  minutes_ago: number;
  is_stale: boolean;
}

export interface CaregiverIoBData {
  current_iob: number;
  projected_30min: number | null;
  confirmed_at: string;
  is_stale: boolean;
}

export interface CaregiverPatientStatus {
  patient_id: string;
  patient_email: string;
  glucose: CaregiverGlucoseData | null;
  iob: CaregiverIoBData | null;
  permissions: CaregiverPermissions;
}

export interface CaregiverGlucoseHistoryReading {
  value: number;
  trend: string;
  trend_rate: number | null;
  reading_timestamp: string;
}

export interface CaregiverGlucoseHistoryResponse {
  patient_id: string;
  readings: CaregiverGlucoseHistoryReading[];
  count: number;
}

/**
 * Get permission-filtered patient status for caregiver dashboard
 */
export async function getCaregiverPatientStatus(
  patientId: string
): Promise<CaregiverPatientStatus> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/caregivers/patients/${encodeURIComponent(patientId)}/status`
  );

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to fetch patient status: ${response.status}`
    );
  }

  return response.json();
}

/**
 * Get glucose history for a linked patient (caregiver view)
 */
export async function getCaregiverGlucoseHistory(
  patientId: string,
  minutes: number = 180,
  limit: number = 36
): Promise<CaregiverGlucoseHistoryResponse> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/caregivers/patients/${encodeURIComponent(patientId)}/glucose/history?minutes=${minutes}&limit=${limit}`
  );

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to fetch glucose history: ${response.status}`
    );
  }

  return response.json();
}

/**
 * Target Glucose Range API types (Story 9.1)
 */
export interface TargetGlucoseRangeResponse {
  id: string;
  urgent_low: number;
  low_target: number;
  high_target: number;
  urgent_high: number;
  updated_at: string;
}

export interface TargetGlucoseRangeUpdate {
  urgent_low?: number;
  low_target?: number;
  high_target?: number;
  urgent_high?: number;
}

export interface TargetGlucoseRangeDefaults {
  urgent_low: number;
  low_target: number;
  high_target: number;
  urgent_high: number;
}

/**
 * Fetch current target glucose range
 */
export async function getTargetGlucoseRange(): Promise<TargetGlucoseRangeResponse> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/settings/target-glucose-range`
  );

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to fetch target glucose range: ${response.status}`
    );
  }

  return response.json();
}

/**
 * Update target glucose range
 */
export async function updateTargetGlucoseRange(
  updates: TargetGlucoseRangeUpdate
): Promise<TargetGlucoseRangeResponse> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/settings/target-glucose-range`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(updates),
    }
  );

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail ||
        `Failed to update target glucose range: ${response.status}`
    );
  }

  return response.json();
}

/**
 * Insulin Configuration API types
 */
export interface InsulinConfigResponse {
  id: string;
  insulin_type: string;
  dia_hours: number;
  onset_minutes: number;
  updated_at: string;
}

export interface InsulinConfigUpdate {
  insulin_type?: string;
  dia_hours?: number;
  onset_minutes?: number;
}

export interface InsulinPresets {
  [key: string]: { dia_hours: number; onset_minutes: number };
}

export interface InsulinConfigDefaults {
  insulin_type: string;
  dia_hours: number;
  onset_minutes: number;
  presets: InsulinPresets;
}

/**
 * Fetch current insulin configuration
 */
export async function getInsulinConfig(): Promise<InsulinConfigResponse> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/settings/insulin-config`
  );

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to fetch insulin config: ${response.status}`
    );
  }

  return response.json();
}

/**
 * Update insulin configuration
 */
export async function updateInsulinConfig(
  updates: InsulinConfigUpdate
): Promise<InsulinConfigResponse> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/settings/insulin-config`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(updates),
    }
  );

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to update insulin config: ${response.status}`
    );
  }

  return response.json();
}

/**
 * Fetch insulin config defaults and presets
 */
export async function getInsulinConfigDefaults(): Promise<InsulinConfigDefaults> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/settings/insulin-config/defaults`
  );

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to fetch insulin defaults: ${response.status}`
    );
  }

  return response.json();
}

/**
 * Brief Delivery Config API types (Story 9.2)
 */
export interface BriefDeliveryConfigResponse {
  id: string;
  enabled: boolean;
  delivery_time: string;
  timezone: string;
  channel: "web_only" | "telegram" | "both";
  updated_at: string;
}

export interface BriefDeliveryConfigUpdate {
  enabled?: boolean;
  delivery_time?: string;
  timezone?: string;
  channel?: "web_only" | "telegram" | "both";
}

export interface BriefDeliveryConfigDefaults {
  enabled: boolean;
  delivery_time: string;
  timezone: string;
  channel: "web_only" | "telegram" | "both";
}

/**
 * Fetch current brief delivery configuration
 */
export async function getBriefDeliveryConfig(): Promise<BriefDeliveryConfigResponse> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/settings/brief-delivery`
  );

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to fetch brief delivery config: ${response.status}`
    );
  }

  return response.json();
}

/**
 * Update brief delivery configuration
 */
export async function updateBriefDeliveryConfig(
  updates: BriefDeliveryConfigUpdate
): Promise<BriefDeliveryConfigResponse> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/settings/brief-delivery`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(updates),
    }
  );

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail ||
        `Failed to update brief delivery config: ${response.status}`
    );
  }

  return response.json();
}

/**
 * Data Retention Config API types (Story 9.3)
 */
export interface DataRetentionConfigResponse {
  id: string;
  glucose_retention_days: number;
  analysis_retention_days: number;
  audit_retention_days: number;
  updated_at: string;
}

export interface DataRetentionConfigUpdate {
  glucose_retention_days?: number;
  analysis_retention_days?: number;
  audit_retention_days?: number;
}

export interface DataRetentionConfigDefaults {
  glucose_retention_days: number;
  analysis_retention_days: number;
  audit_retention_days: number;
}

export interface StorageUsageResponse {
  glucose_records: number;
  pump_records: number;
  analysis_records: number;
  audit_records: number;
  total_records: number;
}

/**
 * Fetch current data retention configuration
 */
export async function getDataRetentionConfig(): Promise<DataRetentionConfigResponse> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/settings/data-retention`
  );

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to fetch data retention config: ${response.status}`
    );
  }

  return response.json();
}

/**
 * Update data retention configuration
 */
export async function updateDataRetentionConfig(
  updates: DataRetentionConfigUpdate
): Promise<DataRetentionConfigResponse> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/settings/data-retention`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(updates),
    }
  );

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail ||
        `Failed to update data retention config: ${response.status}`
    );
  }

  return response.json();
}

/**
 * Fetch storage usage (record counts)
 */
export async function getStorageUsage(): Promise<StorageUsageResponse> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/settings/data-retention/usage`
  );

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to fetch storage usage: ${response.status}`
    );
  }

  return response.json();
}

/**
 * Data purge (Story 9.4)
 */
export interface DataPurgeResponse {
  success: boolean;
  deleted_records: Record<string, number>;
  total_deleted: number;
  message: string;
}

export async function purgeUserData(
  confirmationText: string
): Promise<DataPurgeResponse> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/settings/data-retention/purge`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirmation_text: confirmationText }),
    }
  );

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to purge data: ${response.status}`
    );
  }

  return response.json();
}

/**
 * Settings export (Story 9.5)
 */
export interface SettingsExportResponse {
  export_data: Record<string, unknown>;
}

export async function exportSettings(
  exportType: "settings_only" | "all_data"
): Promise<SettingsExportResponse> {
  const response = await apiFetch(`${API_BASE_URL}/api/settings/export`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ export_type: exportType }),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to export settings: ${response.status}`
    );
  }

  return response.json();
}

/**
 * Caregiver AI Chat (Story 8.4)
 */
export interface CaregiverChatResponse {
  response: string;
  disclaimer: string;
}

export async function sendCaregiverChat(
  patientId: string,
  message: string
): Promise<CaregiverChatResponse> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/caregivers/patients/${encodeURIComponent(patientId)}/chat`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    }
  );

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to send chat message: ${response.status}`
    );
  }

  return response.json();
}

// ============================================================================
// Story 12.1: Integration Management
// ============================================================================

export interface IntegrationResponse {
  integration_type: "dexcom" | "tandem";
  status: "pending" | "connected" | "error" | "disconnected";
  last_sync_at: string | null;
  last_error: string | null;
  created_at: string;
  updated_at: string;
  /**
   * Per-integration region/locale stored on the credential.
   *  - Tandem: ISO-3166-1 alpha-2 country code (or legacy "EU" from an
   *    older schema version, which is no longer supported).
   *  - Dexcom: pydexcom region ("US" | "OUS" | "JP").
   */
  region: string | null;
}

export interface IntegrationListResponse {
  integrations: IntegrationResponse[];
}

export interface IntegrationConnectResponse {
  message: string;
  integration: IntegrationResponse;
}

/**
 * List all configured integrations for the current user.
 */
export async function listIntegrations(): Promise<IntegrationListResponse> {
  const response = await apiFetch(`${API_BASE_URL}/api/integrations`);

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to fetch integrations: ${response.status}`
    );
  }

  return response.json();
}

/**
 * Connect Dexcom integration (validates credentials before storing).
 *
 * `region` selects which Dexcom Share server pydexcom hits:
 *   - "US"  -> share2.dexcom.com           (United States)
 *   - "OUS" -> shareous1.dexcom.com        (Outside US: EU, UK, Canada, AU, ...)
 *   - "JP"  -> share.dexcom.jp             (Japan & Asia-Pacific)
 */
export async function connectDexcom(credentials: {
  username: string;
  password: string;
  region: string;
}): Promise<IntegrationConnectResponse> {
  const response = await apiFetch(`${API_BASE_URL}/api/integrations/dexcom`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(credentials),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to connect Dexcom: ${response.status}`
    );
  }

  return response.json();
}

/**
 * Disconnect Dexcom integration.
 */
export async function disconnectDexcom(): Promise<void> {
  const response = await apiFetch(`${API_BASE_URL}/api/integrations/dexcom`, {
    method: "DELETE",
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to disconnect Dexcom: ${response.status}`
    );
  }
}

/**
 * Connect Tandem integration (validates credentials before storing).
 *
 * `country` is an ISO-3166-1 alpha-2 code that is used to route uploads
 * to the correct Tandem cloud backend (US or EU cluster + per-country
 * config). See `apps/web/src/lib/tandem-countries.ts` for the supported list.
 */
export async function connectTandem(credentials: {
  username: string;
  password: string;
  country: string;
}): Promise<IntegrationConnectResponse> {
  const response = await apiFetch(`${API_BASE_URL}/api/integrations/tandem`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(credentials),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to connect Tandem: ${response.status}`
    );
  }

  return response.json();
}

/**
 * Disconnect Tandem integration.
 */
export async function disconnectTandem(): Promise<void> {
  const response = await apiFetch(`${API_BASE_URL}/api/integrations/tandem`, {
    method: "DELETE",
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to disconnect Tandem: ${response.status}`
    );
  }
}

// ============================================================================
// Story 43.x: Nightscout Cloud-Mediated Integration
// ============================================================================

export type NightscoutAuthType = "auto" | "secret" | "token";
export type NightscoutApiVersion = "auto" | "v1" | "v3";
// Mirrors `apps/api/src/models/nightscout_connection.py::NightscoutSyncStatus`.
// `never` is the default for a newly-created connection (no sync attempted
// yet); `unreachable` is set after repeated failures pause polling.
export type NightscoutSyncStatus =
  | "never"
  | "ok"
  | "error"
  | "auth_failed"
  | "rate_limited"
  | "network"
  | "unreachable";

export interface NightscoutConnectionResponse {
  id: string;
  name: string;
  base_url: string;
  auth_type: NightscoutAuthType;
  api_version: NightscoutApiVersion;
  is_active: boolean;
  has_credential: boolean;
  sync_interval_minutes: number;
  initial_sync_window_days: number;
  last_sync_status: NightscoutSyncStatus;
  last_synced_at: string | null;
  last_sync_error: string | null;
  // Shape varies per uploader; treat as opaque and narrow at the consumer.
  detected_uploaders_json: unknown;
  last_evaluated_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface NightscoutConnectionListResponse {
  connections: NightscoutConnectionResponse[];
}

export interface NightscoutConnectionTestResult {
  ok: boolean;
  server_version: string | null;
  api_version_detected: NightscoutApiVersion | null;
  auth_validated: boolean;
  error: string | null;
}

export interface NightscoutConnectionCreatedResponse {
  connection: NightscoutConnectionResponse;
  test: NightscoutConnectionTestResult;
}

export interface NightscoutConnectionCreate {
  name: string;
  base_url: string;
  auth_type?: NightscoutAuthType;
  credential: string;
  api_version?: NightscoutApiVersion;
  sync_interval_minutes?: number;
  initial_sync_window_days?: number;
}

export async function listNightscoutConnections(): Promise<NightscoutConnectionListResponse> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/integrations/nightscout`
  );
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to list Nightscout connections: ${response.status}`
    );
  }
  return response.json();
}

export async function createNightscoutConnection(
  body: NightscoutConnectionCreate
): Promise<NightscoutConnectionCreatedResponse> {
  const response = await apiFetch(`${API_BASE_URL}/api/integrations/nightscout`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to create Nightscout connection: ${response.status}`
    );
  }
  return response.json();
}

export async function testNightscoutConnection(
  connectionId: string
): Promise<NightscoutConnectionTestResult> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/integrations/nightscout/${encodeURIComponent(
      connectionId
    )}/test`,
    { method: "POST" }
  );
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to test Nightscout connection: ${response.status}`
    );
  }
  return response.json();
}

export interface NightscoutManualSyncResponse {
  connection_id: string;
  status: NightscoutSyncStatus;
  entries_inserted: number;
  entries_skipped: number;
  entries_failed: number;
  treatments_inserted_pump: number;
  treatments_inserted_glucose: number;
  treatments_failed: number;
  devicestatuses_inserted: number;
  devicestatuses_failed: number;
  profile_synced: boolean;
  duration_ms: number;
  error: string | null;
}

export async function syncNightscoutConnection(
  connectionId: string
): Promise<NightscoutManualSyncResponse> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/integrations/nightscout/${encodeURIComponent(
      connectionId
    )}/sync`,
    { method: "POST" }
  );
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to sync Nightscout connection: ${response.status}`
    );
  }
  return response.json();
}

export async function deleteNightscoutConnection(
  connectionId: string
): Promise<void> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/integrations/nightscout/${encodeURIComponent(
      connectionId
    )}`,
    { method: "DELETE" }
  );
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to delete Nightscout connection: ${response.status}`
    );
  }
}

// PATCH body for `update_connection`. The backend re-tests the
// connection ONLY when url / credential / auth_type / api_version
// change (see apps/api/src/routers/nightscout.py:292). Sending only
// `sync_interval_minutes` (the picker's payload) is a fast in-place
// update with no network round-trip to the user's NS instance --
// safe to fire on every chip click.
export interface NightscoutConnectionUpdate {
  name?: string;
  base_url?: string;
  auth_type?: NightscoutAuthType;
  credential?: string;
  api_version?: NightscoutApiVersion;
  is_active?: boolean;
  sync_interval_minutes?: number;
  initial_sync_window_days?: number;
}

export async function patchNightscoutConnection(
  connectionId: string,
  body: NightscoutConnectionUpdate
): Promise<NightscoutConnectionCreatedResponse> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/integrations/nightscout/${encodeURIComponent(
      connectionId
    )}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }
  );
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to update Nightscout connection: ${response.status}`
    );
  }
  return response.json();
}

// ----------------------------------------------------------------------------
// Nightscout smart-onboarding wizard endpoints
// ----------------------------------------------------------------------------

export interface NightscoutProfileSegmentDTO {
  time: string;
  value: number;
  // The backend model has `extra="allow"` — Loop/AAPS-style fields like
  // `timeAsSeconds` may flow through. Keep TS open so we don't strip on
  // round-trip.
  [key: string]: unknown;
}

export interface NightscoutDiscoveryProfileSummary {
  target_low: number | null;
  target_high: number | null;
  dia_hours: number | null;
  units: "mg/dl" | "mmol" | null;
  timezone: string | null;
  carb_ratio_schedule: NightscoutProfileSegmentDTO[] | null;
  isf_schedule: NightscoutProfileSegmentDTO[] | null;
  basal_schedule: NightscoutProfileSegmentDTO[] | null;
  target_low_schedule: NightscoutProfileSegmentDTO[] | null;
  target_high_schedule: NightscoutProfileSegmentDTO[] | null;
  is_malformed: boolean;
}

export interface NightscoutDiscoveryReport {
  status_ok: boolean;
  server_version: string | null;
  earliest_entry_at: string | null;
  entry_count_estimate: number;
  recent_entry_count_7d: number;
  uploaders_detected: string[];
  has_treatments: boolean;
  treatment_count_estimate: number;
  has_devicestatus: boolean;
  has_profile: boolean;
  profile_summary: NightscoutDiscoveryProfileSummary | null;
  active_pump_loop: string | null;
  partial_resources: string[];
  evaluated_at: string;
  error: string | null;
}

export interface OnboardingScheduleSegment {
  start_minutes: number;
  value: number;
}

export interface OnboardingNumericFieldDerivation {
  field: string;
  current_value: number | null;
  proposed_value: number | null;
  default_checked: boolean;
}

export interface OnboardingScheduleFieldDerivation {
  field: string;
  current_segments: OnboardingScheduleSegment[] | null;
  proposed_segments: OnboardingScheduleSegment[] | null;
  default_checked: boolean;
}

export interface OnboardingDerivation {
  has_profile: boolean;
  units_converted: boolean;
  units_unknown: boolean;
  target_low: OnboardingNumericFieldDerivation;
  target_high: OnboardingNumericFieldDerivation;
  dia_hours: OnboardingNumericFieldDerivation;
  carb_ratio_schedule: OnboardingScheduleFieldDerivation;
  isf_schedule: OnboardingScheduleFieldDerivation;
  basal_schedule: OnboardingScheduleFieldDerivation;
}

export type FirstSyncStatus = "ok" | "timeout" | "error" | "skipped";

export interface NightscoutApplyOnboardingRequest {
  import_target_low?: boolean;
  import_target_high?: boolean;
  import_dia_hours?: boolean;
  import_basal_schedule?: boolean;
  import_carb_ratio_schedule?: boolean;
  import_isf_schedule?: boolean;
  override_target_low?: number | null;
  override_target_high?: number | null;
  override_dia_hours?: number | null;
  initial_sync_window_days?: number | null;
  confirm_units_unknown?: boolean;
}

export interface NightscoutApplyOnboardingResponse {
  connection_id: string;
  applied: Record<string, boolean>;
  target_glucose_range: Record<string, unknown> | null;
  insulin_config: Record<string, unknown> | null;
  pump_profile_id: string | null;
  first_sync_status: FirstSyncStatus;
  first_sync_error: string | null;
  sync_result: NightscoutManualSyncResponse | null;
}

// Extract a usable error message from an upstream non-2xx response.
// Falls back to text() when the body isn't JSON (e.g. an nginx 502
// HTML page or a WAF block message) so the user sees something
// actionable instead of a bare status code.
async function _readErrorDetail(
  response: Response,
  fallback: string
): Promise<string> {
  try {
    const text = await response.text();
    if (!text) return `${fallback}: ${response.status}`;
    try {
      const json = JSON.parse(text);
      if (json && typeof json.detail === "string") return json.detail;
      // FastAPI 422 returns `detail` as a list of `{loc, msg, type}`
      // entries; other endpoints may return a structured object.
      // Stringify (trimmed) rather than drop on the floor.
      if (json && json.detail !== undefined) {
        try {
          return `${fallback}: ${response.status} ${JSON.stringify(json.detail).slice(0, 300)}`;
        } catch {
          // serialisation failed (cycles); fall through.
        }
      }
    } catch {
      // Not JSON -- pass the raw text through, trimmed.
      const trimmed = text.trim().slice(0, 300);
      if (trimmed) return `${fallback}: ${response.status} ${trimmed}`;
    }
  } catch {
    // body read failed (network / abort); fall through.
  }
  return `${fallback}: ${response.status}`;
}

// POST evaluate — discovery report. Cached server-side ~5min on the row,
// so two wizard openings in a row don't re-fetch the upstream sample.
export async function evaluateNightscoutConnection(
  connectionId: string
): Promise<NightscoutDiscoveryReport> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/integrations/nightscout/${encodeURIComponent(
      connectionId
    )}/evaluate`,
    { method: "POST" }
  );
  if (!response.ok) {
    throw new Error(
      await _readErrorDetail(response, "Failed to evaluate Nightscout connection")
    );
  }
  return response.json();
}

export async function getNightscoutOnboardingDerivation(
  connectionId: string
): Promise<OnboardingDerivation> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/integrations/nightscout/${encodeURIComponent(
      connectionId
    )}/onboarding-derivation`
  );
  if (!response.ok) {
    throw new Error(
      await _readErrorDetail(
        response,
        "Failed to read Nightscout onboarding derivation"
      )
    );
  }
  return response.json();
}

export async function applyNightscoutOnboarding(
  connectionId: string,
  body: NightscoutApplyOnboardingRequest
): Promise<NightscoutApplyOnboardingResponse> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/integrations/nightscout/${encodeURIComponent(
      connectionId
    )}/apply-onboarding`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }
  );
  if (!response.ok) {
    throw new Error(
      await _readErrorDetail(response, "Failed to apply Nightscout onboarding")
    );
  }
  return response.json();
}

/**
 * AI Provider Configuration API (Story 11.1)
 */

export type AIProviderType =
  | "claude_api"
  | "openai_api"
  | "claude_subscription"
  | "chatgpt_subscription"
  | "openai_compatible"
  | "claude" // Legacy - may appear in existing DB rows
  | "openai"; // Legacy - may appear in existing DB rows
export type AIProviderStatus = "connected" | "error" | "pending";

export interface AIProviderConfigResponse {
  provider_type: AIProviderType;
  status: AIProviderStatus;
  model_name: string | null;
  base_url: string | null;
  max_response_tokens: number | null;
  sidecar_provider: SidecarProviderName | null;
  masked_api_key: string;
  last_validated_at: string | null;
  last_error: string | null;
  created_at: string;
  updated_at: string;
}

export interface AIProviderConfigRequest {
  provider_type: AIProviderType;
  api_key: string;
  model_name?: string | null;
  base_url?: string | null;
  // NULL = use the per-context default (1200 web / 800 Telegram).
  // Raise this when running a thinking model (Qwen3, DeepSeek-R1) --
  // internal reasoning tokens count against the same budget as the
  // visible response. Backend enforces 256-32768. See issue #554.
  max_response_tokens?: number | null;
}

export interface AIProviderTestResponse {
  success: boolean;
  message: string;
}

export interface AIProviderDeleteResponse {
  message: string;
}

export async function getAIProvider(): Promise<AIProviderConfigResponse> {
  const response = await apiFetch(`${API_BASE_URL}/api/ai/provider`);

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      `${response.status}: ${error.detail || "Failed to fetch AI provider"}`
    );
  }
  return response.json();
}

export async function configureAIProvider(
  request: AIProviderConfigRequest
): Promise<AIProviderConfigResponse> {
  const response = await apiFetch(`${API_BASE_URL}/api/ai/provider`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to configure AI provider: ${response.status}`
    );
  }
  return response.json();
}

export async function testAIProvider(): Promise<AIProviderTestResponse> {
  const response = await apiFetch(`${API_BASE_URL}/api/ai/provider/test`, {
    method: "POST",
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to test AI provider: ${response.status}`
    );
  }
  return response.json();
}

export async function deleteAIProvider(): Promise<AIProviderDeleteResponse> {
  const response = await apiFetch(`${API_BASE_URL}/api/ai/provider`, {
    method: "DELETE",
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to delete AI provider: ${response.status}`
    );
  }
  return response.json();
}

// ── Story 15.4: Subscription Configure ──

export type SidecarProviderName = "claude" | "codex";

export interface SubscriptionConfigureRequest {
  sidecar_provider: SidecarProviderName;
  model_name?: string | null;
}

export async function configureSubscriptionProvider(
  request: SubscriptionConfigureRequest
): Promise<AIProviderConfigResponse> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/ai/subscription/configure`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    }
  );

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail ||
        `Failed to configure subscription provider: ${response.status}`
    );
  }

  return response.json();
}

// ── Story 15.2: Subscription Auth ──

export interface SubscriptionAuthStartResponse {
  provider: string;
  auth_method: string;
  instructions: string;
}

export interface SubscriptionAuthTokenResponse {
  success: boolean;
  provider: string;
  error?: string;
}

export interface SubscriptionAuthStatusResponse {
  sidecar_available: boolean;
  claude?: { authenticated: boolean };
  codex?: { authenticated: boolean };
}

export interface SidecarHealthResponse {
  available: boolean;
  status: string;
  claude_auth?: boolean;
  codex_auth?: boolean;
}

export async function startSubscriptionAuth(
  provider: SidecarProviderName
): Promise<SubscriptionAuthStartResponse> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/ai/subscription/auth/start`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ provider }),
    }
  );

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to start subscription auth: ${response.status}`
    );
  }

  return response.json();
}

export async function submitSubscriptionToken(
  provider: SidecarProviderName,
  token: string
): Promise<SubscriptionAuthTokenResponse> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/ai/subscription/auth/token`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ provider, token }),
    }
  );

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to submit token: ${response.status}`
    );
  }

  return response.json();
}

export async function getSubscriptionAuthStatus(): Promise<SubscriptionAuthStatusResponse> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/ai/subscription/auth/status`
  );

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to fetch subscription auth status: ${response.status}`
    );
  }

  return response.json();
}

export async function revokeSubscriptionAuth(
  provider: SidecarProviderName
): Promise<void> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/ai/subscription/auth/revoke`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ provider }),
    }
  );

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to revoke subscription auth: ${response.status}`
    );
  }
}

export async function getSidecarHealth(): Promise<SidecarHealthResponse> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/ai/subscription/sidecar/health`
  );

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to fetch sidecar health: ${response.status}`
    );
  }

  return response.json();
}

// ── Story 11.2: AI Chat ──

export interface AIChatResponse {
  response: string;
  disclaimer: string;
  conversation_id?: string;
  message_id?: string;
}

export interface ChatHistoryMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: string;
  model?: string | null;
  disclaimer?: string | null;
}

export interface ChatHistoryResponse {
  conversation_id: string | null;
  messages: ChatHistoryMessage[];
  total: number;
}

export async function sendAIChat(message: string): Promise<AIChatResponse> {
  const response = await apiFetch(`${API_BASE_URL}/api/ai/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to send message: ${response.status}`
    );
  }
  return response.json();
}

export async function getChatHistory(): Promise<ChatHistoryResponse> {
  const response = await apiFetch(`${API_BASE_URL}/api/ai/chat/history`);
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to load chat history: ${response.status}`
    );
  }
  return response.json();
}

export async function clearChatHistory(): Promise<void> {
  const response = await apiFetch(`${API_BASE_URL}/api/ai/chat/history`, {
    method: "DELETE",
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to clear chat history: ${response.status}`
    );
  }
}

// ============================================================================
// AI Research Sources (Story 35.12)
// ============================================================================

export interface ResearchSource {
  id: string;
  url: string;
  name: string;
  category: string | null;
  is_active: boolean;
  last_researched_at: string | null;
  created_at: string;
}

export interface ResearchSuggestion {
  url: string;
  name: string;
  category: string;
}

export async function getResearchSources(): Promise<{ sources: ResearchSource[]; total: number }> {
  const response = await apiFetch(`${API_BASE_URL}/api/ai/research/sources`);
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `Failed to load research sources: ${response.status}`);
  }
  return response.json();
}

export async function addResearchSource(url: string, name: string, category?: string): Promise<ResearchSource> {
  const response = await apiFetch(`${API_BASE_URL}/api/ai/research/sources`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, name, category }),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `Failed to add source: ${response.status}`);
  }
  return response.json();
}

export async function deleteResearchSource(sourceId: string): Promise<void> {
  const response = await apiFetch(`${API_BASE_URL}/api/ai/research/sources/${encodeURIComponent(sourceId)}`, {
    method: "DELETE",
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `Failed to delete source: ${response.status}`);
  }
}

export async function triggerResearch(): Promise<{ sources: number; updated: number; new: number; unchanged: number; errors: number }> {
  const response = await apiFetch(`${API_BASE_URL}/api/ai/research/run`, {
    method: "POST",
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `Research failed: ${response.status}`);
  }
  return response.json();
}

export async function getResearchSuggestions(): Promise<{ suggestions: ResearchSuggestion[]; based_on: Record<string, string> }> {
  const response = await apiFetch(`${API_BASE_URL}/api/ai/research/suggestions`);
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `Failed to load suggestions: ${response.status}`);
  }
  return response.json();
}

// ============================================================================
// Knowledge Base (Story 35.10)
// ============================================================================

export interface KnowledgeDocument {
  source_name: string;
  source_url: string | null;
  source_type: string;
  trust_tier: string;
  chunk_count: number;
  total_content_length: number;
  first_created: string;
  last_updated: string | null;
  injection_risk_count: number;
  update_source: string | null;
  change_summary: string | null;
}

export interface KnowledgeChunkItem {
  id: string;
  content: string;
  content_preview: string;
  content_length: number;
  source_url: string | null;
  retrieved_at: string | null;
  created_at: string;
  injection_risk: boolean;
}

export interface KnowledgeStats {
  total_documents: number;
  total_chunks: number;
  by_tier: Record<string, number>;
}

export async function getKnowledgeDocuments(params?: {
  trust_tier?: string;
  search?: string;
  page?: number;
  page_size?: number;
}): Promise<{ documents: KnowledgeDocument[]; total_documents: number; total_chunks: number }> {
  const searchParams = new URLSearchParams();
  if (params?.trust_tier) searchParams.set("trust_tier", params.trust_tier);
  if (params?.search) searchParams.set("search", params.search);
  if (params?.page) searchParams.set("page", String(params.page));
  if (params?.page_size) searchParams.set("page_size", String(params.page_size));
  const qs = searchParams.toString();
  const response = await apiFetch(`${API_BASE_URL}/api/knowledge/documents${qs ? `?${qs}` : ""}`);
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `Failed to load knowledge base: ${response.status}`);
  }
  return response.json();
}

export async function getKnowledgeDocumentChunks(
  sourceName: string,
  sourceUrl?: string | null,
  page?: number,
): Promise<{ chunks: KnowledgeChunkItem[]; total: number; source_name: string }> {
  const searchParams = new URLSearchParams({ source_name: sourceName });
  if (sourceUrl) searchParams.set("source_url", sourceUrl);
  if (page) searchParams.set("page", String(page));
  const response = await apiFetch(`${API_BASE_URL}/api/knowledge/documents/chunks?${searchParams}`);
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `Failed to load chunks: ${response.status}`);
  }
  return response.json();
}

export async function deleteKnowledgeDocument(
  sourceName: string,
  sourceUrl?: string | null,
): Promise<{ message: string; chunks_invalidated: number }> {
  const searchParams = new URLSearchParams({ source_name: sourceName });
  if (sourceUrl) searchParams.set("source_url", sourceUrl);
  const response = await apiFetch(`${API_BASE_URL}/api/knowledge/documents?${searchParams}`, {
    method: "DELETE",
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `Failed to delete document: ${response.status}`);
  }
  return response.json();
}

export async function getKnowledgeStats(): Promise<KnowledgeStats> {
  const response = await apiFetch(`${API_BASE_URL}/api/knowledge/stats`);
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `Failed to load stats: ${response.status}`);
  }
  return response.json();
}

// ============================================================================
// Glucose History
// ============================================================================

export interface GlucoseHistoryReading {
  value: number;
  reading_timestamp: string;
  trend: string;
  trend_rate: number | null;
  received_at: string;
  source: string;
}

export interface GlucoseHistoryResponse {
  readings: GlucoseHistoryReading[];
  count: number;
}

export async function getGlucoseHistory(
  minutes: number = 180,
  limit: number = 288
): Promise<GlucoseHistoryResponse> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/integrations/glucose/history?minutes=${minutes}&limit=${limit}`
  );
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to fetch glucose history: ${response.status}`
    );
  }
  return response.json();
}

// ============================================================================
// Pump Event History
// ============================================================================

export type PumpEventType = "basal" | "bolus" | "correction" | "suspend" | "resume" | "bg_reading" | "battery" | "reservoir";

export interface PumpEventReading {
  event_type: PumpEventType;
  event_timestamp: string;
  units: number | null;
  duration_minutes: number | null;
  is_automated: boolean;
  control_iq_reason: string | null;
  pump_activity_mode: string | null;
  basal_adjustment_pct: number | null;
  iob_at_event: number | null;
  cob_at_event: number | null;
  bg_at_event: number | null;
  received_at: string;
  source: string;
}

export interface PumpEventHistoryResponse {
  events: PumpEventReading[];
  count: number;
}

export async function getPumpEventHistory(
  minutes: number = 180,
  limit: number = 500
): Promise<PumpEventHistoryResponse> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/integrations/pump/history?minutes=${minutes}&limit=${limit}`
  );
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to fetch pump events: ${response.status}`
    );
  }
  return response.json();
}

// ============================================================================
// Pump Status (Hero Card)
// ============================================================================

export interface PumpStatusBasal {
  rate: number;
  is_automated: boolean;
  timestamp: string;
}

export interface PumpStatusBattery {
  percentage: number;
  is_charging: boolean;
  timestamp: string;
}

export interface PumpStatusReservoir {
  units_remaining: number;
  timestamp: string;
}

// Story 43.12 PR 6 -- closed-loop runtime state added to the
// pump-status response. All three are nullable; absence means the
// underlying data isn't present or the snapshot is stale.
//
// `state` and `source` mirror the backend's Pydantic `Literal` types
// (`apps/api/src/schemas/pump.py`). Keep these unions in sync if the
// backend's allowed set ever expands -- a frontend that accepts a
// broader string than the backend emits is a quiet contract bug.
export type LoopApiState = "looping" | "not_looping" | "failed";
export type LoopApiSource = "loop" | "aaps" | "trio" | "oref0" | "iaps";

export interface LoopStatusResponse {
  state: LoopApiState;
  source: LoopApiSource;
  issued_at: string;
  failure_reason: string | null;
}

export interface OverrideStatusResponse {
  name: string;
  started_at: string;
  ends_at: string | null;
  multiplier: number | null;
  target_low_mgdl: number | null;
  target_high_mgdl: number | null;
}

export interface PumpStatusResponse {
  basal: PumpStatusBasal | null;
  battery: PumpStatusBattery | null;
  reservoir: PumpStatusReservoir | null;
  // PR 6 additions. Optional in the type (default null) so older
  // backend responses without these fields don't break the client.
  loop_status?: LoopStatusResponse | null;
  override?: OverrideStatusResponse | null;
  cob_grams?: number | null;
}

export async function getPumpStatus(): Promise<PumpStatusResponse> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/integrations/pump/status`
  );
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to fetch pump status: ${response.status}`
    );
  }
  return response.json();
}

// ============================================================================
// Forecast (Story 43.12 PR 3 backend, PR 4 frontend)
// ============================================================================
//
// `source` enums mirror the backend Pydantic `Literal` types
// (apps/api/src/schemas/forecast.py). Keep these unions in sync if the
// backend's allowed set ever expands -- a frontend that accepts a
// broader string than the backend emits is a quiet contract bug.

/** Picker preference values, including the picker-only states. */
export type ForecastSourcePreference =
  | "auto"
  | "none"
  | "loop"
  | "aaps"
  | "trio"
  | "oref0"
  | "iaps"
  | "glycemicgpt";

/** Subset that can actually drive a forecast (excludes picker-only states). */
export type ForecastEngine =
  | "loop"
  | "aaps"
  | "trio"
  | "oref0"
  | "iaps"
  | "glycemicgpt";

/** Why no forecast is rendering. Null = happy path. */
export type ForecastUnavailableReason =
  | "opted_out"
  | "needs_pick"
  | "no_sources"
  | "source_silent"
  | "stale";

/** Mg/dL curves keyed by curve name. Loop populates `main`; OpenAPS
 * family populates any subset of `IOB`/`COB`/`UAM`/`ZT`. */
export interface ForecastCurves {
  main?: number[] | null;
  IOB?: number[] | null;
  COB?: number[] | null;
  UAM?: number[] | null;
  ZT?: number[] | null;
}

export interface ForecastPayload {
  source_engine: ForecastEngine;
  source_uploader: string | null;
  /** ISO 8601. When the loop *emitted* the forecast. */
  issued_at: string;
  /** ISO 8601. t=0 of the curve. */
  start_at: string;
  step_minutes: number;
  horizon_minutes: number;
  curves_mgdl: ForecastCurves;
  default_curve_name: string;
}

export interface ForecastReadResponse {
  source_preference: ForecastSourcePreference;
  effective_source: ForecastEngine | null;
  available_sources: ForecastEngine[];
  forecast: ForecastPayload | null;
  /** Null on the happy path; specific reason when `forecast` is null
   * so the UI can dispatch the right empty-state message. */
  forecast_unavailable_reason: ForecastUnavailableReason | null;
}

export async function getForecast(): Promise<ForecastReadResponse> {
  const response = await apiFetch(`${API_BASE_URL}/api/integrations/forecast`);
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to fetch forecast: ${response.status}`
    );
  }
  return response.json();
}

export async function updateForecastSource(
  source: ForecastSourcePreference
): Promise<{ source_preference: ForecastSourcePreference }> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/integrations/forecast/source`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source }),
    }
  );
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to update forecast source: ${response.status}`
    );
  }
  return response.json();
}

// ============================================================================
// CGM primary-source picker (Story 43.10)
// ============================================================================
// Backend: GET /api/integrations/cgm + PUT /api/integrations/cgm/source
// (apps/api/src/schemas/cgm.py). Keep these shapes in sync.

export type CgmRole = "primary" | "secondary" | "off";

export interface CgmSourceItem {
  /** glucose_readings.source string -- the stable key. */
  source: string;
  /** Human-readable name for the picker. */
  label: string;
  role: CgmRole;
  /** "dexcom" | "nightscout". */
  kind: string;
}

export interface CgmSourcesResponse {
  sources: CgmSourceItem[];
  /** The source currently marked primary, or null. */
  primary_source: string | null;
  /** True only when more than one CGM source exists (picker renders then). */
  multiple_sources: boolean;
}

export async function getCgmSources(): Promise<CgmSourcesResponse> {
  const response = await apiFetch(`${API_BASE_URL}/api/integrations/cgm`);
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to fetch CGM sources: ${response.status}`
    );
  }
  return response.json();
}

export async function updatePrimaryCgmSource(
  source: string
): Promise<{ primary_source: string | null }> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/integrations/cgm/source`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source }),
    }
  );
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to update primary CGM source: ${response.status}`
    );
  }
  return response.json();
}

// ============================================================================
// Safety Limits (Phase 3)
// ============================================================================

/**
 * Safety Limits API types (Phase 3)
 */
export interface SafetyLimitsResponse {
  id: string;
  min_glucose_mgdl: number;
  max_glucose_mgdl: number;
  max_basal_rate_milliunits: number;
  max_bolus_dose_milliunits: number;
  updated_at: string;
}

export interface SafetyLimitsUpdate {
  min_glucose_mgdl?: number;
  max_glucose_mgdl?: number;
  max_basal_rate_milliunits?: number;
  max_bolus_dose_milliunits?: number;
}

export interface SafetyLimitsDefaults {
  min_glucose_mgdl: number;
  max_glucose_mgdl: number;
  max_basal_rate_milliunits: number;
  max_bolus_dose_milliunits: number;
}

/**
 * Fetch current safety limits
 */
export async function getSafetyLimits(): Promise<SafetyLimitsResponse> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/settings/safety-limits`
  );

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to fetch safety limits: ${response.status}`
    );
  }

  return response.json();
}

/**
 * Update safety limits
 */
export async function updateSafetyLimits(
  updates: SafetyLimitsUpdate
): Promise<SafetyLimitsResponse> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/settings/safety-limits`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(updates),
    }
  );

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to update safety limits: ${response.status}`
    );
  }

  return response.json();
}

/**
 * Fetch safety limits defaults
 */
export async function getSafetyLimitsDefaults(): Promise<SafetyLimitsDefaults> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/settings/safety-limits/defaults`
  );

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to fetch safety limits defaults: ${response.status}`
    );
  }

  return response.json();
}

// ============================================================================
// Time in Range Detail Statistics
// ============================================================================

export interface TirBucket {
  label: "urgent_low" | "low" | "in_range" | "high" | "urgent_high";
  pct: number;
  readings: number;
  threshold_low: number | null;
  threshold_high: number | null;
}

export interface TimeInRangeDetailStats {
  buckets: TirBucket[];
  readings_count: number;
  previous_buckets: TirBucket[] | null;
  previous_readings_count: number | null;
  thresholds: { urgent_low: number; low: number; high: number; urgent_high: number };
}

export async function getTimeInRangeDetailStats(
  minutes: number = 1440
): Promise<TimeInRangeDetailStats> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/integrations/glucose/time-in-range?minutes=${minutes}&include_details=true`
  );
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to fetch TIR detail: ${response.status}`
    );
  }
  return response.json();
}

// ============================================================================
// CGM Summary Statistics (Story 30.3)
// ============================================================================

export interface GlucoseStats {
  mean_glucose: number;
  std_dev: number;
  cv_pct: number;
  gmi: number;
  cgm_active_pct: number;
  readings_count: number;
  period_minutes: number;
}

export async function getGlucoseStats(
  minutes: number = 1440
): Promise<GlucoseStats> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/integrations/glucose/stats?minutes=${minutes}`
  );
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to fetch glucose stats: ${response.status}`
    );
  }
  return response.json();
}

// ============================================================================
// AGP Glucose Percentiles (Story 30.5)
// ============================================================================

export interface AGPBucket {
  hour: number;
  p10: number;
  p25: number;
  p50: number;
  p75: number;
  p90: number;
  count: number;
}

export interface GlucosePercentilesResponse {
  buckets: AGPBucket[];
  period_days: number;
  readings_count: number;
  is_truncated: boolean;
}

export async function getGlucosePercentiles(
  days: number = 14,
  tz?: string
): Promise<GlucosePercentilesResponse> {
  const safeDays = Number.isFinite(days) ? days : 14;
  const clampedDays = Math.max(7, Math.min(90, Math.round(safeDays)));
  const timezone = tz ?? Intl.DateTimeFormat().resolvedOptions().timeZone;
  const response = await apiFetch(
    `${API_BASE_URL}/api/integrations/glucose/percentiles?days=${clampedDays}&tz=${encodeURIComponent(timezone)}`
  );
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to fetch glucose percentiles: ${response.status}`
    );
  }
  return response.json();
}

// ============================================================================
// Insulin Summary (Story 30.7)
// ============================================================================

export interface InsulinSummaryResponse {
  tdd: number;
  basal_units: number;
  // Long-acting (basal) pen injections -- MDI, e.g. Lantus/Tresiba. Counted
  // within basal_pct; add to basal_units for the basal total. Optional for
  // backward compatibility with responses predating issue #742.
  basal_injection_units?: number;
  basal_injection_count?: number;
  bolus_units: number;
  correction_units: number;
  basal_pct: number;
  bolus_pct: number;
  bolus_count: number;
  correction_count: number;
  period_days: number;
}

export async function getInsulinSummary(
  days: number = 14
): Promise<InsulinSummaryResponse> {
  const safeDays = Number.isFinite(days) ? days : 14;
  const clampedDays = Math.max(1, Math.min(90, Math.round(safeDays)));
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const response = await apiFetch(
    `${API_BASE_URL}/api/integrations/insulin/summary?days=${clampedDays}&tz=${encodeURIComponent(tz)}`
  );
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to fetch insulin summary: ${response.status}`
    );
  }
  return response.json();
}

// ============================================================================
// Bolus Review (Story 30.7)
// ============================================================================

export interface BolusReviewItem {
  event_timestamp: string;
  // "bolus" | "correction" | "basal_injection". Optional for backward
  // compatibility with responses predating issue #742 (treated as a bolus).
  event_type?: string;
  units: number;
  is_automated: boolean;
  control_iq_reason: string | null;
  pump_activity_mode: string | null;
  iob_at_event: number | null;
  bg_at_event: number | null;
}

export interface BolusReviewResponse {
  boluses: BolusReviewItem[];
  total_count: number;
  period_days: number;
}

export async function getBolusReview(
  days: number = 7,
  limit: number = 100,
  offset: number = 0
): Promise<BolusReviewResponse> {
  const safeDays = Number.isFinite(days) ? days : 7;
  const clampedDays = Math.max(1, Math.min(30, Math.round(safeDays)));
  const safeLimit = Number.isFinite(limit) ? Math.max(1, Math.min(500, Math.round(limit))) : 100;
  const safeOffset = Number.isFinite(offset) ? Math.max(0, Math.round(offset)) : 0;
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const response = await apiFetch(
    `${API_BASE_URL}/api/integrations/bolus/review?days=${clampedDays}&limit=${safeLimit}&offset=${safeOffset}&tz=${encodeURIComponent(tz)}`
  );
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to fetch bolus review: ${response.status}`
    );
  }
  return response.json();
}

// ---------------------------------------------------------------------------
// Analytics Configuration
// ---------------------------------------------------------------------------

export interface DisplayLabel {
  id: string;
  label: string;
  computation_role: string | null;
  pump_source: string | null;
  sort_order: number;
}

export interface AnalyticsConfigResponse {
  id: string;
  day_boundary_hour: number;
  display_labels: DisplayLabel[] | null;
  category_labels: Record<string, string> | null;
  updated_at: string;
}

export interface AnalyticsConfigUpdate {
  day_boundary_hour?: number;
  display_labels?: DisplayLabel[];
}

export const DEFAULT_DISPLAY_LABELS: DisplayLabel[] = [
  { id: "auto_corr", label: "Auto Corr", computation_role: "AUTO_CORRECTION", pump_source: null, sort_order: 0 },
  { id: "meal", label: "Meal", computation_role: "FOOD", pump_source: null, sort_order: 1 },
  { id: "meal_corr", label: "Meal+Corr", computation_role: "FOOD_AND_CORRECTION", pump_source: null, sort_order: 2 },
  { id: "correction", label: "Correction", computation_role: "CORRECTION", pump_source: null, sort_order: 3 },
  { id: "override", label: "Override", computation_role: "OVERRIDE", pump_source: null, sort_order: 4 },
  { id: "other", label: "Other", computation_role: "OTHER", pump_source: null, sort_order: 5 },
];

export const DEFAULT_CATEGORY_LABELS: Record<string, string> = {
  AUTO_CORRECTION: "Auto Corr",
  FOOD: "Meal",
  FOOD_AND_CORRECTION: "Meal+Corr",
  CORRECTION: "Correction",
  OVERRIDE: "Override",
  OTHER: "Other",
};

export const VALID_CATEGORY_KEYS = [
  "AUTO_CORRECTION",
  "FOOD",
  "FOOD_AND_CORRECTION",
  "CORRECTION",
  "OVERRIDE",
  "OTHER",
] as const;

/**
 * Fetch current analytics configuration (day boundary hour).
 */
export async function getAnalyticsConfig(): Promise<AnalyticsConfigResponse> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/settings/analytics-config`
  );
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to fetch analytics config: ${response.status}`
    );
  }
  return response.json();
}

/**
 * Update analytics configuration.
 */
export async function updateAnalyticsConfig(
  updates: AnalyticsConfigUpdate
): Promise<AnalyticsConfigResponse> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/settings/analytics-config`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(updates),
    }
  );
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to update analytics config: ${response.status}`
    );
  }
  return response.json();
}

// ---------------------------------------------------------------------------
// Plugin Declarations
// ---------------------------------------------------------------------------

export interface PluginDeclarationResponse {
  id: string;
  plugin_id: string;
  plugin_name: string;
  plugin_version: string;
  declared_categories: string[];
  category_mappings: Record<string, string>;
  updated_at: string;
}

/**
 * Fetch the current user's active pump plugin declaration.
 * Returns null if no plugin is active (404).
 */
export async function getPluginDeclarations(): Promise<PluginDeclarationResponse | null> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/settings/plugin-declarations`
  );
  if (response.status === 404) {
    return null;
  }
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to fetch plugin declarations: ${response.status}`
    );
  }
  return response.json();
}

// ============================================================================
// Pump Profile (Story 30.8 - Clinical Report)
// ============================================================================

export interface PumpProfileSegment {
  time: string;
  start_minutes: number;
  basal_rate: number;
  correction_factor: number | null;
  carb_ratio: number | null;
  target_bg: number | null;
}

export interface PumpProfileSummaryResponse {
  profile_name: string;
  is_active: boolean;
  dia_minutes: number | null;
  max_bolus_units: number | null;
  segments: PumpProfileSegment[];
  synced_at: string;
}

export async function getPumpProfile(): Promise<PumpProfileSummaryResponse | null> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/settings/pump-profile`
  );
  if (response.status === 404) {
    return null;
  }
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to fetch pump profile: ${response.status}`
    );
  }
  return response.json();
}

// ============================================================================
// Date-Range Report Queries (Story 30.8)
// ============================================================================

function buildDateRangeParams(start: string, end: string): string {
  return `start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`;
}

export async function getGlucoseHistoryByDateRange(
  start: string,
  end: string,
  limit: number = 2000
): Promise<GlucoseHistoryResponse> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/integrations/glucose/history?${buildDateRangeParams(start, end)}&limit=${limit}`
  );
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to fetch glucose history: ${response.status}`
    );
  }
  return response.json();
}

export async function getGlucoseStatsByDateRange(
  start: string,
  end: string
): Promise<GlucoseStats> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/integrations/glucose/stats?${buildDateRangeParams(start, end)}`
  );
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to fetch glucose stats: ${response.status}`
    );
  }
  return response.json();
}

export async function getTimeInRangeDetailByDateRange(
  start: string,
  end: string
): Promise<TimeInRangeDetailStats> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/integrations/glucose/time-in-range?${buildDateRangeParams(start, end)}&include_details=true`
  );
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to fetch TIR detail: ${response.status}`
    );
  }
  return response.json();
}

export async function getInsulinSummaryByDateRange(
  start: string,
  end: string
): Promise<InsulinSummaryResponse> {
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const response = await apiFetch(
    `${API_BASE_URL}/api/integrations/insulin/summary?${buildDateRangeParams(start, end)}&tz=${encodeURIComponent(tz)}`
  );
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to fetch insulin summary: ${response.status}`
    );
  }
  return response.json();
}

export async function getBolusReviewByDateRange(
  start: string,
  end: string,
  limit: number = 500
): Promise<BolusReviewResponse> {
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const response = await apiFetch(
    `${API_BASE_URL}/api/integrations/bolus/review?${buildDateRangeParams(start, end)}&limit=${limit}&tz=${encodeURIComponent(tz)}`
  );
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to fetch bolus review: ${response.status}`
    );
  }
  return response.json();
}

// ============================================================================
// Per-user Tandem cloud sync (download direction)
// ============================================================================

export interface TandemSyncStatusResponse {
  integration_status: string;
  last_sync_at: string | null;
  last_error: string | null;
  events_available: number;
  /** Whether scheduled sync runs for this user. */
  enabled: boolean;
  /** Minutes between scheduled syncs (15-1440). */
  sync_interval_minutes: number;
  /** Cumulative count of events stored across all syncs (display only). */
  events_pulled_total: number;
  /**
   * True when the stored Tandem region is a legacy bucket label (e.g. "EU")
   * that can no longer be resolved to a country -- the user must reconnect
   * with their country selected before sync can run.
   */
  needs_country_reselect: boolean;
}

export interface TandemSyncSettingsRequest {
  enabled: boolean;
  sync_interval_minutes: number;
}

export interface TandemSyncResponse {
  message: string;
  events_fetched: number;
  events_stored: number;
  profiles_stored: number;
}

/** Get the per-user Tandem cloud-sync status + control. */
export async function getTandemSyncStatus(): Promise<TandemSyncStatusResponse> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/integrations/tandem/sync/status`
  );
  if (!response.ok) {
    throw new Error(
      await _readErrorDetail(response, "Failed to load Tandem sync status")
    );
  }
  return response.json();
}

/** Update the per-user Tandem sync toggle + interval. */
export async function updateTandemSyncSettings(
  body: TandemSyncSettingsRequest
): Promise<TandemSyncStatusResponse> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/integrations/tandem/sync/settings`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }
  );
  if (!response.ok) {
    throw new Error(
      await _readErrorDetail(response, "Failed to update Tandem sync settings")
    );
  }
  return response.json();
}

/** Manually trigger a Tandem sync ("Sync now"). */
export async function triggerTandemSync(): Promise<TandemSyncResponse> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/integrations/tandem/sync`,
    { method: "POST" }
  );
  if (!response.ok) {
    throw new Error(
      await _readErrorDetail(response, "Failed to trigger Tandem sync")
    );
  }
  return response.json();
}

export interface TandemAvailabilityResponse {
  /** Oldest date with data available to pull (ISO), or null. */
  earliest: string | null;
  /** Most recent date with data — the last upload to t:connect (ISO), or null. */
  latest: string | null;
  pump_count: number;
}

/** Query the date range of pump data available in the t:connect cloud. */
export async function getTandemSyncAvailability(): Promise<TandemAvailabilityResponse> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/integrations/tandem/sync/availability`
  );
  if (!response.ok) {
    throw new Error(
      await _readErrorDetail(response, "Failed to read available data range")
    );
  }
  return response.json();
}

/** One-time manual import of a chosen date range from t:connect. */
export async function importTandemRange(
  startDate: string,
  endDate: string
): Promise<TandemSyncResponse> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/integrations/tandem/sync/import`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ start_date: startDate, end_date: endDate }),
    }
  );
  if (!response.ok) {
    throw new Error(
      await _readErrorDetail(response, "Failed to import data range")
    );
  }
  return response.json();
}

// ============================================================================
// Medtronic CareLink manual import (stateless -- token captured client-side)
// ============================================================================

export interface MedtronicAvailabilityResponse {
  /** Oldest date with data in the user's CareLink cloud (ISO), or null. */
  start: string | null;
  /** Most recent date with data (ISO), or null. */
  end: string | null;
}

export interface MedtronicImportResponse {
  message: string;
  glucose_fetched: number;
  glucose_stored: number;
  events_fetched: number;
  events_stored: number;
}

/** Trim the captured token and fail fast if empty (avoids sending whitespace
 * that would cause an avoidable auth failure). */
function _normalizeCareLinkToken(token: string): string {
  const t = token.trim();
  if (!t) throw new Error("CareLink token is required");
  return t;
}

/** Validate the captured CareLink token and read the available data range. */
export async function getMedtronicAvailability(
  region: string,
  token: string
): Promise<MedtronicAvailabilityResponse> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/integrations/medtronic/availability`,
    {
      method: "POST",
      // Token goes in a header, never the JSON body, so it can't land in a
      // body-validation error echo or request-body logging.
      headers: {
        "Content-Type": "application/json",
        "X-CareLink-Token": _normalizeCareLinkToken(token),
      },
      body: JSON.stringify({ region }),
    }
  );
  if (!response.ok) {
    throw new Error(
      await _readErrorDetail(response, "Failed to read available data range")
    );
  }
  return response.json();
}

/** One-time manual import of a chosen CareLink date range. */
export async function importMedtronicRange(
  region: string,
  token: string,
  startDate: string,
  endDate: string,
  tz: string
): Promise<MedtronicImportResponse> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/integrations/medtronic/import`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CareLink-Token": _normalizeCareLinkToken(token),
      },
      body: JSON.stringify({
        region,
        start_date: startDate,
        end_date: endDate,
        tz,
      }),
    }
  );
  if (!response.ok) {
    throw new Error(
      await _readErrorDetail(response, "Failed to import data range")
    );
  }
  return response.json();
}

// ============================================================================
// Medtronic CareLink CarePartner (Connect) -- autonomous sync
// The one-time CarePartner login is done by a LOCAL desktop helper CLI (the
// login redirects to a mobile-app scheme a web app can't receive). The web UI
// only mints a short-lived pairing token for that CLI and shows status. The
// refresh token is exchanged + stored server-side; it never reaches the browser.
// ============================================================================

export interface MedtronicConnectStatus {
  connected: boolean;
  status: string;
  enabled: boolean;
  // The not-configured response only includes connected/status/enabled; the
  // rest are present only once connected.
  region?: string | null;
  role?: string | null;
  sync_interval_minutes?: number | null;
  last_sync_at?: string | null;
  last_error?: string | null;
  readings_synced_total?: number;
}

export interface MedtronicConnectInstall {
  handle: string;
  pairing_token: string;
  expires_at: string;
}

export interface MedtronicConnectSyncResult {
  message: string;
  glucose_fetched: number;
  glucose_stored: number;
  events_fetched: number;
  events_stored: number;
}

/** Read the user's Medtronic Connect autonomous-sync status. */
export async function getMedtronicConnectStatus(): Promise<MedtronicConnectStatus> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/integrations/medtronic/connect/status`
  );
  if (!response.ok) {
    throw new Error(
      await _readErrorDetail(response, "Failed to read Connect status")
    );
  }
  return response.json();
}

/** Mint a short-handle install bundle for the desktop helper one-liner.
 * The handle indexes a server-side bundle (pair token + api/username/region)
 * so the copy-paste command stays compact instead of carrying the long
 * Fernet pair token in the URL. Same TTL + single-use gate as the long form. */
export async function installMedtronicConnect(params: {
  apiUrl: string;
  username: string;
  region: string;
}): Promise<MedtronicConnectInstall> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/integrations/medtronic/connect/install`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        api_url: params.apiUrl,
        username: params.username,
        region: params.region,
      }),
    }
  );
  if (!response.ok) {
    throw new Error(
      await _readErrorDetail(response, "Failed to start install")
    );
  }
  return response.json();
}

/** Update the Connect sync toggle + interval. */
export async function updateMedtronicConnectSettings(
  enabled: boolean,
  syncIntervalMinutes: number
): Promise<MedtronicConnectStatus> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/integrations/medtronic/connect/settings`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        enabled,
        sync_interval_minutes: syncIntervalMinutes,
      }),
    }
  );
  if (!response.ok) {
    throw new Error(
      await _readErrorDetail(response, "Failed to update Connect settings")
    );
  }
  return response.json();
}

/** Disconnect Medtronic Connect (deletes the stored refresh token). */
export async function disconnectMedtronicConnect(): Promise<void> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/integrations/medtronic/connect/disconnect`,
    { method: "POST" }
  );
  if (!response.ok) {
    throw new Error(
      await _readErrorDetail(response, "Failed to disconnect Medtronic Connect")
    );
  }
}

/** Trigger a Connect sync now (in addition to the schedule). */
export async function syncMedtronicConnectNow(): Promise<MedtronicConnectSyncResult> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/integrations/medtronic/connect/sync`,
    { method: "POST" }
  );
  if (!response.ok) {
    throw new Error(await _readErrorDetail(response, "Failed to sync now"));
  }
  return response.json();
}

// ============================================================================
// Omnipod via Glooko -- autonomous cloud sync
// Omnipod 5 uploads to Glooko only (Insulet mandates Glooko as the sole data
// system), so Glooko is the onramp. Unlike Medtronic Connect's mobile-app login
// (which needs a desktop helper), Glooko authenticates with a plain web session,
// so the user connects directly with their Glooko email + password. The
// credentials are encrypted at rest on the backend and never returned here.
// ============================================================================

export interface GlookoStatus {
  connected: boolean;
  /** Server-side row status; `not_configured` when the user has never connected.
   * Mirrors the backend `GlookoSyncState.status` vocabulary. */
  status:
    | "not_configured"
    | "pending"
    | "connected"
    | "error"
    | "disconnected";
  enabled: boolean;
  /** Whether Glooko's CGM trace is ingested. False = doses-only source
   * (skip CGM, keep insulin doses) when a direct CGM already provides glucose. */
  cgm_sync_enabled?: boolean;
  region?: string | null;
  /** Minutes between scheduled syncs (15-1440). */
  sync_interval_minutes?: number;
  last_sync_at?: string | null;
  last_error?: string | null;
  readings_synced_total?: number;
  /** When the user acknowledged the unofficial-connection notice, or null.
   * Returned by the API; not yet surfaced in the UI. */
  consent_acknowledged_at?: string | null;
}

export interface GlookoSyncResult {
  message: string;
  glucose_fetched: number;
  glucose_stored: number;
  events_fetched: number;
  events_stored: number;
}

export interface GlookoAvailability {
  connected: boolean;
  /**
   * Whether CGM (sensor glucose) data is reachable in the account. Omnipod 5
   * only streams integrated CGM to Glooko on some setups, so this can be false
   * even when pump data syncs fine -- the card stays honest about it.
   */
  cgm_available: boolean;
  /** Oldest CGM datapoint reachable (ISO), or null. */
  earliest?: string | null;
  /** Most recent CGM datapoint reachable (ISO), or null. */
  latest?: string | null;
}

/** Connect a Glooko account: validates credentials live, then stores them
 * encrypted server-side and records the consent acknowledgment. `acceptRisk`
 * must be true -- the backend refuses to store credentials without it. */
export async function connectGlooko(params: {
  email: string;
  password: string;
  region: string;
  acceptRisk: boolean;
}): Promise<GlookoStatus> {
  const response = await apiFetch(`${API_BASE_URL}/api/integrations/glooko`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      email: params.email,
      password: params.password,
      region: params.region,
      accept_risk: params.acceptRisk,
    }),
  });
  if (!response.ok) {
    throw new Error(await _readErrorDetail(response, "Failed to connect Glooko"));
  }
  return response.json();
}

/** Read the user's Glooko sync status (no credentials exposed). Returns a
 * `not_configured` status rather than 404 when never connected. */
export async function getGlookoStatus(): Promise<GlookoStatus> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/integrations/glooko/status`
  );
  if (!response.ok) {
    throw new Error(await _readErrorDetail(response, "Failed to read Glooko status"));
  }
  return response.json();
}

/** Disconnect Glooko (deletes the stored credentials + consent record). */
export async function disconnectGlooko(): Promise<void> {
  const response = await apiFetch(`${API_BASE_URL}/api/integrations/glooko`, {
    method: "DELETE",
  });
  if (!response.ok) {
    throw new Error(await _readErrorDetail(response, "Failed to disconnect Glooko"));
  }
}

/** Trigger an incremental Glooko sync now (in addition to the schedule). */
export async function syncGlookoNow(): Promise<GlookoSyncResult> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/integrations/glooko/sync`,
    { method: "POST" }
  );
  if (!response.ok) {
    throw new Error(await _readErrorDetail(response, "Failed to sync Glooko"));
  }
  return response.json();
}

/** Update the Glooko sync toggle + interval + CGM-ingestion toggle. */
export async function updateGlookoSyncSettings(
  enabled: boolean,
  syncIntervalMinutes: number,
  cgmSyncEnabled: boolean
): Promise<GlookoStatus> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/integrations/glooko/sync/settings`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        enabled,
        cgm_sync_enabled: cgmSyncEnabled,
        sync_interval_minutes: syncIntervalMinutes,
      }),
    }
  );
  if (!response.ok) {
    throw new Error(
      await _readErrorDetail(response, "Failed to update Glooko settings")
    );
  }
  return response.json();
}

/** Read-only probe of what CGM data is reachable in the user's Glooko cloud.
 * Does not mutate the sync-state row, so it is safe to call to drive honest
 * CGM-availability messaging. */
export async function getGlookoSyncAvailability(): Promise<GlookoAvailability> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/integrations/glooko/sync/availability`
  );
  if (!response.ok) {
    throw new Error(
      await _readErrorDetail(response, "Failed to read available Glooko data")
    );
  }
  return response.json();
}

/** One-time historical backfill from Glooko (no body; fills the past without
 * advancing the incremental cursors). Safe to re-run -- storage is idempotent. */
export async function importGlookoHistory(): Promise<GlookoSyncResult> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/integrations/glooko/sync/import`,
    { method: "POST" }
  );
  if (!response.ok) {
    throw new Error(await _readErrorDetail(response, "Failed to import Glooko history"));
  }
  return response.json();
}

// ============================================================================
// Meal management (food records)
//
// Wires the existing, owner-scoped, flag-gated food-records API into the web
// app. Descriptive nutrition observations only -- there is deliberately no
// dose/insulin field anywhere in these types. The server attaches the cleared
// safety qualifier as `safety_qualifier`; the web renders that field verbatim
// rather than re-stating any carb/dosing copy of its own.
// ============================================================================

/** Record provenance, as the API emits it (snake_case enum value). */
export type FoodRecordSource =
  | "ai_estimate"
  | "user_corrected"
  | "external_grounded";

/**
 * Macro nutrition for a meal. Only visually-estimable macros are present; any
 * subset of the known keys may appear. Carbs are NOT here -- they live in the
 * dedicated carbs_low/carbs_high columns.
 */
export interface FoodRecordNutrition {
  protein_grams?: number;
  fat_grams?: number;
  fiber_grams?: number;
  calories?: number;
  [key: string]: number | undefined;
}

/**
 * One glucose-relevant macro with descriptive framing (Story 50.N1). Read-only:
 * `glucose_note` explains how the macro tends to affect glucose (no peak-timing
 * number, no dosing language) -- never a dose.
 */
export interface MacroFact {
  key: string;
  label: string;
  value: number;
  unit: string;
  glucose_note: string;
}

/**
 * Net carbs (total carbs minus fiber), surfaced only behind `caveat` (Story
 * 50.N1). Display-only and clearly secondary to the total carb range; never a
 * dosing input.
 */
export interface NetCarbsEstimate {
  low: number;
  high: number;
  caveat: string;
}

/**
 * Display-ready, glucose-framed nutrition for a food record (Story 50.N1).
 * Server-computed (never persisted): the assumed `portion` (the estimate's
 * primary sanity-check), the framed `macros`, and caveated `net_carbs`.
 * `disclaimer` carries the never-dose framing over the whole block.
 */
export interface NutritionFacts {
  portion: string | null;
  macros: MacroFact[];
  net_carbs: NetCarbsEstimate | null;
  disclaimer: string;
}

/**
 * One grounding-backed comorbidity nutrient with awareness framing.
 * Read-only: `note` explains why the figure matters for blood-pressure /
 * cardiovascular awareness -- never a dose.
 */
export interface ComorbidityFact {
  key: string;
  label: string;
  value: number;
  unit: string;
  note: string;
}

/**
 * Grounding-backed comorbidity / label nutrition. GROUNDING-ONLY
 * and identity-gated: populated solely from an authoritative grounded source
 * (USDA / Open Food Facts / restaurant) after identity confirmation, never from
 * the photo. Carries its own attribution (distinct from the vision estimate) and a
 * `disclaimer` carrying the never-dose framing. `sugar_note` (the "sugar-free is
 * not carb-free" reminder) is present only when a sugars figure is surfaced.
 */
export interface ComorbidityNutrition {
  facts: ComorbidityFact[];
  sugar_note: string | null;
  source: string | null;
  source_url: string | null;
  trust_tier: string | null;
  disclaimer: string;
}

/**
 * A persisted food record. Mirrors `FoodRecordResponse`
 * (apps/api/src/schemas/food_record.py). `carbs_low`/`carbs_high` are the
 * original AI estimate; when corrected, `corrected_carbs_*` carry the user's
 * values and `source` is `user_corrected`. `confidence` is the EMPIRICAL
 * dispersion band ("low"|"medium"|"high"), not the model's self-reported
 * confidence. The create (upload) response additionally carries transient
 * dispersion detail; reads of an existing record do not, so it is omitted here.
 */
export interface FoodRecord {
  id: string;
  meal_timestamp: string;
  food_description: string | null;
  carbs_low: number;
  carbs_high: number;
  confidence: string | null;
  /** Server-cleared "this is a guess, never dose from it" qualifier. Render verbatim. */
  safety_qualifier: string;
  nutrition_json: FoodRecordNutrition | null;
  /** The model's assumed portion / preparation -- the estimate's primary sanity-check. */
  assumptions: string | null;
  source: FoodRecordSource;
  corrected_carbs_low: number | null;
  corrected_carbs_high: number | null;
  corrected_nutrition_json: FoodRecordNutrition | null;
  corrected_at: string | null;
  common_food_id: string | null;
  ai_model: string | null;
  ai_provider: string | null;
  confirmed_food_name: string | null;
  identity_confirmed: boolean;
  /**
   * Transient create-time own-history pre-fill ("looks like your saved X"); the
   * server emits it on the upload response and it is absent (null) on later reads
   * of a persisted record. Used to pre-fill the identity-confirmation input.
   */
  suggested_identity: string | null;
  grounding_source: string | null;
  grounding_source_url: string | null;
  grounding_trust_tier: string | null;
  /** Server-computed, glucose-framed nutrition (portion + macros + net carbs). */
  nutrition_facts: NutritionFacts | null;
  /**
   * Grounding-backed comorbidity nutrition: the display-ready, awareness-framed,
   * attributed block (saturated fat / sugars / sodium). Null on a record with no
   * grounded comorbidity data. (The raw grounded values are an internal server
   * column and are not part of the response.)
   */
  comorbidity_nutrition: ComorbidityNutrition | null;
  created_at: string;
}

export interface FoodRecordListResponse {
  records: FoodRecord[];
  total: number;
}

/**
 * One raw vision sample as surfaced in the audit trail (Story 50.H3). Mirrors
 * the server `AuditSample`. The model's self-reported confidence is deliberately
 * NOT part of this shape: the server strips it before responding (it is retained
 * internally for eval/triage only, per 50.H1), so it can never reach the UI.
 */
export interface AuditSample {
  carbs_low: number | null;
  carbs_high: number | null;
  identity: string | null;
  parse_ok: boolean;
}

/**
 * The empirical dispersion summary in the audit trail (Story 50.H3). Mirrors the
 * server `AuditDispersion`. `confidence` is the EMPIRICAL dispersion band, never
 * the model's self-reported confidence -- low dispersion is consistency, not
 * correctness, so it is provenance, not a dose signal.
 */
export interface AuditDispersion {
  confidence: string | null;
  coefficient_of_variation: number | null;
  samples_requested: number | null;
  samples_used: number | null;
  identity_agreement: boolean | null;
  distinct_identities: string[];
  wide_spread: boolean | null;
}

/**
 * The precedence decision recorded for an estimate (Story 50.H2/H3). Mirrors the
 * server precedence payload built by `services.meal_audit`: which source won (or
 * vision-only), the identity it was keyed on, and the ladder AS IT STOOD when the
 * decision was made (recorded per-row so the audit reads the ordering that
 * actually applied). Descriptive provenance only -- never a dose.
 */
export interface AuditPrecedence {
  outcome: string;
  chosen_source: string | null;
  trust_tier: string | null;
  source_url: string | null;
  identity_used: string | null;
  identity_confirmed: boolean;
  reason: string | null;
  ladder: string[];
}

/**
 * The "how was this estimated" provenance trail for a food record (Story 50.H3).
 * Mirrors the server `FoodRecordAuditResponse`: the raw per-sample vision reads,
 * the empirical dispersion summary, and the precedence decision. Descriptive
 * only; nothing here is read by dosing math.
 */
export interface FoodRecordAudit {
  food_record_id: string;
  samples: AuditSample[];
  dispersion: AuditDispersion | null;
  precedence: AuditPrecedence | null;
  created_at: string;
  updated_at: string;
}

/**
 * A food-records API failure that preserves the HTTP status and the server's
 * `detail` string, so callers can map it to the right UX state (feature off,
 * no provider, vision unavailable, ...) -- mirroring the mobile client's
 * detail-substring contract. See `classifyMealError` in `@/lib/meal-errors`.
 */
export class MealApiError extends Error {
  readonly status: number;
  readonly detail: string;

  constructor(status: number, detail: string) {
    super(detail || `Food-records request failed: ${status}`);
    this.name = "MealApiError";
    this.status = status;
    this.detail = detail;
  }
}

/**
 * Read a FastAPI error envelope's `detail` as a bare string for substring
 * matching. Tolerates both the common string form and the 422 list-of-objects
 * form; returns "" when no usable detail is present.
 *
 * Distinct from `_readErrorDetail` (above) on purpose: that helper formats a
 * ready-to-throw Error *message* (folding in a fallback + the status and
 * JSON-stringifying a non-string detail), whereas the meal path needs the raw
 * detail string preserved verbatim so callers can substring-match the
 * cross-client contract (e.g. "not enabled", "vision") and carry the status
 * separately on `MealApiError`. Keep the two in sync if the envelope changes.
 */
async function _readMealDetail(response: Response): Promise<string> {
  try {
    const body = await response.json();
    const detail = (body as { detail?: unknown })?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map((e) =>
          e && typeof e === "object" && "msg" in e
            ? String((e as { msg: unknown }).msg)
            : ""
        )
        .filter(Boolean)
        .join("; ");
    }
  } catch {
    // Non-JSON / empty body.
  }
  return "";
}

async function _throwMealError(response: Response): Promise<never> {
  throw new MealApiError(response.status, await _readMealDetail(response));
}

/**
 * List the current user's food records, most recent meal first.
 * Owner-scoped + flag-gated server-side; a 404 whose detail says the feature is
 * "not enabled" means the global flag is off (see `getMealIntelligenceStatus`).
 */
export async function listFoodRecords(
  limit = 50,
  offset = 0
): Promise<FoodRecordListResponse> {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  });
  const response = await apiFetch(
    `${API_BASE_URL}/api/food-records?${params.toString()}`
  );
  if (!response.ok) {
    await _throwMealError(response);
  }
  return response.json();
}

/** Fetch a single owner-scoped food record (404 for missing or cross-user). */
export async function getFoodRecord(recordId: string): Promise<FoodRecord> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/food-records/${encodeURIComponent(recordId)}`
  );
  if (!response.ok) {
    await _throwMealError(response);
  }
  return response.json();
}

/**
 * Fetch a record's "how was this estimated" provenance trail (Story 50.H3).
 *
 * Owner-scoped and IDOR-safe server-side: the record must belong to the caller
 * and the audit row is itself scoped by user id, so a cross-user id yields a 404
 * (never another user's samples). A 404 can also mean a record simply has no
 * stored audit (e.g. created before retention), which the caller renders as a
 * benign "provenance unavailable" state rather than an error. Throws
 * `MealApiError` carrying the status so callers can tell 404 from a transient
 * failure.
 */
export async function getFoodRecordAudit(
  recordId: string
): Promise<FoodRecordAudit> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/food-records/${encodeURIComponent(recordId)}/audit`
  );
  if (!response.ok) {
    await _throwMealError(response);
  }
  return response.json();
}

/**
 * Fetch a record's stored meal photo as a `blob:` object URL.
 *
 * The photo endpoint is same-origin and cookie-protected, and next/image's
 * optimizer can't carry the auth cookie, so we fetch the bytes through apiFetch
 * (which sends credentials) and wrap them in a `blob:` URL the CSP allows. The
 * caller MUST revoke the URL (URL.revokeObjectURL) once it is no longer shown.
 */
export async function fetchFoodRecordPhotoObjectUrl(
  recordId: string
): Promise<string> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/food-records/${encodeURIComponent(recordId)}/photo`
  );
  if (!response.ok) {
    await _throwMealError(response);
  }
  const blob = await response.blob();
  return URL.createObjectURL(blob);
}

/**
 * Upload a meal photo for AI carb estimation. The caller compresses to a JPEG
 * blob first (see `@/lib/image-compress`); this mirrors the mobile client's
 * single-part `file` upload. Returns the persisted record (with the create-time
 * estimate). Throws `MealApiError` on failure for UX-state mapping.
 */
export async function uploadFoodRecord(image: Blob): Promise<FoodRecord> {
  const formData = new FormData();
  // Field name `file` and filename `meal.jpg` mirror the mobile multipart part.
  formData.append("file", image, "meal.jpg");
  // Do NOT set Content-Type -- the browser sets multipart/form-data + boundary.
  const response = await apiFetch(`${API_BASE_URL}/api/food-records`, {
    method: "POST",
    body: formData,
  });
  if (!response.ok) {
    await _throwMealError(response);
  }
  return response.json();
}

/**
 * Correct a food record's carb range (Story 50.C). Fixes a *description of the
 * food*, never a dose: the corrected values land in the record's correction
 * columns and provenance flips to `user_corrected`; the original AI estimate is
 * preserved, and corrected values are never read by IoB / treatment_safety /
 * carb-ratio math. Returns the refreshed record. Throws `MealApiError` (404 for
 * a missing/cross-user id, 422 for out-of-range/inverted) for UX-state mapping.
 */
export async function correctFoodRecord(
  recordId: string,
  correction: { corrected_carbs_low: number; corrected_carbs_high: number }
): Promise<FoodRecord> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/food-records/${encodeURIComponent(recordId)}/correct`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(correction),
    }
  );
  if (!response.ok) {
    await _throwMealError(response);
  }
  return response.json();
}

/**
 * Confirm or correct *what the food is* (Story 50.H2) -- a distinct action from
 * carb correction. The confirmed name opens the grounding gate: only now does
 * the server look up external authoritative nutrition (USDA / Open Food Facts;
 * restaurant facts) keyed on the confirmed name, so a misidentified label is
 * never certified with a citation. Returns the refreshed record (which may now
 * carry grounding attribution). Throws `MealApiError` (404 missing/cross-user,
 * 422 blank/oversized name) for UX-state mapping.
 */
export async function confirmFoodIdentity(
  recordId: string,
  confirmedFoodName: string
): Promise<FoodRecord> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/food-records/${encodeURIComponent(recordId)}/confirm-identity`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirmed_food_name: confirmedFoodName }),
    }
  );
  if (!response.ok) {
    await _throwMealError(response);
  }
  return response.json();
}

/** Delete a food record and unlink its stored photo (204 No Content). */
export async function deleteFoodRecord(recordId: string): Promise<void> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/food-records/${encodeURIComponent(recordId)}`,
    { method: "DELETE" }
  );
  if (!response.ok) {
    await _throwMealError(response);
  }
}

/**
 * Resolve whether meal intelligence is enabled for the current user.
 *
 * There is no server flag endpoint: `meal_intelligence_enabled` is a global
 * deployment flag, and every meal route is hidden behind a 404 when it is off.
 * So we mirror the mobile cross-client contract and probe the list endpoint: a
 * 404 whose detail contains "not enabled" means the flag is off; success (or
 * any transient/other error) is treated as available, so a network blip never
 * hides a real feature.
 */
export async function getMealIntelligenceStatus(): Promise<{ enabled: boolean }> {
  try {
    const response = await apiFetch(`${API_BASE_URL}/api/food-records?limit=1`);
    if (response.status === 404) {
      const detail = (await _readMealDetail(response)).toLowerCase();
      if (detail.includes("not enabled")) return { enabled: false };
    }
    return { enabled: true };
  } catch {
    // Network/other failure: degrade to available, matching the mobile client.
    return { enabled: true };
  }
}

// ============================================================================
// Common-foods management + save/link
//
// A common food is a user-named carb/nutrition baseline for a food eaten often.
// Mirrors `CommonFoodResponse` (apps/api/src/schemas/common_food.py). It is a
// descriptive baseline only: there is deliberately no dose/insulin field, and
// these values never flow into IoB / treatment_safety / carb-ratio math. Every
// endpoint is owner-scoped + flag-gated server-side (a 404 whose detail says the
// feature is "not enabled" means the global flag is off). Failures throw
// `MealApiError` so callers can map status to UX (409 name-in-use, 422 range).
// ============================================================================

/** A saved common-food baseline. The `nutrition_json` macros mirror a record's. */
export interface CommonFood {
  id: string;
  name: string;
  carbs_low: number;
  carbs_high: number;
  nutrition_json: FoodRecordNutrition | null;
  created_at: string;
  updated_at: string;
}

export interface CommonFoodListResponse {
  common_foods: CommonFood[];
  total: number;
}

/** Fields a user can edit on a baseline. Carb bounds are sent together (the
 *  server rejects one without the other), matching the carb-correction contract. */
export interface CommonFoodUpdate {
  name?: string;
  carbs_low?: number;
  carbs_high?: number;
}

/**
 * List the current user's common foods, most recently updated first. Paginated
 * (server caps limit at 200). Flag-gated + owner-scoped server-side.
 */
export async function listCommonFoods(
  limit = 50,
  offset = 0
): Promise<CommonFoodListResponse> {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  });
  const response = await apiFetch(
    `${API_BASE_URL}/api/common-foods?${params.toString()}`
  );
  if (!response.ok) {
    await _throwMealError(response);
  }
  return response.json();
}

/**
 * Rename and/or re-baseline a common food. Throws `MealApiError`: 404 for a
 * missing/cross-user id (IDOR-safe, no existence leak), 409 when the new name
 * collides with another of the user's baselines, 422 for an out-of-range or
 * inverted carb band. The baseline is a description of a food, never a dose.
 */
export async function updateCommonFood(
  commonFoodId: string,
  update: CommonFoodUpdate
): Promise<CommonFood> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/common-foods/${encodeURIComponent(commonFoodId)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(update),
    }
  );
  if (!response.ok) {
    await _throwMealError(response);
  }
  return response.json();
}

/**
 * Delete a common food (204 No Content). Records linked to it are unlinked
 * (FK ON DELETE SET NULL), never deleted. Throws `MealApiError` 404 for a
 * missing/cross-user id.
 */
export async function deleteCommonFood(commonFoodId: string): Promise<void> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/common-foods/${encodeURIComponent(commonFoodId)}`,
    { method: "DELETE" }
  );
  if (!response.ok) {
    await _throwMealError(response);
  }
}

/**
 * Promote a food record to a named common-food baseline and link it. The server
 * uses the record's corrected values when present, else the AI estimate, and
 * dedupes by name (saving under an existing name updates that baseline). Returns
 * the saved/updated baseline. Throws `MealApiError` (404 missing/cross-user
 * record, 422 out-of-range).
 */
export async function saveRecordAsCommonFood(
  recordId: string,
  name: string
): Promise<CommonFood> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/food-records/${encodeURIComponent(recordId)}/save-as-common-food`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    }
  );
  if (!response.ok) {
    await _throwMealError(response);
  }
  return response.json();
}

/**
 * Link an existing food record to one of the user's existing common foods.
 * Both sides are owner-scoped: a missing or cross-user record OR baseline 404s
 * with no existence leak. Returns the refreshed record (now carrying
 * `common_food_id`). Throws `MealApiError` 404.
 */
export async function linkRecordToCommonFood(
  recordId: string,
  commonFoodId: string
): Promise<FoodRecord> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/food-records/${encodeURIComponent(recordId)}/link-common-food`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ common_food_id: commonFoodId }),
    }
  );
  if (!response.ok) {
    await _throwMealError(response);
  }
  return response.json();
}
