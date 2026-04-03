"use client";

/**
 * useGlucoseHistory Hook
 *
 * Fetches historical glucose readings for the trend chart.
 * Manages time period selection and data refreshing.
 */

import { useState, useEffect, useCallback, useRef } from "react";
import {
  getGlucoseHistory,
  type GlucoseHistoryReading,
} from "@/lib/api";
import { type ChartTimePeriod, PERIOD_TO_MINUTES } from "@/lib/chart-periods";

export type { ChartTimePeriod };

// Scale limit to period: ~1 reading per 5 min, capped at 8640 (API max)
const PERIOD_TO_LIMIT: Record<ChartTimePeriod, number> = {
  "3h": 36,
  "6h": 72,
  "12h": 144,
  "24h": 288,
  "3d": 864,
  "7d": 2016,
  "14d": 4032,
  "30d": 8640,
};

export interface UseGlucoseHistoryReturn {
  readings: GlucoseHistoryReading[];
  isLoading: boolean;
  error: string | null;
  period: ChartTimePeriod;
  setPeriod: (p: ChartTimePeriod) => void;
  refetch: () => void;
}

export function useGlucoseHistory(
  initialPeriod: ChartTimePeriod = "3h"
): UseGlucoseHistoryReturn {
  const [readings, setReadings] = useState<GlucoseHistoryReading[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [period, setPeriod] = useState<ChartTimePeriod>(initialPeriod);
  // Fetch generation counter — only the latest fetch writes state
  const fetchGenRef = useRef(0);

  const fetchData = useCallback(async () => {
    const gen = ++fetchGenRef.current;
    setIsLoading(true);
    setError(null);
    try {
      const minutes = PERIOD_TO_MINUTES[period];
      const limit = PERIOD_TO_LIMIT[period];
      const data = await getGlucoseHistory(minutes, limit);
      if (gen === fetchGenRef.current) {
        setReadings(data.readings);
      }
    } catch (err) {
      if (gen === fetchGenRef.current) {
        setError(
          err instanceof Error ? err.message : "Failed to load history"
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

  return { readings, isLoading, error, period, setPeriod, refetch: fetchData };
}
