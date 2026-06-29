/**
 * Bolus insulin catalog for the Settings -> Insulin picker.
 *
 * Both tables mirror the backend in apps/api/src/schemas/insulin_config.py:
 * FALLBACK_PRESETS mirrors INSULIN_PRESETS and is used only when the API is
 * unreachable (the online path uses the API-fetched presets); INSULIN_LABELS
 * supplies the dropdown's display names and its keys mirror VALID_INSULIN_TYPES.
 * Keep all three in sync when adding a type -- the insulin.test.ts parity test
 * guards the relationship between these two tables.
 */

import type { InsulinPresets } from "@/lib/api";

export const FALLBACK_PRESETS: InsulinPresets = {
  humalog: { dia_hours: 4.0, onset_minutes: 15.0 },
  novolog: { dia_hours: 4.0, onset_minutes: 15.0 },
  fiasp: { dia_hours: 3.5, onset_minutes: 5.0 },
  lyumjev: { dia_hours: 3.5, onset_minutes: 5.0 },
  apidra: { dia_hours: 4.0, onset_minutes: 15.0 },
  // Rapid analogs -- same molecule/PK as an entry above
  novorapid: { dia_hours: 4.0, onset_minutes: 15.0 },
  liprolog: { dia_hours: 4.0, onset_minutes: 15.0 },
  admelog: { dia_hours: 4.0, onset_minutes: 15.0 },
  trurapi: { dia_hours: 4.0, onset_minutes: 15.0 },
  kirsty: { dia_hours: 4.0, onset_minutes: 15.0 },
  // Regular (short-acting) human insulin -- longer DIA, later onset
  humulin_r: { dia_hours: 6.0, onset_minutes: 30.0 },
  novolin_r: { dia_hours: 6.0, onset_minutes: 30.0 },
  insuman_rapid: { dia_hours: 6.0, onset_minutes: 30.0 },
};

/**
 * DIA/onset input bounds. These mirror the InsulinConfigUpdate Field
 * constraints in apps/api/src/schemas/insulin_config.py -- the backend is the
 * source of truth, this is the single frontend copy so the form's validation
 * and its tests check the same numbers (and an offline preset auto-fill never
 * produces a value the backend would 422 on save).
 */
export const INSULIN_LIMITS = {
  diaMinHours: 2.0,
  diaMaxHours: 8.0,
  onsetMinMinutes: 1.0,
  onsetMaxMinutes: 60.0,
} as const;

// Dropdown labels. "custom" stays last so it renders at the bottom of the list.
export const INSULIN_LABELS: Record<string, string> = {
  humalog: "Humalog (Lispro)",
  novolog: "NovoLog (Aspart)",
  fiasp: "Fiasp (Faster Aspart)",
  lyumjev: "Lyumjev (Faster Lispro)",
  apidra: "Apidra (Glulisine)",
  novorapid: "NovoRapid (Aspart)",
  liprolog: "Liprolog (Lispro)",
  admelog: "Admelog / Insulin lispro Sanofi (Lispro)",
  trurapi: "Trurapi (Aspart)",
  kirsty: "Kirsty (Aspart)",
  humulin_r: "Humulin R (Regular human)",
  novolin_r: "Novolin R / Actrapid (Regular human)",
  insuman_rapid: "Insuman Rapid (Regular human)",
  custom: "Custom",
};
