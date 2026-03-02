"use client";

/**
 * useTimeInRangeStats Hook
 *
 * Story 18.6: Fetches time-in-range statistics from the API.
 * Manages time period selection and data refreshing.
 */

import { useState, useEffect, useCallback, useRef } from "react";
import {
  getTimeInRangeStats,
  getTimeInRangeDetailStats,
  type TimeInRangeStats,
  type TimeInRangeDetailStats,
} from "@/lib/api";

export type TirPeriod = "24h" | "3d" | "7d" | "14d" | "30d";

const PERIOD_TO_MINUTES: Record<TirPeriod, number> = {
  "24h": 1440,
  "3d": 4320,
  "7d": 10080,
  "14d": 20160,
  "30d": 43200,
};

export interface UseTimeInRangeStatsReturn {
  stats: TimeInRangeStats | null;
  isLoading: boolean;
  error: string | null;
  period: TirPeriod;
  setPeriod: (p: TirPeriod) => void;
  refetch: () => void;
}

export function useTimeInRangeStats(
  initialPeriod: TirPeriod = "24h"
): UseTimeInRangeStatsReturn {
  const [stats, setStats] = useState<TimeInRangeStats | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [period, setPeriod] = useState<TirPeriod>(initialPeriod);
  const fetchGenRef = useRef(0);

  const fetchData = useCallback(async () => {
    const gen = ++fetchGenRef.current;
    setIsLoading(true);
    setError(null);
    try {
      const minutes = PERIOD_TO_MINUTES[period];
      const data = await getTimeInRangeStats(minutes);
      if (gen === fetchGenRef.current) {
        setStats(data);
      }
    } catch (err) {
      if (gen === fetchGenRef.current) {
        setError(
          err instanceof Error ? err.message : "Failed to load time in range"
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

export interface UseTimeInRangeDetailStatsReturn {
  stats: TimeInRangeDetailStats | null;
  isLoading: boolean;
  error: string | null;
  period: TirPeriod;
  setPeriod: (p: TirPeriod) => void;
  refetch: () => void;
}

export function useTimeInRangeDetailStats(
  initialPeriod: TirPeriod = "24h"
): UseTimeInRangeDetailStatsReturn {
  const [stats, setStats] = useState<TimeInRangeDetailStats | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [period, setPeriod] = useState<TirPeriod>(initialPeriod);
  const fetchGenRef = useRef(0);

  const fetchData = useCallback(async () => {
    const gen = ++fetchGenRef.current;
    setIsLoading(true);
    setError(null);
    try {
      const minutes = PERIOD_TO_MINUTES[period];
      const data = await getTimeInRangeDetailStats(minutes);
      if (gen === fetchGenRef.current) {
        setStats(data);
      }
    } catch (err) {
      if (gen === fetchGenRef.current) {
        setError(
          err instanceof Error ? err.message : "Failed to load TIR detail"
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
