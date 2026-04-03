/**
 * useGlucosePercentiles Hook Tests
 *
 * Story 30.5: Tests for the AGP percentile data fetching hook.
 */

import { renderHook, act, waitFor } from "@testing-library/react";
import {
  useGlucosePercentiles,
  type AgpPeriod,
  AGP_PERIOD_LABELS,
} from "@/hooks/use-glucose-percentiles";
import { getGlucosePercentiles, type GlucosePercentilesResponse } from "@/lib/api";

jest.mock("@/lib/api", () => ({
  getGlucosePercentiles: jest.fn(),
}));

const mockGetGlucosePercentiles = getGlucosePercentiles as jest.MockedFunction<
  typeof getGlucosePercentiles
>;

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

function makeResponse(overrides?: Partial<GlucosePercentilesResponse>) {
  return {
    buckets: makeBuckets(),
    period_days: 14,
    readings_count: 1200,
    is_truncated: false,
    ...overrides,
  };
}

beforeEach(() => {
  jest.clearAllMocks();
  mockGetGlucosePercentiles.mockResolvedValue(makeResponse());
});

describe("useGlucosePercentiles", () => {
  it("fetches data on mount with default 14d period", async () => {
    const { result } = renderHook(() => useGlucosePercentiles());

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    expect(mockGetGlucosePercentiles).toHaveBeenCalledWith(14);
    expect(result.current.data).not.toBeNull();
    expect(result.current.data!.buckets).toHaveLength(24);
    expect(result.current.error).toBeNull();
    expect(result.current.period).toBe("14d");
  });

  it("maps each period to correct days", async () => {
    const periods: [AgpPeriod, number][] = [
      ["7d", 7],
      ["14d", 14],
      ["30d", 30],
      ["90d", 90],
    ];

    for (const [period, expectedDays] of periods) {
      mockGetGlucosePercentiles.mockClear();
      mockGetGlucosePercentiles.mockResolvedValue(makeResponse());

      const { result } = renderHook(() => useGlucosePercentiles(period));

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      expect(mockGetGlucosePercentiles).toHaveBeenCalledWith(expectedDays);
    }
  });

  it("refetches when period changes", async () => {
    const { result } = renderHook(() => useGlucosePercentiles("14d"));

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    expect(mockGetGlucosePercentiles).toHaveBeenCalledTimes(1);

    act(() => {
      result.current.setPeriod("30d");
    });

    await waitFor(() => {
      expect(mockGetGlucosePercentiles).toHaveBeenCalledTimes(2);
    });

    expect(mockGetGlucosePercentiles).toHaveBeenLastCalledWith(30);
  });

  it("handles API errors gracefully", async () => {
    mockGetGlucosePercentiles.mockRejectedValueOnce(
      new Error("Network failure")
    );

    const { result } = renderHook(() => useGlucosePercentiles());

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    expect(result.current.error).toBe("Network failure");
    expect(result.current.data).toBeNull();
  });

  it("handles non-Error thrown values", async () => {
    mockGetGlucosePercentiles.mockRejectedValueOnce("string error");

    const { result } = renderHook(() => useGlucosePercentiles());

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    expect(result.current.error).toBe("Failed to load AGP data");
  });

  it("clears data on period change to avoid stale display", async () => {
    const { result } = renderHook(() => useGlucosePercentiles("14d"));

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    expect(result.current.data).not.toBeNull();

    // Use a slow-resolving promise for the next fetch
    mockGetGlucosePercentiles.mockReturnValueOnce(
      new Promise(() => {}) as never
    );

    act(() => {
      result.current.setPeriod("30d");
    });

    // Data should be cleared immediately while loading
    expect(result.current.data).toBeNull();
    expect(result.current.isLoading).toBe(true);
  });

  it("discards stale fetch results when period changes rapidly", async () => {
    let resolveFirst: (value: unknown) => void;
    const firstPromise = new Promise((resolve) => {
      resolveFirst = resolve;
    });

    mockGetGlucosePercentiles
      .mockReturnValueOnce(firstPromise as never)
      .mockResolvedValueOnce(makeResponse({ period_days: 30 }));

    const { result } = renderHook(() => useGlucosePercentiles("14d"));

    // Immediately switch period before first fetch resolves
    act(() => {
      result.current.setPeriod("30d");
    });

    // Wait for the second (30d) fetch to complete
    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    // Now resolve the first (stale) fetch
    resolveFirst!(makeResponse({ period_days: 14 }));

    // Should have data from the 30d fetch, not stale 14d
    expect(result.current.data!.period_days).toBe(30);
  });

  it("starts in loading state", () => {
    const { result } = renderHook(() => useGlucosePercentiles());
    expect(result.current.isLoading).toBe(true);
  });

  it("exposes a refetch function", async () => {
    const { result } = renderHook(() => useGlucosePercentiles());

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    expect(mockGetGlucosePercentiles).toHaveBeenCalledTimes(1);

    act(() => {
      result.current.refetch();
    });

    await waitFor(() => {
      expect(mockGetGlucosePercentiles).toHaveBeenCalledTimes(2);
    });
  });

  it("exports AGP_PERIOD_LABELS with correct values", () => {
    expect(AGP_PERIOD_LABELS["7d"]).toBe("7 Days");
    expect(AGP_PERIOD_LABELS["14d"]).toBe("14 Days");
    expect(AGP_PERIOD_LABELS["30d"]).toBe("30 Days");
    expect(AGP_PERIOD_LABELS["90d"]).toBe("90 Days");
  });
});
