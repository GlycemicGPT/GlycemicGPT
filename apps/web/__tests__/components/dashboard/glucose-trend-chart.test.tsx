/**
 * Tests for the GlucoseTrendChart component.
 *
 * Glucose trend chart with colored dots, target range band,
 * and time period selector (3H, 6H, 12H, 24H).
 */

import { render, screen, fireEvent } from "@testing-library/react";
import {
  GlucoseTrendChart,
  type GlucoseTrendChartProps,
  getPointColor,
  PERIOD_TO_MS,
} from "../../../src/components/dashboard/glucose-trend-chart";
import { GLUCOSE_THRESHOLDS } from "../../../src/components/dashboard/glucose-hero";

// --- Mocks ---

// Mock the useGlucoseHistory hook
const mockSetPeriod = jest.fn();
const mockRefetch = jest.fn();
let mockHookReturn = {
  readings: [] as Array<{
    value: number;
    reading_timestamp: string;
    trend: string;
    trend_rate: number | null;
    received_at: string;
    source: string;
  }>,
  isLoading: false,
  error: null as string | null,
  period: "3h" as const,
  setPeriod: mockSetPeriod,
  refetch: mockRefetch,
};

jest.mock("../../../src/hooks/use-glucose-history", () => ({
  useGlucoseHistory: () => mockHookReturn,
}));

// Mock the usePumpEvents hook
const mockRefetchPump = jest.fn();
let mockPumpReturn = {
  events: [] as Array<{
    event_type: string;
    event_timestamp: string;
    units: number | null;
    is_automated: boolean;
  }>,
  isLoading: false,
  refetch: mockRefetchPump,
};

jest.mock("../../../src/hooks/use-pump-events", () => ({
  usePumpEvents: () => mockPumpReturn,
}));

// Mock recharts - render minimal DOM so we can test surrounding logic
jest.mock("recharts", () => ({
  ResponsiveContainer: ({
    children,
  }: {
    children: React.ReactNode;
  }) => <div data-testid="responsive-container">{children}</div>,
  ComposedChart: ({
    children,
  }: {
    children: React.ReactNode;
  }) => <div data-testid="scatter-chart">{children}</div>,
  Scatter: ({ data }: { data: unknown[] }) => (
    <div data-testid="scatter" data-count={data?.length ?? 0} />
  ),
  Line: ({ data, dataKey }: { data: unknown[]; dataKey: string }) => (
    <div
      data-testid="line"
      data-count={data?.length ?? 0}
      data-key={dataKey}
    />
  ),
  Area: () => <div data-testid="area" />,
  XAxis: () => <div data-testid="x-axis" />,
  YAxis: () => <div data-testid="y-axis" />,
  CartesianGrid: () => <div data-testid="cartesian-grid" />,
  Tooltip: () => <div data-testid="tooltip" />,
  ReferenceArea: ({ y1, y2 }: { y1: number; y2: number }) => (
    <div data-testid="reference-area" data-y1={y1} data-y2={y2} />
  ),
  ReferenceLine: () => <div data-testid="reference-line" />,
  Cell: () => <div data-testid="cell" />,
}));

// --- Helpers ---

function makeReading(
  value: number,
  minutesAgo: number
): (typeof mockHookReturn.readings)[0] {
  const ts = new Date(Date.now() - minutesAgo * 60_000).toISOString();
  return {
    value,
    reading_timestamp: ts,
    trend: "flat",
    trend_rate: null,
    received_at: ts,
    source: "dexcom",
  };
}

function renderChart(props: Partial<GlucoseTrendChartProps> = {}) {
  return render(<GlucoseTrendChart {...props} />);
}

// --- Tests ---

beforeEach(() => {
  jest.clearAllMocks();
  mockHookReturn = {
    readings: [],
    isLoading: false,
    error: null,
    period: "3h",
    setPeriod: mockSetPeriod,
    refetch: mockRefetch,
  };
  mockPumpReturn = {
    events: [],
    isLoading: false,
    refetch: mockRefetchPump,
  };
});

describe("getPointColor", () => {
  it("returns red for urgent low values (< 55)", () => {
    expect(getPointColor(54)).toBe("#dc2626");
    expect(getPointColor(30)).toBe("#dc2626");
    expect(getPointColor(0)).toBe("#dc2626");
  });

  it("returns amber for low values (55-69)", () => {
    expect(getPointColor(55)).toBe("#f59e0b");
    expect(getPointColor(60)).toBe("#f59e0b");
    expect(getPointColor(69)).toBe("#f59e0b");
  });

  it("returns green for in-range values (70-180)", () => {
    expect(getPointColor(70)).toBe("#22c55e");
    expect(getPointColor(120)).toBe("#22c55e");
    expect(getPointColor(180)).toBe("#22c55e");
  });

  it("returns amber for high values (181-250)", () => {
    expect(getPointColor(181)).toBe("#f59e0b");
    expect(getPointColor(200)).toBe("#f59e0b");
    expect(getPointColor(250)).toBe("#f59e0b");
  });

  it("returns red for urgent high values (> 250)", () => {
    expect(getPointColor(251)).toBe("#dc2626");
    expect(getPointColor(300)).toBe("#dc2626");
    expect(getPointColor(400)).toBe("#dc2626");
  });

  it("handles exact boundary values correctly", () => {
    expect(getPointColor(GLUCOSE_THRESHOLDS.URGENT_LOW)).toBe("#f59e0b"); // 55 = low, not urgent
    expect(getPointColor(GLUCOSE_THRESHOLDS.LOW)).toBe("#22c55e"); // 70 = in range
    expect(getPointColor(GLUCOSE_THRESHOLDS.HIGH)).toBe("#22c55e"); // 180 = in range
    expect(getPointColor(GLUCOSE_THRESHOLDS.URGENT_HIGH)).toBe("#f59e0b"); // 250 = high, not urgent
  });
});

describe("PERIOD_TO_MS", () => {
  it("maps 3h to 3 hours in milliseconds", () => {
    expect(PERIOD_TO_MS["3h"]).toBe(3 * 60 * 60 * 1000);
  });

  it("maps 6h to 6 hours in milliseconds", () => {
    expect(PERIOD_TO_MS["6h"]).toBe(6 * 60 * 60 * 1000);
  });

  it("maps 12h to 12 hours in milliseconds", () => {
    expect(PERIOD_TO_MS["12h"]).toBe(12 * 60 * 60 * 1000);
  });

  it("maps 24h to 24 hours in milliseconds", () => {
    expect(PERIOD_TO_MS["24h"]).toBe(24 * 60 * 60 * 1000);
  });
});

describe("GlucoseTrendChart", () => {
  describe("loading state", () => {
    it("renders loading skeleton when loading with no data", () => {
      mockHookReturn.isLoading = true;
      renderChart();
      expect(
        screen.getByRole("region", {
          name: /loading glucose trend chart/i,
        })
      ).toBeInTheDocument();
      expect(screen.getByRole("region")).toHaveAttribute(
        "aria-busy",
        "true"
      );
    });

    it("has correct test id", () => {
      mockHookReturn.isLoading = true;
      renderChart();
      expect(screen.getByTestId("glucose-trend-chart")).toBeInTheDocument();
    });
  });

  describe("error state", () => {
    it("shows error message when there is an error and no data", () => {
      mockHookReturn.error = "Network error";
      renderChart();
      expect(
        screen.getByText("Unable to load glucose history")
      ).toBeInTheDocument();
    });

    it("still shows period selector in error state", () => {
      mockHookReturn.error = "Network error";
      renderChart();
      expect(
        screen.getByRole("radiogroup", { name: /time period/i })
      ).toBeInTheDocument();
    });

    it("shows a retry button in error state", () => {
      mockHookReturn.error = "Network error";
      renderChart();
      const retryButton = screen.getByRole("button", { name: /retry/i });
      expect(retryButton).toBeInTheDocument();
    });

    it("calls refetch when retry button is clicked", () => {
      mockHookReturn.error = "Network error";
      renderChart();
      fireEvent.click(screen.getByRole("button", { name: /retry/i }));
      expect(mockRefetch).toHaveBeenCalledTimes(1);
    });
  });

  describe("empty state", () => {
    it("shows empty message when no readings", () => {
      renderChart();
      expect(
        screen.getByText("No glucose readings yet")
      ).toBeInTheDocument();
    });

    it("still shows period selector in empty state", () => {
      renderChart();
      expect(
        screen.getByRole("radiogroup", { name: /time period/i })
      ).toBeInTheDocument();
    });
  });

  describe("data rendering", () => {
    it("renders the chart when readings are available", () => {
      mockHookReturn.readings = [
        makeReading(120, 30),
        makeReading(150, 20),
        makeReading(100, 10),
      ];
      renderChart();
      expect(screen.getByTestId("scatter-chart")).toBeInTheDocument();
      expect(screen.getByTestId("reference-area")).toBeInTheDocument();
    });

    it("shows the chart heading", () => {
      mockHookReturn.readings = [makeReading(120, 5)];
      renderChart();
      expect(screen.getByText("Glucose Trend")).toBeInTheDocument();
    });

    it("sets aria-label with period", () => {
      mockHookReturn.readings = [makeReading(120, 5)];
      renderChart();
      expect(
        screen.getByRole("region", {
          name: /glucose trend chart, 3h view/i,
        })
      ).toBeInTheDocument();
    });

    it("renders the range legend derived from thresholds (with the unit label)", () => {
      mockHookReturn.readings = [makeReading(120, 5)];
      renderChart();
      expect(
        screen.getByText(`${GLUCOSE_THRESHOLDS.LOW}-${GLUCOSE_THRESHOLDS.HIGH} mg/dL Target`)
      ).toBeInTheDocument();
      expect(screen.getByText("High/Low")).toBeInTheDocument();
      expect(screen.getByText("Urgent")).toBeInTheDocument();
    });

    it("renders target range band at threshold values", () => {
      mockHookReturn.readings = [makeReading(120, 5)];
      renderChart();
      const band = screen.getByTestId("reference-area");
      expect(band).toHaveAttribute("data-y1", String(GLUCOSE_THRESHOLDS.LOW));
      expect(band).toHaveAttribute("data-y2", String(GLUCOSE_THRESHOLDS.HIGH));
    });
  });

  describe("period selector", () => {
    it("renders all period options", () => {
      mockHookReturn.readings = [makeReading(120, 5)];
      renderChart();
      expect(screen.getByRole("radio", { name: "3H" })).toBeInTheDocument();
      expect(screen.getByRole("radio", { name: "6H" })).toBeInTheDocument();
      expect(screen.getByRole("radio", { name: "12H" })).toBeInTheDocument();
      expect(screen.getByRole("radio", { name: "24H" })).toBeInTheDocument();
    });

    it("marks the active period as checked", () => {
      mockHookReturn.readings = [makeReading(120, 5)];
      renderChart();
      expect(screen.getByRole("radio", { name: "3H" })).toHaveAttribute(
        "aria-checked",
        "true"
      );
      expect(screen.getByRole("radio", { name: "6H" })).toHaveAttribute(
        "aria-checked",
        "false"
      );
    });

    it("calls setPeriod when clicking a period button", () => {
      mockHookReturn.readings = [makeReading(120, 5)];
      renderChart();
      fireEvent.click(screen.getByRole("radio", { name: "12H" }));
      expect(mockSetPeriod).toHaveBeenCalledWith("12h");
    });
  });

  describe("refreshKey", () => {
    it("calls refetch when refreshKey changes", () => {
      mockHookReturn.readings = [makeReading(120, 5)];
      const { rerender } = render(<GlucoseTrendChart refreshKey={1} />);
      expect(mockRefetch).not.toHaveBeenCalled();

      rerender(<GlucoseTrendChart refreshKey={2} />);
      expect(mockRefetch).toHaveBeenCalledTimes(1);
    });

    it("does not refetch on initial render with refreshKey=0", () => {
      mockHookReturn.readings = [makeReading(120, 5)];
      render(<GlucoseTrendChart refreshKey={0} />);
      expect(mockRefetch).not.toHaveBeenCalled();
    });
  });

  describe("className prop", () => {
    it("applies custom className", () => {
      mockHookReturn.readings = [makeReading(120, 5)];
      renderChart({ className: "custom-class" });
      expect(screen.getByTestId("glucose-trend-chart")).toHaveClass(
        "custom-class"
      );
    });
  });

  // Story 43.12 PR 4: forecast overlay
  describe("forecast overlay", () => {
    function makeForecastProp(
      overrides: Partial<
        NonNullable<GlucoseTrendChartProps["forecast"]>
      > = {}
    ): GlucoseTrendChartProps["forecast"] {
      return {
        source_preference: "auto",
        effective_source: "loop",
        available_sources: ["loop"],
        forecast: {
          source_engine: "loop",
          source_uploader: "Loop",
          issued_at: new Date().toISOString(),
          start_at: new Date().toISOString(),
          step_minutes: 5,
          horizon_minutes: 180,
          curves_mgdl: { main: [120, 125, 130, 135] },
          default_curve_name: "main",
        },
        forecast_unavailable_reason: null,
        ...overrides,
      };
    }

    it("renders the dotted line on 3H when forecast data is present", () => {
      mockHookReturn.readings = [makeReading(120, 5)];
      mockHookReturn.period = "3h";
      renderChart({ forecast: makeForecastProp() });

      const line = screen.queryByTestId("line");
      expect(line).not.toBeNull();
      expect(line?.getAttribute("data-key")).toBe("forecast_value");
    });

    it("renders the dotted line on 6H too", () => {
      mockHookReturn.readings = [makeReading(120, 5)];
      mockHookReturn.period = "6h" as typeof mockHookReturn.period;
      renderChart({ forecast: makeForecastProp() });

      expect(screen.queryByTestId("line")).not.toBeNull();
    });

    it("hides the dotted line on 24H and longer", () => {
      mockHookReturn.readings = [makeReading(120, 5)];
      mockHookReturn.period = "24h" as typeof mockHookReturn.period;
      renderChart({ forecast: makeForecastProp() });

      expect(screen.queryByTestId("line")).toBeNull();
    });

    it("hides the dotted line when forecast prop is null", () => {
      mockHookReturn.readings = [makeReading(120, 5)];
      mockHookReturn.period = "3h";
      renderChart({ forecast: null });

      expect(screen.queryByTestId("line")).toBeNull();
    });

    it("hides the dotted line when forecast payload is missing", () => {
      mockHookReturn.readings = [makeReading(120, 5)];
      mockHookReturn.period = "3h";
      renderChart({
        forecast: makeForecastProp({
          forecast: null,
          forecast_unavailable_reason: "source_silent",
        }),
      });

      expect(screen.queryByTestId("line")).toBeNull();
    });

    it("renders the attribution legend chip when overlay is drawing", () => {
      mockHookReturn.readings = [makeReading(120, 5)];
      mockHookReturn.period = "3h";
      renderChart({ forecast: makeForecastProp() });

      const chip = screen.queryByTestId("forecast-legend-chip");
      expect(chip).not.toBeNull();
      expect(chip?.textContent).toContain("Loop");
    });

    it("renders the unavailable-reason chip when overlay is not drawing", () => {
      mockHookReturn.readings = [makeReading(120, 5)];
      mockHookReturn.period = "3h";
      renderChart({
        forecast: makeForecastProp({
          forecast: null,
          forecast_unavailable_reason: "stale",
        }),
      });

      const chip = screen.queryByTestId("forecast-legend-chip");
      expect(chip).not.toBeNull();
      expect(chip?.textContent?.toLowerCase()).toContain("30 minutes");
    });
  });
});
