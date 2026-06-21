"use client";

/**
 * Target Glucose Range Configuration
 *
 * Allows users to set all four glucose thresholds:
 * urgent_low, low_target, high_target, urgent_high.
 */

import { useState, useEffect, useCallback } from "react";
import {
  Target,
  Loader2,
  AlertTriangle,
  Check,
  ArrowLeft,
  RotateCcw,
} from "lucide-react";
import Link from "next/link";
import clsx from "clsx";
import {
  getTargetGlucoseRange,
  updateTargetGlucoseRange,
  type TargetGlucoseRangeResponse,
} from "@/lib/api";
import {
  toDisplayNumber,
  clampMgdl,
  toStoredMgdl,
  formatGlucose,
  unitLabel,
  stepFor,
} from "@/lib/glucose-units";
import { useGlucoseUnit } from "@/hooks/use-glucose-unit";
import { OfflineBanner } from "@/components/ui/offline-banner";

// All thresholds are stored and validated in canonical mg/dL (locked decision
// 6). The form displays/accepts the active unit and converts on the edges.
const DEFAULTS = {
  urgent_low: 55,
  low_target: 70,
  high_target: 180,
  urgent_high: 250,
};

// mg/dL validation bounds per field (never converted).
const BOUNDS = {
  urgentLow: { min: 30, max: 70 },
  lowTarget: { min: 40, max: 200 },
  highTarget: { min: 80, max: 400 },
  urgentHigh: { min: 200, max: 500 },
};

export default function GlucoseRangePage() {
  const [range, setRange] = useState<TargetGlucoseRangeResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [isOffline, setIsOffline] = useState(false);

  const unit = useGlucoseUnit();
  // Display a stored mg/dL threshold as the active-unit string for an input.
  const toDisplay = useCallback(
    (mgdl: number) => formatGlucose(mgdl, unit),
    [unit]
  );

  // Form state (holds DISPLAY-unit strings; converted to mg/dL on save).
  const [urgentLow, setUrgentLow] = useState<string>("55");
  const [lowTarget, setLowTarget] = useState<string>("70");
  const [highTarget, setHighTarget] = useState<string>("180");
  const [urgentHigh, setUrgentHigh] = useState<string>("250");

  const fetchRange = useCallback(async () => {
    try {
      setError(null);
      const data = await getTargetGlucoseRange();
      setRange(data);
      setUrgentLow(toDisplay(data.urgent_low));
      setLowTarget(toDisplay(data.low_target));
      setHighTarget(toDisplay(data.high_target));
      setUrgentHigh(toDisplay(data.urgent_high));
      setIsOffline(false);
    } catch (err) {
      if (!(err instanceof Error && err.message.includes("401"))) {
        setIsOffline(true);
      }
      setRange({
        urgent_low: DEFAULTS.urgent_low,
        low_target: DEFAULTS.low_target,
        high_target: DEFAULTS.high_target,
        urgent_high: DEFAULTS.urgent_high,
      } as TargetGlucoseRangeResponse);
    } finally {
      setIsLoading(false);
    }
  }, [toDisplay]);

  useEffect(() => {
    fetchRange();
  }, [fetchRange]);

  useEffect(() => {
    if (!success) return;
    const timer = setTimeout(() => setSuccess(null), 5000);
    return () => clearTimeout(timer);
  }, [success]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSaving(true);
    setError(null);
    setSuccess(null);

    const ulInput = parseFloat(urgentLow);
    const lowInput = parseFloat(lowTarget);
    const highInput = parseFloat(highTarget);
    const uhInput = parseFloat(urgentHigh);

    if ([ulInput, lowInput, highInput, uhInput].some(isNaN)) {
      setError("Please enter valid numbers for all fields");
      setIsSaving(false);
      return;
    }

    // Convert the entered display values back to canonical integer mg/dL,
    // CLAMPED to each field's bound so a boundary
    // unit-rounding overshoot (e.g. 27.8 mmol -> 501) never crosses the bound.
    const ul = clampMgdl(toStoredMgdl(ulInput, unit), BOUNDS.urgentLow.min, BOUNDS.urgentLow.max);
    const low = clampMgdl(toStoredMgdl(lowInput, unit), BOUNDS.lowTarget.min, BOUNDS.lowTarget.max);
    const high = clampMgdl(toStoredMgdl(highInput, unit), BOUNDS.highTarget.min, BOUNDS.highTarget.max);
    const uh = clampMgdl(toStoredMgdl(uhInput, unit), BOUNDS.urgentHigh.min, BOUNDS.urgentHigh.max);

    if (!(ul < low && low < high && high < uh)) {
      setError(
        "Thresholds must be in ascending order: Urgent Low < Low < High < Urgent High"
      );
      setIsSaving(false);
      return;
    }

    try {
      const updated = await updateTargetGlucoseRange({
        urgent_low: ul,
        low_target: low,
        high_target: high,
        urgent_high: uh,
      });
      setRange(updated);
      // Re-sync inputs to the canonical-converted display values; a saved mmol
      // value may visibly "snap" (e.g. 5.5 -> 99 mg/dL -> 5.5). Expected.
      setUrgentLow(toDisplay(updated.urgent_low));
      setLowTarget(toDisplay(updated.low_target));
      setHighTarget(toDisplay(updated.high_target));
      setUrgentHigh(toDisplay(updated.urgent_high));
      setSuccess("Glucose thresholds updated successfully");
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to update thresholds"
      );
    } finally {
      setIsSaving(false);
    }
  };

  const handleReset = async () => {
    setIsSaving(true);
    setError(null);
    setSuccess(null);

    try {
      const updated = await updateTargetGlucoseRange({
        urgent_low: DEFAULTS.urgent_low,
        low_target: DEFAULTS.low_target,
        high_target: DEFAULTS.high_target,
        urgent_high: DEFAULTS.urgent_high,
      });
      setRange(updated);
      setUrgentLow(toDisplay(DEFAULTS.urgent_low));
      setLowTarget(toDisplay(DEFAULTS.low_target));
      setHighTarget(toDisplay(DEFAULTS.high_target));
      setUrgentHigh(toDisplay(DEFAULTS.urgent_high));
      setSuccess("Glucose thresholds reset to defaults");
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to reset thresholds"
      );
    } finally {
      setIsSaving(false);
    }
  };

  // Display-unit values (what the user typed / sees in the inputs + preview).
  const ulNum = parseFloat(urgentLow);
  const lowNum = parseFloat(lowTarget);
  const highNum = parseFloat(highTarget);
  const uhNum = parseFloat(urgentHigh);
  const allParsed = [ulNum, lowNum, highNum, uhNum].every((n) => !isNaN(n));
  // Range validity in DISPLAY space so the displayed bound is accepted; the
  // saved value is clamped to canonical mg/dL.
  const inRange = (v: number, b: { min: number; max: number }) =>
    v >= toDisplayNumber(b.min, unit) && v <= toDisplayNumber(b.max, unit);
  // Compare in display space so the load-time round-trip "snap" doesn't read
  // as an unsaved change.
  const hasChanges =
    range &&
    (urgentLow !== toDisplay(range.urgent_low) ||
      lowTarget !== toDisplay(range.low_target) ||
      highTarget !== toDisplay(range.high_target) ||
      urgentHigh !== toDisplay(range.urgent_high));
  const isValid =
    allParsed &&
    inRange(ulNum, BOUNDS.urgentLow) &&
    inRange(lowNum, BOUNDS.lowTarget) &&
    inRange(highNum, BOUNDS.highTarget) &&
    inRange(uhNum, BOUNDS.urgentHigh) &&
    ulNum < lowNum &&
    lowNum < highNum &&
    highNum < uhNum;

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div>
        <Link
          href="/dashboard/settings"
          className="flex items-center gap-1 text-sm text-slate-500 dark:text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 mb-2"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to Settings
        </Link>
        <h1 className="text-2xl font-bold">Glucose Thresholds</h1>
        <p className="text-slate-500 dark:text-slate-400">
          Configure your glucose range thresholds for charts, alerts, and AI
          analysis
        </p>
      </div>

      {isOffline && (
        <OfflineBanner onRetry={fetchRange} isRetrying={isLoading} />
      )}

      {error && (
        <div
          className="bg-red-500/10 rounded-xl p-4 border border-red-500/20"
          role="alert"
        >
          <div className="flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-red-400 shrink-0" />
            <p className="text-sm text-red-400">{error}</p>
          </div>
        </div>
      )}

      {success && (
        <div
          className="bg-green-500/10 rounded-xl p-4 border border-green-500/20"
          role="status"
        >
          <div className="flex items-center gap-2">
            <Check className="h-4 w-4 text-green-400 shrink-0" />
            <p className="text-sm text-green-400">{success}</p>
          </div>
        </div>
      )}

      {isLoading && (
        <div
          className="bg-white dark:bg-slate-900 rounded-xl p-12 border border-slate-200 dark:border-slate-800 text-center"
          role="status"
          aria-label="Loading glucose thresholds"
        >
          <Loader2 className="h-8 w-8 text-blue-400 animate-spin mx-auto mb-3" />
          <p className="text-slate-500 dark:text-slate-400">Loading thresholds...</p>
        </div>
      )}

      {!isLoading && (
        <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-6">
          <div className="flex items-center gap-3 mb-6">
            <div className="p-2 bg-green-500/10 rounded-lg">
              <Target className="h-5 w-5 text-green-400" />
            </div>
            <div>
              <h2 className="text-lg font-semibold">Threshold Settings</h2>
              <p className="text-xs text-slate-500">
                Used by Time in Range, glucose charts, color coding, and alerts
              </p>
            </div>
          </div>

          <form onSubmit={handleSubmit} className="space-y-6">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
              {/* Urgent Low */}
              <div>
                <label
                  htmlFor="urgent-low"
                  className="block text-sm font-medium text-red-400 mb-1"
                >
                  Urgent Low ({unitLabel(unit)})
                </label>
                <input
                  id="urgent-low"
                  type="number"
                  min={toDisplayNumber(BOUNDS.urgentLow.min, unit)}
                  max={toDisplayNumber(BOUNDS.urgentLow.max, unit)}
                  step={stepFor(unit)}
                  value={urgentLow}
                  onChange={(e) => setUrgentLow(e.target.value)}
                  disabled={isSaving}
                  className={clsx(
                    "w-full rounded-lg border px-3 py-2 text-sm",
                    "bg-slate-100 dark:bg-slate-800 border-slate-300 dark:border-slate-700 text-slate-900 dark:text-slate-200",
                    "focus:outline-hidden focus:ring-2 focus:ring-red-500 focus:border-transparent",
                    "disabled:opacity-50 disabled:cursor-not-allowed"
                  )}
                  aria-describedby="urgent-low-hint"
                />
                <p
                  id="urgent-low-hint"
                  className="text-xs text-slate-500 mt-1"
                >
                  Range: {toDisplayNumber(BOUNDS.urgentLow.min, unit)}-{toDisplayNumber(BOUNDS.urgentLow.max, unit)} {unitLabel(unit)}. Default: {toDisplay(DEFAULTS.urgent_low)} {unitLabel(unit)}
                </p>
              </div>

              {/* Low Target */}
              <div>
                <label
                  htmlFor="low-target"
                  className="block text-sm font-medium text-amber-400 mb-1"
                >
                  Low Target ({unitLabel(unit)})
                </label>
                <input
                  id="low-target"
                  type="number"
                  min={toDisplayNumber(BOUNDS.lowTarget.min, unit)}
                  max={toDisplayNumber(BOUNDS.lowTarget.max, unit)}
                  step={stepFor(unit)}
                  value={lowTarget}
                  onChange={(e) => setLowTarget(e.target.value)}
                  disabled={isSaving}
                  className={clsx(
                    "w-full rounded-lg border px-3 py-2 text-sm",
                    "bg-slate-100 dark:bg-slate-800 border-slate-300 dark:border-slate-700 text-slate-900 dark:text-slate-200",
                    "focus:outline-hidden focus:ring-2 focus:ring-amber-500 focus:border-transparent",
                    "disabled:opacity-50 disabled:cursor-not-allowed"
                  )}
                  aria-describedby="low-target-hint"
                />
                <p id="low-target-hint" className="text-xs text-slate-500 mt-1">
                  Range: {toDisplayNumber(BOUNDS.lowTarget.min, unit)}-{toDisplayNumber(BOUNDS.lowTarget.max, unit)} {unitLabel(unit)}. Default: {toDisplay(DEFAULTS.low_target)} {unitLabel(unit)}
                </p>
              </div>

              {/* High Target */}
              <div>
                <label
                  htmlFor="high-target"
                  className="block text-sm font-medium text-amber-400 mb-1"
                >
                  High Target ({unitLabel(unit)})
                </label>
                <input
                  id="high-target"
                  type="number"
                  min={toDisplayNumber(BOUNDS.highTarget.min, unit)}
                  max={toDisplayNumber(BOUNDS.highTarget.max, unit)}
                  step={stepFor(unit)}
                  value={highTarget}
                  onChange={(e) => setHighTarget(e.target.value)}
                  disabled={isSaving}
                  className={clsx(
                    "w-full rounded-lg border px-3 py-2 text-sm",
                    "bg-slate-100 dark:bg-slate-800 border-slate-300 dark:border-slate-700 text-slate-900 dark:text-slate-200",
                    "focus:outline-hidden focus:ring-2 focus:ring-amber-500 focus:border-transparent",
                    "disabled:opacity-50 disabled:cursor-not-allowed"
                  )}
                  aria-describedby="high-target-hint"
                />
                <p
                  id="high-target-hint"
                  className="text-xs text-slate-500 mt-1"
                >
                  Range: {toDisplayNumber(BOUNDS.highTarget.min, unit)}-{toDisplayNumber(BOUNDS.highTarget.max, unit)} {unitLabel(unit)}. Default: {toDisplay(DEFAULTS.high_target)} {unitLabel(unit)}
                </p>
              </div>

              {/* Urgent High */}
              <div>
                <label
                  htmlFor="urgent-high"
                  className="block text-sm font-medium text-red-400 mb-1"
                >
                  Urgent High ({unitLabel(unit)})
                </label>
                <input
                  id="urgent-high"
                  type="number"
                  min={toDisplayNumber(BOUNDS.urgentHigh.min, unit)}
                  max={toDisplayNumber(BOUNDS.urgentHigh.max, unit)}
                  step={stepFor(unit)}
                  value={urgentHigh}
                  onChange={(e) => setUrgentHigh(e.target.value)}
                  disabled={isSaving}
                  className={clsx(
                    "w-full rounded-lg border px-3 py-2 text-sm",
                    "bg-slate-100 dark:bg-slate-800 border-slate-300 dark:border-slate-700 text-slate-900 dark:text-slate-200",
                    "focus:outline-hidden focus:ring-2 focus:ring-red-500 focus:border-transparent",
                    "disabled:opacity-50 disabled:cursor-not-allowed"
                  )}
                  aria-describedby="urgent-high-hint"
                />
                <p
                  id="urgent-high-hint"
                  className="text-xs text-slate-500 mt-1"
                >
                  Range: {toDisplayNumber(BOUNDS.urgentHigh.min, unit)}-{toDisplayNumber(BOUNDS.urgentHigh.max, unit)} {unitLabel(unit)}. Default: {toDisplay(DEFAULTS.urgent_high)} {unitLabel(unit)}
                </p>
              </div>
            </div>

            {/* Visual preview */}
            {isValid && (
              <div className="bg-slate-100/50 dark:bg-slate-800/50 rounded-lg p-4 border border-slate-300/50 dark:border-slate-700/50">
                <p className="text-xs text-slate-500 mb-2">Preview</p>
                <div className="flex items-center gap-2 text-sm">
                  <span className="text-red-400 font-medium">{ulNum}</span>
                  <span className="text-slate-600">|</span>
                  <span className="text-amber-400 font-medium">{lowNum}</span>
                  <span className="text-slate-600">---</span>
                  <span className="text-lg font-semibold text-green-400">
                    Target: {lowNum}-{highNum} {unitLabel(unit)}
                  </span>
                  <span className="text-slate-600">---</span>
                  <span className="text-amber-400 font-medium">{highNum}</span>
                  <span className="text-slate-600">|</span>
                  <span className="text-red-400 font-medium">{uhNum}</span>
                </div>
              </div>
            )}

            {/* Actions */}
            <div className="flex items-center gap-3 pt-2">
              <button
                type="submit"
                disabled={isSaving || !hasChanges || !isValid || isOffline}
                title={isOffline ? "Cannot save while disconnected" : undefined}
                className={clsx(
                  "flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium",
                  "bg-blue-600 text-white hover:bg-blue-500",
                  "transition-colors",
                  "focus:outline-hidden focus-visible:ring-2 focus-visible:ring-blue-500",
                  "disabled:opacity-50 disabled:cursor-not-allowed"
                )}
              >
                {isSaving ? (
                  <Loader2
                    className="h-4 w-4 animate-spin"
                    aria-hidden="true"
                  />
                ) : (
                  <Check className="h-4 w-4" aria-hidden="true" />
                )}
                {isSaving ? "Saving..." : "Save Changes"}
              </button>

              <button
                type="button"
                onClick={handleReset}
                disabled={
                  isSaving ||
                  isOffline ||
                  (range?.urgent_low === DEFAULTS.urgent_low &&
                    range?.low_target === DEFAULTS.low_target &&
                    range?.high_target === DEFAULTS.high_target &&
                    range?.urgent_high === DEFAULTS.urgent_high)
                }
                className={clsx(
                  "flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium",
                  "bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700",
                  "transition-colors",
                  "focus:outline-hidden focus-visible:ring-2 focus-visible:ring-slate-500",
                  "disabled:opacity-50 disabled:cursor-not-allowed"
                )}
              >
                <RotateCcw className="h-4 w-4" aria-hidden="true" />
                Reset to Defaults
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Info card */}
      <div className="bg-slate-50/50 dark:bg-slate-900/50 rounded-xl p-4 border border-slate-200 dark:border-slate-800">
        <p className="text-xs text-slate-500">
          These thresholds control how glucose values are color-coded on your
          dashboard, where the target range band appears on charts, and what
          counts as &quot;in range&quot; for the Time in Range bar. They also
          influence AI-generated suggestions and alert triggers. The standard
          target range for most people with diabetes is {toDisplay(70)}-{toDisplay(180)}{" "}
          {unitLabel(unit)} with urgent thresholds at {toDisplay(55)} and{" "}
          {toDisplay(250)} {unitLabel(unit)}. Consult your healthcare provider
          before changing these values.
        </p>
      </div>
    </div>
  );
}
