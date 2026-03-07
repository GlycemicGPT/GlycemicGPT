/**
 * Story 13.1: Frontend Page Smoke Tests
 *
 * Verifies that all major pages render without crashing.
 * These are shallow render tests that confirm components mount,
 * display expected headings, and don't throw errors.
 */

import { render, screen, waitFor, act } from "@testing-library/react";

// Mock next/navigation
jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: jest.fn(), back: jest.fn(), replace: jest.fn() }),
  usePathname: () => "/dashboard",
  useSearchParams: () => new URLSearchParams(),
}));

// Mock next/link
jest.mock("next/link", () => {
  return function MockLink({
    children,
    href,
    ...props
  }: {
    children: React.ReactNode;
    href: string;
    [key: string]: unknown;
  }) {
    return (
      <a href={href} {...props}>
        {children}
      </a>
    );
  };
});

// Mock next/image
jest.mock("next/image", () => {
  return function MockImage(props: { alt: string; [key: string]: unknown }) {
    // eslint-disable-next-line @next/next/no-img-element
    return <img alt={props.alt} />;
  };
});

// Mock providers
jest.mock("@/providers", () => ({
  useUserContext: () => ({ user: { role: "diabetic" } }),
  useGlucoseStreamContext: () => ({
    latestReading: null,
    readings: [],
    isConnected: false,
    error: null,
    reconnect: jest.fn(),
  }),
}));

// Mock all API functions used by page components
jest.mock("@/lib/api", () => ({
  // Sidebar
  getUnreadInsightsCount: jest.fn().mockResolvedValue(0),
  // Briefs
  getInsightDetail: jest.fn().mockResolvedValue({}),
  getInsights: jest.fn().mockResolvedValue({ insights: [], total: 0 }),
  respondToInsight: jest.fn().mockResolvedValue({}),
  // AI Chat
  sendAIChat: jest.fn().mockResolvedValue({ response: "test" }),
  getAIProvider: jest.fn().mockRejectedValue(new Error("No AI provider configured: 404")),
  // AI Provider settings
  configureAIProvider: jest.fn().mockResolvedValue({}),
  testAIProvider: jest.fn().mockResolvedValue({ success: true }),
  deleteAIProvider: jest.fn().mockResolvedValue({}),
  // Dashboard
  getTargetGlucoseRange: jest.fn().mockResolvedValue({ low_threshold: 70, high_threshold: 180 }),
  // Settings pages
  updateTargetGlucoseRange: jest.fn().mockResolvedValue({}),
  getBriefDeliveryConfig: jest.fn().mockResolvedValue({ delivery_time: "07:00", timezone: "UTC", channel: "web", enabled: true }),
  updateBriefDeliveryConfig: jest.fn().mockResolvedValue({}),
  getAlertThresholds: jest.fn().mockResolvedValue({ low_warning: 70, urgent_low: 55, high_warning: 180, urgent_high: 250, iob_warning: 3.0 }),
  updateAlertThresholds: jest.fn().mockResolvedValue({}),
  getEscalationConfig: jest.fn().mockResolvedValue({ initial_delay_minutes: 15, reminder_interval_minutes: 30, max_escalation_level: 3 }),
  updateEscalationConfig: jest.fn().mockResolvedValue({}),
  getEmergencyContacts: jest.fn().mockResolvedValue({ contacts: [] }),
  createEmergencyContact: jest.fn().mockResolvedValue({}),
  updateEmergencyContact: jest.fn().mockResolvedValue({}),
  deleteEmergencyContact: jest.fn().mockResolvedValue({}),
  getDataRetentionConfig: jest.fn().mockResolvedValue({ glucose_retention_days: 365, alert_retention_days: 90, analysis_retention_days: 180 }),
  updateDataRetentionConfig: jest.fn().mockResolvedValue({}),
  getStorageUsage: jest.fn().mockResolvedValue({ glucose_records: 0, pump_records: 0, analysis_records: 0, audit_records: 0, total_records: 0 }),
  purgeUserData: jest.fn().mockResolvedValue({}),
  exportSettings: jest.fn().mockResolvedValue({}),
  // Profile
  getCurrentUser: jest.fn().mockResolvedValue({ email: "test@test.com", role: "diabetic", display_name: null, created_at: "2026-01-01" }),
  updateProfile: jest.fn().mockResolvedValue({}),
  changePassword: jest.fn().mockResolvedValue({}),
  // Integrations
  listIntegrations: jest.fn().mockResolvedValue({ dexcom: { connected: false }, tandem: { connected: false } }),
  connectDexcom: jest.fn().mockResolvedValue({}),
  disconnectDexcom: jest.fn().mockResolvedValue(undefined),
  connectTandem: jest.fn().mockResolvedValue({}),
  disconnectTandem: jest.fn().mockResolvedValue(undefined),
  // Caregivers
  listLinkedCaregivers: jest.fn().mockResolvedValue({ caregivers: [] }),
  listCaregiverInvitations: jest.fn().mockResolvedValue({ invitations: [] }),
  createCaregiverInvitation: jest.fn().mockResolvedValue({}),
  revokeCaregiverInvitation: jest.fn().mockResolvedValue(undefined),
  getCaregiverPermissions: jest.fn().mockResolvedValue({ permissions: {} }),
  updateCaregiverPermissions: jest.fn().mockResolvedValue({}),
  // Telegram & Communications
  getTelegramStatus: jest.fn().mockResolvedValue({ linked: false }),
  getTelegramBotConfig: jest.fn().mockResolvedValue({ configured: false }),
  saveTelegramBotToken: jest.fn().mockResolvedValue({}),
  removeTelegramBotToken: jest.fn().mockResolvedValue(undefined),
  generateTelegramCode: jest.fn().mockResolvedValue({ code: "TEST123" }),
  unlinkTelegram: jest.fn().mockResolvedValue({}),
  sendTelegramTestMessage: jest.fn().mockResolvedValue({}),
  // Analytics config
  getAnalyticsConfig: jest.fn().mockResolvedValue({ id: "test", day_boundary_hour: 0, display_labels: null, category_labels: null, updated_at: "2026-01-01" }),
  updateAnalyticsConfig: jest.fn().mockResolvedValue({}),
  getPluginDeclarations: jest.fn().mockResolvedValue(null),
  DEFAULT_DISPLAY_LABELS: [
    { id: "auto_corr", label: "Auto Corr", computation_role: "AUTO_CORRECTION", pump_source: null, sort_order: 0 },
    { id: "meal", label: "Meal", computation_role: "FOOD", pump_source: null, sort_order: 1 },
    { id: "meal_corr", label: "Meal+Corr", computation_role: "FOOD_AND_CORRECTION", pump_source: null, sort_order: 2 },
    { id: "correction", label: "Correction", computation_role: "CORRECTION", pump_source: null, sort_order: 3 },
    { id: "override", label: "Override", computation_role: "OVERRIDE", pump_source: null, sort_order: 4 },
    { id: "other", label: "Other", computation_role: "OTHER", pump_source: null, sort_order: 5 },
  ],
  VALID_CATEGORY_KEYS: [
    "AUTO_CORRECTION", "FOOD", "FOOD_AND_CORRECTION",
    "CORRECTION", "OVERRIDE", "OTHER",
  ],
  DEFAULT_CATEGORY_LABELS: {
    AUTO_CORRECTION: "Auto Corr",
    FOOD: "Meal",
    FOOD_AND_CORRECTION: "Meal+Corr",
    CORRECTION: "Correction",
    OVERRIDE: "Override",
    OTHER: "Other",
  },
  // Alerts page
  getActiveAlerts: jest.fn().mockResolvedValue({ alerts: [] }),
  acknowledgeAlert: jest.fn().mockResolvedValue({}),
  getAlertEscalationTimeline: jest.fn().mockResolvedValue({ timeline: [] }),
}));

// Mock EventSource for SSE
class MockEventSource {
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  close() {}
}
Object.defineProperty(global, "EventSource", {
  value: MockEventSource,
  writable: true,
});

// Mock fetch
const originalFetch = global.fetch;
const mockFetch = jest.fn();

beforeEach(() => {
  jest.clearAllMocks();
  global.fetch = mockFetch;
  mockFetch.mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({}),
    text: async () => "",
  });
});

afterEach(() => {
  global.fetch = originalFetch;
});

// --- Page imports ---
import DashboardPage from "@/app/dashboard/page";
import SettingsPage from "@/app/dashboard/settings/page";
import GlucoseRangePage from "@/app/dashboard/settings/glucose-range/page";
import BriefDeliveryPage from "@/app/dashboard/settings/brief-delivery/page";
import DataPage from "@/app/dashboard/settings/data/page";
import EmergencyContactsPage from "@/app/dashboard/settings/emergency-contacts/page";
import ProfilePage from "@/app/dashboard/settings/profile/page";
import AlertsSettingsPage from "@/app/dashboard/settings/alerts/page";
import IntegrationsPage from "@/app/dashboard/settings/integrations/page";
import CaregiversPage from "@/app/dashboard/settings/caregivers/page";
import CommunicationsPage from "@/app/dashboard/settings/communications/page";
import TelegramPage from "@/app/dashboard/settings/telegram/page";
import AIProviderPage from "@/app/dashboard/settings/ai-provider/page";
import BriefsPage from "@/app/dashboard/briefs/page";
import AIChatPage from "@/app/dashboard/ai-chat/page";

describe("Page smoke tests - all pages render without crashing", () => {
  it("renders Dashboard page", async () => {
    await act(async () => {
      render(<DashboardPage />);
    });
    expect(screen.getByText("Dashboard")).toBeInTheDocument();
  });

  it("renders Settings index page", async () => {
    await act(async () => {
      render(<SettingsPage />);
    });
    expect(screen.getByText("Settings")).toBeInTheDocument();
  });

  it("renders Profile settings page", async () => {
    mockFetch.mockResolvedValue({
      ok: false,
      status: 401,
      json: async () => ({ detail: "Unauthorized" }),
    });
    await act(async () => {
      render(<ProfilePage />);
    });
    await waitFor(() => {
      expect(screen.getByText("Profile")).toBeInTheDocument();
    });
  });

  it("renders Glucose Range settings page", async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        urgent_low: 55,
        low_target: 70,
        high_target: 180,
        urgent_high: 250,
      }),
    });
    await act(async () => {
      render(<GlucoseRangePage />);
    });
    await waitFor(() => {
      expect(screen.getByText("Glucose Thresholds")).toBeInTheDocument();
    });
  });

  it("renders Brief Delivery settings page", async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        delivery_time: "07:00",
        timezone: "America/New_York",
        channel: "web",
        enabled: true,
      }),
    });
    await act(async () => {
      render(<BriefDeliveryPage />);
    });
    await waitFor(() => {
      expect(screen.getByText("Daily Brief Delivery")).toBeInTheDocument();
    });
  });

  it("renders Alerts settings page", async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        low_warning: 70,
        urgent_low: 55,
        high_warning: 180,
        urgent_high: 250,
        iob_warning: 3.0,
      }),
    });
    await act(async () => {
      render(<AlertsSettingsPage />);
    });
    await waitFor(() => {
      expect(screen.getByText("Alert Settings")).toBeInTheDocument();
    });
  });

  it("renders Emergency Contacts page", async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ contacts: [] }),
    });
    await act(async () => {
      render(<EmergencyContactsPage />);
    });
    await waitFor(() => {
      expect(screen.getByText("Emergency Contacts")).toBeInTheDocument();
    });
  });

  it("renders Data Management page", async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        glucose_retention_days: 365,
        alert_retention_days: 90,
        analysis_retention_days: 180,
      }),
    });
    await act(async () => {
      render(<DataPage />);
    });
    await waitFor(() => {
      expect(screen.getByText("Data Retention")).toBeInTheDocument();
    });
  });

  it("renders Integrations settings page", async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ connected: false }),
    });
    await act(async () => {
      render(<IntegrationsPage />);
    });
    await waitFor(() => {
      expect(screen.getByText("Integrations")).toBeInTheDocument();
    });
  });

  it("renders Caregivers settings page", async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ([]),
    });
    await act(async () => {
      render(<CaregiversPage />);
    });
    await waitFor(() => {
      expect(screen.getByText("Caregiver Access")).toBeInTheDocument();
    });
  });

  it("renders Communications settings page", async () => {
    await act(async () => {
      render(<CommunicationsPage />);
    });
    await waitFor(() => {
      expect(screen.getByText("Communications")).toBeInTheDocument();
    });
  });

  it("renders Telegram settings page", async () => {
    await act(async () => {
      render(<TelegramPage />);
    });
    await waitFor(() => {
      expect(screen.getByText("Telegram")).toBeInTheDocument();
    });
  });

  it("renders AI Provider settings page", async () => {
    await act(async () => {
      render(<AIProviderPage />);
    });
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "AI Provider" })).toBeInTheDocument();
    });
  });

  it("renders Daily Briefs page", async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ insights: [], total: 0 }),
    });
    await act(async () => {
      render(<BriefsPage />);
    });
    await waitFor(() => {
      expect(screen.getByText("AI Insights")).toBeInTheDocument();
    });
  });

  it("renders AI Chat page", async () => {
    await act(async () => {
      render(<AIChatPage />);
    });
    await waitFor(() => {
      // Should show either the chat interface or the provider check
      const hasChat = screen.queryByText("AI Chat");
      const hasChecking = screen.queryByText(/checking ai provider/i);
      const hasUnable = screen.queryByText(/unable to connect/i);
      const hasNoProvider = screen.queryByText(/no ai provider/i);
      expect(hasChat || hasChecking || hasUnable || hasNoProvider).toBeTruthy();
    });
  });
});
