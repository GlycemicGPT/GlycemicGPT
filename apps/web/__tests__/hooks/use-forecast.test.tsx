/**
 * useForecast Hook Tests (Story 43.12 PR 4)
 *
 * Covers:
 * - Initial fetch on mount
 * - Refetch when refreshKey changes
 * - `refresh()` after a write
 * - Race-prevention (gen counter) so stale responses don't clobber
 *   newer state when the refreshKey changes mid-flight
 * - Error path preserves previous forecast so the chart doesn't
 *   flicker the dotted line away on a transient blip
 */

import { renderHook, waitFor, act } from "@testing-library/react";
import { useForecast } from "@/hooks/use-forecast";
import { getForecast, type ForecastReadResponse } from "@/lib/api";

jest.mock("@/lib/api", () => ({
  getForecast: jest.fn(),
}));

const mockGetForecast = getForecast as jest.MockedFunction<typeof getForecast>;

function makeResponse(
  overrides: Partial<ForecastReadResponse> = {}
): ForecastReadResponse {
  return {
    source_preference: "auto",
    effective_source: "loop",
    available_sources: ["loop"],
    forecast: {
      source_engine: "loop",
      source_uploader: "Loop",
      issued_at: "2026-05-15T12:00:00Z",
      start_at: "2026-05-15T12:00:00Z",
      step_minutes: 5,
      horizon_minutes: 180,
      curves_mgdl: { main: [120, 125, 130] },
      default_curve_name: "main",
    },
    forecast_unavailable_reason: null,
    ...overrides,
  };
}

beforeEach(() => {
  jest.clearAllMocks();
  mockGetForecast.mockResolvedValue(makeResponse());
});

describe("useForecast", () => {
  it("fetches on mount and exposes the response", async () => {
    const { result } = renderHook(() => useForecast());

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    expect(mockGetForecast).toHaveBeenCalledTimes(1);
    expect(result.current.forecast?.effective_source).toBe("loop");
    expect(result.current.error).toBeNull();
  });

  it("refetches when refreshKey changes", async () => {
    const { result, rerender } = renderHook(
      ({ key }: { key: number }) => useForecast(key),
      { initialProps: { key: 0 } }
    );

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(mockGetForecast).toHaveBeenCalledTimes(1);

    rerender({ key: 1 });
    await waitFor(() => expect(mockGetForecast).toHaveBeenCalledTimes(2));
  });

  it("refresh() forces a re-read", async () => {
    const { result } = renderHook(() => useForecast());
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await act(async () => {
      await result.current.refresh();
    });

    expect(mockGetForecast).toHaveBeenCalledTimes(2);
  });

  it("preserves previous forecast on error so the chart doesn't flicker", async () => {
    const { result, rerender } = renderHook(
      ({ key }: { key: number }) => useForecast(key),
      { initialProps: { key: 0 } }
    );

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.forecast?.effective_source).toBe("loop");

    mockGetForecast.mockRejectedValueOnce(new Error("network blip"));
    rerender({ key: 1 });

    await waitFor(() => expect(result.current.error).not.toBeNull());
    // Forecast is preserved -- chart keeps drawing the previous overlay
    expect(result.current.forecast?.effective_source).toBe("loop");
  });

  it("ignores stale responses when a newer fetch supersedes them", async () => {
    let resolveFirst: (v: ForecastReadResponse) => void = () => {};
    const firstPromise = new Promise<ForecastReadResponse>((resolve) => {
      resolveFirst = resolve;
    });
    mockGetForecast
      .mockReturnValueOnce(firstPromise)
      .mockResolvedValueOnce(makeResponse({ effective_source: "aaps" }));

    const { result, rerender } = renderHook(
      ({ key }: { key: number }) => useForecast(key),
      { initialProps: { key: 0 } }
    );

    // Trigger a second fetch before the first resolves
    rerender({ key: 1 });
    await waitFor(() =>
      expect(result.current.forecast?.effective_source).toBe("aaps")
    );

    // Now resolve the stale first request -- it must NOT overwrite "aaps"
    await act(async () => {
      resolveFirst(makeResponse({ effective_source: "loop" }));
      await Promise.resolve();
    });

    expect(result.current.forecast?.effective_source).toBe("aaps");
  });
});
