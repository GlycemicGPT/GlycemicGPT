/**
 * Tests for the TirDonutChart component.
 *
 * Story 30.4: 5-bucket TIR donut chart with previous-period comparison.
 */

import { render, screen, fireEvent } from "@testing-library/react";
import {
  TirDonutChart,
  type TirDonutChartProps,
} from "../../../src/components/dashboard/tir-donut-chart";
import type { TirBucket } from "../../../src/lib/api";

// --- Mocks ---

// Mock recharts - render minimal DOM so we can test surrounding logic
jest.mock("recharts", () => ({
  ResponsiveContainer: ({
    children,
  }: {
    children: React.ReactNode;
  }) => <div data-testid="responsive-container">{children}</div>,
  PieChart: ({
    children,
  }: {
    children: React.ReactNode;
  }) => <div data-testid="pie-chart">{children}</div>,
  Pie: ({
    data,
    children,
  }: {
    data: unknown[];
    children: React.ReactNode;
  }) => (
    <div data-testid="pie" data-count={data?.length ?? 0}>
      {children}
    </div>
  ),
  Cell: () => <div data-testid="cell" />,
}));

// --- Test Fixtures ---

function makeBuckets(overrides?: Partial<Record<string, number>>): TirBucket[] {
  const defaults: Record<string, number> = {
    urgent_low: 2,
    low: 8,
    in_range: 70,
    high: 15,
    urgent_high: 5,
    ...overrides,
  };
  return [
    { label: "urgent_low", pct: defaults.urgent_low, readings: 5, threshold_low: null, threshold_high: 55 },
    { label: "low", pct: defaults.low, readings: 20, threshold_low: 55, threshold_high: 70 },
    { label: "in_range", pct: defaults.in_range, readings: 175, threshold_low: 70, threshold_high: 180 },
    { label: "high", pct: defaults.high, readings: 38, threshold_low: 180, threshold_high: 250 },
    { label: "urgent_high", pct: defaults.urgent_high, readings: 12, threshold_low: 250, threshold_high: null },
  ];
}

const defaultProps: TirDonutChartProps = {
  buckets: makeBuckets(),
  readingsCount: 250,
  previousBuckets: null,
  previousReadingsCount: null,
};

// --- Tests ---

describe("TirDonutChart", () => {
  it("renders 5 legend items with correct labels", () => {
    render(<TirDonutChart {...defaultProps} />);
    const legend = screen.getByTestId("tir-legend");
    expect(legend).toBeInTheDocument();
    expect(screen.getByText("Urgent Low")).toBeInTheDocument();
    const legendItems = screen.getAllByTestId("tir-legend-item");
    expect(legendItems).toHaveLength(5);
    expect(screen.getByText("High")).toBeInTheDocument();
    expect(screen.getByText("Urgent High")).toBeInTheDocument();
  });

  it("shows loading skeleton when isLoading", () => {
    render(<TirDonutChart {...defaultProps} isLoading={true} />);
    const chart = screen.getByTestId("tir-donut-chart");
    expect(chart).toHaveAttribute("aria-busy", "true");
    // Legend should NOT be present while loading
    expect(screen.queryByTestId("tir-legend")).not.toBeInTheDocument();
  });

  it("shows error message when error prop is set", () => {
    render(
      <TirDonutChart
        {...defaultProps}
        error="Failed to load TIR detail"
      />
    );
    const errorMsg = screen.getByTestId("error-message");
    expect(errorMsg).toHaveTextContent("Failed to load TIR detail");
    expect(errorMsg).toHaveAttribute("role", "alert");
  });

  it("shows no-data message when stats are null", () => {
    render(
      <TirDonutChart
        buckets={null}
        readingsCount={0}
        previousBuckets={null}
        previousReadingsCount={null}
      />
    );
    expect(screen.getByTestId("no-data-message")).toBeInTheDocument();
    expect(screen.getByText(/No glucose data/)).toBeInTheDocument();
  });

  it("shows no-data message when readingsCount is 0", () => {
    render(
      <TirDonutChart
        buckets={makeBuckets()}
        readingsCount={0}
        previousBuckets={null}
        previousReadingsCount={null}
      />
    );
    expect(screen.getByTestId("no-data-message")).toBeInTheDocument();
  });

  it("displays in-range percentage in center with clinical color", () => {
    render(<TirDonutChart {...defaultProps} />);
    const center = screen.getByTestId("in-range-center");
    expect(center).toHaveTextContent("70%");
    // 70% in range = green (>= 70% threshold)
    expect(center.className).toContain("text-green-400");
  });

  it("shows amber center text for moderate in-range (50-69%)", () => {
    const moderateBuckets = makeBuckets({ in_range: 55, high: 30, urgent_high: 7 });
    render(
      <TirDonutChart
        buckets={moderateBuckets}
        readingsCount={250}
        previousBuckets={null}
        previousReadingsCount={null}
      />
    );
    const center = screen.getByTestId("in-range-center");
    expect(center.className).toContain("text-amber-400");
  });

  it("shows red center text for poor in-range (<50%)", () => {
    const poorBuckets = makeBuckets({ in_range: 30, high: 40, urgent_high: 22 });
    render(
      <TirDonutChart
        buckets={poorBuckets}
        readingsCount={250}
        previousBuckets={null}
        previousReadingsCount={null}
      />
    );
    const center = screen.getByTestId("in-range-center");
    expect(center.className).toContain("text-red-400");
  });

  it("shows delta when previous period data exists and differs", () => {
    const prevBuckets = makeBuckets({ in_range: 65 });
    render(
      <TirDonutChart
        {...defaultProps}
        previousBuckets={prevBuckets}
        previousReadingsCount={200}
      />
    );
    const delta = screen.getByTestId("delta-indicator");
    expect(delta).toHaveTextContent("+5%");
  });

  it("shows negative delta when in-range decreased", () => {
    const prevBuckets = makeBuckets({ in_range: 80 });
    render(
      <TirDonutChart
        {...defaultProps}
        previousBuckets={prevBuckets}
        previousReadingsCount={200}
      />
    );
    const delta = screen.getByTestId("delta-indicator");
    expect(delta).toHaveTextContent("-10%");
  });

  it("does not show delta when previous period is null", () => {
    render(<TirDonutChart {...defaultProps} />);
    expect(screen.queryByTestId("delta-indicator")).not.toBeInTheDocument();
  });

  it("does not show delta when delta is zero", () => {
    const prevBuckets = makeBuckets({ in_range: 70 });
    render(
      <TirDonutChart
        {...defaultProps}
        previousBuckets={prevBuckets}
        previousReadingsCount={200}
      />
    );
    expect(screen.queryByTestId("delta-indicator")).not.toBeInTheDocument();
  });

  it("period selector triggers callback", () => {
    const onPeriodChange = jest.fn();
    render(
      <TirDonutChart
        {...defaultProps}
        period="24h"
        onPeriodChange={onPeriodChange}
      />
    );
    const btn7d = screen.getByRole("radio", { name: /7D/i });
    fireEvent.click(btn7d);
    expect(onPeriodChange).toHaveBeenCalledWith("7d");
  });

  it("handles all-zero data gracefully", () => {
    const zeroBuckets = makeBuckets({
      urgent_low: 0,
      low: 0,
      in_range: 0,
      high: 0,
      urgent_high: 0,
    });
    // Zero readings should show no-data message even with buckets
    render(
      <TirDonutChart
        buckets={zeroBuckets}
        readingsCount={0}
        previousBuckets={null}
        previousReadingsCount={null}
      />
    );
    expect(screen.getByTestId("no-data-message")).toBeInTheDocument();
  });

  it("handles malformed data (NaN, Infinity) without crashing", () => {
    const badBuckets: TirBucket[] = [
      { label: "urgent_low", pct: NaN, readings: 0, threshold_low: null, threshold_high: 55 },
      { label: "low", pct: Infinity, readings: 0, threshold_low: 55, threshold_high: 70 },
      { label: "in_range", pct: -5, readings: 0, threshold_low: 70, threshold_high: 180 },
      { label: "high", pct: 200, readings: 0, threshold_low: 180, threshold_high: 250 },
      { label: "urgent_high", pct: 0, readings: 0, threshold_low: 250, threshold_high: null },
    ];
    // Should not throw
    render(
      <TirDonutChart
        buckets={badBuckets}
        readingsCount={100}
        previousBuckets={null}
        previousReadingsCount={null}
      />
    );
    expect(screen.getByTestId("tir-donut-chart")).toBeInTheDocument();
  });

  it("renders readings count text", () => {
    render(<TirDonutChart {...defaultProps} />);
    expect(screen.getByText("250 readings")).toBeInTheDocument();
  });

  it("renders previous readings count when present", () => {
    const prevBuckets = makeBuckets();
    render(
      <TirDonutChart
        {...defaultProps}
        previousBuckets={prevBuckets}
        previousReadingsCount={200}
      />
    );
    expect(screen.getByText(/prev: 200/)).toBeInTheDocument();
  });
});
