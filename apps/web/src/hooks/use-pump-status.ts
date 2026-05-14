"use client";

/**
 * usePumpStatus Hook
 *
 * Fetches the latest pump status (basal, battery, reservoir) for the hero card.
 * Re-fetches when refreshKey changes (triggered by SSE glucose updates).
 */

import { useState, useEffect, useCallback, useRef } from "react";
import {
  getPumpStatus,
  type LoopStatusResponse,
  type OverrideStatusResponse,
  type PumpStatusBasal,
  type PumpStatusBattery,
  type PumpStatusReservoir,
} from "@/lib/api";

export interface UsePumpStatusReturn {
  basal: PumpStatusBasal | null;
  battery: PumpStatusBattery | null;
  reservoir: PumpStatusReservoir | null;
  // Story 43.12 PR 6 additions.
  loopStatus: LoopStatusResponse | null;
  override: OverrideStatusResponse | null;
  cobGrams: number | null;
  isLoading: boolean;
}

export function usePumpStatus(refreshKey: number): UsePumpStatusReturn {
  const [basal, setBasal] = useState<PumpStatusBasal | null>(null);
  const [battery, setBattery] = useState<PumpStatusBattery | null>(null);
  const [reservoir, setReservoir] = useState<PumpStatusReservoir | null>(null);
  const [loopStatus, setLoopStatus] = useState<LoopStatusResponse | null>(null);
  const [override, setOverride] = useState<OverrideStatusResponse | null>(null);
  const [cobGrams, setCobGrams] = useState<number | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const fetchGenRef = useRef(0);

  const fetchData = useCallback(async () => {
    const gen = ++fetchGenRef.current;
    setIsLoading(true);
    try {
      const data = await getPumpStatus();
      if (gen === fetchGenRef.current) {
        setBasal(data.basal);
        setBattery(data.battery);
        setReservoir(data.reservoir);
        // PR 6 fields are optional on the wire; default to null so
        // an older backend without these fields renders cleanly.
        setLoopStatus(data.loop_status ?? null);
        setOverride(data.override ?? null);
        setCobGrams(data.cob_grams ?? null);
      }
    } catch (err) {
      if (process.env.NODE_ENV === "development") {
        console.warn("Failed to fetch pump status:", err);
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

  return {
    basal,
    battery,
    reservoir,
    loopStatus,
    override,
    cobGrams,
    isLoading,
  };
}
