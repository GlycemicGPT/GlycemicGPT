/**
 * Pure helpers for the common-food (baseline) management surface.
 *
 * A common food is the user's curated truth for a food they eat often, but it is
 * still a *description* of that food, never a dose target. Kept free of JSX so it
 * is unit-testable; carb display reuses `formatCarbRange` from `meal-format`.
 */

import { MealApiError } from "./api";

/**
 * The always-present never-dose framing for baselines. A baseline is the user's
 * own number, so it reads as more trustworthy than an AI estimate -- which is
 * exactly why the never-dose qualifier must stay attached: consistency is not a
 * dose. Mirrors the voice of the record `safety_qualifier` ("never dose from
 * it") rather than introducing new dosing-adjacent copy.
 */
export const NEVER_DOSE_BASELINE_NOTE =
  "A baseline describes a food you eat often — it's still an estimate, not a dose target. Never dose from it.";

/**
 * Map a common-food API failure to friendly copy, preserving the server detail
 * where it is safe to show. Handles the three states the baseline endpoints
 * raise: 409 name-in-use, 422 out-of-range carbs, and the owner-scoped 404
 * (a missing or cross-user id). Anything else falls back to a generic retry.
 */
export function describeCommonFoodError(err: unknown): string {
  if (err instanceof MealApiError) {
    if (err.status === 404) {
      return "That common food no longer exists.";
    }
    if (err.status === 409) {
      return "You already have a common food with that name.";
    }
    if (err.status === 422) {
      const detail = err.detail.toLowerCase();
      if (detail.includes("exceed")) {
        return "The low value must not exceed the high value.";
      }
      // A name length violation (server caps the name at 120 chars) surfaces as a
      // Pydantic "String should have at most/least N characters" message — map it
      // to a name-specific hint so it never falls through to the carb default.
      if (
        detail.includes("at most") ||
        detail.includes("at least") ||
        detail.includes("character")
      ) {
        return "Choose a name between 1 and 120 characters.";
      }
      if (detail.includes("empty") || detail.includes("name")) {
        return "Enter a name for this common food.";
      }
      return "Enter carb values between 0 and 1000 grams.";
    }
    return err.detail || "Couldn't save that change. Try again.";
  }
  return "Couldn't save that change. Try again.";
}
