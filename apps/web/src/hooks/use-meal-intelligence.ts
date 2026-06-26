"use client";

/**
 * useMealIntelligence -- resolves whether the meal-photo feature is enabled.
 *
 * Reads the per-user `meal_intelligence_enabled` preference from the shared
 * UserProvider context (one /api/auth/me fetch for the whole dashboard), so the
 * "Meals" nav and meal surfaces gate on the setting without a separate probe.
 * `enabled` is `null` while the user is loading, then the boolean; an absent
 * field (deploy skew against an older API) defaults to `true` so the feature
 * stays visible rather than vanishing on a version mismatch.
 */

import { useUserContext } from "@/providers";

export interface UseMealIntelligenceReturn {
  /** null while the user is loading; true/false once resolved. Gating keys off this. */
  enabled: boolean | null;
  /** The shared user-context loading flag (kept for API symmetry); gate on `enabled`. */
  isLoading: boolean;
}

export function useMealIntelligence(): UseMealIntelligenceReturn {
  const { user, isLoading } = useUserContext();
  const enabled = user ? (user.meal_intelligence_enabled ?? true) : null;
  return { enabled, isLoading };
}
