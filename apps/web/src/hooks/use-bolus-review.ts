"use client";

/**
 * useBolusReview Hook
 *
 * Story 30.7: Fetches paginated bolus review data from the API.
 * Manages time period selection and data refreshing with
 * generation counter for race-condition safety.
 */

import { useState, useEffect, useCallback, useRef } from "react";
import {
  getBolusReview,
  type BolusReviewResponse,
} from "@/lib/api";

export type BolusReviewPeriod = "24h" | "3d" | "7d" | "14d" | "30d";

const PERIOD_TO_DAYS: Record<BolusReviewPeriod, number> = {
  "24h": 1,
  "3d": 3,
  "7d": 7,
  "14d": 14,
  "30d": 30,
};

export const BOLUS_PERIOD_LABELS: Record<BolusReviewPeriod, string> = {
  "24h": "24 Hours",
  "3d": "3 Days",
  "7d": "7 Days",
  "14d": "14 Days",
  "30d": "30 Days",
};

export interface UseBolusReviewReturn {
  data: BolusReviewResponse | null;
  isLoading: boolean;
  error: string | null;
  period: BolusReviewPeriod;
  setPeriod: (p: BolusReviewPeriod) => void;
  refetch: () => void;
}

export function useBolusReview(
  initialPeriod: BolusReviewPeriod = "7d"
): UseBolusReviewReturn {
  const [data, setData] = useState<BolusReviewResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [period, setPeriod] = useState<BolusReviewPeriod>(initialPeriod);
  const fetchGenRef = useRef(0);

  const fetchData = useCallback(async () => {
    const gen = ++fetchGenRef.current;
    setIsLoading(true);
    setError(null);
    setData(null);
    try {
      const days = PERIOD_TO_DAYS[period];
      const result = await getBolusReview(days, 100, 0);
      if (gen === fetchGenRef.current) {
        setData(result);
      }
    } catch (err) {
      if (gen === fetchGenRef.current) {
        setError(
          err instanceof Error ? err.message : "Failed to load bolus review"
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
