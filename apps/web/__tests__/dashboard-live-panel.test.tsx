import { act, render, screen, waitFor, within } from "@testing-library/react";
import DashboardNewDesignPage from "@/app/v2/(authenticated)/dashboard/page";
import { hasNightscoutPumpHint } from "@/lib/pump/pump-history-context";
import {
  getCgmSources,
  getGlookoStatus,
  getMedtronicConnectStatus,
  listIntegrations,
  listNightscoutConnections,
} from "@/lib/api";

const mockRefreshWindow = jest.fn();

jest.mock("next/navigation", () => ({
  useRouter: () => ({
    replace: jest.fn(),
  }),
}));

jest.mock("@/components/AnimatedCard", () => ({
  AnimatedCard: ({
    children,
    className,
  }: {
    children: React.ReactNode;
    className?: string;
  }) => <div className={className}>{children}</div>,
}));

jest.mock("@/components/PageTransition", () => ({
  PageTransition: ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  ),
}));

jest.mock("@/components/AgpChart", () => ({
  AgpChart: () => <div data-testid="agp-chart" />,
}));

jest.mock("@/components/CgmSummaryStats", () => ({
  CgmSummaryStats: () => <div data-testid="cgm-summary-stats" />,
}));

jest.mock("@/components/ConnectionStatusBanner", () => ({
  ConnectionStatusBanner: () => <div data-testid="connection-status-banner" />,
}));

jest.mock("@/components/DashboardTimeRangePicker", () => ({
  DashboardTimeRangePicker: ({ maxRangeDays }: { maxRangeDays?: number }) => (
    <div
      data-max-range-days={String(maxRangeDays ?? "")}
      data-testid="dashboard-time-range-picker"
    />
  ),
  DashboardTimeRangeQuickSelect: ({ ranges }: { ranges?: string[] }) => (
    <div
      data-ranges={ranges?.join(",")}
      data-testid="dashboard-time-range-quick-select"
    />
  ),
}));

jest.mock("@/components/DataSourcesFreshnessCard", () => ({
  DataSourcesFreshnessCard: ({
    cgmSources,
    cgmUpdatedAt,
    dexcom,
    glooko,
    medtronic,
    now,
  }: {
    cgmSources: { primary_source: string | null } | null;
    cgmUpdatedAt: string | null;
    dexcom: { last_sync_at: string | null } | null;
    glooko: { status: string } | null;
    medtronic: { status: string } | null;
    now: number;
  }) => (
    <div
      data-cgm-primary-source={cgmSources?.primary_source ?? ""}
      data-cgm-updated-at={cgmUpdatedAt ?? ""}
      data-dexcom-last-sync={dexcom?.last_sync_at ?? ""}
      data-glooko-status={glooko?.status ?? ""}
      data-medtronic-status={medtronic?.status ?? ""}
      data-now={String(now)}
      data-testid="freshness-card"
    />
  ),
}));

jest.mock("@/components/GlucoseHero", () => ({
  GlucoseHero: ({
    embedded,
    loopStatus,
    override,
    readingAgeNow,
    isStale,
    showPumpStats,
    timestamp,
  }: {
    embedded?: boolean;
    loopStatus?: unknown;
    override?: unknown;
    readingAgeNow?: number;
    isStale?: boolean;
    showPumpStats?: boolean;
    timestamp?: string | null;
  }) => (
    <div
      data-embedded={String(Boolean(embedded))}
      data-has-loop-status={String(Boolean(loopStatus))}
      data-has-override={String(Boolean(override))}
      data-reading-age-now={String(readingAgeNow ?? "")}
      data-is-stale={String(Boolean(isStale))}
      data-show-pump-stats={String(Boolean(showPumpStats))}
      data-timestamp={timestamp ?? ""}
      data-testid="glucose-hero"
    >
      Current glucose reading
    </div>
  ),
  parseLoopState: (value: string) => value,
}));

jest.mock("@/components/GlucoseTrendChart", () => ({
  GlucoseTrendChart: () => <div data-testid="glucose-trend-chart" />,
}));

jest.mock("@/components/MergedGlucoseTrendChart", () => ({
  MergedGlucoseTrendChart: () => (
    <div data-testid="merged-glucose-trend-chart" />
  ),
}));

jest.mock("@/components/GlucoseUnitSeedNotice", () => ({
  GlucoseUnitSeedNotice: () => null,
}));

jest.mock("@/components/InsulinSummaryStats", () => ({
  InsulinSummaryStats: () => <div data-testid="insulin-summary-stats" />,
}));

jest.mock("@/components/LivePumpStats", () => ({
  LivePumpStats: ({
    basalRate,
    batteryPct,
    iob,
    loopStatus,
    override,
    reservoirUnits,
  }: {
    basalRate: number | null;
    batteryPct: number | null;
    iob: number | null;
    loopStatus?: unknown;
    override?: unknown;
    reservoirUnits: number | null;
  }) => (
    <div
      data-has-loop-status={String(Boolean(loopStatus))}
      data-has-override={String(Boolean(override))}
      data-testid="live-pump-stats"
    >
      IOB: {iob} Basal: {basalRate} Battery: {batteryPct} Reservoir:{" "}
      {reservoirUnits}
    </div>
  ),
}));

jest.mock("@/components/DashboardTimeRangeProvider", () => ({
  useDashboardTimeRange: () => ({
    currentWindow: {
      from: "2026-07-03T10:00:00.000Z",
      to: "2026-07-04T10:00:00.000Z",
    },
    label: "Last 24 hours",
    selection: { kind: "preset", range: "24h" },
    setSelection: jest.fn(),
    refreshWindow: mockRefreshWindow,
    timeZone: "UTC",
  }),
}));

jest.mock("@/providers/glucose-stream-provider", () => ({
  useGlucoseStreamContext: () => ({
    glucose: {
      iob: { current: 1.2 },
      is_stale: true,
      minutes_ago: 5,
      reading_timestamp: "2026-07-04T10:00:00.000Z",
      trend: "Stable",
      value: 120,
    },
    isLive: true,
    isReconnecting: false,
    error: null,
    reconnect: jest.fn(),
  }),
}));

jest.mock("@/providers/user-provider", () => ({
  useUserContext: () => ({
    user: { role: "diabetic" },
    isLoading: false,
  }),
}));

jest.mock("@/hooks/use-glucose-unit", () => ({
  useGlucoseUnit: () => "mgdl",
}));

jest.mock("@/hooks/use-time-in-range-stats", () => ({
  useTimeInRangeDetailStats: () => ({
    stats: {
      buckets: [{ label: "in_range", pct: 82 }],
      readings_count: 12,
    },
    isLoading: false,
    error: null,
    period: "24h",
    setPeriod: jest.fn(),
  }),
}));

jest.mock("@/hooks/use-glucose-stats", () => ({
  useGlucoseStats: () => ({
    stats: null,
    isLoading: false,
    error: null,
    period: "24h",
    setPeriod: jest.fn(),
  }),
}));

jest.mock("@/hooks/use-glucose-range", () => ({
  useGlucoseRange: () => ({
    high: 180,
    low: 70,
    urgentHigh: 250,
    urgentLow: 55,
  }),
}));

jest.mock("@/hooks/use-pump-status", () => ({
  usePumpStatus: () => ({
    basal: { rate: 0.8 },
    battery: { percentage: 75 },
    cobGrams: null,
    loopStatus: {
      state: "looping",
      source: "aaps",
      issued_at: "2026-07-04T10:00:00.000Z",
      failure_reason: null,
    },
    override: {
      name: "Exercise",
      started_at: "2026-07-04T09:30:00.000Z",
      ends_at: "2026-07-04T11:00:00.000Z",
      multiplier: 0.65,
      target_low_mgdl: 130,
      target_high_mgdl: 150,
    },
    reservoir: { units_remaining: 120 },
  }),
}));

jest.mock("@/hooks/use-forecast", () => ({
  useForecast: () => ({
    forecast: null,
  }),
}));

jest.mock("@/lib/api", () => ({
  getCgmSources: jest.fn(),
  getGlookoStatus: jest.fn(),
  getMedtronicConnectStatus: jest.fn(),
  listIntegrations: jest.fn(),
  listNightscoutConnections: jest.fn(),
}));

const mockGetCgmSources = getCgmSources as jest.MockedFunction<
  typeof getCgmSources
>;
const mockGetGlookoStatus = getGlookoStatus as jest.MockedFunction<
  typeof getGlookoStatus
>;
const mockGetMedtronicConnectStatus =
  getMedtronicConnectStatus as jest.MockedFunction<
    typeof getMedtronicConnectStatus
  >;
const mockListIntegrations = listIntegrations as jest.MockedFunction<
  typeof listIntegrations
>;
const mockListNightscoutConnections =
  listNightscoutConnections as jest.MockedFunction<
    typeof listNightscoutConnections
  >;

const NOW_MS = new Date("2026-07-04T10:05:06.000Z").getTime();
const DEXCOM_LAST_SYNC_AT = "2026-07-04T10:00:00.000Z";

async function settleConnectionStatusRequests() {
  await act(async () => {
    await Promise.all([
      mockGetCgmSources.mock.results[0].value,
      mockGetGlookoStatus.mock.results[0].value,
      mockGetMedtronicConnectStatus.mock.results[0].value,
    ]);
  });
}

describe("Dashboard live data panel", () => {
  beforeEach(() => {
    jest.spyOn(Date, "now").mockReturnValue(NOW_MS);
    mockGetCgmSources.mockResolvedValue({
      multiple_sources: false,
      primary_source: null,
      sources: [],
    });
    mockGetGlookoStatus.mockResolvedValue({
      connected: false,
      enabled: false,
      status: "not_configured",
    });
    mockGetMedtronicConnectStatus.mockResolvedValue({
      connected: false,
      enabled: false,
      status: "not_configured",
    });
    mockListIntegrations.mockReturnValue(new Promise(() => {}));
    mockListNightscoutConnections.mockReturnValue(new Promise(() => {}));
  });

  afterEach(() => {
    jest.restoreAllMocks();
    jest.clearAllMocks();
  });

  it("renders the split live CGM, pump stats, and connections panels", async () => {
    render(<DashboardNewDesignPage />);

    const liveCgmPanel = screen.getByRole("region", { name: "Live CGM" });
    const livePumpStatsPanel = screen.getByRole("region", {
      name: /Live pump/i,
    });
    const connectionsPanel = screen.getByRole("region", {
      name: /Connections/i,
    });
    const mergedGlucoseTrendPanel = screen.getByRole("region", {
      name: "Merged Glucose Trend",
    });

    expect(
      within(liveCgmPanel).getByRole("heading", {
        level: 2,
        name: "Live CGM",
      }),
    ).toBeInTheDocument();
    expect(
      within(liveCgmPanel)
        .getByRole("heading", { level: 2, name: "Live CGM" })
        .closest("header"),
    ).toHaveClass("sr-only", "lg:not-sr-only", "lg:px-4", "lg:py-3");
    expect(within(liveCgmPanel).getByTestId("glucose-hero")).toHaveAttribute(
      "data-embedded",
      "true",
    );
    expect(mergedGlucoseTrendPanel).toHaveClass(
      "-mx-dashboard-panel-gap",
      "rounded-none",
      "lg:mx-0",
      "lg:rounded-panel",
    );
    expect(
      within(mergedGlucoseTrendPanel)
        .getByRole("heading", { name: "Merged Glucose Trend" })
        .closest("header"),
    ).toHaveClass("sr-only", "lg:not-sr-only");
    expect(within(liveCgmPanel).getByTestId("glucose-hero")).toHaveAttribute(
      "data-show-pump-stats",
      "false",
    );
    expect(
      within(livePumpStatsPanel).getByRole("heading", {
        level: 2,
        name: /Live pump/i,
      }),
    ).toBeInTheDocument();
    expect(
      within(livePumpStatsPanel).getByTestId("live-pump-stats"),
    ).toHaveTextContent("IOB: 1.2");
    expect(within(liveCgmPanel).getByTestId("glucose-hero")).toHaveAttribute(
      "data-has-loop-status",
      "false",
    );
    expect(within(liveCgmPanel).getByTestId("glucose-hero")).toHaveAttribute(
      "data-has-override",
      "false",
    );
    expect(
      within(livePumpStatsPanel).getByTestId("live-pump-stats"),
    ).toHaveAttribute("data-has-loop-status", "true");
    expect(
      within(livePumpStatsPanel).getByTestId("live-pump-stats"),
    ).toHaveAttribute("data-has-override", "true");
    expect(
      within(connectionsPanel).getByRole("heading", {
        level: 2,
        name: /Connections/i,
      }),
    ).toBeInTheDocument();
    expect(
      within(connectionsPanel).getByText("No connected data sources yet."),
    ).toBeInTheDocument();
    expect(connectionsPanel).toHaveClass("hidden", "lg:block");
    expect(liveCgmPanel.parentElement).toHaveClass("gap-dashboard-panel-gap");
    expect(liveCgmPanel.parentElement?.className).toContain(
      "lg:grid-cols-[minmax(0,1fr)_minmax(18rem,0.6fr)_minmax(0,1fr)]",
    );
    expect(liveCgmPanel.parentElement?.parentElement).toHaveClass(
      "space-y-dashboard-panel-gap",
    );
    expect(
      screen.queryByRole("heading", { level: 3, name: "Data Sources" }),
    ).not.toBeInTheDocument();
    await settleConnectionStatusRequests();
  });

  it("shows the merged chart on mobile and the standard chart on desktop", async () => {
    render(<DashboardNewDesignPage />);

    const mergedGlucoseTrendPanel = screen.getByRole("region", {
      name: "Merged Glucose Trend",
    });
    const glucoseTrendPanel = screen.getByRole("region", {
      name: "Glucose Trend",
    });

    expect(mergedGlucoseTrendPanel.parentElement).toHaveClass("lg:hidden");
    expect(glucoseTrendPanel.parentElement).toHaveClass("hidden", "lg:block");
    await settleConnectionStatusRequests();
  });

  it("places CGM summary before insulin summary and above AGP", async () => {
    render(<DashboardNewDesignPage />);

    const cgmSummary = screen.getByTestId("cgm-summary-stats");
    const insulinSummary = screen.getByTestId("insulin-summary-stats");
    const agpChart = screen.getByTestId("agp-chart");

    expect(
      cgmSummary.compareDocumentPosition(insulinSummary) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      insulinSummary.compareDocumentPosition(agpChart) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    await settleConnectionStatusRequests();
  });

  it("keeps the sticky time range toolbar after all live panels", async () => {
    render(<DashboardNewDesignPage />);

    const liveConnectionsPanel = screen.getByRole("region", {
      name: /Connections/i,
    });
    const toolbarRegion = screen.getByLabelText("Dashboard time range");

    expect(
      liveConnectionsPanel.compareDocumentPosition(toolbarRegion) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(toolbarRegion).toHaveClass(
      "sticky",
      "-top-dashboard-panel-gap",
      "-mx-dashboard-panel-gap",
      "px-dashboard-panel-gap",
    );
    expect(toolbarRegion).not.toHaveClass("order-first");
    expect(
      within(toolbarRegion).getByTestId("dashboard-time-range-quick-select"),
    ).toHaveAttribute("data-ranges", "3h,24h,3d,7d");
    expect(
      within(toolbarRegion).queryByText("Create report"),
    ).not.toBeInTheDocument();
    expect(
      within(toolbarRegion).queryByRole("button", { name: "Share dashboard" }),
    ).not.toBeInTheDocument();
    expect(
      within(toolbarRegion).getByTestId("dashboard-time-range-picker"),
    ).toHaveAttribute("data-max-range-days", "31");
    await settleConnectionStatusRequests();
  });

  it("keeps live timestamp refreshes scoped to their own widgets", async () => {
    mockListIntegrations.mockResolvedValue({
      integrations: [
        {
          created_at: "2026-07-01T00:00:00.000Z",
          integration_type: "dexcom",
          last_error: null,
          last_sync_at: DEXCOM_LAST_SYNC_AT,
          region: null,
          status: "connected",
          updated_at: "2026-07-01T00:00:00.000Z",
        },
      ],
    });
    mockListNightscoutConnections.mockResolvedValue({ connections: [] });

    render(<DashboardNewDesignPage />);

    await waitFor(() => {
      expect(screen.getByTestId("freshness-card")).toHaveAttribute(
        "data-dexcom-last-sync",
        DEXCOM_LAST_SYNC_AT,
      );
    });

    expect(screen.getByTestId("freshness-card")).toHaveAttribute(
      "data-now",
      "undefined",
    );
    expect(screen.getByTestId("glucose-hero")).toHaveAttribute(
      "data-timestamp",
      "2026-07-04T10:00:00.000Z",
    );
    expect(screen.getByTestId("glucose-hero")).toHaveAttribute(
      "data-reading-age-now",
      "",
    );
    expect(screen.getByTestId("glucose-hero")).toHaveAttribute(
      "data-is-stale",
      "true",
    );
  });

  it("loads xDrip, Glooko, and Medtronic for Live Connections", async () => {
    mockListIntegrations.mockResolvedValue({ integrations: [] });
    mockListNightscoutConnections.mockResolvedValue({ connections: [] });
    mockGetCgmSources.mockResolvedValue({
      multiple_sources: false,
      primary_source: "xdrip_bridge",
      sources: [
        {
          kind: "dexcom",
          label: "xDrip",
          role: "primary",
          source: "xdrip_bridge",
        },
      ],
    });
    mockGetGlookoStatus.mockResolvedValue({
      connected: true,
      enabled: true,
      last_sync_at: DEXCOM_LAST_SYNC_AT,
      status: "connected",
    });
    mockGetMedtronicConnectStatus.mockResolvedValue({
      connected: true,
      enabled: true,
      last_sync_at: DEXCOM_LAST_SYNC_AT,
      status: "connected",
    });

    render(<DashboardNewDesignPage />);

    await waitFor(() => {
      expect(screen.getByTestId("freshness-card")).toHaveAttribute(
        "data-cgm-primary-source",
        "xdrip_bridge",
      );
    });

    expect(screen.getByTestId("freshness-card")).toHaveAttribute(
      "data-cgm-updated-at",
      "2026-07-04T10:00:00.000Z",
    );
    expect(screen.getByTestId("freshness-card")).toHaveAttribute(
      "data-glooko-status",
      "connected",
    );
    expect(screen.getByTestId("freshness-card")).toHaveAttribute(
      "data-medtronic-status",
      "connected",
    );
  });
});

describe("hasNightscoutPumpHint", () => {
  const connection = {
    id: "nightscout-1",
    name: "Nightscout",
    base_url: "https://nightscout.example",
    auth_type: "token" as const,
    api_version: "v3" as const,
    is_active: true,
    has_credential: true,
    sync_interval_minutes: 5,
    initial_sync_window_days: 30,
    last_sync_status: "ok" as const,
    last_synced_at: null,
    last_sync_error: null,
    last_evaluated_at: null,
    created_at: "2026-07-01T00:00:00.000Z",
    updated_at: "2026-07-01T00:00:00.000Z",
  };

  it("does not treat generic device status data as pump evidence", () => {
    expect(
      hasNightscoutPumpHint({
        ...connection,
        detected_uploaders_json: {
          has_devicestatus: true,
          uploaders_detected: ["xdrip"],
        },
      }),
    ).toBe(false);
  });

  it("recognizes explicit loop or pump metadata", () => {
    expect(
      hasNightscoutPumpHint({
        ...connection,
        detected_uploaders_json: { active_pump_loop: "aaps" },
      }),
    ).toBe(true);
    expect(
      hasNightscoutPumpHint({
        ...connection,
        detected_uploaders_json: { pump: "tandem" },
      }),
    ).toBe(true);
  });

  it("rejects empty loop uploader values", () => {
    expect(
      hasNightscoutPumpHint({
        ...connection,
        detected_uploaders_json: { active_pump_loop: "  " },
      }),
    ).toBe(false);
  });
});
