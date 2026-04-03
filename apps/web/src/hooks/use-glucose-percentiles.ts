"use client";

/**
 * useGlucosePercentiles Hook
 *
 * Story 30.5: Fetches AGP percentile band data from the API.
 * Manages time period selection and data refreshing with
 * generation counter for race-condition safety.
 */

import { useState, useEffect, useCallback, useRef } from "react";
import {
  getGlucosePercentiles,
  type GlucosePercentilesResponse,
} from "@/lib/api";

export type AgpPeriod = "7d" | "14d" | "30d" | "90d";

const PERIOD_TO_DAYS: Record<AgpPeriod, number> = {
  "7d": 7,
  "14d": 14,
  "30d": 30,
  "90d": 90,
};

export const AGP_PERIOD_LABELS: Record<AgpPeriod, string> = {
  "7d": "7 Days",
  "14d": "14 Days",
  "30d": "30 Days",
  "90d": "90 Days",
};

export interface UseGlucosePercentilesReturn {
  data: GlucosePercentilesResponse | null;
  isLoading: boolean;
  error: string | null;
  period: AgpPeriod;
  setPeriod: (p: AgpPeriod) => void;
  refetch: () => void;
}

export function useGlucosePercentiles(
  initialPeriod: AgpPeriod = "14d"
): UseGlucosePercentilesReturn {
  const [data, setData] = useState<GlucosePercentilesResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [period, setPeriod] = useState<AgpPeriod>(initialPeriod);
  const fetchGenRef = useRef(0);

  const fetchData = useCallback(async () => {
    const gen = ++fetchGenRef.current;
    setIsLoading(true);
    setError(null);
    setData(null); // Clear stale data to avoid showing wrong period's values
    try {
      const days = PERIOD_TO_DAYS[period];
      const result = await getGlucosePercentiles(days);
      if (gen === fetchGenRef.current) {
        setData(result);
      }
    } catch (err) {
      if (gen === fetchGenRef.current) {
        setError(
          err instanceof Error ? err.message : "Failed to load AGP data"
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

  return { data, isLoading, error, period, setPeriod, refetch: fetchData };
}
