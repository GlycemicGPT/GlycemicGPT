/**
 * useInsulinSummary Hook Tests
 *
 * Story 30.7: Tests for the insulin summary data fetching hook.
 */

import { renderHook, act, waitFor } from "@testing-library/react";
import {
  useInsulinSummary,
  type InsulinPeriod,
  INSULIN_PERIOD_LABELS,
} from "@/hooks/use-insulin-summary";
import { getInsulinSummary, type InsulinSummaryResponse } from "@/lib/api";

jest.mock("@/lib/api", () => ({
  getInsulinSummary: jest.fn(),
}));

const mockGetInsulinSummary = getInsulinSummary as jest.MockedFunction<
  typeof getInsulinSummary
>;

function makeResponse(overrides?: Partial<InsulinSummaryResponse>): InsulinSummaryResponse {
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

beforeEach(() => {
  jest.clearAllMocks();
  mockGetInsulinSummary.mockResolvedValue(makeResponse());
});

describe("useInsulinSummary", () => {
  it("fetches data on mount with default 14d period", async () => {
    const { result } = renderHook(() => useInsulinSummary());

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    expect(mockGetInsulinSummary).toHaveBeenCalledWith(14);
    expect(result.current.data).not.toBeNull();
    expect(result.current.data!.tdd).toBe(42.5);
    expect(result.current.error).toBeNull();
    expect(result.current.period).toBe("14d");
  });

  it("maps each period to correct days", async () => {
    const periods: [InsulinPeriod, number][] = [
      ["7d", 7],
      ["14d", 14],
      ["30d", 30],
      ["90d", 90],
    ];

    for (const [period, expectedDays] of periods) {
      mockGetInsulinSummary.mockClear();
      mockGetInsulinSummary.mockResolvedValue(makeResponse());

      const { result } = renderHook(() => useInsulinSummary(period));

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      expect(mockGetInsulinSummary).toHaveBeenCalledWith(expectedDays);
    }
  });

  it("refetches when period changes", async () => {
    const { result } = renderHook(() => useInsulinSummary("14d"));

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    expect(mockGetInsulinSummary).toHaveBeenCalledTimes(1);

    act(() => {
      result.current.setPeriod("30d");
    });

    await waitFor(() => {
      expect(mockGetInsulinSummary).toHaveBeenCalledTimes(2);
    });

    expect(mockGetInsulinSummary).toHaveBeenLastCalledWith(30);
  });

  it("handles API errors gracefully", async () => {
    mockGetInsulinSummary.mockRejectedValueOnce(
      new Error("Network failure")
    );

    const { result } = renderHook(() => useInsulinSummary());

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    expect(result.current.error).toBe("Network failure");
    expect(result.current.data).toBeNull();
  });

  it("handles non-Error thrown values", async () => {
    mockGetInsulinSummary.mockRejectedValueOnce("string error");

    const { result } = renderHook(() => useInsulinSummary());

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    expect(result.current.error).toBe("Failed to load insulin summary");
  });

  it("clears data on period change to avoid stale display", async () => {
    const { result } = renderHook(() => useInsulinSummary("14d"));

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    expect(result.current.data).not.toBeNull();

    mockGetInsulinSummary.mockReturnValueOnce(
      new Promise(() => {}) as never
    );

    act(() => {
      result.current.setPeriod("30d");
    });

    expect(result.current.data).toBeNull();
    expect(result.current.isLoading).toBe(true);
  });

  it("discards stale fetch results when period changes rapidly", async () => {
    let resolveFirst: (value: unknown) => void;
    const firstPromise = new Promise((resolve) => {
      resolveFirst = resolve;
    });

    mockGetInsulinSummary
      .mockReturnValueOnce(firstPromise as never)
      .mockResolvedValueOnce(makeResponse({ period_days: 30 }));

    const { result } = renderHook(() => useInsulinSummary("14d"));

    act(() => {
      result.current.setPeriod("30d");
    });

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    resolveFirst!(makeResponse({ period_days: 14 }));

    expect(result.current.data!.period_days).toBe(30);
  });

  it("starts in loading state", () => {
    const { result } = renderHook(() => useInsulinSummary());
    expect(result.current.isLoading).toBe(true);
  });

  it("exposes a refetch function", async () => {
    const { result } = renderHook(() => useInsulinSummary());

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    expect(mockGetInsulinSummary).toHaveBeenCalledTimes(1);

    act(() => {
      result.current.refetch();
    });

    await waitFor(() => {
      expect(mockGetInsulinSummary).toHaveBeenCalledTimes(2);
    });
  });

  it("exports INSULIN_PERIOD_LABELS with correct values", () => {
    expect(INSULIN_PERIOD_LABELS["7d"]).toBe("7 Days");
    expect(INSULIN_PERIOD_LABELS["14d"]).toBe("14 Days");
    expect(INSULIN_PERIOD_LABELS["30d"]).toBe("30 Days");
    expect(INSULIN_PERIOD_LABELS["90d"]).toBe("90 Days");
  });
});
