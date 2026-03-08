"use client";

/**
 * Insulin Configuration Page
 *
 * Allows users to select their insulin type and configure DIA (Duration of
 * Insulin Action) used for IoB decay calculations.
 */

import { useState, useEffect, useCallback } from "react";
import {
  Syringe,
  Loader2,
  AlertTriangle,
  Check,
  ArrowLeft,
  RotateCcw,
} from "lucide-react";
import Link from "next/link";
import clsx from "clsx";
import {
  getInsulinConfig,
  updateInsulinConfig,
  getInsulinConfigDefaults,
  type InsulinConfigResponse,
  type InsulinPresets,
} from "@/lib/api";
import { OfflineBanner } from "@/components/ui/offline-banner";

type SavedConfig = Pick<InsulinConfigResponse, "insulin_type" | "dia_hours" | "onset_minutes">;

const DEFAULTS = {
  insulin_type: "humalog",
  dia_hours: 4.0,
  onset_minutes: 15.0,
};

// Hardcoded fallback so the page works when the API is unreachable
const FALLBACK_PRESETS: InsulinPresets = {
  humalog: { dia_hours: 4.0, onset_minutes: 15.0 },
  novolog: { dia_hours: 4.0, onset_minutes: 15.0 },
  fiasp: { dia_hours: 3.5, onset_minutes: 5.0 },
  lyumjev: { dia_hours: 3.5, onset_minutes: 5.0 },
  apidra: { dia_hours: 4.0, onset_minutes: 15.0 },
};

const INSULIN_LABELS: Record<string, string> = {
  humalog: "Humalog (Lispro)",
  novolog: "NovoLog (Aspart)",
  fiasp: "Fiasp (Faster Aspart)",
  lyumjev: "Lyumjev (Faster Lispro)",
  apidra: "Apidra (Glulisine)",
  custom: "Custom",
};

export default function InsulinConfigPage() {
  const [config, setConfig] = useState<SavedConfig | null>(null);
  const [presets, setPresets] = useState<InsulinPresets>({});
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [isOffline, setIsOffline] = useState(false);

  // Form state
  const [insulinType, setInsulinType] = useState<string>("humalog");
  const [diaHours, setDiaHours] = useState<string>("4.0");
  const [onsetMinutes, setOnsetMinutes] = useState<string>("15");

  const fetchConfig = useCallback(async () => {
    try {
      setError(null);
      const [configData, defaults] = await Promise.all([
        getInsulinConfig(),
        getInsulinConfigDefaults(),
      ]);
      setConfig(configData);
      setPresets(defaults.presets);
      setInsulinType(configData.insulin_type);
      setDiaHours(String(configData.dia_hours));
      setOnsetMinutes(String(configData.onset_minutes));
      setIsOffline(false);
    } catch (err) {
      if (!(err instanceof Error && err.message.includes("401"))) {
        setIsOffline(true);
      }
      setPresets(FALLBACK_PRESETS);
      setConfig({
        insulin_type: DEFAULTS.insulin_type,
        dia_hours: DEFAULTS.dia_hours,
        onset_minutes: DEFAULTS.onset_minutes,
      });
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchConfig();
  }, [fetchConfig]);

  // Auto-clear success message after 5 seconds
  useEffect(() => {
    if (!success) return;
    const timer = setTimeout(() => setSuccess(null), 5000);
    return () => clearTimeout(timer);
  }, [success]);

  // When insulin type changes (and it's a preset), auto-populate DIA/onset
  const handleInsulinTypeChange = (newType: string) => {
    setInsulinType(newType);
    const preset = presets[newType];
    if (preset) {
      setDiaHours(String(preset.dia_hours));
      setOnsetMinutes(String(preset.onset_minutes));
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSaving(true);
    setError(null);
    setSuccess(null);

    const dia = parseFloat(diaHours);
    const onset = parseFloat(onsetMinutes);

    if (isNaN(dia) || isNaN(onset)) {
      setError("Please enter valid numbers");
      setIsSaving(false);
      return;
    }

    try {
      const updated = await updateInsulinConfig({
        insulin_type: insulinType,
        dia_hours: dia,
        onset_minutes: onset,
      });
      setConfig(updated);
      setSuccess("Insulin configuration updated successfully");
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to update insulin config"
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
      const updated = await updateInsulinConfig({
        insulin_type: DEFAULTS.insulin_type,
        dia_hours: DEFAULTS.dia_hours,
        onset_minutes: DEFAULTS.onset_minutes,
      });
      setConfig(updated);
      setInsulinType(DEFAULTS.insulin_type);
      setDiaHours(String(DEFAULTS.dia_hours));
      setOnsetMinutes(String(DEFAULTS.onset_minutes));
      setSuccess("Insulin configuration reset to defaults");
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to reset insulin config"
      );
    } finally {
      setIsSaving(false);
    }
  };

  const diaNum = parseFloat(diaHours);
  const onsetNum = parseFloat(onsetMinutes);
  const hasChanges =
    config &&
    (insulinType !== config.insulin_type ||
      parseFloat(diaHours) !== config.dia_hours ||
      parseFloat(onsetMinutes) !== config.onset_minutes);
  const isValid =
    !isNaN(diaNum) &&
    !isNaN(onsetNum) &&
    diaNum >= 2.0 &&
    diaNum <= 8.0 &&
    onsetNum >= 1.0 &&
    onsetNum <= 60.0;
  const isCustom = insulinType === "custom" || !(insulinType in (presets || {}));

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
        <h1 className="text-2xl font-bold">Insulin Configuration</h1>
        <p className="text-slate-500 dark:text-slate-400">
          Select your insulin type to configure IoB (Insulin on Board)
          calculations
        </p>
      </div>

      {/* Offline banner */}
      {isOffline && (
        <OfflineBanner onRetry={fetchConfig} isRetrying={isLoading} />
      )}

      {/* Error state */}
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

      {/* Success state */}
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

      {/* Loading state */}
      {isLoading && (
        <div
          className="bg-white dark:bg-slate-900 rounded-xl p-12 border border-slate-200 dark:border-slate-800 text-center"
          role="status"
          aria-label="Loading insulin configuration"
        >
          <Loader2 className="h-8 w-8 text-blue-400 animate-spin mx-auto mb-3" />
          <p className="text-slate-500 dark:text-slate-400">Loading insulin configuration...</p>
        </div>
      )}

      {/* Configuration form */}
      {!isLoading && (
        <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-6">
          <div className="flex items-center gap-3 mb-6">
            <div className="p-2 bg-blue-500/10 rounded-lg">
              <Syringe className="h-5 w-5 text-blue-400" />
            </div>
            <div>
              <h2 className="text-lg font-semibold">Insulin Settings</h2>
              <p className="text-xs text-slate-500">
                Used for IoB decay calculations on the dashboard
              </p>
            </div>
          </div>

          <form onSubmit={handleSubmit} className="space-y-6">
            {/* Insulin type selector */}
            <div>
              <label
                htmlFor="insulin-type"
                className="block text-sm font-medium text-slate-600 dark:text-slate-300 mb-1"
              >
                Insulin Type
              </label>
              <select
                id="insulin-type"
                value={insulinType}
                onChange={(e) => handleInsulinTypeChange(e.target.value)}
                disabled={isSaving}
                className={clsx(
                  "w-full rounded-lg border px-3 py-2 text-sm",
                  "bg-slate-100 dark:bg-slate-800 border-slate-300 dark:border-slate-700 text-slate-200",
                  "focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent",
                  "disabled:opacity-50 disabled:cursor-not-allowed"
                )}
              >
                {Object.entries(INSULIN_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
              <p className="text-xs text-slate-500 mt-1">
                Select the rapid-acting insulin in your pump
              </p>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
              {/* DIA */}
              <div>
                <label
                  htmlFor="dia-hours"
                  className="block text-sm font-medium text-slate-600 dark:text-slate-300 mb-1"
                >
                  Duration of Insulin Action (hours)
                </label>
                <input
                  id="dia-hours"
                  type="number"
                  min={2}
                  max={8}
                  step={0.5}
                  value={diaHours}
                  onChange={(e) => setDiaHours(e.target.value)}
                  disabled={isSaving || (!isCustom && insulinType !== "custom")}
                  className={clsx(
                    "w-full rounded-lg border px-3 py-2 text-sm",
                    "bg-slate-100 dark:bg-slate-800 border-slate-300 dark:border-slate-700 text-slate-200",
                    "focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent",
                    "placeholder:text-slate-500",
                    "disabled:opacity-50 disabled:cursor-not-allowed"
                  )}
                  aria-describedby="dia-hint"
                />
                <p id="dia-hint" className="text-xs text-slate-500 mt-1">
                  {isCustom
                    ? "Range: 2-8 hours"
                    : "Auto-set from insulin type. Select Custom to override."}
                </p>
              </div>

              {/* Onset */}
              <div>
                <label
                  htmlFor="onset-minutes"
                  className="block text-sm font-medium text-slate-600 dark:text-slate-300 mb-1"
                >
                  Onset Time (minutes)
                </label>
                <input
                  id="onset-minutes"
                  type="number"
                  min={1}
                  max={60}
                  step={1}
                  value={onsetMinutes}
                  onChange={(e) => setOnsetMinutes(e.target.value)}
                  disabled={isSaving || (!isCustom && insulinType !== "custom")}
                  className={clsx(
                    "w-full rounded-lg border px-3 py-2 text-sm",
                    "bg-slate-100 dark:bg-slate-800 border-slate-300 dark:border-slate-700 text-slate-200",
                    "focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent",
                    "placeholder:text-slate-500",
                    "disabled:opacity-50 disabled:cursor-not-allowed"
                  )}
                  aria-describedby="onset-hint"
                />
                <p id="onset-hint" className="text-xs text-slate-500 mt-1">
                  {isCustom
                    ? "Range: 1-60 minutes"
                    : "Auto-set from insulin type. Select Custom to override."}
                </p>
              </div>
            </div>

            {/* Preview */}
            {isValid && (
              <div className="bg-slate-100/50 dark:bg-slate-800/50 rounded-lg p-4 border border-slate-300/50 dark:border-slate-700/50">
                <p className="text-xs text-slate-500 mb-2">Active Configuration</p>
                <p className="text-lg font-semibold text-blue-400">
                  {INSULIN_LABELS[insulinType] || insulinType} - {diaNum}h DIA, {onsetNum}min onset
                </p>
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
                  (config?.insulin_type === DEFAULTS.insulin_type &&
                    config?.dia_hours === DEFAULTS.dia_hours &&
                    config?.onset_minutes === DEFAULTS.onset_minutes)
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
          Your insulin type determines the Duration of Insulin Action (DIA) used
          to calculate how much active insulin remains in your body (IoB). This
          affects the IoB display on your dashboard and in AI analysis. Most
          rapid-acting insulins have a DIA of 3.5-4 hours. Consult your
          healthcare provider if unsure about your insulin settings.
        </p>
      </div>
    </div>
  );
}
