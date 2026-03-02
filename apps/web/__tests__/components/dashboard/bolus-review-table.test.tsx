/**
 * Tests for the BolusReviewTable component.
 *
 * Story 30.7: Bolus review table with period selector.
 */

import { render, screen, fireEvent } from "@testing-library/react";
import {
  BolusReviewTable,
  type BolusReviewTableProps,
} from "../../../src/components/dashboard/bolus-review-table";

// --- Mocks ---

const mockSetPeriod = jest.fn();
const mockRefetch = jest.fn();
let mockHookReturn: {
  data: {
    boluses: Array<{
      event_timestamp: string;
      units: number;
      is_automated: boolean;
      control_iq_reason: string | null;
      control_iq_mode: string | null;
      iob_at_event: number | null;
      bg_at_event: number | null;
    }>;
    total_count: number;
    period_days: number;
  } | null;
  isLoading: boolean;
  error: string | null;
  period: "1d" | "3d" | "7d" | "14d";
  setPeriod: typeof mockSetPeriod;
  refetch: typeof mockRefetch;
};

jest.mock("../../../src/hooks/use-bolus-review", () => ({
  useBolusReview: () => mockHookReturn,
  BOLUS_PERIOD_LABELS: {
    "1d": "1 Day",
    "3d": "3 Days",
    "7d": "7 Days",
    "14d": "14 Days",
  },
}));

// --- Helpers ---

function makeBoluses() {
  return [
    {
      event_timestamp: "2026-03-01T14:30:00Z",
      units: 3.5,
      is_automated: false,
      control_iq_reason: null,
      control_iq_mode: null,
      iob_at_event: 2.1,
      bg_at_event: 185,
    },
    {
      event_timestamp: "2026-03-01T12:00:00Z",
      units: 0.8,
      is_automated: true,
      control_iq_reason: "Correction",
      control_iq_mode: "Auto",
      iob_at_event: 1.5,
      bg_at_event: 210,
    },
    {
      event_timestamp: "2026-03-01T09:15:00Z",
      units: 5.0,
      is_automated: false,
      control_iq_reason: null,
      control_iq_mode: null,
      iob_at_event: null,
      bg_at_event: null,
    },
  ];
}

function makeData(overrides?: Record<string, unknown>) {
  return {
    boluses: makeBoluses(),
    total_count: 3,
    period_days: 7,
    ...overrides,
  };
}

function renderComponent(props: Partial<BolusReviewTableProps> = {}) {
  return render(<BolusReviewTable {...props} />);
}

// --- Tests ---

beforeEach(() => {
  jest.clearAllMocks();
  mockHookReturn = {
    data: null,
    isLoading: false,
    error: null,
    period: "7d",
    setPeriod: mockSetPeriod,
    refetch: mockRefetch,
  };
});

describe("BolusReviewTable", () => {
  describe("loading state", () => {
    it("renders loading skeleton with aria-busy", () => {
      mockHookReturn.isLoading = true;
      renderComponent();
      const el = screen.getByTestId("bolus-review");
      expect(el).toHaveAttribute("aria-busy", "true");
    });

    it("shows skeleton rows", () => {
      mockHookReturn.isLoading = true;
      renderComponent();
      const skeletons = screen.getByTestId("bolus-review").querySelectorAll(".animate-pulse");
      expect(skeletons.length).toBeGreaterThan(0);
    });

    it("has correct test id", () => {
      mockHookReturn.isLoading = true;
      renderComponent();
      expect(screen.getByTestId("bolus-review")).toBeInTheDocument();
    });
  });

  describe("error state", () => {
    it("shows error message", () => {
      mockHookReturn.error = "Server error";
      renderComponent();
      expect(
        screen.getByText("Failed to load bolus data.")
      ).toBeInTheDocument();
    });

    it("shows error detail text", () => {
      mockHookReturn.error = "Server error";
      renderComponent();
      expect(screen.getByText("Server error")).toBeInTheDocument();
    });

    it("shows a retry button", () => {
      mockHookReturn.error = "Server error";
      renderComponent();
      const retryButton = screen.getByRole("button", { name: /retry/i });
      expect(retryButton).toBeInTheDocument();
    });

    it("calls refetch when retry button is clicked", () => {
      mockHookReturn.error = "Server error";
      renderComponent();
      fireEvent.click(screen.getByRole("button", { name: /retry/i }));
      expect(mockRefetch).toHaveBeenCalledTimes(1);
    });

    it("shows period selector in error state", () => {
      mockHookReturn.error = "Server error";
      renderComponent();
      expect(
        screen.getByRole("radiogroup", { name: /bolus review time period/i })
      ).toBeInTheDocument();
    });
  });

  describe("no-data state", () => {
    it("shows no-data message when data is null", () => {
      mockHookReturn.data = null;
      renderComponent();
      expect(
        screen.getByText("No bolus events recorded for this period.")
      ).toBeInTheDocument();
    });

    it("shows no-data message when boluses array is empty", () => {
      mockHookReturn.data = makeData({ boluses: [], total_count: 0 });
      renderComponent();
      expect(
        screen.getByText("No bolus events recorded for this period.")
      ).toBeInTheDocument();
    });
  });

  describe("data rendering", () => {
    beforeEach(() => {
      mockHookReturn.data = makeData();
    });

    it("renders table headers", () => {
      renderComponent();
      expect(screen.getByText("Time")).toBeInTheDocument();
      expect(screen.getByText("Units")).toBeInTheDocument();
      expect(screen.getByText("Type")).toBeInTheDocument();
      expect(screen.getByText("BG")).toBeInTheDocument();
      expect(screen.getByText("IoB")).toBeInTheDocument();
      expect(screen.getByText("Reason")).toBeInTheDocument();
    });

    it("renders bolus rows", () => {
      renderComponent();
      expect(screen.getByText("3.50 U")).toBeInTheDocument();
      expect(screen.getByText("0.80 U")).toBeInTheDocument();
      expect(screen.getByText("5.00 U")).toBeInTheDocument();
    });

    it("shows Manual badge for non-automated boluses", () => {
      renderComponent();
      const manualBadges = screen.getAllByText("Manual");
      expect(manualBadges.length).toBe(2);
    });

    it("shows Auto badge for automated boluses", () => {
      renderComponent();
      expect(screen.getByText("Auto")).toBeInTheDocument();
    });

    it("displays BG values where available", () => {
      renderComponent();
      expect(screen.getByText("185 mg/dL")).toBeInTheDocument();
      expect(screen.getByText("210 mg/dL")).toBeInTheDocument();
    });

    it("displays --- for null BG values", () => {
      renderComponent();
      // Third bolus has null bg_at_event -- look for --- in BG column
      const dashes = screen.getAllByText("---");
      expect(dashes.length).toBeGreaterThanOrEqual(2); // null BG + null IoB
    });

    it("displays IoB values where available", () => {
      renderComponent();
      expect(screen.getByText("2.1 U")).toBeInTheDocument();
      expect(screen.getByText("1.5 U")).toBeInTheDocument();
    });

    it("displays Control-IQ reason for automated boluses", () => {
      renderComponent();
      expect(screen.getByText("Correction")).toBeInTheDocument();
    });

    it("shows heading text", () => {
      renderComponent();
      expect(screen.getByText("Recent Boluses")).toBeInTheDocument();
    });

    it("shows truncation notice when total > displayed", () => {
      mockHookReturn.data = makeData({ total_count: 150 });
      renderComponent();
      expect(screen.getByText(/Showing 3 of 150 bolus events/)).toBeInTheDocument();
    });

    it("does not show truncation notice when all displayed", () => {
      renderComponent();
      expect(screen.queryByText(/Showing/)).not.toBeInTheDocument();
    });
  });

  describe("period selector", () => {
    beforeEach(() => {
      mockHookReturn.data = makeData();
    });

    it("renders all 4 period options", () => {
      renderComponent();
      expect(screen.getByRole("radio", { name: "1 Day" })).toBeInTheDocument();
      expect(screen.getByRole("radio", { name: "3 Days" })).toBeInTheDocument();
      expect(screen.getByRole("radio", { name: "7 Days" })).toBeInTheDocument();
      expect(screen.getByRole("radio", { name: "14 Days" })).toBeInTheDocument();
    });

    it("marks the active period as checked", () => {
      renderComponent();
      expect(screen.getByRole("radio", { name: "7 Days" })).toHaveAttribute(
        "aria-checked",
        "true"
      );
      expect(screen.getByRole("radio", { name: "1 Day" })).toHaveAttribute(
        "aria-checked",
        "false"
      );
    });

    it("calls setPeriod when clicking a period button", () => {
      renderComponent();
      fireEvent.click(screen.getByRole("radio", { name: "14 Days" }));
      expect(mockSetPeriod).toHaveBeenCalledWith("14d");
    });
  });

  describe("className prop", () => {
    it("applies custom className", () => {
      mockHookReturn.data = makeData();
      renderComponent({ className: "custom-class" });
      expect(screen.getByTestId("bolus-review")).toHaveClass("custom-class");
    });
  });
});
