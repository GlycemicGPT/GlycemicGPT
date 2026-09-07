"use client";

import { useEffect, useRef, useState } from "react";
import { useDashboardTimeRange } from "@/components/DashboardTimeRangeProvider";

const REFRESH_INTERVAL_MS = 5 * 60 * 1000;

/** Coalesce live readings, retaining a trailing refresh for throttled updates. */
export function useDashboardLiveRefresh(readingTimestamp?: string): number {
  const { refreshWindow } = useDashboardTimeRange();
  const [refreshKey, setRefreshKey] = useState(0);
  const lastRefreshAt = useRef<number | null>(null);
  const lastRefreshedReading = useRef<number | null>(null);
  const pendingReading = useRef<number | null>(null);
  const pendingTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => {
    if (pendingTimer.current !== null) clearTimeout(pendingTimer.current);
    pendingTimer.current = null;
    pendingReading.current = null;
  }, []);

  useEffect(() => {
    const readingTime = readingTimestamp ? Date.parse(readingTimestamp) : NaN;
    if (
      !Number.isFinite(readingTime) ||
      readingTime <= (lastRefreshedReading.current ?? -Infinity) ||
      readingTime <= (pendingReading.current ?? -Infinity)
    ) {
      return;
    }

    pendingReading.current = readingTime;
    // Newer readings join the queued refresh without postponing its deadline.
    // Older or duplicate events cannot cancel work that is already pending.
    if (pendingTimer.current !== null) return;

    const refresh = () => {
      lastRefreshAt.current = Date.now();
      lastRefreshedReading.current = pendingReading.current;
      pendingReading.current = null;
      pendingTimer.current = null;
      // React batches the window and refresh key so all requests use the new range.
      refreshWindow();
      setRefreshKey((key) => key + 1);
    };
    const delay = lastRefreshAt.current === null
      ? 0
      : Math.max(0, REFRESH_INTERVAL_MS - (Date.now() - lastRefreshAt.current));

    if (delay === 0) {
      refresh();
      return;
    }

    pendingTimer.current = setTimeout(refresh, delay);
  }, [readingTimestamp, refreshWindow]);

  return refreshKey;
}
