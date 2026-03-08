"use client";

/**
 * Stories 9.3, 9.4, 9.5: Data Retention, Purge & Export
 *
 * Allows users to configure retention periods for glucose data,
 * AI analysis results, and audit logs. Displays storage usage.
 * Provides a "Danger Zone" section for permanently purging all data.
 * Provides export of settings and/or all data as a JSON download.
 */

import { useState, useEffect, useCallback } from "react";
import {
  Database,
  Loader2,
  AlertTriangle,
  Check,
  ArrowLeft,
  RotateCcw,
  Trash2,
  Download,
  Clock,
  Tag,
  Plug,
  Plus,
  X,
  ArrowUp,
  ArrowDown,
  FileText,
  ChevronRight,
} from "lucide-react";
import Link from "next/link";
import clsx from "clsx";
import {
  getDataRetentionConfig,
  updateDataRetentionConfig,
  getStorageUsage,
  purgeUserData,
  exportSettings,
  getAnalyticsConfig,
  updateAnalyticsConfig,
  getPluginDeclarations,
  DEFAULT_DISPLAY_LABELS,
  type DisplayLabel,
  type DataRetentionConfigResponse,
  type StorageUsageResponse,
  type AnalyticsConfigResponse,
  type PluginDeclarationResponse,
} from "@/lib/api";
import { OfflineBanner } from "@/components/ui/offline-banner";

const DEFAULTS = {
  glucose_retention_days: 365,
  analysis_retention_days: 365,
  audit_retention_days: 730,
};

const RETENTION_OPTIONS = [
  { value: 30, label: "30 days" },
  { value: 90, label: "90 days" },
  { value: 180, label: "6 months" },
  { value: 365, label: "1 year" },
  { value: 730, label: "2 years" },
  { value: 1825, label: "5 years" },
  { value: 3650, label: "10 years" },
];

/** Check if two DisplayLabel arrays are equal (by content). */
function displayLabelsEqual(a: DisplayLabel[], b: DisplayLabel[]): boolean {
  if (a.length !== b.length) return false;
  return a.every(
    (item, i) =>
      item.id === b[i].id &&
      item.label === b[i].label &&
      item.computation_role === b[i].computation_role &&
      item.pump_source === b[i].pump_source &&
      item.sort_order === b[i].sort_order,
  );
}

/** Build default labels, auto-populating pump_source from plugin category_mappings when available. */
function buildDefaultLabels(plugin: PluginDeclarationResponse | null): DisplayLabel[] {
  const defaults = DEFAULT_DISPLAY_LABELS.map((d) => ({ ...d }));
  if (plugin && plugin.category_mappings) {
    const roleToSource: Record<string, string> = {};
    for (const [pumpCat, role] of Object.entries(plugin.category_mappings)) {
      if (!roleToSource[role]) {
        roleToSource[role] = pumpCat;
      }
    }
    for (const label of defaults) {
      if (label.computation_role && roleToSource[label.computation_role]) {
        label.pump_source = roleToSource[label.computation_role];
      }
    }
  }
  return defaults;
}

/** Generate a unique slug id for a new label. */
function generateLabelId(existingIds: Set<string>): string {
  for (let i = 1; i <= 100; i++) {
    const candidate = `custom_${i}`;
    if (!existingIds.has(candidate)) return candidate;
  }
  return `custom_${Date.now()}`;
}

const HOUR_OPTIONS = Array.from({ length: 24 }, (_, i) => {
  const ampm = i === 0 ? "12:00 AM (midnight)" : i === 12 ? "12:00 PM (noon)"
    : i < 12 ? `${i}:00 AM` : `${i - 12}:00 PM`;
  return { value: i, label: ampm };
});

function formatNumber(n: number): string {
  return n.toLocaleString();
}

export default function DataRetentionPage() {
  const [config, setConfig] = useState<DataRetentionConfigResponse | null>(
    null
  );
  const [usage, setUsage] = useState<StorageUsageResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [isOffline, setIsOffline] = useState(false);

  // Purge state (Story 9.4)
  const [showPurgeConfirm, setShowPurgeConfirm] = useState(false);
  const [purgeInput, setPurgeInput] = useState("");
  const [isPurging, setIsPurging] = useState(false);

  // Export state (Story 9.5)
  const [exportType, setExportType] = useState<"settings_only" | "all_data">(
    "settings_only"
  );
  const [isExporting, setIsExporting] = useState(false);

  // Analytics config state
  const [analyticsConfig, setAnalyticsConfig] =
    useState<AnalyticsConfigResponse | null>(null);
  const [boundaryHour, setBoundaryHour] = useState(0);
  const [isSavingBoundary, setIsSavingBoundary] = useState(false);

  // Display labels state
  const [displayLabels, setDisplayLabels] = useState<DisplayLabel[]>(
    () => DEFAULT_DISPLAY_LABELS.map((d) => ({ ...d }))
  );
  const [savedLabels, setSavedLabels] = useState<DisplayLabel[]>(
    () => DEFAULT_DISPLAY_LABELS.map((d) => ({ ...d }))
  );
  const [isSavingLabels, setIsSavingLabels] = useState(false);

  // Plugin declaration state
  const [pluginDeclaration, setPluginDeclaration] =
    useState<PluginDeclarationResponse | null>(null);

  // Form state
  const [glucoseDays, setGlucoseDays] = useState(365);
  const [analysisDays, setAnalysisDays] = useState(365);
  const [auditDays, setAuditDays] = useState(730);

  // Auto-clear success message after 5 seconds
  useEffect(() => {
    if (!success) return;
    const timer = setTimeout(() => setSuccess(null), 5000);
    return () => clearTimeout(timer);
  }, [success]);

  const fetchData = useCallback(async () => {
    try {
      setError(null);
      const [configData, usageData, analyticsData, pluginData] = await Promise.all([
        getDataRetentionConfig(),
        getStorageUsage(),
        getAnalyticsConfig().catch(() => null),
        getPluginDeclarations().catch(() => null),
      ]);
      setConfig(configData);
      setUsage(usageData);
      setGlucoseDays(configData.glucose_retention_days);
      setAnalysisDays(configData.analysis_retention_days);
      setAuditDays(configData.audit_retention_days);
      if (analyticsData) {
        setAnalyticsConfig(analyticsData);
        setBoundaryHour(analyticsData.day_boundary_hour);
        if (analyticsData.display_labels && analyticsData.display_labels.length > 0) {
          const sorted = [...analyticsData.display_labels].sort(
            (a, b) => a.sort_order - b.sort_order,
          );
          setDisplayLabels(sorted);
          setSavedLabels(sorted.map((d) => ({ ...d })));
        }
      }
      setPluginDeclaration(pluginData);
      setIsOffline(false);
    } catch (err) {
      if (!(err instanceof Error && err.message.includes("401"))) {
        setIsOffline(true);
      }
      // Use defaults as baseline so the form is still functional
      setConfig({
        glucose_retention_days: DEFAULTS.glucose_retention_days,
        analysis_retention_days: DEFAULTS.analysis_retention_days,
        audit_retention_days: DEFAULTS.audit_retention_days,
      } as DataRetentionConfigResponse);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Check if any retention period is being reduced (destructive operation)
  const isReducingRetention =
    config &&
    (glucoseDays < config.glucose_retention_days ||
      analysisDays < config.analysis_retention_days ||
      auditDays < config.audit_retention_days);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    // Warn the user if they are reducing any retention period
    if (isReducingRetention) {
      const confirmed = window.confirm(
        "You are reducing one or more retention periods. " +
          "Data older than the new retention period will be permanently " +
          "deleted during the next enforcement cycle. This cannot be undone.\n\n" +
          "Are you sure you want to continue?"
      );
      if (!confirmed) return;
    }

    setIsSaving(true);
    setError(null);
    setSuccess(null);

    try {
      // Only send fields that actually changed
      const payload: Record<string, unknown> = {};
      if (config && glucoseDays !== config.glucose_retention_days)
        payload.glucose_retention_days = glucoseDays;
      if (config && analysisDays !== config.analysis_retention_days)
        payload.analysis_retention_days = analysisDays;
      if (config && auditDays !== config.audit_retention_days)
        payload.audit_retention_days = auditDays;

      const updated = await updateDataRetentionConfig(
        payload as Parameters<typeof updateDataRetentionConfig>[0]
      );
      setConfig(updated);
      setSuccess("Data retention configuration updated successfully");
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Failed to update data retention configuration"
      );
    } finally {
      setIsSaving(false);
    }
  };

  const handleReset = async () => {
    // Resetting to defaults may reduce retention periods — confirm with user
    if (config) {
      const wouldReduce =
        DEFAULTS.glucose_retention_days < config.glucose_retention_days ||
        DEFAULTS.analysis_retention_days < config.analysis_retention_days ||
        DEFAULTS.audit_retention_days < config.audit_retention_days;

      if (wouldReduce) {
        const confirmed = window.confirm(
          "Resetting to defaults will reduce one or more retention periods. " +
            "Data older than the default retention period will be permanently " +
            "deleted during the next enforcement cycle. This cannot be undone.\n\n" +
            "Are you sure you want to reset to defaults?"
        );
        if (!confirmed) return;
      }
    }

    setIsSaving(true);
    setError(null);
    setSuccess(null);

    try {
      const updated = await updateDataRetentionConfig({
        glucose_retention_days: DEFAULTS.glucose_retention_days,
        analysis_retention_days: DEFAULTS.analysis_retention_days,
        audit_retention_days: DEFAULTS.audit_retention_days,
      });
      setConfig(updated);
      setGlucoseDays(DEFAULTS.glucose_retention_days);
      setAnalysisDays(DEFAULTS.analysis_retention_days);
      setAuditDays(DEFAULTS.audit_retention_days);
      setSuccess("Data retention configuration reset to defaults");
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Failed to reset data retention configuration"
      );
    } finally {
      setIsSaving(false);
    }
  };

  const handlePurge = async () => {
    if (purgeInput !== "DELETE") return;

    setIsPurging(true);
    setError(null);
    setSuccess(null);

    try {
      const result = await purgeUserData("DELETE");
      setSuccess(
        `${result.message}. All glucose data, AI analysis, and audit records have been permanently removed.`
      );
      setShowPurgeConfirm(false);
      setPurgeInput("");
      // Refresh storage usage to reflect the purge (failure here is non-critical)
      try {
        const usageData = await getStorageUsage();
        setUsage(usageData);
      } catch {
        // Usage refresh failed but purge succeeded — don't overwrite success
      }
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to purge data"
      );
    } finally {
      setIsPurging(false);
    }
  };

  const handleExport = async () => {
    setIsExporting(true);
    setError(null);
    setSuccess(null);

    try {
      const result = await exportSettings(exportType);
      const json = JSON.stringify(result.export_data, null, 2);
      const blob = new Blob([json], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      const date = new Date().toISOString().slice(0, 10);
      a.download = `glycemicgpt-${exportType === "all_data" ? "full-export" : "settings"}-${date}.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      setSuccess(
        exportType === "all_data"
          ? "Full data export downloaded successfully"
          : "Settings export downloaded successfully"
      );
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to export data"
      );
    } finally {
      setIsExporting(false);
    }
  };

  const hasChanges =
    config &&
    (glucoseDays !== config.glucose_retention_days ||
      analysisDays !== config.analysis_retention_days ||
      auditDays !== config.audit_retention_days);

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
        <h1 className="text-2xl font-bold">Data Retention</h1>
        <p className="text-slate-500 dark:text-slate-400">
          Configure how long your data is retained before automatic cleanup
        </p>
      </div>

      {/* Offline banner */}
      {isOffline && (
        <OfflineBanner onRetry={fetchData} isRetrying={isLoading} />
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
          aria-label="Loading data retention configuration"
        >
          <Loader2 className="h-8 w-8 text-blue-400 animate-spin mx-auto mb-3" />
          <p className="text-slate-500 dark:text-slate-400">
            Loading data retention configuration...
          </p>
        </div>
      )}

      {/* Storage usage */}
      {!isLoading && usage && (
        <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-6">
          <div className="flex items-center gap-3 mb-4">
            <div className="p-2 bg-purple-500/10 rounded-lg">
              <Database className="h-5 w-5 text-purple-400" />
            </div>
            <div>
              <h2 className="text-lg font-semibold">Storage Usage</h2>
              <p className="text-xs text-slate-500">
                Current record counts by category
              </p>
            </div>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <div className="bg-slate-100/50 dark:bg-slate-800/50 rounded-lg p-3 border border-slate-300/50 dark:border-slate-700/50">
              <p className="text-xs text-slate-500 mb-1">Glucose Data</p>
              <p className="text-lg font-semibold text-blue-400">
                {formatNumber(usage.glucose_records + usage.pump_records)}
              </p>
              <p className="text-xs text-slate-600">
                {formatNumber(usage.glucose_records)} CGM +{" "}
                {formatNumber(usage.pump_records)} pump
              </p>
            </div>
            <div className="bg-slate-100/50 dark:bg-slate-800/50 rounded-lg p-3 border border-slate-300/50 dark:border-slate-700/50">
              <p className="text-xs text-slate-500 mb-1">AI Analysis</p>
              <p className="text-lg font-semibold text-green-400">
                {formatNumber(usage.analysis_records)}
              </p>
              <p className="text-xs text-slate-600">
                briefs, meals, corrections
              </p>
            </div>
            <div className="bg-slate-100/50 dark:bg-slate-800/50 rounded-lg p-3 border border-slate-300/50 dark:border-slate-700/50">
              <p className="text-xs text-slate-500 mb-1">Audit Logs</p>
              <p className="text-lg font-semibold text-amber-400">
                {formatNumber(usage.audit_records)}
              </p>
              <p className="text-xs text-slate-600">
                safety, alerts, escalations
              </p>
            </div>
            <div className="bg-slate-100/50 dark:bg-slate-800/50 rounded-lg p-3 border border-slate-300/50 dark:border-slate-700/50">
              <p className="text-xs text-slate-500 mb-1">Total Records</p>
              <p className="text-lg font-semibold text-slate-900 dark:text-white">
                {formatNumber(usage.total_records)}
              </p>
              <p className="text-xs text-slate-600">across all categories</p>
            </div>
          </div>
        </div>
      )}

      {/* Configuration form */}
      {!isLoading && (
        <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-6">
          <div className="flex items-center gap-3 mb-6">
            <div className="p-2 bg-blue-500/10 rounded-lg">
              <Database className="h-5 w-5 text-blue-400" />
            </div>
            <div>
              <h2 className="text-lg font-semibold">Retention Periods</h2>
              <p className="text-xs text-slate-500">
                Set how long each category of data is kept
              </p>
            </div>
          </div>

          <form onSubmit={handleSubmit} className="space-y-6">
            {/* Glucose retention */}
            <div>
              <label
                htmlFor="glucose-retention"
                className="block text-sm font-medium text-slate-600 dark:text-slate-300 mb-1"
              >
                Glucose Data Retention
              </label>
              <select
                id="glucose-retention"
                value={glucoseDays}
                onChange={(e) => setGlucoseDays(Number(e.target.value))}
                disabled={isSaving}
                className={clsx(
                  "w-full rounded-lg border px-3 py-2 text-sm",
                  "bg-slate-100 dark:bg-slate-800 border-slate-300 dark:border-slate-700 text-slate-900 dark:text-slate-200",
                  "focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent",
                  "disabled:opacity-50 disabled:cursor-not-allowed"
                )}
                aria-describedby="glucose-retention-hint"
              >
                {RETENTION_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
              <p
                id="glucose-retention-hint"
                className="text-xs text-slate-500 mt-1"
              >
                CGM readings and pump events. Default: 1 year
              </p>
            </div>

            {/* Analysis retention */}
            <div>
              <label
                htmlFor="analysis-retention"
                className="block text-sm font-medium text-slate-600 dark:text-slate-300 mb-1"
              >
                AI Analysis Retention
              </label>
              <select
                id="analysis-retention"
                value={analysisDays}
                onChange={(e) => setAnalysisDays(Number(e.target.value))}
                disabled={isSaving}
                className={clsx(
                  "w-full rounded-lg border px-3 py-2 text-sm",
                  "bg-slate-100 dark:bg-slate-800 border-slate-300 dark:border-slate-700 text-slate-900 dark:text-slate-200",
                  "focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent",
                  "disabled:opacity-50 disabled:cursor-not-allowed"
                )}
                aria-describedby="analysis-retention-hint"
              >
                {RETENTION_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
              <p
                id="analysis-retention-hint"
                className="text-xs text-slate-500 mt-1"
              >
                Daily briefs, meal analyses, correction analyses. Default: 1 year
              </p>
            </div>

            {/* Audit retention */}
            <div>
              <label
                htmlFor="audit-retention"
                className="block text-sm font-medium text-slate-600 dark:text-slate-300 mb-1"
              >
                Audit Log Retention
              </label>
              <select
                id="audit-retention"
                value={auditDays}
                onChange={(e) => setAuditDays(Number(e.target.value))}
                disabled={isSaving}
                className={clsx(
                  "w-full rounded-lg border px-3 py-2 text-sm",
                  "bg-slate-100 dark:bg-slate-800 border-slate-300 dark:border-slate-700 text-slate-900 dark:text-slate-200",
                  "focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent",
                  "disabled:opacity-50 disabled:cursor-not-allowed"
                )}
                aria-describedby="audit-retention-hint"
              >
                {RETENTION_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
              <p
                id="audit-retention-hint"
                className="text-xs text-slate-500 mt-1"
              >
                Safety logs, alerts, escalation events. Default: 2 years
              </p>
            </div>

            {/* Preview */}
            {!isLoading && (
              <div className="bg-slate-100/50 dark:bg-slate-800/50 rounded-lg p-4 border border-slate-300/50 dark:border-slate-700/50">
                <p className="text-xs text-slate-500 mb-2">Preview</p>
                <p className="text-lg font-semibold text-blue-400">
                  Glucose:{" "}
                  {RETENTION_OPTIONS.find((o) => o.value === glucoseDays)
                    ?.label ?? `${glucoseDays} days`}{" "}
                  &middot; Analysis:{" "}
                  {RETENTION_OPTIONS.find((o) => o.value === analysisDays)
                    ?.label ?? `${analysisDays} days`}{" "}
                  &middot; Audit:{" "}
                  {RETENTION_OPTIONS.find((o) => o.value === auditDays)
                    ?.label ?? `${auditDays} days`}
                </p>
              </div>
            )}

            {/* Actions */}
            <div className="flex items-center gap-3 pt-2">
              <button
                type="submit"
                disabled={isSaving || !hasChanges || isOffline}
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
                  !config ||
                  (config.glucose_retention_days ===
                    DEFAULTS.glucose_retention_days &&
                    config.analysis_retention_days ===
                      DEFAULTS.analysis_retention_days &&
                    config.audit_retention_days ===
                      DEFAULTS.audit_retention_days)
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

      {/* Analytics Day Boundary */}
      {!isLoading && (
        <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-6">
          <div className="flex items-center gap-3 mb-4">
            <div className="p-2 bg-cyan-500/10 rounded-lg">
              <Clock className="h-5 w-5 text-cyan-400" />
            </div>
            <div>
              <h2 className="text-lg font-semibold">Analytics Day Boundary</h2>
              <p className="text-xs text-slate-500">
                Controls when your daily analytics period resets
              </p>
            </div>
          </div>

          <div className="space-y-4">
            <div className="bg-slate-100/50 dark:bg-slate-800/50 rounded-lg p-4 border border-slate-300/50 dark:border-slate-700/50">
              <p className="text-sm text-slate-600 dark:text-slate-300 mb-2">
                The day boundary determines when analytics periods like Insulin
                Summary and Recent Boluses start counting each day. Most insulin
                pumps reset their Delivery Summary at midnight, so the default
                boundary is <strong className="text-slate-800 dark:text-slate-200">12:00 AM</strong>.
              </p>
              <p className="text-sm text-slate-500 dark:text-slate-400">
                Changing this affects how &ldquo;24H&rdquo;, &ldquo;3D&rdquo;, and
                &ldquo;7D&rdquo; periods are calculated for insulin delivery
                statistics. For example, if your pump resets at a different time, or
                you work night shifts, you can align the boundary to match your
                schedule. Charts, Time in Range, and CGM Stats are not affected
                &mdash; they always use a rolling window.
              </p>
            </div>

            <div>
              <label
                htmlFor="day-boundary-hour"
                className="block text-sm font-medium text-slate-600 dark:text-slate-300 mb-1"
              >
                Day starts at
              </label>
              <select
                id="day-boundary-hour"
                value={boundaryHour}
                onChange={(e) => setBoundaryHour(Number(e.target.value))}
                disabled={isSavingBoundary || isOffline}
                className={clsx(
                  "w-full rounded-lg border px-3 py-2 text-sm",
                  "bg-slate-100 dark:bg-slate-800 border-slate-300 dark:border-slate-700 text-slate-900 dark:text-slate-200",
                  "focus:outline-none focus:ring-2 focus:ring-cyan-500 focus:border-transparent",
                  "disabled:opacity-50 disabled:cursor-not-allowed"
                )}
                aria-describedby="day-boundary-hint"
              >
                {HOUR_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
              <p
                id="day-boundary-hint"
                className="text-xs text-slate-500 mt-1"
              >
                Hour in your local time when the analytics day resets. Default:
                12:00 AM (midnight)
              </p>
            </div>

            <button
              type="button"
              disabled={
                isSavingBoundary ||
                isOffline ||
                (analyticsConfig !== null &&
                  boundaryHour === analyticsConfig.day_boundary_hour)
              }
              onClick={async () => {
                setIsSavingBoundary(true);
                setError(null);
                setSuccess(null);
                try {
                  const updated = await updateAnalyticsConfig({
                    day_boundary_hour: boundaryHour,
                  });
                  setAnalyticsConfig(updated);
                  setBoundaryHour(updated.day_boundary_hour);
                  setSuccess("Analytics day boundary updated successfully");
                } catch (err) {
                  setError(
                    err instanceof Error
                      ? err.message
                      : "Failed to update analytics day boundary"
                  );
                } finally {
                  setIsSavingBoundary(false);
                }
              }}
              className={clsx(
                "flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium",
                "bg-cyan-600 text-white hover:bg-cyan-500",
                "transition-colors",
                "focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500",
                "disabled:opacity-50 disabled:cursor-not-allowed"
              )}
            >
              {isSavingBoundary ? (
                <Loader2
                  className="h-4 w-4 animate-spin"
                  aria-hidden="true"
                />
              ) : (
                <Check className="h-4 w-4" aria-hidden="true" />
              )}
              {isSavingBoundary ? "Saving..." : "Save Boundary"}
            </button>
          </div>
        </div>
      )}

      {/* Bolus Display Labels */}
      {!isLoading && (
        <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-6">
          <div className="flex items-center gap-3 mb-4">
            <div className="p-2 bg-violet-500/10 rounded-lg">
              <Tag className="h-5 w-5 text-violet-400" />
            </div>
            <div>
              <h2 className="text-lg font-semibold">Bolus Display Labels</h2>
              <p className="text-xs text-slate-500">
                Customize how bolus categories are displayed across the platform
              </p>
            </div>
          </div>

          <div className="space-y-4">
            {/* Active plugin info */}
            <div className="bg-slate-100/50 dark:bg-slate-800/50 rounded-lg p-4 border border-slate-300/50 dark:border-slate-700/50">
              <div className="flex items-center gap-2 mb-2">
                <Plug className="h-4 w-4 text-slate-500 dark:text-slate-400" aria-hidden="true" />
                <span className="text-sm font-medium text-slate-600 dark:text-slate-300">
                  Active Plugin:
                </span>
                {pluginDeclaration ? (
                  <span className="text-sm text-violet-400">
                    {pluginDeclaration.plugin_name} v{pluginDeclaration.plugin_version}
                  </span>
                ) : (
                  <span className="text-sm text-slate-500 italic">
                    No pump plugin connected
                  </span>
                )}
              </div>
              <p className="text-sm text-slate-500 dark:text-slate-400">
                Labels control how bolus categories appear in the Insulin
                Summary, charts, and dashboards on both web and mobile.
                Assign a Pump Source to link labels with your pump&apos;s native categories.
              </p>
            </div>

            {/* Display labels table */}
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-300 dark:border-slate-700">
                    <th className="text-left py-2 pr-2 text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider w-8">
                      <span className="sr-only">Order</span>
                    </th>
                    <th className="text-left py-2 px-2 text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                      Display Label
                    </th>
                    <th className="text-left py-2 px-2 text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                      Pump Source
                    </th>
                    <th className="text-right py-2 pl-2 text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider w-10">
                      <span className="sr-only">Actions</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {displayLabels.map((item, index) => (
                    <tr key={item.id} className="border-b border-slate-200/50 dark:border-slate-800/50">
                      {/* Reorder controls */}
                      <td className="py-2 pr-2">
                        <div className="flex flex-col gap-0.5">
                          <button
                            type="button"
                            disabled={index === 0 || isSavingLabels}
                            aria-label={`Move ${item.label} up`}
                            onClick={() => {
                              setDisplayLabels((prev) => {
                                const next = [...prev];
                                [next[index - 1], next[index]] = [next[index], next[index - 1]];
                                return next.map((l, i) => ({ ...l, sort_order: i }));
                              });
                            }}
                            className="text-slate-500 hover:text-slate-300 disabled:opacity-30 disabled:cursor-not-allowed"
                          >
                            <ArrowUp className="h-3 w-3" />
                          </button>
                          <button
                            type="button"
                            disabled={index === displayLabels.length - 1 || isSavingLabels}
                            aria-label={`Move ${item.label} down`}
                            onClick={() => {
                              setDisplayLabels((prev) => {
                                const next = [...prev];
                                [next[index], next[index + 1]] = [next[index + 1], next[index]];
                                return next.map((l, i) => ({ ...l, sort_order: i }));
                              });
                            }}
                            className="text-slate-500 hover:text-slate-300 disabled:opacity-30 disabled:cursor-not-allowed"
                          >
                            <ArrowDown className="h-3 w-3" />
                          </button>
                        </div>
                      </td>
                      {/* Label text input */}
                      <td className="py-2 px-2">
                        <div className="flex items-center gap-1.5">
                          <input
                            id={`label-${item.id}`}
                            type="text"
                            maxLength={20}
                            aria-label={`${item.label} display label`}
                            value={item.label}
                            onChange={(e) => {
                              const newLabel = e.target.value;
                              setDisplayLabels((prev) =>
                                prev.map((l) =>
                                  l.id === item.id ? { ...l, label: newLabel } : l
                                )
                              );
                            }}
                            disabled={isSavingLabels || isOffline}
                            className={clsx(
                              "w-full rounded-lg border px-2 py-1.5 text-sm",
                              "bg-slate-100 dark:bg-slate-800 border-slate-300 dark:border-slate-700 text-slate-900 dark:text-slate-200",
                              "placeholder:text-slate-600",
                              "focus:outline-none focus:ring-2 focus:ring-violet-500 focus:border-transparent",
                              "disabled:opacity-50 disabled:cursor-not-allowed"
                            )}
                          />
                        </div>
                      </td>
                      {/* Pump source dropdown */}
                      <td className="py-2 px-2">
                        <select
                          aria-label={`${item.label} pump source`}
                          value={item.pump_source ?? ""}
                          onChange={(e) => {
                            const val = e.target.value || null;
                            setDisplayLabels((prev) =>
                              prev.map((l) =>
                                l.id === item.id ? { ...l, pump_source: val } : l
                              )
                            );
                          }}
                          disabled={isSavingLabels || isOffline || !pluginDeclaration}
                          className={clsx(
                            "w-full rounded-lg border px-2 py-1.5 text-sm",
                            "bg-slate-100 dark:bg-slate-800 border-slate-300 dark:border-slate-700 text-slate-900 dark:text-slate-200",
                            "focus:outline-none focus:ring-2 focus:ring-violet-500 focus:border-transparent",
                            "disabled:opacity-50 disabled:cursor-not-allowed"
                          )}
                        >
                          <option value="">{"\u2014"}</option>
                          {pluginDeclaration?.declared_categories.map((cat) => (
                            <option key={cat} value={cat}>
                              {cat}
                            </option>
                          ))}
                        </select>
                      </td>
                      {/* Delete button */}
                      <td className="py-2 pl-2 text-right">
                        <button
                          type="button"
                          aria-label={`Delete ${item.label}`}
                          disabled={isSavingLabels || displayLabels.length <= 1}
                          onClick={() => {
                            setDisplayLabels((prev) =>
                              prev
                                .filter((l) => l.id !== item.id)
                                .map((l, i) => ({ ...l, sort_order: i }))
                            );
                          }}
                          className="text-slate-500 hover:text-red-400 disabled:opacity-30 disabled:cursor-not-allowed p-1"
                        >
                          <X className="h-4 w-4" />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Add Label button */}
            <button
              type="button"
              disabled={isSavingLabels || isOffline || displayLabels.length >= 20}
              onClick={() => {
                const existingIds = new Set(displayLabels.map((l) => l.id));
                const newId = generateLabelId(existingIds);
                setDisplayLabels((prev) => [
                  ...prev,
                  {
                    id: newId,
                    label: "New Label",
                    computation_role: null,
                    pump_source: null,
                    sort_order: prev.length,
                  },
                ]);
              }}
              className={clsx(
                "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm",
                "bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700",
                "transition-colors border border-slate-300 dark:border-slate-700",
                "focus:outline-none focus-visible:ring-2 focus-visible:ring-violet-500",
                "disabled:opacity-50 disabled:cursor-not-allowed"
              )}
            >
              <Plus className="h-4 w-4" aria-hidden="true" />
              Add Label
            </button>

            <div className="flex items-center gap-3 pt-2">
              <button
                type="button"
                disabled={
                  isSavingLabels ||
                  isOffline ||
                  displayLabels.length === 0 ||
                  displayLabelsEqual(displayLabels, savedLabels)
                }
                onClick={async () => {
                  setIsSavingLabels(true);
                  setError(null);
                  setSuccess(null);
                  try {
                    const updated = await updateAnalyticsConfig({
                      display_labels: displayLabels,
                    });
                    setAnalyticsConfig(updated);
                    if (updated.display_labels && updated.display_labels.length > 0) {
                      const sorted = [...updated.display_labels].sort(
                        (a, b) => a.sort_order - b.sort_order,
                      );
                      setDisplayLabels(sorted);
                      setSavedLabels(sorted.map((d) => ({ ...d })));
                    }
                    setSuccess("Display labels updated successfully");
                  } catch (err) {
                    setError(
                      err instanceof Error
                        ? err.message
                        : "Failed to update display labels"
                    );
                  } finally {
                    setIsSavingLabels(false);
                  }
                }}
                className={clsx(
                  "flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium",
                  "bg-violet-600 text-white hover:bg-violet-500",
                  "transition-colors",
                  "focus:outline-none focus-visible:ring-2 focus-visible:ring-violet-500",
                  "disabled:opacity-50 disabled:cursor-not-allowed"
                )}
              >
                {isSavingLabels ? (
                  <Loader2
                    className="h-4 w-4 animate-spin"
                    aria-hidden="true"
                  />
                ) : (
                  <Check className="h-4 w-4" aria-hidden="true" />
                )}
                {isSavingLabels ? "Saving..." : "Save Labels"}
              </button>

              <button
                type="button"
                onClick={() => {
                  setDisplayLabels(buildDefaultLabels(pluginDeclaration));
                }}
                disabled={
                  isSavingLabels ||
                  displayLabelsEqual(displayLabels, buildDefaultLabels(pluginDeclaration))
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
          </div>
        </div>
      )}

      {/* Export Data (Story 9.5) */}
      {!isLoading && (
        <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-6">
          <div className="flex items-center gap-3 mb-4">
            <div className="p-2 bg-green-500/10 rounded-lg">
              <Download className="h-5 w-5 text-green-400" />
            </div>
            <div>
              <h2 className="text-lg font-semibold">Export Data</h2>
              <p className="text-xs text-slate-500">
                Download your settings and data as a JSON file
              </p>
            </div>
          </div>

          <div className="space-y-4">
            <fieldset>
              <legend className="text-sm font-medium text-slate-600 dark:text-slate-300 mb-2">
                Export type
              </legend>
              <div className="space-y-2">
                <label className="flex items-start gap-3 cursor-pointer">
                  <input
                    type="radio"
                    name="export-type"
                    value="settings_only"
                    checked={exportType === "settings_only"}
                    onChange={() => setExportType("settings_only")}
                    disabled={isExporting}
                    className="mt-1 accent-blue-500"
                  />
                  <div>
                    <p className="text-sm text-slate-900 dark:text-slate-200">Settings only</p>
                    <p className="text-xs text-slate-500">
                      Alert thresholds, glucose range, escalation timing, brief
                      delivery, data retention, AI provider, integrations
                      (without credentials), and emergency contacts
                    </p>
                  </div>
                </label>
                <label className="flex items-start gap-3 cursor-pointer">
                  <input
                    type="radio"
                    name="export-type"
                    value="all_data"
                    checked={exportType === "all_data"}
                    onChange={() => setExportType("all_data")}
                    disabled={isExporting}
                    className="mt-1 accent-blue-500"
                  />
                  <div>
                    <p className="text-sm text-slate-900 dark:text-slate-200">
                      All data (JSON archive)
                    </p>
                    <p className="text-xs text-slate-500">
                      Everything above plus glucose readings, pump events, daily
                      briefs, AI analyses, safety logs, and alerts
                    </p>
                  </div>
                </label>
              </div>
            </fieldset>

            <button
              type="button"
              onClick={handleExport}
              disabled={isExporting || isSaving || isPurging || isOffline}
              className={clsx(
                "flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium",
                "bg-green-600 text-white hover:bg-green-500",
                "transition-colors",
                "focus:outline-none focus-visible:ring-2 focus-visible:ring-green-500",
                "disabled:opacity-50 disabled:cursor-not-allowed"
              )}
            >
              {isExporting ? (
                <Loader2
                  className="h-4 w-4 animate-spin"
                  aria-hidden="true"
                />
              ) : (
                <Download className="h-4 w-4" aria-hidden="true" />
              )}
              {isExporting ? "Exporting..." : "Download Export"}
            </button>
          </div>
        </div>
      )}

      {/* Clinical Report Link */}
      {!isLoading && (
        <Link
          href="/dashboard/reports/clinical"
          className="block bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-6 hover:border-blue-500/50 transition-colors group"
        >
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="p-2 bg-blue-500/10 rounded-lg">
                <FileText className="h-5 w-5 text-blue-400" aria-hidden="true" />
              </div>
              <div>
                <h2 className="text-lg font-semibold text-slate-900 dark:text-white group-hover:text-blue-400 transition-colors">
                  Clinical Report
                </h2>
                <p className="text-sm text-slate-500 dark:text-slate-400">
                  Generate a printable report for your healthcare provider
                </p>
              </div>
            </div>
            <ChevronRight className="h-5 w-5 text-slate-400 group-hover:text-blue-400 transition-colors" aria-hidden="true" />
          </div>
        </Link>
      )}

      {/* Danger Zone (Story 9.4) */}
      {!isLoading && (
        <div className="bg-white dark:bg-slate-900 rounded-xl border border-red-500/30 p-6">
          <div className="flex items-center gap-3 mb-4">
            <div className="p-2 bg-red-500/10 rounded-lg">
              <Trash2 className="h-5 w-5 text-red-400" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-red-400">
                Danger Zone
              </h2>
              <p className="text-xs text-slate-500">
                Irreversible actions that permanently delete your data
              </p>
            </div>
          </div>

          {!showPurgeConfirm ? (
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-slate-600 dark:text-slate-300">Purge All Data</p>
                <p className="text-xs text-slate-500">
                  Permanently delete all glucose readings, pump events, AI
                  analysis, and audit records. Account settings are preserved.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setShowPurgeConfirm(true)}
                disabled={isPurging || isSaving || isOffline}
                className={clsx(
                  "flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium",
                  "bg-red-600/10 text-red-400 border border-red-500/30",
                  "hover:bg-red-600/20",
                  "transition-colors",
                  "focus:outline-none focus-visible:ring-2 focus-visible:ring-red-500",
                  "disabled:opacity-50 disabled:cursor-not-allowed"
                )}
              >
                <Trash2 className="h-4 w-4" aria-hidden="true" />
                Purge All Data
              </button>
            </div>
          ) : (
            <div className="space-y-4">
              <div
                className="bg-red-500/10 rounded-lg p-4 border border-red-500/20"
                role="alert"
              >
                <div className="flex items-start gap-2">
                  <AlertTriangle className="h-4 w-4 text-red-400 shrink-0 mt-0.5" />
                  <div className="text-sm text-red-400">
                    <p className="font-medium mb-1">
                      This action is irreversible
                    </p>
                    <p>
                      All glucose readings, pump events, daily briefs, meal
                      analyses, correction analyses, safety logs, alerts, and
                      escalation events will be permanently deleted.
                    </p>
                    <p className="mt-2">
                      Your account, settings, integrations, emergency contacts,
                      and caregiver links will be preserved.
                    </p>
                  </div>
                </div>
              </div>

              <div>
                <label
                  htmlFor="purge-confirm"
                  className="block text-sm font-medium text-slate-600 dark:text-slate-300 mb-1"
                >
                  Type <span className="font-mono text-red-400">DELETE</span> to
                  confirm
                </label>
                <input
                  id="purge-confirm"
                  type="text"
                  value={purgeInput}
                  onChange={(e) => setPurgeInput(e.target.value)}
                  disabled={isPurging}
                  placeholder="Type DELETE to confirm"
                  autoComplete="off"
                  className={clsx(
                    "w-full rounded-lg border px-3 py-2 text-sm",
                    "bg-slate-100 dark:bg-slate-800 border-slate-300 dark:border-slate-700 text-slate-900 dark:text-slate-200",
                    "placeholder:text-slate-600",
                    "focus:outline-none focus:ring-2 focus:ring-red-500 focus:border-transparent",
                    "disabled:opacity-50 disabled:cursor-not-allowed"
                  )}
                />
              </div>

              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={handlePurge}
                  disabled={purgeInput !== "DELETE" || isPurging}
                  className={clsx(
                    "flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium",
                    "bg-red-600 text-white hover:bg-red-500",
                    "transition-colors",
                    "focus:outline-none focus-visible:ring-2 focus-visible:ring-red-500",
                    "disabled:opacity-50 disabled:cursor-not-allowed"
                  )}
                >
                  {isPurging ? (
                    <Loader2
                      className="h-4 w-4 animate-spin"
                      aria-hidden="true"
                    />
                  ) : (
                    <Trash2 className="h-4 w-4" aria-hidden="true" />
                  )}
                  {isPurging ? "Purging..." : "Permanently Delete All Data"}
                </button>

                <button
                  type="button"
                  onClick={() => {
                    setShowPurgeConfirm(false);
                    setPurgeInput("");
                  }}
                  disabled={isPurging}
                  className={clsx(
                    "px-4 py-2 rounded-lg text-sm font-medium",
                    "bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700",
                    "transition-colors",
                    "focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-500",
                    "disabled:opacity-50 disabled:cursor-not-allowed"
                  )}
                >
                  Cancel
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Info card */}
      <div className="bg-slate-50/50 dark:bg-slate-900/50 rounded-xl p-4 border border-slate-200 dark:border-slate-800">
        <p className="text-xs text-slate-500">
          Data retention policies are enforced automatically on a daily schedule.
          Records older than the configured retention period will be permanently
          deleted. Reducing retention periods will cause older data to be removed
          during the next enforcement cycle. Minimum retention is 30 days.
        </p>
      </div>
    </div>
  );
}
