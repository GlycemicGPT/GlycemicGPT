/**
 * Tests for the AgpChart component.
 *
 * Story 30.5: AGP percentile band chart with period selector.
 */

import { render, screen, fireEvent } from "@testing-library/react";
import {
  AgpChart,
  type AgpChartProps,
  transformBuckets,
  formatHour,
} from "../../../src/components/dashboard/agp-chart";

// --- Mocks ---

const mockSetPeriod = jest.fn();
const mockRefetch = jest.fn();
let mockHookReturn: {
  data: {
    buckets: Array<{
      hour: number;
      p10: number;
      p25: number;
      p50: number;
      p75: number;
      p90: number;
      count: number;
    }>;
    period_days: number;
    readings_count: number;
    is_truncated: boolean;
  } | null;
  isLoading: boolean;
  error: string | null;
  period: "7d" | "14d" | "30d" | "90d";
  setPeriod: typeof mockSetPeriod;
  refetch: typeof mockRefetch;
};

jest.mock("../../../src/hooks/use-glucose-percentiles", () => ({
  useGlucosePercentiles: () => mockHookReturn,
  AGP_PERIOD_LABELS: {
    "7d": "7 Days",
    "14d": "14 Days",
    "30d": "30 Days",
    "90d": "90 Days",
  },
}));

// Mock recharts
jest.mock("recharts", () => ({
  ResponsiveContainer: ({
    children,
  }: {
    children: React.ReactNode;
  }) => <div data-testid="responsive-container">{children}</div>,
  AreaChart: ({
    children,
  }: {
    children: React.ReactNode;
  }) => <div data-testid="area-chart">{children}</div>,
  Area: ({ dataKey }: { dataKey: string }) => (
    <div data-testid={`area-${dataKey}`} />
  ),
  XAxis: () => <div data-testid="x-axis" />,
  YAxis: () => <div data-testid="y-axis" />,
  CartesianGrid: () => <div data-testid="cartesian-grid" />,
  Tooltip: () => <div data-testid="tooltip" />,
  ReferenceLine: ({ y }: { y: number }) => (
    <div data-testid="reference-line" data-y={y} />
  ),
}));

// --- Helpers ---

function makeBuckets(count: number = 24) {
  return Array.from({ length: count }, (_, i) => ({
    hour: i,
    p10: 70 + i,
    p25: 80 + i,
    p50: 100 + i,
    p75: 130 + i,
    p90: 160 + i,
    count: 50 + i,
  }));
}

function renderAgpChart(props: Partial<AgpChartProps> = {}) {
  return render(<AgpChart {...props} />);
}

// --- Tests ---

beforeEach(() => {
  jest.clearAllMocks();
  mockHookReturn = {
    data: null,
    isLoading: false,
    error: null,
    period: "14d",
    setPeriod: mockSetPeriod,
    refetch: mockRefetch,
  };
});

describe("AgpChart", () => {
  describe("loading state", () => {
    it("renders loading skeleton with aria-busy", () => {
      mockHookReturn.isLoading = true;
      renderAgpChart();
      const el = screen.getByTestId("agp-chart");
      expect(el).toHaveAttribute("aria-busy", "true");
      expect(el).toHaveAttribute("aria-label", "Loading AGP chart");
    });

    it("has correct test id", () => {
      mockHookReturn.isLoading = true;
      renderAgpChart();
      expect(screen.getByTestId("agp-chart")).toBeInTheDocument();
    });
  });

  describe("error state", () => {
    it("shows error message", () => {
      mockHookReturn.error = "Network error";
      renderAgpChart();
      expect(
        screen.getByText("Unable to load AGP data")
      ).toBeInTheDocument();
    });

    it("shows a retry button", () => {
      mockHookReturn.error = "Network error";
      renderAgpChart();
      const retryButton = screen.getByRole("button", { name: /retry/i });
      expect(retryButton).toBeInTheDocument();
    });

    it("calls refetch when retry button is clicked", () => {
      mockHookReturn.error = "Network error";
      renderAgpChart();
      fireEvent.click(screen.getByRole("button", { name: /retry/i }));
      expect(mockRefetch).toHaveBeenCalledTimes(1);
    });

    it("shows period selector in error state", () => {
      mockHookReturn.error = "Network error";
      renderAgpChart();
      expect(
        screen.getByRole("radiogroup", { name: /agp time period/i })
      ).toBeInTheDocument();
    });
  });

  describe("no-data state", () => {
    it("shows no-data message", () => {
      mockHookReturn.data = {
        buckets: [],
        period_days: 14,
        readings_count: 0,
        is_truncated: false,
      };
      renderAgpChart();
      expect(
        screen.getByText(
          "Not enough glucose data for AGP analysis (minimum 7 days needed)"
        )
      ).toBeInTheDocument();
    });

    it("shows period selector in no-data state", () => {
      mockHookReturn.data = {
        buckets: [],
        period_days: 14,
        readings_count: 0,
        is_truncated: false,
      };
      renderAgpChart();
      expect(
        screen.getByRole("radiogroup", { name: /agp time period/i })
      ).toBeInTheDocument();
    });
  });

  describe("data rendering", () => {
    beforeEach(() => {
      mockHookReturn.data = {
        buckets: makeBuckets(),
        period_days: 14,
        readings_count: 1200,
        is_truncated: false,
      };
    });

    it("renders the chart", () => {
      renderAgpChart();
      expect(screen.getByTestId("area-chart")).toBeInTheDocument();
    });

    it("shows heading text", () => {
      renderAgpChart();
      expect(
        screen.getByText("Ambulatory Glucose Profile")
      ).toBeInTheDocument();
    });

    it("sets aria-label with period", () => {
      renderAgpChart();
      expect(
        screen.getByLabelText(/ambulatory glucose profile, 14 days view/i)
      ).toBeInTheDocument();
    });

    it("displays readings count", () => {
      renderAgpChart();
      expect(screen.getByText(/1,200 readings/)).toBeInTheDocument();
    });

    it("shows truncation warning when data is truncated", () => {
      mockHookReturn.data!.is_truncated = true;
      renderAgpChart();
      expect(
        screen.getByTestId("agp-truncation-warning")
      ).toBeInTheDocument();
    });

    it("does not show truncation warning when data is not truncated", () => {
      renderAgpChart();
      expect(
        screen.queryByTestId("agp-truncation-warning")
      ).not.toBeInTheDocument();
    });

    it("shows actual error detail text", () => {
      mockHookReturn.data = null;
      mockHookReturn.error = "Permission denied";
      renderAgpChart();
      expect(screen.getByText("Permission denied")).toBeInTheDocument();
    });

    it("renders reference lines at threshold values", () => {
      renderAgpChart();
      const refLines = screen.getAllByTestId("reference-line");
      expect(refLines).toHaveLength(2);
      // Default thresholds: low=70, high=180
      expect(refLines[0]).toHaveAttribute("data-y", "70");
      expect(refLines[1]).toHaveAttribute("data-y", "180");
    });

    it("uses custom thresholds for reference lines", () => {
      renderAgpChart({
        thresholds: { urgentLow: 50, low: 80, high: 200, urgentHigh: 300 },
      });
      const refLines = screen.getAllByTestId("reference-line");
      expect(refLines[0]).toHaveAttribute("data-y", "80");
      expect(refLines[1]).toHaveAttribute("data-y", "200");
    });

    it("renders stacked area bands", () => {
      renderAgpChart();
      expect(screen.getByTestId("area-base")).toBeInTheDocument();
      expect(screen.getByTestId("area-band_p10_p25")).toBeInTheDocument();
      expect(screen.getByTestId("area-band_p25_p50")).toBeInTheDocument();
      expect(screen.getByTestId("area-band_p50_p75")).toBeInTheDocument();
      expect(screen.getByTestId("area-band_p75_p90")).toBeInTheDocument();
    });

    it("renders median line", () => {
      renderAgpChart();
      expect(screen.getByTestId("area-p50")).toBeInTheDocument();
    });

    it("renders legend items", () => {
      renderAgpChart();
      expect(screen.getByText("Median")).toBeInTheDocument();
      expect(screen.getByText("25th-75th pctl")).toBeInTheDocument();
      expect(screen.getByText("10th-90th pctl")).toBeInTheDocument();
      expect(screen.getByText("Target range")).toBeInTheDocument();
    });
  });

  describe("period selector", () => {
    beforeEach(() => {
      mockHookReturn.data = {
        buckets: makeBuckets(),
        period_days: 14,
        readings_count: 1200,
        is_truncated: false,
      };
    });

    it("renders all 4 period options", () => {
      renderAgpChart();
      expect(screen.getByRole("radio", { name: "7 Days" })).toBeInTheDocument();
      expect(screen.getByRole("radio", { name: "14 Days" })).toBeInTheDocument();
      expect(screen.getByRole("radio", { name: "30 Days" })).toBeInTheDocument();
      expect(screen.getByRole("radio", { name: "90 Days" })).toBeInTheDocument();
    });

    it("marks the active period as checked", () => {
      renderAgpChart();
      expect(screen.getByRole("radio", { name: "14 Days" })).toHaveAttribute(
        "aria-checked",
        "true"
      );
      expect(screen.getByRole("radio", { name: "7 Days" })).toHaveAttribute(
        "aria-checked",
        "false"
      );
    });

    it("calls setPeriod when clicking a period button", () => {
      renderAgpChart();
      fireEvent.click(screen.getByRole("radio", { name: "30 Days" }));
      expect(mockSetPeriod).toHaveBeenCalledWith("30d");
    });
  });

  describe("className prop", () => {
    it("applies custom className", () => {
      mockHookReturn.data = {
        buckets: makeBuckets(),
        period_days: 14,
        readings_count: 1200,
        is_truncated: false,
      };
      renderAgpChart({ className: "custom-class" });
      expect(screen.getByTestId("agp-chart")).toHaveClass("custom-class");
    });
  });
});

describe("formatHour", () => {
  it("formats midnight as 12 AM", () => {
    expect(formatHour(0)).toBe("12 AM");
  });

  it("formats noon as 12 PM", () => {
    expect(formatHour(12)).toBe("12 PM");
  });

  it("formats AM hours correctly", () => {
    expect(formatHour(3)).toBe("3 AM");
    expect(formatHour(9)).toBe("9 AM");
    expect(formatHour(11)).toBe("11 AM");
  });

  it("formats PM hours correctly", () => {
    expect(formatHour(13)).toBe("1 PM");
    expect(formatHour(18)).toBe("6 PM");
    expect(formatHour(23)).toBe("11 PM");
  });

  it("clamps out-of-range values", () => {
    expect(formatHour(-1)).toBe("12 AM");
    expect(formatHour(25)).toBe("11 PM");
  });
});

describe("transformBuckets", () => {
  it("computes stacked band deltas correctly", () => {
    const buckets = [
      { hour: 6, p10: 60, p25: 80, p50: 100, p75: 130, p90: 170, count: 42 },
    ];
    const result = transformBuckets(buckets);
    expect(result).toHaveLength(1);

    const pt = result[0];
    expect(pt.hour).toBe(6);
    expect(pt.label).toBe("6 AM");
    expect(pt.base).toBe(60);
    expect(pt.band_p10_p25).toBe(20); // 80 - 60
    expect(pt.band_p25_p50).toBe(20); // 100 - 80
    expect(pt.band_p50_p75).toBe(30); // 130 - 100
    expect(pt.band_p75_p90).toBe(40); // 170 - 130
    expect(pt.count).toBe(42);
  });

  it("guards against negative band values with Math.max(0, ...)", () => {
    const buckets = [
      { hour: 0, p10: 100, p25: 100, p50: 100, p75: 100, p90: 100, count: 1 },
    ];
    const result = transformBuckets(buckets);
    expect(result[0].band_p10_p25).toBe(0);
    expect(result[0].band_p25_p50).toBe(0);
    expect(result[0].band_p50_p75).toBe(0);
    expect(result[0].band_p75_p90).toBe(0);
  });

  it("rounds float values in bands", () => {
    const buckets = [
      { hour: 12, p10: 70.3, p25: 80.7, p50: 100.1, p75: 130.9, p90: 160.4, count: 10 },
    ];
    const result = transformBuckets(buckets);
    expect(result[0].base).toBe(70);
    expect(result[0].band_p10_p25).toBe(10); // round(80.7 - 70.3) = round(10.4) = 10
    expect(result[0].band_p25_p50).toBe(19); // round(100.1 - 80.7) = round(19.4) = 19
    expect(result[0].band_p50_p75).toBe(31); // round(130.9 - 100.1) = round(30.8) = 31
    expect(result[0].band_p75_p90).toBe(30); // round(160.4 - 130.9) = round(29.5) = 30
  });

  it("transforms all 24 hourly buckets", () => {
    const result = transformBuckets(makeBuckets(24));
    expect(result).toHaveLength(24);
    expect(result[0].hour).toBe(0);
    expect(result[23].hour).toBe(23);
  });
});
