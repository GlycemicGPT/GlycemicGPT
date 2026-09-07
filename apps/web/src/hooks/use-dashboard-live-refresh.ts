"use client";

import { useEffect, useRef, useState } from "react";
import { useDashboardTimeRange } from "@/components/DashboardTimeRangeProvider";

const REFRESH_INTERVAL_MS = 5 * 60 * 1000;

/** Coalesce live readings, retaining a trailing refresh for throttled updates. */
export function useDashboardLiveRefresh(readingTimestamp?: string): number {
  const { refreshWindow } = useDashboardTimeRange();
  const [refreshKey, setRefreshKey] = useState(0);
  const lastRefreshAt = useRef<number | null>(null);
  const lastRefreshedReading = useRef<string | undefined>(undefined);

  useEffect(() => {
    if (!readingTimestamp || readingTimestamp === lastRefreshedReading.current) {
      return;
    }

    const refresh = () => {
      lastRefreshAt.current = Date.now();
      lastRefreshedReading.current = readingTimestamp;
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

    const timeout = setTimeout(refresh, delay);
    return () => clearTimeout(timeout);
  }, [readingTimestamp, refreshWindow]);

  return refreshKey;
}
