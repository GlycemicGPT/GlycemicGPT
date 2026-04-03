/**
 * Shared chart time period constants.
 *
 * Single source of truth for period type, minute mappings, and millisecond
 * mappings used by glucose history, pump events, and chart components.
 */

export type ChartTimePeriod = "3h" | "6h" | "12h" | "24h" | "3d" | "7d" | "14d" | "30d";

export const PERIOD_TO_MINUTES: Record<ChartTimePeriod, number> = {
  "3h": 180,
  "6h": 360,
  "12h": 720,
  "24h": 1440,
  "3d": 4320,
  "7d": 10080,
  "14d": 20160,
  "30d": 43200,
};

export const PERIOD_TO_MS: Record<ChartTimePeriod, number> = {
  "3h": 3 * 60 * 60 * 1000,
  "6h": 6 * 60 * 60 * 1000,
  "12h": 12 * 60 * 60 * 1000,
  "24h": 24 * 60 * 60 * 1000,
  "3d": 3 * 24 * 60 * 60 * 1000,
  "7d": 7 * 24 * 60 * 60 * 1000,
  "14d": 14 * 24 * 60 * 60 * 1000,
  "30d": 30 * 24 * 60 * 60 * 1000,
};

/** Returns true if the period represents multiple days (>= 3d) */
export function isMultiDay(period: ChartTimePeriod): boolean {
  return period.endsWith("d");
}
