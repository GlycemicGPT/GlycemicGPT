/**
 * Shared alert-threshold defaults and canonical validation bounds.
 *
 * Both the dashboard alerts page and the settings alerts page consume these so
 * the two surfaces cannot drift apart. The four glucose bounds are canonical
 * mg/dL (never converted on the wire); the IoB bound is in units.
 */

// Keys are the API payload field names (snake_case, matching
// AlertThresholdUpdate) so these spread straight into update calls — distinct
// on purpose from GLUCOSE_THRESHOLD_BOUNDS' per-field camelCase lookup keys.
export const ALERT_THRESHOLD_DEFAULTS = {
  low_warning: 70,
  urgent_low: 55,
  high_warning: 180,
  urgent_high: 250,
  iob_warning: 3.0,
};

/**
 * Canonical mg/dL min/max for the four glucose alert thresholds.
 *
 * The per-field ranges intentionally OVERLAP (e.g. urgent-low and low-warning
 * both span 40-80) so users keep reasonable individual latitude. The required
 * ordering — urgent_low < low_warning < high_warning < urgent_high — is NOT
 * encoded here; it is enforced by cross-field validation on save in both the
 * dashboard and settings alert pages.
 */
export const GLUCOSE_THRESHOLD_BOUNDS = {
  urgentLow: { min: 30, max: 80 },
  lowWarning: { min: 40, max: 100 },
  highWarning: { min: 120, max: 300 },
  urgentHigh: { min: 150, max: 400 },
};

/** IoB alert threshold bound (units, never converted). */
export const IOB_THRESHOLD_BOUNDS = { min: 0.5, max: 20 };
