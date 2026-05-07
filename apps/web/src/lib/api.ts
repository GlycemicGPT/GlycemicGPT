/**
 * API client configuration and utilities.
 *
 * Story 1.3: First-Run Safety Disclaimer
 * Story 15.1: Authentication API functions
 * Story 15.4: Global 401 handling via apiFetch wrapper
 */

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
  disclaimer_acknowledged: boolean;
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
 */
export async function connectDexcom(credentials: {
  username: string;
  password: string;
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
 */
export async function connectTandem(credentials: {
  username: string;
  password: string;
  region: string;
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

// ============================================================================
// Story 18.3: Tandem Cloud Upload
// ============================================================================

export interface TandemUploadStatusResponse {
  enabled: boolean;
  upload_interval_minutes: number;
  last_upload_at: string | null;
  last_upload_status: string | null;
  last_error: string | null;
  max_event_index_uploaded: number;
  pending_raw_events: number;
}

export interface TandemUploadTriggerResponse {
  message: string;
  events_uploaded: number;
  status: string;
}

/**
 * Get the Tandem cloud upload status for the current user.
 */
export async function getTandemUploadStatus(): Promise<TandemUploadStatusResponse> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/integrations/tandem/cloud-upload/status`
  );

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to fetch upload status: ${response.status}`
    );
  }

  return response.json();
}

/**
 * Update Tandem cloud upload settings (enable/disable, interval).
 */
export async function updateTandemUploadSettings(data: {
  enabled: boolean;
  interval_minutes: number;
}): Promise<TandemUploadStatusResponse> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/integrations/tandem/cloud-upload/settings`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }
  );

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to update upload settings: ${response.status}`
    );
  }

  return response.json();
}

/**
 * Trigger an immediate Tandem cloud upload.
 */
export async function triggerTandemUpload(): Promise<TandemUploadTriggerResponse> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/integrations/tandem/cloud-upload/trigger`,
    { method: "POST" }
  );

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Failed to trigger upload: ${response.status}`
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

export interface PumpStatusResponse {
  basal: PumpStatusBasal | null;
  battery: PumpStatusBattery | null;
  reservoir: PumpStatusReservoir | null;
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
