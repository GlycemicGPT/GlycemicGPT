/**
 * useBolusReview Hook Tests
 *
 * Story 30.7: Tests for the bolus review data fetching hook.
 */

import { renderHook, act, waitFor } from "@testing-library/react";
import {
  useBolusReview,
  type BolusReviewPeriod,
  BOLUS_PERIOD_LABELS,
} from "@/hooks/use-bolus-review";
import { getBolusReview, type BolusReviewResponse } from "@/lib/api";

jest.mock("@/lib/api", () => ({
  getBolusReview: jest.fn(),
}));

const mockGetBolusReview = getBolusReview as jest.MockedFunction<
  typeof getBolusReview
>;

function makeResponse(overrides?: Partial<BolusReviewResponse>): BolusReviewResponse {
  return {
    boluses: [
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
    ],
    total_count: 2,
    period_days: 7,
    ...overrides,
  };
}

beforeEach(() => {
  jest.clearAllMocks();
  mockGetBolusReview.mockResolvedValue(makeResponse());
});

describe("useBolusReview", () => {
  it("fetches data on mount with default 7d period", async () => {
    const { result } = renderHook(() => useBolusReview());

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    expect(mockGetBolusReview).toHaveBeenCalledWith(7, 100, 0);
    expect(result.current.data).not.toBeNull();
    expect(result.current.data!.boluses).toHaveLength(2);
    expect(result.current.error).toBeNull();
    expect(result.current.period).toBe("7d");
  });

  it("maps each period to correct days", async () => {
    const periods: [BolusReviewPeriod, number][] = [
      ["1d", 1],
      ["3d", 3],
      ["7d", 7],
      ["14d", 14],
    ];

    for (const [period, expectedDays] of periods) {
      mockGetBolusReview.mockClear();
      mockGetBolusReview.mockResolvedValue(makeResponse());

      const { result } = renderHook(() => useBolusReview(period));

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      expect(mockGetBolusReview).toHaveBeenCalledWith(expectedDays, 100, 0);
    }
  });

  it("refetches when period changes", async () => {
    const { result } = renderHook(() => useBolusReview("7d"));

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    expect(mockGetBolusReview).toHaveBeenCalledTimes(1);

    act(() => {
      result.current.setPeriod("14d");
    });

    await waitFor(() => {
      expect(mockGetBolusReview).toHaveBeenCalledTimes(2);
    });

    expect(mockGetBolusReview).toHaveBeenLastCalledWith(14, 100, 0);
  });

  it("handles API errors gracefully", async () => {
    mockGetBolusReview.mockRejectedValueOnce(
      new Error("Server error")
    );

    const { result } = renderHook(() => useBolusReview());

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    expect(result.current.error).toBe("Server error");
    expect(result.current.data).toBeNull();
  });

  it("handles non-Error thrown values", async () => {
    mockGetBolusReview.mockRejectedValueOnce(42);

    const { result } = renderHook(() => useBolusReview());

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    expect(result.current.error).toBe("Failed to load bolus review");
  });

  it("clears data on period change to avoid stale display", async () => {
    const { result } = renderHook(() => useBolusReview("7d"));

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    expect(result.current.data).not.toBeNull();

    mockGetBolusReview.mockReturnValueOnce(
      new Promise(() => {}) as never
    );

    act(() => {
      result.current.setPeriod("14d");
    });

    expect(result.current.data).toBeNull();
    expect(result.current.isLoading).toBe(true);
  });

  it("discards stale fetch results when period changes rapidly", async () => {
    let resolveFirst: (value: unknown) => void;
    const firstPromise = new Promise((resolve) => {
      resolveFirst = resolve;
    });

    mockGetBolusReview
      .mockReturnValueOnce(firstPromise as never)
      .mockResolvedValueOnce(makeResponse({ period_days: 14 }));

    const { result } = renderHook(() => useBolusReview("7d"));

    act(() => {
      result.current.setPeriod("14d");
    });

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    resolveFirst!(makeResponse({ period_days: 7 }));

    expect(result.current.data!.period_days).toBe(14);
  });

  it("starts in loading state", () => {
    const { result } = renderHook(() => useBolusReview());
    expect(result.current.isLoading).toBe(true);
  });

  it("exposes a refetch function", async () => {
    const { result } = renderHook(() => useBolusReview());

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    expect(mockGetBolusReview).toHaveBeenCalledTimes(1);

    act(() => {
      result.current.refetch();
    });

    await waitFor(() => {
      expect(mockGetBolusReview).toHaveBeenCalledTimes(2);
    });
  });

  it("exports BOLUS_PERIOD_LABELS with correct values", () => {
    expect(BOLUS_PERIOD_LABELS["1d"]).toBe("1 Day");
    expect(BOLUS_PERIOD_LABELS["3d"]).toBe("3 Days");
    expect(BOLUS_PERIOD_LABELS["7d"]).toBe("7 Days");
    expect(BOLUS_PERIOD_LABELS["14d"]).toBe("14 Days");
  });
});
