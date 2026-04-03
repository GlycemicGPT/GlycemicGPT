"use client";

/**
 * useGlucoseStats Hook
 *
 * Story 30.3: Fetches CGM summary statistics from the API.
 * Manages time period selection and data refreshing.
 */

import { useState, useEffect, useCallback, useRef } from "react";
import { getGlucoseStats, type GlucoseStats } from "@/lib/api";

export type StatsPeriod = "24h" | "3d" | "7d" | "14d" | "30d";

const PERIOD_TO_MINUTES: Record<StatsPeriod, number> = {
  "24h": 1440,
  "3d": 4320,
  "7d": 10080,
  "14d": 20160,
  "30d": 43200,
};

export interface UseGlucoseStatsReturn {
  stats: GlucoseStats | null;
  isLoading: boolean;
  error: string | null;
  period: StatsPeriod;
  setPeriod: (p: StatsPeriod) => void;
  refetch: () => void;
}

export function useGlucoseStats(
  initialPeriod: StatsPeriod = "24h"
): UseGlucoseStatsReturn {
  const [stats, setStats] = useState<GlucoseStats | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [period, setPeriod] = useState<StatsPeriod>(initialPeriod);
  const fetchGenRef = useRef(0);

  const fetchData = useCallback(async () => {
    const gen = ++fetchGenRef.current;
    setIsLoading(true);
    setError(null);
    try {
      const minutes = PERIOD_TO_MINUTES[period];
      const data = await getGlucoseStats(minutes);
      if (gen === fetchGenRef.current) {
        setStats(data);
      }
    } catch (err) {
      if (gen === fetchGenRef.current) {
        setStats(null);
        setError(
          err instanceof Error ? err.message : "Failed to load glucose stats"
        );
      }
    } finally {
      if (gen === fetchGenRef.current) {
        setIsLoading(false);
      }
    }
  }, [period]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  return { stats, isLoading, error, period, setPeriod, refetch: fetchData };
}
