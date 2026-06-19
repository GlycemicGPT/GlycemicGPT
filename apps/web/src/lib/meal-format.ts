/**
 * Pure formatting/derivation helpers for meal (food-record) display.
 *
 * Kept free of JSX so they can be unit-tested directly. All carb rendering is
 * descriptive ("≈ N g carbs") and never a dose -- the server-cleared
 * `safety_qualifier` field carries the never-dose framing on the surface.
 */

import type { FoodRecord, FoodRecordSource } from "./api";

/** Round to whole grams; avoids false precision on a float estimate. */
function grams(value: number): string {
  return String(Math.round(value));
}

export interface CarbRange {
  low: number;
  high: number;
  /** True when these are the user's corrected values rather than the AI estimate. */
  corrected: boolean;
}

/**
 * The carb band to display: the user's corrected values when both are present,
 * otherwise the original AI estimate.
 */
export function effectiveCarbRange(record: FoodRecord): CarbRange {
  if (
    record.corrected_carbs_low != null &&
    record.corrected_carbs_high != null
  ) {
    return {
      low: record.corrected_carbs_low,
      high: record.corrected_carbs_high,
      corrected: true,
    };
  }
  return { low: record.carbs_low, high: record.carbs_high, corrected: false };
}

/**
 * Render a carb band as "≈ 40–55 g carbs" (or "≈ 50 g carbs" when the rounded
 * endpoints coincide). Mirrors the mobile `formatCarbRange`. Carbs only.
 */
export function formatCarbRange(low: number, high: number): string {
  const lo = grams(low);
  const hi = grams(high);
  return lo === hi ? `≈ ${lo} g carbs` : `≈ ${lo}–${hi} g carbs`;
}

/**
 * Human label for the EMPIRICAL dispersion confidence band. Mirrors the mobile
 * `confidenceLabel`. Low dispersion is NOT "safe to dose" -- consistency is not
 * correctness -- so the never-dose qualifier stays dominant regardless of this.
 */
export function confidenceLabel(confidence: string | null): string {
  switch ((confidence ?? "").toLowerCase()) {
    case "low":
      return "Low confidence";
    case "medium":
      return "Medium confidence";
    case "high":
      return "High confidence";
    default:
      return "Confidence unavailable";
  }
}

export interface SourceMeta {
  label: string;
  /** Tailwind background + text classes for the badge (dual light/dark). */
  bg: string;
  text: string;
}

const SOURCE_META: Record<FoodRecordSource, SourceMeta> = {
  ai_estimate: {
    label: "AI estimate",
    bg: "bg-amber-500/15",
    text: "text-amber-700 dark:text-amber-400",
  },
  user_corrected: {
    label: "You corrected this",
    bg: "bg-emerald-500/15",
    text: "text-emerald-700 dark:text-emerald-400",
  },
  external_grounded: {
    label: "Grounded",
    bg: "bg-blue-500/15",
    text: "text-blue-700 dark:text-blue-400",
  },
};

/** Badge styling/label for a record source; falls back gracefully for unknowns. */
export function sourceMeta(source: FoodRecordSource | string): SourceMeta {
  return (
    SOURCE_META[source as FoodRecordSource] ?? {
      label: String(source),
      bg: "bg-slate-500/15",
      text: "text-slate-600 dark:text-slate-400",
    }
  );
}

/** The display name for a record: confirmed identity, else the AI description. */
export function mealTitle(record: FoodRecord): string {
  return (
    record.confirmed_food_name?.trim() ||
    record.food_description?.trim() ||
    "Unidentified meal"
  );
}

/**
 * Render a macro value with its unit ("12 g", "520 kcal"). Whole units only --
 * no false precision on an estimate. Mirrors the carb rounding. The label, unit,
 * and descriptive glucose framing come from the server `nutrition_facts` block
 * (Story 50.N1) so the safety-adjacent copy lives in one scrubber-checked place.
 */
export function formatMacroValue(value: number, unit: string): string {
  return `${Math.round(value)} ${unit}`.trim();
}

/** Render a net-carb band as "≈ 34–49 g" (or "≈ 26 g" when the endpoints meet). */
export function formatNetCarbs(low: number, high: number): string {
  const lo = grams(low);
  const hi = grams(high);
  return lo === hi ? `≈ ${lo} g` : `≈ ${lo}–${hi} g`;
}
