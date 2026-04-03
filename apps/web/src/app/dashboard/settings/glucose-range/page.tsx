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
import { OfflineBanner } from "@/components/ui/offline-banner";

const DEFAULTS = {
  urgent_low: 55,
  low_target: 70,
  high_target: 180,
  urgent_high: 250,
};

export default function GlucoseRangePage() {
  const [range, setRange] = useState<TargetGlucoseRangeResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [isOffline, setIsOffline] = useState(false);

  // Form state
  const [urgentLow, setUrgentLow] = useState<string>("55");
  const [lowTarget, setLowTarget] = useState<string>("70");
  const [highTarget, setHighTarget] = useState<string>("180");
  const [urgentHigh, setUrgentHigh] = useState<string>("250");

  const fetchRange = useCallback(async () => {
    try {
      setError(null);
      const data = await getTargetGlucoseRange();
      setRange(data);
      setUrgentLow(String(data.urgent_low));
      setLowTarget(String(data.low_target));
      setHighTarget(String(data.high_target));
      setUrgentHigh(String(data.urgent_high));
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
  }, []);

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

    const ul = parseFloat(urgentLow);
    const low = parseFloat(lowTarget);
    const high = parseFloat(highTarget);
    const uh = parseFloat(urgentHigh);

    if ([ul, low, high, uh].some(isNaN)) {
      setError("Please enter valid numbers for all fields");
      setIsSaving(false);
      return;
    }

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
      setUrgentLow(String(DEFAULTS.urgent_low));
      setLowTarget(String(DEFAULTS.low_target));
      setHighTarget(String(DEFAULTS.high_target));
      setUrgentHigh(String(DEFAULTS.urgent_high));
      setSuccess("Glucose thresholds reset to defaults");
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to reset thresholds"
      );
    } finally {
      setIsSaving(false);
    }
  };

  const ulNum = parseFloat(urgentLow);
  const lowNum = parseFloat(lowTarget);
  const highNum = parseFloat(highTarget);
  const uhNum = parseFloat(urgentHigh);
  const allParsed = [ulNum, lowNum, highNum, uhNum].every((n) => !isNaN(n));
  const hasChanges =
    range &&
    (ulNum !== range.urgent_low ||
      lowNum !== range.low_target ||
      highNum !== range.high_target ||
      uhNum !== range.urgent_high);
  const isValid =
    allParsed &&
    ulNum >= 30 &&
    ulNum <= 70 &&
    lowNum >= 40 &&
    lowNum <= 200 &&
    highNum >= 80 &&
    highNum <= 400 &&
    uhNum >= 200 &&
    uhNum <= 500 &&
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
                  Urgent Low (mg/dL)
                </label>
                <input
                  id="urgent-low"
                  type="number"
                  min={30}
                  max={70}
                  step={1}
                  value={urgentLow}
                  onChange={(e) => setUrgentLow(e.target.value)}
                  disabled={isSaving}
                  className={clsx(
                    "w-full rounded-lg border px-3 py-2 text-sm",
                    "bg-slate-100 dark:bg-slate-800 border-slate-300 dark:border-slate-700 text-slate-900 dark:text-slate-200",
                    "focus:outline-none focus:ring-2 focus:ring-red-500 focus:border-transparent",
                    "disabled:opacity-50 disabled:cursor-not-allowed"
                  )}
                  aria-describedby="urgent-low-hint"
                />
                <p
                  id="urgent-low-hint"
                  className="text-xs text-slate-500 mt-1"
                >
                  Range: 30-70 mg/dL. Default: 55 mg/dL
                </p>
              </div>

              {/* Low Target */}
              <div>
                <label
                  htmlFor="low-target"
                  className="block text-sm font-medium text-amber-400 mb-1"
                >
                  Low Target (mg/dL)
                </label>
                <input
                  id="low-target"
                  type="number"
                  min={40}
                  max={200}
                  step={1}
                  value={lowTarget}
                  onChange={(e) => setLowTarget(e.target.value)}
                  disabled={isSaving}
                  className={clsx(
                    "w-full rounded-lg border px-3 py-2 text-sm",
                    "bg-slate-100 dark:bg-slate-800 border-slate-300 dark:border-slate-700 text-slate-900 dark:text-slate-200",
                    "focus:outline-none focus:ring-2 focus:ring-amber-500 focus:border-transparent",
                    "disabled:opacity-50 disabled:cursor-not-allowed"
                  )}
                  aria-describedby="low-target-hint"
                />
                <p id="low-target-hint" className="text-xs text-slate-500 mt-1">
                  Range: 40-200 mg/dL. Default: 70 mg/dL
                </p>
              </div>

              {/* High Target */}
              <div>
                <label
                  htmlFor="high-target"
                  className="block text-sm font-medium text-amber-400 mb-1"
                >
                  High Target (mg/dL)
                </label>
                <input
                  id="high-target"
                  type="number"
                  min={80}
                  max={400}
                  step={1}
                  value={highTarget}
                  onChange={(e) => setHighTarget(e.target.value)}
                  disabled={isSaving}
                  className={clsx(
                    "w-full rounded-lg border px-3 py-2 text-sm",
                    "bg-slate-100 dark:bg-slate-800 border-slate-300 dark:border-slate-700 text-slate-900 dark:text-slate-200",
                    "focus:outline-none focus:ring-2 focus:ring-amber-500 focus:border-transparent",
                    "disabled:opacity-50 disabled:cursor-not-allowed"
                  )}
                  aria-describedby="high-target-hint"
                />
                <p
                  id="high-target-hint"
                  className="text-xs text-slate-500 mt-1"
                >
                  Range: 80-400 mg/dL. Default: 180 mg/dL
                </p>
              </div>

              {/* Urgent High */}
              <div>
                <label
                  htmlFor="urgent-high"
                  className="block text-sm font-medium text-red-400 mb-1"
                >
                  Urgent High (mg/dL)
                </label>
                <input
                  id="urgent-high"
                  type="number"
                  min={200}
                  max={500}
                  step={1}
                  value={urgentHigh}
                  onChange={(e) => setUrgentHigh(e.target.value)}
                  disabled={isSaving}
                  className={clsx(
                    "w-full rounded-lg border px-3 py-2 text-sm",
                    "bg-slate-100 dark:bg-slate-800 border-slate-300 dark:border-slate-700 text-slate-900 dark:text-slate-200",
                    "focus:outline-none focus:ring-2 focus:ring-red-500 focus:border-transparent",
                    "disabled:opacity-50 disabled:cursor-not-allowed"
                  )}
                  aria-describedby="urgent-high-hint"
                />
                <p
                  id="urgent-high-hint"
                  className="text-xs text-slate-500 mt-1"
                >
                  Range: 200-500 mg/dL. Default: 250 mg/dL
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
                    Target: {lowNum}-{highNum} mg/dL
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
                  "focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500",
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
                  "focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-500",
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
          target range for most people with diabetes is 70-180 mg/dL with urgent
          thresholds at 55 and 250 mg/dL. Consult your healthcare provider
          before changing these values.
        </p>
      </div>
    </div>
  );
}
