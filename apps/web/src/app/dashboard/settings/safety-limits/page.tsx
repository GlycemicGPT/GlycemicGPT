"use client";

/**
 * Safety Limits Configuration
 *
 * Allows users to configure platform-enforced safety guardrails for
 * sensor data validation and delivery rate constraints. These limits
 * are synced to the mobile app where they gate data processing.
 */

import { useState, useEffect, useCallback, useRef } from "react";
import {
  ShieldCheck,
  Loader2,
  AlertTriangle,
  Check,
  ArrowLeft,
  RotateCcw,
  Info,
} from "lucide-react";
import Link from "next/link";
import clsx from "clsx";
import {
  getSafetyLimits,
  getSafetyLimitsDefaults,
  updateSafetyLimits,
  type SafetyLimitsResponse,
  type SafetyLimitsDefaults,
} from "@/lib/api";
import { OfflineBanner } from "@/components/ui/offline-banner";
import { useUserContext } from "@/providers";

// Hardcoded fallback if the defaults endpoint is unreachable
const FALLBACK_DEFAULTS: SafetyLimitsDefaults = {
  min_glucose_mgdl: 20,
  max_glucose_mgdl: 500,
  max_basal_rate_milliunits: 15000,
  max_bolus_dose_milliunits: 25000,
};

/** Convert milliunits to units for display (3 decimal places to avoid precision loss) */
function milliunitsToUnits(mu: number): string {
  return (mu / 1000).toFixed(3).replace(/\.?0+$/, "");
}

/** Format a display string for the preview (3 decimal places max) */
function formatUnits(raw: string): string {
  const n = parseFloat(raw);
  if (isNaN(n)) return raw;
  return n.toFixed(3).replace(/\.?0+$/, "");
}

/** Convert units to milliunits for API */
function unitsToMilliunits(u: number): number {
  return Math.round(u * 1000);
}

export default function SafetyLimitsPage() {
  const { user } = useUserContext();
  const [defaults, setDefaults] = useState<SafetyLimitsDefaults>(FALLBACK_DEFAULTS);
  const [limits, setLimits] = useState<SafetyLimitsResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [isOffline, setIsOffline] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [pendingAction, setPendingAction] = useState<"save" | "reset" | null>(null);

  // Form state -- glucose in mg/dL, insulin in units (displayed) backed by milliunits
  const [minGlucose, setMinGlucose] = useState<string>("20");
  const [maxGlucose, setMaxGlucose] = useState<string>("500");
  const [maxBasal, setMaxBasal] = useState<string>("15");
  const [maxBolus, setMaxBolus] = useState<string>("25");

  const fetchLimits = useCallback(async () => {
    try {
      setIsLoading(true);
      setError(null);
      const [data, serverDefaults] = await Promise.all([
        getSafetyLimits(),
        getSafetyLimitsDefaults().catch(() => FALLBACK_DEFAULTS),
      ]);
      setLimits(data);
      setDefaults(serverDefaults);
      setMinGlucose(String(data.min_glucose_mgdl));
      setMaxGlucose(String(data.max_glucose_mgdl));
      setMaxBasal(milliunitsToUnits(data.max_basal_rate_milliunits));
      setMaxBolus(milliunitsToUnits(data.max_bolus_dose_milliunits));
      setIsOffline(false);
    } catch (err) {
      if (!(err instanceof Error && err.message.includes("401"))) {
        setIsOffline(true);
      }
      setLimits({
        id: "",
        min_glucose_mgdl: FALLBACK_DEFAULTS.min_glucose_mgdl,
        max_glucose_mgdl: FALLBACK_DEFAULTS.max_glucose_mgdl,
        max_basal_rate_milliunits: FALLBACK_DEFAULTS.max_basal_rate_milliunits,
        max_bolus_dose_milliunits: FALLBACK_DEFAULTS.max_bolus_dose_milliunits,
        updated_at: "",
      });
      setMinGlucose(String(FALLBACK_DEFAULTS.min_glucose_mgdl));
      setMaxGlucose(String(FALLBACK_DEFAULTS.max_glucose_mgdl));
      setMaxBasal(milliunitsToUnits(FALLBACK_DEFAULTS.max_basal_rate_milliunits));
      setMaxBolus(milliunitsToUnits(FALLBACK_DEFAULTS.max_bolus_dose_milliunits));
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchLimits();
  }, [fetchLimits]);

  useEffect(() => {
    if (!success) return;
    const timer = setTimeout(() => setSuccess(null), 5000);
    return () => clearTimeout(timer);
  }, [success]);

  const cancelAction = useCallback(() => {
    setShowConfirm(false);
    setPendingAction(null);
  }, []);

  const cancelButtonRef = useRef<HTMLButtonElement>(null);

  // Focus the Cancel button when the confirmation dialog appears
  useEffect(() => {
    if (showConfirm) {
      cancelButtonRef.current?.focus();
    }
  }, [showConfirm]);

  // Dismiss confirmation dialog on Escape key
  useEffect(() => {
    if (!showConfirm) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") cancelAction();
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [showConfirm, cancelAction]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (isSaving) return;

    const minG = parseInt(minGlucose, 10);
    const maxG = parseInt(maxGlucose, 10);
    const basalU = parseFloat(maxBasal);
    const bolusU = parseFloat(maxBolus);

    if ([minG, maxG].some(isNaN) || [basalU, bolusU].some(isNaN)) {
      setError("Please enter valid numbers for all fields");
      return;
    }

    if (String(minG) !== minGlucose.trim() || String(maxG) !== maxGlucose.trim()) {
      setError("Glucose values must be whole numbers (no decimals)");
      return;
    }

    if (minG >= maxG) {
      setError("Minimum glucose must be less than maximum glucose");
      return;
    }

    const basalMu = unitsToMilliunits(basalU);
    const bolusMu = unitsToMilliunits(bolusU);
    if (minG < 20 || minG > 499 || maxG < 21 || maxG > 500 ||
        basalMu < 1 || basalMu > 15000 || bolusMu < 1 || bolusMu > 25000) {
      setError("One or more values are outside the allowed range");
      return;
    }

    // Show confirmation dialog
    setPendingAction("save");
    setShowConfirm(true);
  };

  const executeSave = async () => {
    setIsSaving(true);
    setError(null);
    setSuccess(null);

    const minG = parseInt(minGlucose, 10);
    const maxG = parseInt(maxGlucose, 10);
    const basalU = parseFloat(maxBasal);
    const bolusU = parseFloat(maxBolus);
    const basalMu = unitsToMilliunits(basalU);
    const bolusMu = unitsToMilliunits(bolusU);

    try {
      const updated = await updateSafetyLimits({
        min_glucose_mgdl: minG,
        max_glucose_mgdl: maxG,
        max_basal_rate_milliunits: basalMu,
        max_bolus_dose_milliunits: bolusMu,
      });
      setLimits(updated);
      setMinGlucose(String(updated.min_glucose_mgdl));
      setMaxGlucose(String(updated.max_glucose_mgdl));
      setMaxBasal(milliunitsToUnits(updated.max_basal_rate_milliunits));
      setMaxBolus(milliunitsToUnits(updated.max_bolus_dose_milliunits));
      setSuccess("Safety limits updated successfully");
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to update safety limits"
      );
    } finally {
      setIsSaving(false);
    }
  };

  const handleReset = () => {
    if (isSaving) return;
    setPendingAction("reset");
    setShowConfirm(true);
  };

  const executeReset = async () => {
    setIsSaving(true);
    setError(null);
    setSuccess(null);

    try {
      const updated = await updateSafetyLimits({
        min_glucose_mgdl: defaults.min_glucose_mgdl,
        max_glucose_mgdl: defaults.max_glucose_mgdl,
        max_basal_rate_milliunits: defaults.max_basal_rate_milliunits,
        max_bolus_dose_milliunits: defaults.max_bolus_dose_milliunits,
      });
      setLimits(updated);
      setMinGlucose(String(updated.min_glucose_mgdl));
      setMaxGlucose(String(updated.max_glucose_mgdl));
      setMaxBasal(milliunitsToUnits(updated.max_basal_rate_milliunits));
      setMaxBolus(milliunitsToUnits(updated.max_bolus_dose_milliunits));
      setSuccess("Safety limits reset to defaults");
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to reset safety limits"
      );
    } finally {
      setIsSaving(false);
    }
  };

  const confirmAction = async () => {
    setShowConfirm(false);
    if (pendingAction === "save") {
      await executeSave();
    } else if (pendingAction === "reset") {
      await executeReset();
    }
    setPendingAction(null);
  };

  const minGNum = parseInt(minGlucose, 10);
  const maxGNum = parseInt(maxGlucose, 10);
  const basalNum = parseFloat(maxBasal);
  const bolusNum = parseFloat(maxBolus);
  const basalMuNum = isNaN(basalNum) ? NaN : unitsToMilliunits(basalNum);
  const bolusMuNum = isNaN(bolusNum) ? NaN : unitsToMilliunits(bolusNum);

  const allParsed = [minGNum, maxGNum, basalNum, bolusNum].every(
    (n) => !isNaN(n)
  );
  const hasChanges =
    limits &&
    (minGNum !== limits.min_glucose_mgdl ||
      maxGNum !== limits.max_glucose_mgdl ||
      basalMuNum !== limits.max_basal_rate_milliunits ||
      bolusMuNum !== limits.max_bolus_dose_milliunits);
  const isValid =
    allParsed &&
    minGNum >= 20 &&
    minGNum <= 499 &&
    maxGNum >= 21 &&
    maxGNum <= 500 &&
    minGNum < maxGNum &&
    basalMuNum >= 1 &&
    basalMuNum <= 15000 &&
    bolusMuNum >= 1 &&
    bolusMuNum <= 25000;

  // Auth guard: wait for user context to resolve
  if (!user) return null;

  // Role guard: only diabetic users and admins should access this page
  if (user.role === "caregiver") {
    return (
      <div className="space-y-6">
        <div>
          <Link
            href="/dashboard/settings"
            className="flex items-center gap-1 text-sm text-slate-400 hover:text-slate-300 mb-2"
          >
            <ArrowLeft className="h-4 w-4" />
            Back to Settings
          </Link>
          <h1 className="text-2xl font-bold">Safety Limits</h1>
        </div>
        <div className="bg-slate-900 rounded-xl p-6 border border-slate-800 text-center">
          <p className="text-slate-400">
            Safety limits can only be configured by the account owner.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div>
        <Link
          href="/dashboard/settings"
          className="flex items-center gap-1 text-sm text-slate-400 hover:text-slate-300 mb-2"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to Settings
        </Link>
        <h1 className="text-2xl font-bold">Safety Limits</h1>
        <p className="text-slate-400">
          Platform-enforced bounds for data validation and delivery rates
        </p>
      </div>

      {/* About Safety Limits */}
      <div className="bg-slate-900/50 rounded-xl p-5 border border-slate-800">
        <div className="flex items-start gap-3">
          <Info className="h-5 w-5 text-orange-400 shrink-0 mt-0.5" />
          <div className="space-y-2">
            <h2 className="text-sm font-semibold text-slate-200">
              About Safety Limits
            </h2>
            <p className="text-xs text-slate-400 leading-relaxed">
              Safety limits define the platform-enforced bounds that constrain
              all data processing. These guardrails operate at the platform
              level {"\u2014"} sensor readings outside the configured glucose range
              are flagged as implausible, and delivery rate parameters are
              capped at the configured maximums. These bounds are also enforced
              on any user-compiled extension modules installed into the mobile
              app (e.g., custom data sources or device integrations built using
              the GlycemicGPT plugin SDK).
            </p>
            <p className="text-xs text-slate-400 leading-relaxed">
              GlycemicGPT is an open-source data monitoring and analysis
              platform. It does not provide medical advice, diagnosis, or
              treatment. Configuration of appropriate values and any use of
              user-compiled extensions is solely the responsibility of the end
              user. The platform enforces these bounds as engineering
              constraints but makes no clinical safety guarantees. Consult your
              healthcare provider before adjusting these values. Changes sync
              to connected devices within one hour or on next app launch.
            </p>
          </div>
        </div>
      </div>

      {isOffline && (
        <OfflineBanner onRetry={fetchLimits} isRetrying={isLoading} />
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

      {/* Confirmation dialog */}
      {showConfirm && (
        <div
          className="bg-amber-500/10 rounded-xl p-4 border border-amber-500/30"
          role="alertdialog"
          aria-modal="true"
          aria-label="Confirm safety limits change"
        >
          <div className="flex items-start gap-3">
            <AlertTriangle className="h-5 w-5 text-amber-400 shrink-0 mt-0.5" />
            <div className="flex-1">
              <p className="text-sm font-medium text-amber-300">
                {pendingAction === "reset"
                  ? "Reset safety limits to defaults?"
                  : "Update safety limits?"}
              </p>
              <p className="text-xs text-slate-400 mt-1">
                These values control data validation bounds and delivery rate
                constraints enforced across the platform. Changes sync to
                connected devices. Confirm to proceed.
              </p>
              <div className="flex items-center gap-2 mt-3">
                <button
                  type="button"
                  onClick={confirmAction}
                  className={clsx(
                    "px-3 py-1.5 rounded-lg text-sm font-medium",
                    "bg-amber-600 text-white hover:bg-amber-500",
                    "transition-colors"
                  )}
                >
                  Confirm
                </button>
                <button
                  ref={cancelButtonRef}
                  type="button"
                  onClick={cancelAction}
                  className={clsx(
                    "px-3 py-1.5 rounded-lg text-sm font-medium",
                    "bg-slate-700 text-slate-300 hover:bg-slate-600",
                    "transition-colors"
                  )}
                >
                  Cancel
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {isLoading && (
        <div
          className="bg-slate-900 rounded-xl p-12 border border-slate-800 text-center"
          role="status"
          aria-label="Loading safety limits"
        >
          <Loader2 className="h-8 w-8 text-blue-400 animate-spin mx-auto mb-3" />
          <p className="text-slate-400">Loading safety limits...</p>
        </div>
      )}

      {!isLoading && (
        <form onSubmit={handleSubmit} className="space-y-6">
          {/* Glucose bounds */}
          <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
            <div className="flex items-center gap-3 mb-6">
              <div className="p-2 bg-orange-500/10 rounded-lg">
                <ShieldCheck className="h-5 w-5 text-orange-400" />
              </div>
              <div>
                <h2 className="text-lg font-semibold">Glucose Validation Bounds</h2>
                <p className="text-xs text-slate-500">
                  Readings outside these bounds are rejected as sensor errors
                </p>
              </div>
            </div>

            <div className="space-y-6">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
                {/* Min Glucose */}
                <div>
                  <label
                    htmlFor="min-glucose"
                    className="block text-sm font-medium text-slate-300 mb-1"
                  >
                    Minimum Glucose (mg/dL)
                  </label>
                  <input
                    id="min-glucose"
                    type="number"
                    min={20}
                    max={499}
                    step={1}
                    value={minGlucose}
                    onChange={(e) => setMinGlucose(e.target.value)}
                    disabled={isSaving || showConfirm}
                    aria-invalid={!isNaN(minGNum) && (minGNum < 20 || minGNum > 499) ? true : undefined}
                    className={clsx(
                      "w-full rounded-lg border px-3 py-2 text-sm",
                      "bg-slate-800 text-slate-200",
                      !isNaN(minGNum) && (minGNum < 20 || minGNum > 499)
                        ? "border-red-500 focus:ring-red-500"
                        : "border-slate-700 focus:ring-orange-500",
                      "focus:outline-none focus:ring-2 focus:border-transparent",
                      "disabled:opacity-50 disabled:cursor-not-allowed"
                    )}
                    aria-describedby="min-glucose-hint"
                  />
                  <p
                    id="min-glucose-hint"
                    className="text-xs text-slate-500 mt-1"
                  >
                    Range: 20-499 mg/dL. Default: {defaults.min_glucose_mgdl} mg/dL
                  </p>
                </div>

                {/* Max Glucose */}
                <div>
                  <label
                    htmlFor="max-glucose"
                    className="block text-sm font-medium text-slate-300 mb-1"
                  >
                    Maximum Glucose (mg/dL)
                  </label>
                  <input
                    id="max-glucose"
                    type="number"
                    min={21}
                    max={500}
                    step={1}
                    value={maxGlucose}
                    onChange={(e) => setMaxGlucose(e.target.value)}
                    disabled={isSaving || showConfirm}
                    aria-invalid={!isNaN(maxGNum) && (maxGNum < 21 || maxGNum > 500) ? true : undefined}
                    className={clsx(
                      "w-full rounded-lg border px-3 py-2 text-sm",
                      "bg-slate-800 text-slate-200",
                      !isNaN(maxGNum) && (maxGNum < 21 || maxGNum > 500)
                        ? "border-red-500 focus:ring-red-500"
                        : "border-slate-700 focus:ring-orange-500",
                      "focus:outline-none focus:ring-2 focus:border-transparent",
                      "disabled:opacity-50 disabled:cursor-not-allowed"
                    )}
                    aria-describedby="max-glucose-hint"
                  />
                  <p
                    id="max-glucose-hint"
                    className="text-xs text-slate-500 mt-1"
                  >
                    Range: 21-500 mg/dL. Default: {defaults.max_glucose_mgdl} mg/dL
                  </p>
                </div>
              </div>

              {/* Visual preview for glucose bounds */}
              {isValid && minGNum < maxGNum && (
                <div className="bg-slate-800/50 rounded-lg p-4 border border-slate-700/50">
                  <p className="text-xs text-slate-500 mb-2">Valid Glucose Range</p>
                  <p className="text-lg font-semibold text-orange-400">
                    {minGNum} - {maxGNum} mg/dL
                  </p>
                  <p className="text-xs text-slate-500 mt-1">
                    Readings below {minGNum} or above {maxGNum} mg/dL will be
                    rejected as sensor errors
                  </p>
                </div>
              )}
            </div>
          </div>

          {/* Delivery rate constraints */}
          <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
            <div className="flex items-center gap-3 mb-6">
              <div className="p-2 bg-orange-500/10 rounded-lg">
                <ShieldCheck className="h-5 w-5 text-orange-400" />
              </div>
              <div>
                <h2 className="text-lg font-semibold">Delivery Rate Constraints</h2>
                <p className="text-xs text-slate-500">
                  Maximum delivery rates enforced by the platform
                </p>
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
              {/* Max Basal Rate */}
              <div>
                <label
                  htmlFor="max-basal"
                  className="block text-sm font-medium text-slate-300 mb-1"
                >
                  Max Basal Rate (u/hr)
                </label>
                <input
                  id="max-basal"
                  type="number"
                  min={0.001}
                  max={15}
                  step="any"
                  value={maxBasal}
                  onChange={(e) => setMaxBasal(e.target.value)}
                  disabled={isSaving || showConfirm}
                  aria-invalid={!isNaN(basalMuNum) && (basalMuNum < 1 || basalMuNum > 15000) ? true : undefined}
                  className={clsx(
                    "w-full rounded-lg border px-3 py-2 text-sm",
                    "bg-slate-800 text-slate-200",
                    !isNaN(basalMuNum) && (basalMuNum < 1 || basalMuNum > 15000)
                      ? "border-red-500 focus:ring-red-500"
                      : "border-slate-700 focus:ring-orange-500",
                    "focus:outline-none focus:ring-2 focus:border-transparent",
                    "disabled:opacity-50 disabled:cursor-not-allowed"
                  )}
                  aria-describedby="max-basal-hint"
                />
                <p
                  id="max-basal-hint"
                  className="text-xs text-slate-500 mt-1"
                >
                  Range: 0.001-15.0 u/hr. Default: {milliunitsToUnits(defaults.max_basal_rate_milliunits)} u/hr
                </p>
              </div>

              {/* Max Bolus Dose */}
              <div>
                <label
                  htmlFor="max-bolus"
                  className="block text-sm font-medium text-slate-300 mb-1"
                >
                  Max Bolus Dose (units)
                </label>
                <input
                  id="max-bolus"
                  type="number"
                  min={0.001}
                  max={25}
                  step="any"
                  value={maxBolus}
                  onChange={(e) => setMaxBolus(e.target.value)}
                  disabled={isSaving || showConfirm}
                  aria-invalid={!isNaN(bolusMuNum) && (bolusMuNum < 1 || bolusMuNum > 25000) ? true : undefined}
                  className={clsx(
                    "w-full rounded-lg border px-3 py-2 text-sm",
                    "bg-slate-800 text-slate-200",
                    !isNaN(bolusMuNum) && (bolusMuNum < 1 || bolusMuNum > 25000)
                      ? "border-red-500 focus:ring-red-500"
                      : "border-slate-700 focus:ring-orange-500",
                    "focus:outline-none focus:ring-2 focus:border-transparent",
                    "disabled:opacity-50 disabled:cursor-not-allowed"
                  )}
                  aria-describedby="max-bolus-hint"
                />
                <p
                  id="max-bolus-hint"
                  className="text-xs text-slate-500 mt-1"
                >
                  Range: 0.001-25.0 units. Default: {milliunitsToUnits(defaults.max_bolus_dose_milliunits)} units
                </p>
              </div>
            </div>

            {/* Visual preview for insulin limits */}
            {isValid && (
              <div className="bg-slate-800/50 rounded-lg p-4 border border-slate-700/50 mt-6">
                <p className="text-xs text-slate-500 mb-2">Active Limits</p>
                <div className="flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-6">
                  <p className="text-sm text-orange-400">
                    <span className="font-semibold">{formatUnits(maxBasal)}</span> u/hr max basal
                  </p>
                  <p className="text-sm text-orange-400">
                    <span className="font-semibold">{formatUnits(maxBolus)}</span> units max bolus
                  </p>
                </div>
              </div>
            )}
          </div>

          {/* Actions */}
          <div className="flex items-center gap-3">
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
                (limits?.min_glucose_mgdl === defaults.min_glucose_mgdl &&
                  limits?.max_glucose_mgdl === defaults.max_glucose_mgdl &&
                  limits?.max_basal_rate_milliunits === defaults.max_basal_rate_milliunits &&
                  limits?.max_bolus_dose_milliunits === defaults.max_bolus_dose_milliunits)
              }
              className={clsx(
                "flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium",
                "bg-slate-800 text-slate-300 hover:bg-slate-700",
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
      )}

      {/* Platform disclaimer */}
      <div className="bg-slate-900/50 rounded-xl p-4 border border-slate-800">
        <p className="text-xs text-slate-500 leading-relaxed">
          Always consult a qualified healthcare professional regarding diabetes
          management decisions. GlycemicGPT is not a medical device and makes
          no clinical safety guarantees.
        </p>
      </div>
    </div>
  );
}
