/**
 * Tests for the InsulinSummaryStats component.
 *
 * Story 30.7: Insulin summary stats panel with period selector.
 */

import { render, screen, fireEvent } from "@testing-library/react";
import {
  InsulinSummaryStats,
  type InsulinSummaryStatsProps,
} from "../../../src/components/dashboard/insulin-summary-stats";

// --- Mocks ---

const mockSetPeriod = jest.fn();
const mockRefetch = jest.fn();
let mockHookReturn: {
  data: {
    tdd: number;
    basal_units: number;
    bolus_units: number;
    correction_units: number;
    basal_pct: number;
    bolus_pct: number;
    bolus_count: number;
    correction_count: number;
    period_days: number;
  } | null;
  isLoading: boolean;
  error: string | null;
  period: "24h" | "3d" | "7d" | "14d" | "30d" | "90d";
  setPeriod: typeof mockSetPeriod;
  refetch: typeof mockRefetch;
};

jest.mock("../../../src/hooks/use-insulin-summary", () => ({
  useInsulinSummary: () => mockHookReturn,
  INSULIN_PERIOD_LABELS: {
    "24h": "24 Hours",
    "3d": "3 Days",
    "7d": "7 Days",
    "14d": "14 Days",
    "30d": "30 Days",
    "90d": "90 Days",
  },
}));

// --- Helpers ---

function makeData(overrides?: Record<string, unknown>) {
  return {
    tdd: 42.5,
    basal_units: 22.0,
    bolus_units: 20.5,
    correction_units: 5.2,
    basal_pct: 51.8,
    bolus_pct: 48.2,
    bolus_count: 56,
    correction_count: 14,
    period_days: 14,
    ...overrides,
  };
}

function renderComponent(props: Partial<InsulinSummaryStatsProps> = {}) {
  return render(<InsulinSummaryStats {...props} />);
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

describe("InsulinSummaryStats", () => {
  describe("loading state", () => {
    it("renders loading skeleton with aria-busy", () => {
      mockHookReturn.isLoading = true;
      renderComponent();
      const el = screen.getByTestId("insulin-summary");
      expect(el).toHaveAttribute("aria-busy", "true");
    });

    it("shows 6 skeleton placeholders", () => {
      mockHookReturn.isLoading = true;
      renderComponent();
      const skeletons = screen.getByTestId("insulin-summary").querySelectorAll(".animate-pulse");
      expect(skeletons).toHaveLength(6);
    });

    it("has correct test id", () => {
      mockHookReturn.isLoading = true;
      renderComponent();
      expect(screen.getByTestId("insulin-summary")).toBeInTheDocument();
    });
  });

  describe("error state", () => {
    it("shows error message", () => {
      mockHookReturn.error = "Network error";
      renderComponent();
      expect(
        screen.getByText("Failed to load insulin summary.")
      ).toBeInTheDocument();
    });

    it("shows error detail text", () => {
      mockHookReturn.error = "Network error";
      renderComponent();
      expect(screen.getByText("Network error")).toBeInTheDocument();
    });

    it("shows a retry button", () => {
      mockHookReturn.error = "Network error";
      renderComponent();
      const retryButton = screen.getByRole("button", { name: /retry/i });
      expect(retryButton).toBeInTheDocument();
    });

    it("calls refetch when retry button is clicked", () => {
      mockHookReturn.error = "Network error";
      renderComponent();
      fireEvent.click(screen.getByRole("button", { name: /retry/i }));
      expect(mockRefetch).toHaveBeenCalledTimes(1);
    });

    it("shows period selector in error state", () => {
      mockHookReturn.error = "Network error";
      renderComponent();
      expect(
        screen.getByRole("radiogroup", { name: /insulin summary time period/i })
      ).toBeInTheDocument();
    });
  });

  describe("no-data state", () => {
    it("shows no-data message when data is null", () => {
      mockHookReturn.data = null;
      renderComponent();
      expect(
        screen.getByText("No insulin delivery data available for this period.")
      ).toBeInTheDocument();
    });

    it("shows no-data message when TDD is 0", () => {
      mockHookReturn.data = makeData({ tdd: 0 });
      renderComponent();
      expect(
        screen.getByText("No insulin delivery data available for this period.")
      ).toBeInTheDocument();
    });
  });

  describe("data rendering", () => {
    beforeEach(() => {
      mockHookReturn.data = makeData();
    });

    it("renders all 6 stat cards", () => {
      renderComponent();
      expect(screen.getByText("TDD")).toBeInTheDocument();
      expect(screen.getByText("Basal")).toBeInTheDocument();
      expect(screen.getByText("Bolus")).toBeInTheDocument();
      expect(screen.getByText("Corrections")).toBeInTheDocument();
      expect(screen.getByText("Bolus Count")).toBeInTheDocument();
      expect(screen.getByText("Correction Count")).toBeInTheDocument();
    });

    it("displays TDD value with correct formatting", () => {
      renderComponent();
      expect(screen.getByText("42.5")).toBeInTheDocument();
      expect(screen.getByText("U/day")).toBeInTheDocument();
    });

    it("displays basal units with percentage", () => {
      renderComponent();
      expect(screen.getByText("22.0 U")).toBeInTheDocument();
      expect(screen.getByText("52% of TDD")).toBeInTheDocument();
    });

    it("displays bolus units with percentage and split assessment", () => {
      renderComponent();
      expect(screen.getByText("20.5 U")).toBeInTheDocument();
      // 51.8% basal is balanced (40-60%)
      expect(screen.getByText(/48% of TDD/)).toBeInTheDocument();
      expect(screen.getByText(/Balanced/)).toBeInTheDocument();
    });

    it("displays correction units", () => {
      renderComponent();
      expect(screen.getByText("5.2 U")).toBeInTheDocument();
    });

    it("displays bolus count with per-day average", () => {
      renderComponent();
      expect(screen.getByText("56")).toBeInTheDocument();
      expect(screen.getByText("4.0/day avg")).toBeInTheDocument();
    });

    it("displays correction count with per-day average", () => {
      renderComponent();
      expect(screen.getByText("14")).toBeInTheDocument();
      expect(screen.getByText("1.0/day avg")).toBeInTheDocument();
    });

    it("shows heading text with period", () => {
      renderComponent();
      expect(screen.getByText("Insulin Summary")).toBeInTheDocument();
      expect(screen.getByText("14 Days")).toBeInTheDocument();
    });
  });

  describe("basal/bolus split assessment", () => {
    it("shows Balanced for 40-60% basal", () => {
      mockHookReturn.data = makeData({ basal_pct: 50, bolus_pct: 50 });
      renderComponent();
      expect(screen.getByText(/Balanced/)).toBeInTheDocument();
    });

    it("shows Moderate for 30-40% basal", () => {
      mockHookReturn.data = makeData({ basal_pct: 35, bolus_pct: 65 });
      renderComponent();
      expect(screen.getByText(/Moderate/)).toBeInTheDocument();
    });

    it("shows Moderate for 60-70% basal", () => {
      mockHookReturn.data = makeData({ basal_pct: 65, bolus_pct: 35 });
      renderComponent();
      expect(screen.getByText(/Moderate/)).toBeInTheDocument();
    });

    it("shows Review for <30% basal", () => {
      mockHookReturn.data = makeData({ basal_pct: 25, bolus_pct: 75 });
      renderComponent();
      expect(screen.getByText(/Review/)).toBeInTheDocument();
    });

    it("shows Review for >70% basal", () => {
      mockHookReturn.data = makeData({ basal_pct: 75, bolus_pct: 25 });
      renderComponent();
      expect(screen.getByText(/Review/)).toBeInTheDocument();
    });
  });

  describe("period selector", () => {
    beforeEach(() => {
      mockHookReturn.data = makeData();
    });

    it("renders all 6 period options", () => {
      renderComponent();
      expect(screen.getByRole("radio", { name: "24 Hours" })).toBeInTheDocument();
      expect(screen.getByRole("radio", { name: "3 Days" })).toBeInTheDocument();
      expect(screen.getByRole("radio", { name: "7 Days" })).toBeInTheDocument();
      expect(screen.getByRole("radio", { name: "14 Days" })).toBeInTheDocument();
      expect(screen.getByRole("radio", { name: "30 Days" })).toBeInTheDocument();
      expect(screen.getByRole("radio", { name: "90 Days" })).toBeInTheDocument();
    });

    it("marks the active period as checked", () => {
      renderComponent();
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
      renderComponent();
      fireEvent.click(screen.getByRole("radio", { name: "30 Days" }));
      expect(mockSetPeriod).toHaveBeenCalledWith("30d");
    });
  });

  describe("className prop", () => {
    it("applies custom className", () => {
      mockHookReturn.data = makeData();
      renderComponent({ className: "custom-class" });
      expect(screen.getByTestId("insulin-summary")).toHaveClass("custom-class");
    });
  });
});
