/**
 * Tests for the TimeInRangeBar component.
 *
 * Story 4.4 / 30.4 consolidated: 5-bucket clinical TIR bar with
 * previous-period comparison and delta indicator.
 */

import { render, screen, fireEvent } from "@testing-library/react";
import {
  TimeInRangeBar,
  normalizeBuckets,
  formatPercentage,
  getQualityAssessment,
  PERIOD_LABELS,
  type TimePeriod,
} from "../../../src/components/dashboard/time-in-range-bar";
import TimeInRangeBarDefault from "../../../src/components/dashboard/time-in-range-bar";
import type { TirBucket } from "../../../src/lib/api";

// Mock framer-motion
const mockUseReducedMotion = jest.fn(() => false);

jest.mock("framer-motion", () => ({
  motion: {
    div: ({
      children,
      className,
      style,
      ...props
    }: {
      children: React.ReactNode;
      className?: string;
      style?: React.CSSProperties;
      [key: string]: unknown;
    }) => (
      <div className={className} style={style} {...props}>
        {children}
      </div>
    ),
  },
  useReducedMotion: () => mockUseReducedMotion(),
}));

beforeEach(() => {
  mockUseReducedMotion.mockReturnValue(false);
});

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

const defaultBuckets = makeBuckets();

// --- Tests ---

describe("PERIOD_LABELS constant", () => {
  it("contains all time periods", () => {
    expect(PERIOD_LABELS["24h"]).toBe("24 Hours");
    expect(PERIOD_LABELS["3d"]).toBe("3 Days");
    expect(PERIOD_LABELS["7d"]).toBe("7 Days");
    expect(PERIOD_LABELS["14d"]).toBe("14 Days");
    expect(PERIOD_LABELS["30d"]).toBe("30 Days");
  });
});

describe("normalizeBuckets", () => {
  it("returns buckets unchanged if already sums to 100", () => {
    const buckets = makeBuckets();
    const result = normalizeBuckets(buckets);
    const total = result.reduce((s, b) => s + b.pct, 0);
    expect(total).toBeCloseTo(100, 1);
  });

  it("normalizes buckets that sum to more than 100", () => {
    const buckets = makeBuckets({ urgent_low: 10, low: 20, in_range: 80, high: 20, urgent_high: 10 });
    const result = normalizeBuckets(buckets);
    const total = result.reduce((s, b) => s + b.pct, 0);
    expect(total).toBeCloseTo(100, 1);
  });

  it("normalizes buckets that sum to less than 100", () => {
    const buckets = makeBuckets({ urgent_low: 1, low: 3, in_range: 30, high: 5, urgent_high: 1 });
    const result = normalizeBuckets(buckets);
    const total = result.reduce((s, b) => s + b.pct, 0);
    expect(total).toBeCloseTo(100, 1);
  });

  it("returns all zeros for all-zero data", () => {
    const buckets = makeBuckets({ urgent_low: 0, low: 0, in_range: 0, high: 0, urgent_high: 0 });
    const result = normalizeBuckets(buckets);
    result.forEach((b) => expect(b.pct).toBe(0));
  });

  it("handles near-100 floating point totals unchanged", () => {
    const buckets = makeBuckets({ urgent_low: 2.001, low: 7.999, in_range: 70.002, high: 14.999, urgent_high: 4.999 });
    const result = normalizeBuckets(buckets);
    // Within 0.01 of 100 -- should return unchanged
    expect(result[0].pct).toBe(2.001);
  });

  it("ensures in_range is never negative", () => {
    const buckets = makeBuckets({ urgent_low: 25.3, low: 25.3, in_range: 0, high: 25.3, urgent_high: 25.3 });
    const result = normalizeBuckets(buckets);
    const inRange = result.find((b) => b.label === "in_range");
    expect(inRange!.pct).toBeGreaterThanOrEqual(0);
  });
});

describe("formatPercentage", () => {
  it("formats 0 as '0%'", () => {
    expect(formatPercentage(0)).toBe("0%");
  });

  it("formats values less than 0.5 as '<1%'", () => {
    expect(formatPercentage(0.1)).toBe("<1%");
    expect(formatPercentage(0.4)).toBe("<1%");
  });

  it("formats 0.5 as '1%' (rounds up)", () => {
    expect(formatPercentage(0.5)).toBe("1%");
  });

  it("formats 99.5 as '>99%' (at threshold)", () => {
    expect(formatPercentage(99.5)).toBe(">99%");
  });

  it("formats 99.9 as '>99%' (above threshold)", () => {
    expect(formatPercentage(99.9)).toBe(">99%");
  });

  it("rounds values to nearest integer", () => {
    expect(formatPercentage(50)).toBe("50%");
    expect(formatPercentage(75.4)).toBe("75%");
    expect(formatPercentage(75.6)).toBe("76%");
  });

  it("formats 100 as '100%'", () => {
    expect(formatPercentage(100)).toBe("100%");
  });
});

describe("getQualityAssessment", () => {
  it("returns Excellent for 70% or higher", () => {
    expect(getQualityAssessment(70)).toEqual({
      label: "Excellent",
      colorClass: "text-green-400",
    });
    expect(getQualityAssessment(85)).toEqual({
      label: "Excellent",
      colorClass: "text-green-400",
    });
  });

  it("returns Good for 50-69%", () => {
    expect(getQualityAssessment(50)).toEqual({
      label: "Good",
      colorClass: "text-amber-400",
    });
    expect(getQualityAssessment(69)).toEqual({
      label: "Good",
      colorClass: "text-amber-400",
    });
  });

  it("returns Needs Improvement for below 50%", () => {
    expect(getQualityAssessment(49)).toEqual({
      label: "Needs Improvement",
      colorClass: "text-red-400",
    });
    expect(getQualityAssessment(0)).toEqual({
      label: "Needs Improvement",
      colorClass: "text-red-400",
    });
  });
});

describe("TimeInRangeBar component", () => {
  const baseProps = {
    buckets: defaultBuckets,
    readingsCount: 250,
    previousBuckets: null,
    previousReadingsCount: null,
    error: null,
  };

  describe("rendering", () => {
    it("renders with data-testid", () => {
      render(<TimeInRangeBar {...baseProps} />);
      expect(screen.getByTestId("time-in-range-bar")).toBeInTheDocument();
    });

    it("displays the Time in Range heading", () => {
      render(<TimeInRangeBar {...baseProps} />);
      expect(screen.getByText("Time in Range")).toBeInTheDocument();
    });

    it("displays the default period label", () => {
      render(<TimeInRangeBar {...baseProps} />);
      expect(screen.getByTestId("period-label")).toHaveTextContent("24 Hours");
    });

    it("displays custom period label", () => {
      render(<TimeInRangeBar {...baseProps} period="7d" />);
      expect(screen.getByTestId("period-label")).toHaveTextContent("7 Days");
    });

    it("displays quality assessment", () => {
      render(<TimeInRangeBar {...baseProps} />);
      expect(screen.getByText("Excellent")).toBeInTheDocument();
    });

    it("displays correct quality for Good range", () => {
      const buckets = makeBuckets({ in_range: 55, high: 30, urgent_high: 7 });
      render(<TimeInRangeBar {...baseProps} buckets={buckets} />);
      expect(screen.getByText("Good")).toBeInTheDocument();
    });

    it("displays correct quality for Needs Improvement range", () => {
      const buckets = makeBuckets({ in_range: 40, high: 40, urgent_high: 12 });
      render(<TimeInRangeBar {...baseProps} buckets={buckets} />);
      expect(screen.getByText("Needs Improvement")).toBeInTheDocument();
    });

    it("displays target range info", () => {
      render(<TimeInRangeBar {...baseProps} />);
      expect(screen.getByText(/Target: 70-180 mg\/dL/)).toBeInTheDocument();
    });

    it("displays custom target range", () => {
      render(<TimeInRangeBar {...baseProps} targetRange="80-140 mg/dL" />);
      expect(screen.getByText(/Target: 80-140 mg\/dL/)).toBeInTheDocument();
    });
  });

  describe("5-segment rendering", () => {
    it("renders all 5 segments with clinical colors", () => {
      render(<TimeInRangeBar {...baseProps} />);
      const bar = screen.getByRole("img");
      // Each non-zero segment should have a title attribute
      expect(bar).toBeInTheDocument();
      // All 5 labels should appear in the title attributes
      const segments = bar.querySelectorAll("[title]");
      expect(segments.length).toBe(5);
    });

    it("skips zero-pct segments", () => {
      const buckets = makeBuckets({ urgent_low: 0, urgent_high: 0 });
      render(<TimeInRangeBar {...baseProps} buckets={buckets} />);
      const bar = screen.getByRole("img");
      const segments = bar.querySelectorAll("[title]");
      expect(segments.length).toBe(3); // low, in_range, high
    });

    it("shows labels on segments >= 10%", () => {
      render(<TimeInRangeBar {...baseProps} />);
      // 70% in_range and 15% high should have labels, 2% urgent_low should not
      const bar = screen.getByRole("img");
      const labels = bar.querySelectorAll("span");
      // in_range (70%) and high (15%) get labels
      expect(labels.length).toBe(2);
    });
  });

  describe("previous-period comparison", () => {
    it("renders previous-period bar when previousBuckets is provided", () => {
      const prevBuckets = makeBuckets({ in_range: 65 });
      render(
        <TimeInRangeBar
          {...baseProps}
          previousBuckets={prevBuckets}
          previousReadingsCount={200}
        />
      );
      expect(screen.getByTestId("previous-period-bar")).toBeInTheDocument();
    });

    it("does not render previous-period bar when previousBuckets is null", () => {
      render(<TimeInRangeBar {...baseProps} />);
      expect(screen.queryByTestId("previous-period-bar")).not.toBeInTheDocument();
    });

    it("renders previous readings count", () => {
      const prevBuckets = makeBuckets({ in_range: 65 });
      render(
        <TimeInRangeBar
          {...baseProps}
          previousBuckets={prevBuckets}
          previousReadingsCount={200}
        />
      );
      expect(screen.getByText(/prev: 200/)).toBeInTheDocument();
    });
  });

  describe("delta indicator", () => {
    it("shows positive delta when in-range improved", () => {
      // prev in_range=65, high=20 (total stays 100: 2+8+65+20+5=100)
      const prevBuckets = makeBuckets({ in_range: 65, high: 20 });
      render(
        <TimeInRangeBar
          {...baseProps}
          previousBuckets={prevBuckets}
          previousReadingsCount={200}
        />
      );
      const delta = screen.getByTestId("delta-indicator");
      expect(delta).toHaveTextContent("+5%");
    });

    it("shows negative delta when in-range decreased", () => {
      // prev in_range=80, high=5 (total stays 100: 2+8+80+5+5=100)
      const prevBuckets = makeBuckets({ in_range: 80, high: 5 });
      render(
        <TimeInRangeBar
          {...baseProps}
          previousBuckets={prevBuckets}
          previousReadingsCount={200}
        />
      );
      const delta = screen.getByTestId("delta-indicator");
      expect(delta).toHaveTextContent("-10%");
    });

    it("does not show delta when previous period is null", () => {
      render(<TimeInRangeBar {...baseProps} />);
      expect(screen.queryByTestId("delta-indicator")).not.toBeInTheDocument();
    });

    it("does not show delta when delta is zero", () => {
      const prevBuckets = makeBuckets({ in_range: 70 });
      render(
        <TimeInRangeBar
          {...baseProps}
          previousBuckets={prevBuckets}
          previousReadingsCount={200}
        />
      );
      expect(screen.queryByTestId("delta-indicator")).not.toBeInTheDocument();
    });
  });

  describe("error state", () => {
    it("shows error message with role=alert", () => {
      render(
        <TimeInRangeBar
          {...baseProps}
          error="Failed to load TIR detail"
        />
      );
      const errorMsg = screen.getByTestId("error-message");
      expect(errorMsg).toHaveTextContent("Failed to load TIR detail");
      expect(errorMsg).toHaveAttribute("role", "alert");
    });

    it("does not show bar or legend in error state", () => {
      render(
        <TimeInRangeBar
          {...baseProps}
          error="Some error"
        />
      );
      expect(screen.queryByRole("img")).not.toBeInTheDocument();
      expect(screen.queryByTestId("range-legend")).not.toBeInTheDocument();
    });
  });

  describe("no-data state", () => {
    it("shows no-data message when buckets is null", () => {
      render(
        <TimeInRangeBar
          buckets={null}
          readingsCount={0}
          previousBuckets={null}
          previousReadingsCount={null}
          error={null}
        />
      );
      expect(screen.getByTestId("no-data-message")).toBeInTheDocument();
      expect(screen.getByText(/No glucose data/)).toBeInTheDocument();
    });

    it("shows no-data message when readingsCount is 0", () => {
      render(
        <TimeInRangeBar
          buckets={defaultBuckets}
          readingsCount={0}
          previousBuckets={null}
          previousReadingsCount={null}
          error={null}
        />
      );
      expect(screen.getByTestId("no-data-message")).toBeInTheDocument();
    });
  });

  describe("legend", () => {
    it("shows 5 legend items", () => {
      render(<TimeInRangeBar {...baseProps} />);
      const legend = screen.getByTestId("range-legend");
      expect(legend).toBeInTheDocument();
      expect(screen.getByText("Urgent Low")).toBeInTheDocument();
      expect(screen.getByText("Low")).toBeInTheDocument();
      expect(screen.getByText("In Range")).toBeInTheDocument();
      expect(screen.getByText("High")).toBeInTheDocument();
      expect(screen.getByText("Urgent High")).toBeInTheDocument();
    });
  });

  describe("accessibility", () => {
    it("has region role on main render path", () => {
      render(<TimeInRangeBar {...baseProps} />);
      const region = screen.getByRole("region");
      expect(region).toHaveAttribute("aria-label", "Time in range");
    });

    it("has accessible bar with role=img", () => {
      render(<TimeInRangeBar {...baseProps} />);
      const bar = screen.getByRole("img");
      expect(bar).toBeInTheDocument();
    });

    it("has descriptive aria-label on bar", () => {
      render(<TimeInRangeBar {...baseProps} />);
      const bar = screen.getByRole("img");
      expect(bar).toHaveAttribute(
        "aria-label",
        expect.stringContaining("Time in range for 24 Hours")
      );
      expect(bar).toHaveAttribute(
        "aria-label",
        expect.stringContaining("Urgent Low")
      );
      expect(bar).toHaveAttribute(
        "aria-label",
        expect.stringContaining("In Range")
      );
    });

    it("includes target range in aria-label", () => {
      render(<TimeInRangeBar {...baseProps} targetRange="70-180 mg/dL" />);
      const bar = screen.getByRole("img");
      expect(bar).toHaveAttribute(
        "aria-label",
        expect.stringContaining("Target: 70-180 mg/dL")
      );
    });
  });

  describe("data handling", () => {
    it("sanitizes NaN values without crashing", () => {
      const badBuckets: TirBucket[] = [
        { label: "urgent_low", pct: NaN, readings: 0, threshold_low: null, threshold_high: 55 },
        { label: "low", pct: Infinity, readings: 0, threshold_low: 55, threshold_high: 70 },
        { label: "in_range", pct: -5, readings: 0, threshold_low: 70, threshold_high: 180 },
        { label: "high", pct: 200, readings: 0, threshold_low: 180, threshold_high: 250 },
        { label: "urgent_high", pct: 0, readings: 0, threshold_low: 250, threshold_high: null },
      ];
      render(
        <TimeInRangeBar
          buckets={badBuckets}
          readingsCount={100}
          previousBuckets={null}
          previousReadingsCount={null}
          error={null}
        />
      );
      expect(screen.getByTestId("time-in-range-bar")).toBeInTheDocument();
    });

    it("handles fewer than 5 buckets gracefully", () => {
      const partialBuckets: TirBucket[] = [
        { label: "low", pct: 20, readings: 50, threshold_low: 55, threshold_high: 70 },
        { label: "in_range", pct: 60, readings: 150, threshold_low: 70, threshold_high: 180 },
        { label: "high", pct: 20, readings: 50, threshold_low: 180, threshold_high: 250 },
      ];
      render(
        <TimeInRangeBar
          buckets={partialBuckets}
          readingsCount={250}
          previousBuckets={null}
          previousReadingsCount={null}
          error={null}
        />
      );
      expect(screen.getByTestId("time-in-range-bar")).toBeInTheDocument();
      const bar = screen.getByRole("img");
      const segments = bar.querySelectorAll("[title]");
      expect(segments.length).toBe(3);
    });

    it("handles buckets in non-canonical order", () => {
      const shuffledBuckets: TirBucket[] = [
        { label: "high", pct: 15, readings: 38, threshold_low: 180, threshold_high: 250 },
        { label: "urgent_low", pct: 2, readings: 5, threshold_low: null, threshold_high: 55 },
        { label: "in_range", pct: 70, readings: 175, threshold_low: 70, threshold_high: 180 },
        { label: "urgent_high", pct: 5, readings: 12, threshold_low: 250, threshold_high: null },
        { label: "low", pct: 8, readings: 20, threshold_low: 55, threshold_high: 70 },
      ];
      render(
        <TimeInRangeBar
          buckets={shuffledBuckets}
          readingsCount={250}
          previousBuckets={null}
          previousReadingsCount={null}
          error={null}
        />
      );
      expect(screen.getByTestId("time-in-range-bar")).toBeInTheDocument();
      // Should still render all 5 segments
      const bar = screen.getByRole("img");
      const segments = bar.querySelectorAll("[title]");
      expect(segments.length).toBe(5);
    });
  });

  describe("styling", () => {
    it("applies custom className", () => {
      render(<TimeInRangeBar {...baseProps} className="custom-test-class" />);
      expect(screen.getByTestId("time-in-range-bar")).toHaveClass("custom-test-class");
    });

    it("has correct base styling classes", () => {
      render(<TimeInRangeBar {...baseProps} />);
      expect(screen.getByTestId("time-in-range-bar")).toHaveClass(
        "rounded-xl",
        "border",
      );
    });
  });

  describe("animation", () => {
    it("renders with animation by default", () => {
      render(<TimeInRangeBar {...baseProps} />);
      expect(screen.getByTestId("time-in-range-bar")).toBeInTheDocument();
    });
  });

  describe("reduced motion", () => {
    it("respects prefers-reduced-motion preference", () => {
      mockUseReducedMotion.mockReturnValue(true);
      render(<TimeInRangeBar {...baseProps} />);
      expect(screen.getByTestId("time-in-range-bar")).toBeInTheDocument();
    });
  });

  describe("loading state", () => {
    it("shows skeleton when isLoading is true", () => {
      render(<TimeInRangeBar {...baseProps} isLoading={true} />);
      expect(screen.getByTestId("time-in-range-bar")).toBeInTheDocument();
      expect(screen.getByRole("region")).toHaveAttribute("aria-busy", "true");
    });

    it("does not show legend when loading", () => {
      render(<TimeInRangeBar {...baseProps} isLoading={true} />);
      expect(screen.queryByTestId("range-legend")).not.toBeInTheDocument();
    });

    it("has accessible loading label", () => {
      render(<TimeInRangeBar {...baseProps} isLoading={true} />);
      expect(screen.getByRole("region")).toHaveAttribute(
        "aria-label",
        "Loading time in range data"
      );
    });
  });

  describe("period selector", () => {
    it("renders period selector when onPeriodChange is provided", () => {
      const onChange = jest.fn();
      render(<TimeInRangeBar {...baseProps} onPeriodChange={onChange} />);
      expect(screen.getByTestId("period-selector")).toBeInTheDocument();
      expect(screen.queryByTestId("period-label")).not.toBeInTheDocument();
    });

    it("renders static label when onPeriodChange is not provided", () => {
      render(<TimeInRangeBar {...baseProps} />);
      expect(screen.getByTestId("period-label")).toBeInTheDocument();
      expect(screen.queryByTestId("period-selector")).not.toBeInTheDocument();
    });

    it("calls onPeriodChange when a period button is clicked", () => {
      const onChange = jest.fn();
      render(
        <TimeInRangeBar {...baseProps} period="24h" onPeriodChange={onChange} />
      );
      fireEvent.click(screen.getByRole("radio", { name: "7 Days" }));
      expect(onChange).toHaveBeenCalledWith("7d");
    });

    it("marks the current period as checked", () => {
      const onChange = jest.fn();
      render(
        <TimeInRangeBar {...baseProps} period="7d" onPeriodChange={onChange} />
      );
      expect(screen.getByRole("radio", { name: "7 Days" })).toHaveAttribute(
        "aria-checked",
        "true"
      );
      expect(screen.getByRole("radio", { name: "24 Hours" })).toHaveAttribute(
        "aria-checked",
        "false"
      );
    });

    it("renders all five period options", () => {
      const onChange = jest.fn();
      render(<TimeInRangeBar {...baseProps} onPeriodChange={onChange} />);
      const radios = screen.getAllByRole("radio");
      expect(radios).toHaveLength(5);
      expect(radios.map((r) => r.textContent)).toEqual([
        "24H",
        "3D",
        "7D",
        "14D",
        "30D",
      ]);
    });
  });

  describe("readings count", () => {
    it("shows readings count", () => {
      render(<TimeInRangeBar {...baseProps} />);
      expect(screen.getByText(/250 readings/)).toBeInTheDocument();
    });
  });

  describe("exports", () => {
    it("default export works", () => {
      render(<TimeInRangeBarDefault {...baseProps} />);
      expect(screen.getByTestId("time-in-range-bar")).toBeInTheDocument();
    });
  });
});
