"use client";

/**
 * useForecast Hook (Story 43.12 PR 4)
 *
 * Fetches the latest forecast picker state + payload for the dashboard
 * chart's dotted-line overlay. Refreshes when `refreshKey` changes --
 * mirrors `usePumpStatus`'s SSE-driven refresh so the forecast line
 * stays in sync with the rest of the chart.
 *
 * Race-prevention via `fetchGenRef`: a stale response can't overwrite
 * a newer one if the user changes filters / settings between fetches.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  type ForecastReadResponse,
  getForecast,
} from "@/lib/api";

export interface UseForecastReturn {
  forecast: ForecastReadResponse | null;
  isLoading: boolean;
  error: Error | null;
  /** Force a fresh fetch outside the normal `refreshKey` cycle.
   * The picker calls this after a successful PUT so the response
   * reflects the new preference immediately. */
  refresh: () => Promise<void>;
}

export function useForecast(refreshKey: number = 0): UseForecastReturn {
  const [forecast, setForecast] = useState<ForecastReadResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const fetchGenRef = useRef(0);

  const fetchData = useCallback(async () => {
    const gen = ++fetchGenRef.current;
    setIsLoading(true);
    try {
      const data = await getForecast();
      if (gen === fetchGenRef.current) {
        setForecast(data);
        setError(null);
      }
    } catch (err) {
      if (gen === fetchGenRef.current) {
        // Network blip / 401: leave the previous forecast in state so
        // the chart doesn't flicker the dotted line away on transient
        // failures. The error state surfaces for callers that want to
        // show a toast.
        setError(err instanceof Error ? err : new Error(String(err)));
      }
      if (process.env.NODE_ENV === "development") {
        console.warn("Failed to fetch forecast:", err);
      }
    } finally {
      if (gen === fetchGenRef.current) {
        setIsLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData, refreshKey]);

  return { forecast, isLoading, error, refresh: fetchData };
}
