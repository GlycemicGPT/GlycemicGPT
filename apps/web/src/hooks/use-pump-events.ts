"use client";

/**
 * usePumpEvents Hook
 *
 * Fetches pump event history (bolus, basal, etc.) for chart overlays.
 * Mirrors the useGlucoseHistory pattern with generation-counter fetch.
 */

import { useState, useEffect, useCallback, useRef } from "react";
import {
  getPumpEventHistory,
  type PumpEventReading,
} from "@/lib/api";
import { type ChartTimePeriod, PERIOD_TO_MINUTES } from "@/lib/chart-periods";

// Scale limit to period -- pump events are sparser than glucose but
// Control-IQ basal adjustments can generate ~288/day
const PERIOD_TO_LIMIT: Record<ChartTimePeriod, number> = {
  "3h": 200,
  "6h": 400,
  "12h": 600,
  "24h": 1000,
  "3d": 2000,
  "7d": 3500,
  "14d": 5000,
  "30d": 5000,
};

export interface UsePumpEventsReturn {
  events: PumpEventReading[];
  isLoading: boolean;
  error: string | null;
  refetch: () => void;
}

export function usePumpEvents(
  period: ChartTimePeriod
): UsePumpEventsReturn {
  const [events, setEvents] = useState<PumpEventReading[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const fetchGenRef = useRef(0);

  const fetchData = useCallback(async () => {
    const gen = ++fetchGenRef.current;
    setIsLoading(true);
    setError(null);
    try {
      const minutes = PERIOD_TO_MINUTES[period];
      const limit = PERIOD_TO_LIMIT[period];
      const data = await getPumpEventHistory(minutes, limit);
      if (gen === fetchGenRef.current) {
        setEvents(data.events);
      }
    } catch (err) {
      if (gen === fetchGenRef.current) {
        setError(
          err instanceof Error ? err.message : "Failed to load pump events"
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

  return { events, isLoading, error, refetch: fetchData };
}
