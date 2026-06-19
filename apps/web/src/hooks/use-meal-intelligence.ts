/**
 * useMealIntelligence -- resolves whether the meal-photo feature is enabled.
 *
 * There is no server flag endpoint, so this probes the food-records list once on
 * mount (see `getMealIntelligenceStatus`). `enabled` is `null` while resolving,
 * then `false` only when the server explicitly reports the feature is off, else
 * `true`. Mirrors the mobile client's reactive availability probe.
 */

"use client";

import { useState, useEffect } from "react";
import { getMealIntelligenceStatus } from "@/lib/api";

export interface UseMealIntelligenceReturn {
  /** null while the probe is in flight; true/false once resolved. */
  enabled: boolean | null;
  isLoading: boolean;
}

export function useMealIntelligence(): UseMealIntelligenceReturn {
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    async function probe() {
      // getMealIntelligenceStatus never rejects (it degrades to enabled on a
      // transient failure), so a throw here would be unexpected; keep the guard
      // so the nav simply stays hidden rather than crashing.
      try {
        const { enabled: isEnabled } = await getMealIntelligenceStatus();
        if (!cancelled) setEnabled(isEnabled);
      } catch {
        if (!cancelled) setEnabled(false);
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    }

    probe();
    return () => {
      cancelled = true;
    };
  }, []);

  return { enabled, isLoading };
}
