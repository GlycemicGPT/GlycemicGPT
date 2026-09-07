import { StrictMode, type ReactNode } from "react";
import { act, render, renderHook, screen } from "@testing-library/react";
import uPlot from "uplot";
import {
  DashboardTimeRangeProvider,
  useDashboardTimeRange,
} from "@/components/DashboardTimeRangeProvider";
import { useDashboardLiveRefresh } from "@/hooks/use-dashboard-live-refresh";
import { useGlucoseHistory } from "@/hooks/use-glucose-history";
import { getGlucoseHistoryByDateRange, type GlucoseHistoryReading } from "@/lib/api";
import { GlucoseTrendChart } from "@/components/GlucoseTrendChart";
import { MergedGlucoseTrendChart } from "@/components/MergedGlucoseTrendChart";

jest.mock("@/lib/api", () => ({
  getGlucoseHistory: jest.fn(),
  getGlucoseHistoryByDateRange: jest.fn(),
  getBolusReviewByDateRange: jest.fn(async () => ({ boluses: [], total_count: 0 })),
  getPumpEventHistory: jest.fn(async () => ({ events: [], count: 0 })),
}));

jest.mock("uplot", () => ({
  __esModule: true,
  default: jest.fn().mockImplementation(() => ({ destroy: jest.fn() })),
}));

const getHistory = jest.mocked(getGlucoseHistoryByDateRange);
const START = new Date("2026-09-06T10:00:00.000Z");
const FIVE_MINUTES = 5 * 60_000;

/** Exercise refresh effects with the real time-range provider and Strict Mode replay. */
function Wrapper({ children }: { children: ReactNode }) {
  return (
    <StrictMode>
      <DashboardTimeRangeProvider>{children}</DashboardTimeRangeProvider>
    </StrictMode>
  );
}

/** Connect incoming reading timestamps to the real history query for integration assertions. */
function useLiveHistory(readingTimestamp?: string) {
  const range = useDashboardTimeRange();
  const refreshKey = useDashboardLiveRefresh(readingTimestamp);
  const history = useGlucoseHistory("3h", range.currentWindow);
  return { range, refreshKey, history };
}

/** Advance the simulated clock and flush timer-driven React updates and API promises. */
async function advance(ms: number) {
  await act(async () => { jest.advanceTimersByTime(ms); });
}

beforeEach(() => {
  jest.useFakeTimers().setSystemTime(START);
  getHistory.mockReset().mockResolvedValue({ readings: [], count: 0 });
});

afterEach(() => { jest.useRealTimers(); });

it("advances the history query and includes a reading received after the page opened", async () => {
  const newReading: GlucoseHistoryReading = {
    value: 145,
    reading_timestamp: "2026-09-06T10:04:00.000Z",
    received_at: "2026-09-06T10:04:00.000Z",
    trend: "flat",
    trend_rate: null,
    source: "dexcom",
  };
  getHistory.mockImplementation(async (_from, to) => {
    const readings = newReading.reading_timestamp < to ? [newReading] : [];
    return { readings, count: readings.length };
  });
  const { result, rerender } = renderHook(
    ({ timestamp }) => useLiveHistory(timestamp),
    { wrapper: Wrapper, initialProps: { timestamp: START.toISOString() } },
  );
  await advance(0);
  expect(result.current.refreshKey).toBe(1);
  expect(result.current.history.readings).toEqual([]);
  const selection = result.current.range.selection;

  await advance(4 * 60_000);
  rerender({ timestamp: newReading.reading_timestamp });
  expect(result.current.refreshKey).toBe(1);
  // No further SSE event is needed to flush this reading.
  await advance(60_000);

  expect(result.current.refreshKey).toBe(2);
  // Keep the selection stable so a live refresh does not reset picker drafts.
  expect(result.current.range.selection).toBe(selection);
  expect(getHistory).toHaveBeenLastCalledWith(
    "2026-09-05T10:05:00.000Z", "2026-09-06T10:05:00.000Z", 288,
  );
  expect(result.current.history.readings).toEqual([newReading]);
});

it("coalesces a burst without moving the trailing refresh deadline", async () => {
  const { result, rerender } = renderHook(
    ({ timestamp }) => useLiveHistory(timestamp),
    { wrapper: Wrapper, initialProps: { timestamp: START.toISOString() } },
  );
  await advance(60_000);
  rerender({ timestamp: "2026-09-06T10:01:00.000Z" });
  await advance(3 * 60_000);
  rerender({ timestamp: "2026-09-06T10:04:00.000Z" });
  await advance(60_000);
  expect(result.current.refreshKey).toBe(2);
  const calls = getHistory.mock.calls.length;
  // Duplicate glucose events and idle time must not trigger polling.
  rerender({ timestamp: "2026-09-06T10:04:00.000Z" });
  await advance(FIVE_MINUTES);
  expect(result.current.refreshKey).toBe(2);
  expect(getHistory).toHaveBeenCalledTimes(calls);
});

it("refreshes immediately for a new reading exactly at the throttle boundary", async () => {
  const { result, rerender } = renderHook(
    ({ timestamp }) => useLiveHistory(timestamp),
    { wrapper: Wrapper, initialProps: { timestamp: START.toISOString() } },
  );
  await advance(FIVE_MINUTES);
  await act(async () => {
    rerender({ timestamp: "2026-09-06T10:05:00.000Z" });
  });
  expect(result.current.refreshKey).toBe(2);
});

it("retains the newest queued reading when an older duplicate arrives", async () => {
  const { result, rerender } = renderHook(
    ({ timestamp }) => useLiveHistory(timestamp),
    { wrapper: Wrapper, initialProps: { timestamp: START.toISOString() } },
  );
  await advance(4 * 60_000);
  const newestTimestamp = "2026-09-06T10:04:00.000Z";
  rerender({ timestamp: newestTimestamp });
  await advance(30_000);
  // A -> B -> A must not cancel the work queued for B.
  rerender({ timestamp: START.toISOString() });
  await advance(30_000);
  expect(result.current.refreshKey).toBe(2);
  expect(result.current.range.currentWindow?.to).toBe("2026-09-06T10:05:00.000Z");

  const calls = getHistory.mock.calls.length;
  await advance(FIVE_MINUTES);
  rerender({ timestamp: newestTimestamp });
  await advance(FIVE_MINUTES);
  expect(result.current.refreshKey).toBe(2);
  expect(getHistory).toHaveBeenCalledTimes(calls);
});

it("keeps a custom historical window fixed across live updates", async () => {
  const { result, rerender } = renderHook(
    ({ timestamp }) => useLiveHistory(timestamp),
    { wrapper: Wrapper, initialProps: { timestamp: START.toISOString() } },
  );
  const window = { from: "2026-09-01T10:00:00.000Z", to: "2026-09-02T10:00:00.000Z" };
  await act(async () => {
    result.current.range.setSelection({ kind: "custom", window });
  });
  await advance(FIVE_MINUTES);
  await act(async () => {
    rerender({ timestamp: "2026-09-06T10:05:00.000Z" });
  });
  expect(result.current.refreshKey).toBe(2);
  expect(result.current.range.currentWindow).toBe(window);
  expect(getHistory).toHaveBeenLastCalledWith(window.from, window.to, 288);
});

it("does not refresh without readings and cancels pending work on unmount", async () => {
  const { result, rerender, unmount } = renderHook(
    ({ timestamp }) => useLiveHistory(timestamp),
    { wrapper: Wrapper, initialProps: { timestamp: undefined as string | undefined } },
  );
  await advance(0);
  expect(result.current.refreshKey).toBe(0);
  await act(async () => { rerender({ timestamp: START.toISOString() }); });
  expect(result.current.refreshKey).toBe(1);
  await advance(60_000);
  rerender({ timestamp: "2026-09-06T10:01:00.000Z" });
  const pendingTimers = jest.getTimerCount();
  const calls = getHistory.mock.calls.length;
  unmount();
  expect(jest.getTimerCount()).toBeLessThan(pendingTimers);
  await advance(FIVE_MINUTES);
  expect(getHistory).toHaveBeenCalledTimes(calls);
});

describe("chart refresh integration", () => {
  beforeEach(() => {
    jest.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(640);
    jest.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(300);
    global.ResizeObserver = class {
      observe() {}
      unobserve() {}
      disconnect() {}
    };
    jest.mocked(uPlot).mockClear();
    getHistory.mockImplementation(async (_from, to) => ({
      readings: [{
        value: to === START.toISOString() ? 120 : 145,
        reading_timestamp: new Date(new Date(to).getTime() - 60_000).toISOString(),
        received_at: to,
        trend: "flat",
        trend_rate: null,
        source: "dexcom",
      }],
      count: 1,
    }));
  });

  afterEach(() => { jest.restoreAllMocks(); });

  it.each([GlucoseTrendChart, MergedGlucoseTrendChart])(
    "%p plots fresh history with one request per refresh and keeps fixed-range refreshes working",
    async (Chart) => {
      let range: ReturnType<typeof useDashboardTimeRange>;
      /** Drive either chart with the same refresh signal used by the dashboard page. */
      function LiveChart({ timestamp }: { timestamp: string }) {
        range = useDashboardTimeRange();
        const refreshKey = useDashboardLiveRefresh(timestamp);
        return <Chart refreshKey={refreshKey} />;
      }
      const { rerender } = render(<LiveChart timestamp={START.toISOString()} />, { wrapper: Wrapper });
      await advance(0);
      const initialCalls = getHistory.mock.calls.length;
      await advance(4 * 60_000);
      rerender(<LiveChart timestamp="2026-09-06T10:04:00.000Z" />);
      await advance(60_000);
      expect(getHistory).toHaveBeenCalledTimes(initialCalls + 1);
      const chartCalls = jest.mocked(uPlot).mock.calls;
      expect(chartCalls[chartCalls.length - 1][1]?.[1]).toContain(145);

      await act(async () => {
        range.setSelection({ kind: "custom", window: {
          from: "2026-09-01T10:00:00.000Z", to: "2026-09-02T10:00:00.000Z",
        } });
      });
      const fixedRangeCalls = getHistory.mock.calls.length;
      await advance(FIVE_MINUTES);
      await act(async () => { rerender(<LiveChart timestamp="2026-09-06T10:10:00.000Z" />); });
      expect(getHistory).toHaveBeenCalledTimes(fixedRangeCalls + 1);
      expect(getHistory).toHaveBeenLastCalledWith(
        "2026-09-01T10:00:00.000Z", "2026-09-02T10:00:00.000Z", 288,
      );
    },
  );

  it("preserves desktop zoom on live refresh and resets it when the selection changes", async () => {
    let range: ReturnType<typeof useDashboardTimeRange>;
    /** Keep the desktop chart mounted while live timestamps and the selection change. */
    function LiveChart({ timestamp }: { timestamp: string }) {
      range = useDashboardTimeRange();
      const refreshKey = useDashboardLiveRefresh(timestamp);
      return <GlucoseTrendChart refreshKey={refreshKey} />;
    }
    const { rerender } = render(<LiveChart timestamp={START.toISOString()} />, { wrapper: Wrapper });
    await advance(0);
    const chartCalls = jest.mocked(uPlot).mock.calls;
    const options = chartCalls[chartCalls.length - 1][0];
    act(() => {
      options.hooks?.setSelect?.[0]?.({
        posToVal: (position: number) => START.getTime() / 1000 - 3600 + position * 60,
        select: { left: 10, width: 20 },
        setSelect: jest.fn(),
      } as unknown as uPlot);
    });
    expect(screen.getByRole("button", { name: "Reset zoom" })).toBeInTheDocument();
    await advance(FIVE_MINUTES);
    await act(async () => { rerender(<LiveChart timestamp="2026-09-06T10:05:00.000Z" />); });
    expect(screen.getByRole("button", { name: "Reset zoom" })).toBeInTheDocument();
    await act(async () => { range.setSelection({ kind: "preset", range: "7d" }); });
    expect(screen.queryByRole("button", { name: "Reset zoom" })).not.toBeInTheDocument();
  });
});
