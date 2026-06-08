"use client";

/**
 * useCgmSources Hook (Story 43.10)
 *
 * Fetches the user's CGM-providing integrations and which one is the
 * primary source driving charts/stats. Mirrors `useForecast`: a
 * generation counter (`fetchGenRef`) prevents a stale response from
 * overwriting a newer one when the user switches the primary between
 * fetches, and the previous state is preserved on a transient failure.
 */

import { type CgmSourcesResponse, getCgmSources } from "@/lib/api";
import { useCallback, useEffect, useRef, useState } from "react";

export interface UseCgmSourcesReturn {
  cgm: CgmSourcesResponse | null;
  isLoading: boolean;
  error: Error | null;
  /** Force a fresh fetch (the picker calls this after a successful PUT). */
  refresh: () => Promise<void>;
}

export function useCgmSources(refreshKey: number = 0): UseCgmSourcesReturn {
  const [cgm, setCgm] = useState<CgmSourcesResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const fetchGenRef = useRef(0);

  const fetchData = useCallback(async () => {
    const gen = ++fetchGenRef.current;
    setIsLoading(true);
    try {
      const data = await getCgmSources();
      if (gen === fetchGenRef.current) {
        setCgm(data);
        setError(null);
      }
    } catch (err) {
      if (gen === fetchGenRef.current) {
        // Preserve the previous state on a network blip so the picker
        // doesn't flicker away on a transient failure.
        setError(err instanceof Error ? err : new Error(String(err)));
      }
      if (process.env.NODE_ENV === "development") {
        console.warn("Failed to fetch CGM sources:", err);
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

  return { cgm, isLoading, error, refresh: fetchData };
}
