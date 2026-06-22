/**
 * Glucose unit conversion + formatting — the single source of truth for the web
 * client.
 *
 * Canonical storage and transport are ALWAYS mg/dL: the API,
 * the SSE proxy, chart data/domains, and every threshold on the wire stay in
 * mg/dL. All comparison, range classification, alert banding, and safety-limit
 * enforcement also stay in mg/dL. This module converts ONLY
 * the numbers and labels shown to the user, and converts user-entered values
 * back to integer mg/dL before they leave the browser.
 *
 * Round once, round LAST: convert from the most-precise
 * mg/dL source a single time and round only at the display edge. Never write a
 * re-converted value back to storage.
 */

/** User's preferred glucose display unit. Mirrors the backend `GlucoseUnit` enum. */
export type GlucoseUnit = "mgdl" | "mmol";

/**
 * Provenance of a stored glucose-unit preference. Mirrors the backend
 * `GlucoseUnitSource` enum. `"seed"` is a smart default (registration locale or
 * a confidently-mmol Nightscout) that is still overridable; `"user"` is an
 * explicit choice. Drives the one-time smart-default notice (Story 53.10).
 */
export type GlucoseUnitSource = "seed" | "user";

/**
 * The ONE canonical conversion factor: 1 mmol/L = 18.0156 mg/dL — the exact
 * glucose mass-to-molarity factor. Mirrors the backend's
 * `src/core/units.py` `MGDL_PER_MMOL`. Do NOT introduce a second value
 * (18.02 / 18.0182); a drift here desyncs the client from the server.
 */
export const MGDL_PER_MMOL = 18.0156;

/** Convert mg/dL → mmol/L. No rounding — round LAST at the display edge. */
export function mgdlToMmol(mgdl: number): number {
  return mgdl / MGDL_PER_MMOL;
}

/** Convert mmol/L → mg/dL. No rounding. */
export function mmolToMgdl(mmol: number): number {
  return mmol * MGDL_PER_MMOL;
}

/**
 * Format a stored glucose value (mg/dL) for display in the active unit.
 *
 * Converts from the precise mg/dL source ONCE and rounds LAST: an integer for
 * mg/dL, exactly one decimal for mmol/L. Returns
 * the numeric string only — pair it with {@link unitLabel} for the unit text.
 * Does not mutate or re-store the input.
 */
export function formatGlucose(valueMgdl: number, unit: GlucoseUnit): string {
  if (unit === "mmol") {
    return mgdlToMmol(valueMgdl).toFixed(1);
  }
  return Math.round(valueMgdl).toString();
}

/**
 * Format a glucose trend RATE (stored mg/dL per minute) for display.
 *
 * mg/dL/min keeps one decimal; mmol/L/min uses two because ÷18.0156 yields
 * roughly 0.06–0.17, where one decimal collapses otherwise-distinct trend
 * arrows. The trend-arrow buckets themselves stay mg/dL/min internally; this only relabels the displayed rate. Returns the
 * numeric string only; the caller supplies the `${unitLabel}/min` suffix.
 */
export function formatTrendRate(mgdlPerMin: number, unit: GlucoseUnit): string {
  if (unit === "mmol") {
    return mgdlToMmol(mgdlPerMin).toFixed(2);
  }
  return mgdlPerMin.toFixed(1);
}

/** Display label for the active unit: `"mg/dL"` | `"mmol/L"`. */
export function unitLabel(unit: GlucoseUnit): string {
  return unit === "mmol" ? "mmol/L" : "mg/dL";
}

/**
 * Numeric-input `step` for a glucose field in the active unit: 0.1 for mmol/L
 * (one decimal), 1 for mg/dL (integer).
 */
export function stepFor(unit: GlucoseUnit): number {
  return unit === "mmol" ? 0.1 : 1;
}

/**
 * Spoken unit for screen-reader announcements. Uses the British "litre"
 * spelling for mmol/L to match clinical convention in mmol markets.
 */
export function spokenUnit(unit: GlucoseUnit): string {
  return unit === "mmol"
    ? "millimoles per litre"
    : "milligrams per deciliter";
}

/**
 * Convert a stored mg/dL bound into the active unit as a NUMBER, for an input's
 * `min`/`max` attribute and the matching range hint (e.g. 20 → 1.1, 500 → 27.8).
 *
 * Uses naive 1-decimal rounding so the displayed bound matches how a stored
 * value at that bound renders (a stored 500 shows 27.8, and so does the max
 * bound — no "value above its own max" mismatch). mmol's 1-decimal granularity
 * means the displayed bound can round-trip ±1 mg/dL past the canonical limit
 * (27.8 → 501); that is contained by {@link clampMgdl} on save so the value on
 * the wire never crosses the canonical bound. mg/dL stays an integer.
 */
export function toDisplayNumber(valueMgdl: number, unit: GlucoseUnit): number {
  if (unit === "mmol") {
    return Math.round(mgdlToMmol(valueMgdl) * 10) / 10;
  }
  return Math.round(valueMgdl);
}

/**
 * Clamp a canonical mg/dL value into `[min, max]`. Applied on save AFTER
 * {@link toStoredMgdl} so a unit-rounding overshoot at the boundary (e.g. an
 * entered 27.8 mmol → 501 mg/dL against a 500 ceiling) is pinned to the
 * canonical bound rather than crossing it. This is the medical-safety
 * guarantee for threshold inputs: the stored value is ALWAYS within range.
 */
export function clampMgdl(valueMgdl: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, valueMgdl));
}

/**
 * Convert a user-entered value (in the active unit) back to the canonical
 * integer mg/dL that is stored and sent to the API.
 *
 * The value on the wire is ALWAYS integer mg/dL: mmol
 * entries round-trip through {@link mmolToMgdl} + `Math.round`, mg/dL entries
 * just round. A saved mmol value may visibly "snap" on reload (e.g.
 * 5.5 mmol → 99 mg/dL → 5.5) — this is expected and acceptable. This is the
 * medical-safety chokepoint for threshold inputs: a mis-conversion here would
 * silently move a hypo/safety limit, so it is round-trip property-tested.
 */
export function toStoredMgdl(value: number, unit: GlucoseUnit): number {
  if (unit === "mmol") {
    return Math.round(mmolToMgdl(value));
  }
  return Math.round(value);
}
