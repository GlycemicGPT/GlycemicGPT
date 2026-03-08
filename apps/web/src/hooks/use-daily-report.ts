"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type {
  GlucoseHistoryReading,
  GlucoseStats,
  TimeInRangeDetailStats,
  InsulinSummaryResponse,
  BolusReviewResponse,
} from "@/lib/api";
import {
  getGlucoseHistoryByDateRange,
  getGlucoseStatsByDateRange,
  getTimeInRangeDetailByDateRange,
  getInsulinSummaryByDateRange,
  getBolusReviewByDateRange,
} from "@/lib/api";

export interface DailyReportData {
  glucoseReadings: GlucoseHistoryReading[];
  cgmStats: GlucoseStats | null;
  tirStats: TimeInRangeDetailStats | null;
  insulinSummary: InsulinSummaryResponse | null;
  bolusReview: BolusReviewResponse | null;
}

export interface UseDailyReportResult {
  data: DailyReportData | null;
  isLoading: boolean;
  error: string | null;
  refetch: () => void;
}

/**
 * Compute UTC ISO strings for the start/end of a local date.
 * e.g. date="2026-03-07" in America/Chicago -> midnight..midnight CT in UTC.
 *
 * NOTE: The date string is intentionally parsed WITHOUT a timezone suffix so
 * that `new Date()` interprets it as local time. `.toISOString()` then
 * converts to UTC, which means the server receives the correct UTC window
 * for the user's local day.
 */
function dateToUtcRange(date: string): { start: string; end: string } {
  const dayStart = new Date(`${date}T00:00:00`);
  if (isNaN(dayStart.getTime())) {
    throw new Error(`Invalid date: ${date}`);
  }
  const dayEnd = new Date(`${date}T00:00:00`);
  dayEnd.setDate(dayEnd.getDate() + 1);
  return {
    start: dayStart.toISOString(),
    end: dayEnd.toISOString(),
  };
}

export function useDailyReport(date: string): UseDailyReportResult {
  const [data, setData] = useState<DailyReportData | null>(null);
  const [isLoading, setIsLoading] = useState(!!date);
  const [error, setError] = useState<string | null>(null);
  const fetchIdRef = useRef(0);

  const fetchReport = useCallback(async () => {
    if (!date) return;
    const fetchId = ++fetchIdRef.current;
    setIsLoading(true);
    setError(null);

    try {
      const { start, end } = dateToUtcRange(date);

      const [glucose, stats, tir, insulin, bolus] = await Promise.allSettled([
        getGlucoseHistoryByDateRange(start, end, 2000),
        getGlucoseStatsByDateRange(start, end),
        getTimeInRangeDetailByDateRange(start, end),
        getInsulinSummaryByDateRange(start, end),
        getBolusReviewByDateRange(start, end, 500),
      ]);

      // Stale request guard
      if (fetchId !== fetchIdRef.current) return;

      const result: DailyReportData = {
        glucoseReadings:
          glucose.status === "fulfilled" ? glucose.value.readings : [],
        cgmStats:
          stats.status === "fulfilled" ? stats.value : null,
        tirStats:
          tir.status === "fulfilled" ? tir.value : null,
        insulinSummary:
          insulin.status === "fulfilled" ? insulin.value : null,
        bolusReview:
          bolus.status === "fulfilled" ? bolus.value : null,
      };

      // If ALL fetches failed, surface an error
      const allFailed = [glucose, stats, tir, insulin, bolus].every(
        (r) => r.status === "rejected"
      );
      if (allFailed) {
        const firstError =
          glucose.status === "rejected" ? glucose.reason : null;
        throw firstError || new Error("Failed to load report data");
      }

      setData(result);
    } catch (err) {
      if (fetchId !== fetchIdRef.current) return;
      setError(err instanceof Error ? err.message : "Failed to load report");
      setData(null);
    } finally {
      if (fetchId === fetchIdRef.current) {
        setIsLoading(false);
      }
    }
  }, [date]);

  useEffect(() => {
    fetchReport();
  }, [fetchReport]);

  return { data, isLoading, error, refetch: fetchReport };
}
