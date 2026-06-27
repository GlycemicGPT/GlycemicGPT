"use client";

/**
 * useGlucoseUnit hook.
 *
 * Reads the logged-in user's preferred glucose display unit from the shared
 * UserProvider context (one /api/auth/me fetch for the whole dashboard) so
 * pages and components can render in the active unit WITHOUT prop-drilling
 *. Defaults to "mgdl" while the user is loading or the field is absent,
 * preserving existing mg/dL behavior.
 *
 * NOTE: this is the SELF-VIEW unit. The caregiver page must render patient
 * data in the PATIENT's unit, not the viewer's — it does not use this
 * hook for patient values.
 */

import { useUserContext } from "@/providers";
import type { GlucoseUnit } from "@/lib/glucose-units";

export function useGlucoseUnit(): GlucoseUnit {
  const { user } = useUserContext();
  return user?.glucose_unit ?? "mgdl";
}
