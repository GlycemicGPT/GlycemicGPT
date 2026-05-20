"use client";

import { useState, useEffect, useCallback } from "react";
import {
  Loader2,
  Check,
  CloudDownload,
  Clock,
  RefreshCw,
  AlertTriangle,
} from "lucide-react";
import clsx from "clsx";
import {
  getTandemSyncStatus,
  triggerTandemSync,
  updateTandemSyncSettings,
  type TandemSyncStatusResponse,
} from "@/lib/api";

const MIN_INTERVAL = 15;
const MAX_INTERVAL = 1440;

export function TandemSyncCard({ isOffline }: { isOffline: boolean }) {
  const [isLoading, setIsLoading] = useState(true);
  const [syncStatus, setSyncStatus] = useState<TandemSyncStatusResponse | null>(
    null
  );
  const [intervalInput, setIntervalInput] = useState<string>("60");
  const [isSaving, setIsSaving] = useState(false);
  const [isSyncing, setIsSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  useEffect(() => {
    if (!success) return;
    const timer = setTimeout(() => setSuccess(null), 5000);
    return () => clearTimeout(timer);
  }, [success]);

  const fetchStatus = useCallback(async () => {
    try {
      setError(null);
      const status = await getTandemSyncStatus();
      setSyncStatus(status);
      setIntervalInput(String(status.sync_interval_minutes));
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to load sync status"
      );
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  const saveSettings = async (enabled: boolean, interval: number) => {
    setIsSaving(true);
    setError(null);
    try {
      const result = await updateTandemSyncSettings({
        enabled,
        sync_interval_minutes: interval,
      });
      setSyncStatus(result);
      setIntervalInput(String(result.sync_interval_minutes));
      setSuccess(
        enabled ? "Automatic sync enabled" : "Automatic sync disabled"
      );
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to update settings"
      );
    } finally {
      setIsSaving(false);
    }
  };

  const handleToggle = (enabled: boolean) => {
    if (!syncStatus) return;
    void saveSettings(enabled, syncStatus.sync_interval_minutes);
  };

  const handleIntervalApply = () => {
    if (!syncStatus) return;
    const parsed = Number(intervalInput);
    if (
      !Number.isInteger(parsed) ||
      parsed < MIN_INTERVAL ||
      parsed > MAX_INTERVAL
    ) {
      setError(
        `Interval must be a whole number between ${MIN_INTERVAL} and ${MAX_INTERVAL} minutes`
      );
      return;
    }
    void saveSettings(syncStatus.enabled, parsed);
  };

  const handleSyncNow = async () => {
    setIsSyncing(true);
    setError(null);
    try {
      const result = await triggerTandemSync();
      setSuccess(
        `Synced ${result.events_stored} new event(s) from t:connect`
      );
      await fetchStatus();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to trigger sync"
      );
    } finally {
      setIsSyncing(false);
    }
  };

  if (isLoading) {
    return (
      <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-6">
        <div className="flex items-center gap-3">
          <Loader2 className="h-5 w-5 text-blue-400 animate-spin" />
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Loading cloud sync settings...
          </p>
        </div>
      </div>
    );
  }

  const needsCountryReselect = syncStatus?.needs_country_reselect ?? false;
  const intervalChanged =
    syncStatus != null && Number(intervalInput) !== syncStatus.sync_interval_minutes;

  return (
    <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-6">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-slate-700/50">
            <CloudDownload className="h-5 w-5 text-blue-400" />
          </div>
          <div>
            <h2 className="text-lg font-semibold">Automatic Pump Sync</h2>
            <p className="text-xs text-slate-500">
              Pull pump history from t:connect on a schedule
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={() => handleToggle(!syncStatus?.enabled)}
          disabled={
            isSaving ||
            isOffline ||
            !syncStatus ||
            // Block ENABLING into a legacy region (sync would 409), but
            // always allow turning sync OFF.
            (needsCountryReselect && !syncStatus?.enabled)
          }
          className={clsx(
            "relative inline-flex h-6 w-11 items-center rounded-full transition-colors",
            "focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500",
            "disabled:opacity-50 disabled:cursor-not-allowed",
            syncStatus?.enabled ? "bg-blue-600" : "bg-slate-600"
          )}
          role="switch"
          aria-checked={syncStatus?.enabled ?? false}
          aria-label="Toggle automatic sync"
        >
          <span
            className={clsx(
              "inline-block h-4 w-4 transform rounded-full bg-white transition-transform",
              syncStatus?.enabled ? "translate-x-6" : "translate-x-1"
            )}
          />
        </button>
      </div>

      {needsCountryReselect && (
        <div
          className="bg-amber-500/10 rounded-lg px-3 py-3 border border-amber-500/30 mb-4"
          role="alert"
        >
          <div className="flex items-start gap-2">
            <AlertTriangle className="h-4 w-4 text-amber-400 shrink-0 mt-0.5" />
            <div className="text-xs text-amber-300 space-y-1">
              <p className="font-medium">Re-select your country</p>
              <p>
                Your Tandem integration was saved under an older region
                format. Re-connect Tandem above and pick your country so sync
                can route to the correct Tandem cloud backend.
              </p>
            </div>
          </div>
        </div>
      )}

      {error && (
        <div
          className="bg-red-500/10 rounded-lg px-3 py-2 border border-red-500/20 mb-4"
          role="alert"
        >
          <p className="text-xs text-red-400 line-clamp-3">{error}</p>
        </div>
      )}

      {success && (
        <div
          className="bg-green-500/10 rounded-lg px-3 py-2 border border-green-500/20 mb-4"
          role="status"
        >
          <div className="flex items-center gap-1.5">
            <Check className="h-3.5 w-3.5 text-green-400" />
            <p className="text-xs text-green-400">{success}</p>
          </div>
        </div>
      )}

      {syncStatus && (
        <div className="space-y-4">
          {/* Custom interval input -- only relevant when scheduled sync is on */}
          {syncStatus.enabled && (
            <div>
              <label
                htmlFor="tandem-sync-interval"
                className="block text-sm font-medium text-slate-600 dark:text-slate-300 mb-2"
              >
                Sync Interval (minutes)
              </label>
              <div className="flex gap-2">
                <input
                  id="tandem-sync-interval"
                  type="number"
                  min={MIN_INTERVAL}
                  max={MAX_INTERVAL}
                  step={1}
                  value={intervalInput}
                  onChange={(e) => setIntervalInput(e.target.value)}
                  disabled={isSaving || isOffline}
                  className={clsx(
                    "w-28 px-3 py-1.5 rounded-lg text-sm",
                    "bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-200",
                    "border border-slate-300 dark:border-slate-700",
                    "focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500",
                    "disabled:opacity-50 disabled:cursor-not-allowed"
                  )}
                  aria-describedby="tandem-sync-interval-help"
                />
                <button
                  type="button"
                  onClick={handleIntervalApply}
                  disabled={isSaving || isOffline || !intervalChanged}
                  className={clsx(
                    "px-4 py-1.5 rounded-lg text-sm font-medium transition-colors",
                    "bg-blue-600 text-white hover:bg-blue-500",
                    "focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500",
                    "disabled:opacity-50 disabled:cursor-not-allowed"
                  )}
                >
                  Apply
                </button>
              </div>
              <p
                id="tandem-sync-interval-help"
                className="text-[11px] text-slate-500 mt-1.5 leading-snug"
              >
                {MIN_INTERVAL}&ndash;{MAX_INTERVAL} minutes. t:connect refreshes
                roughly hourly, so 60 is a sensible default; lower values
                won&apos;t surface fresher data. The scheduler checks about
                every 15 minutes, so syncs land within ~15 min of the interval.
              </p>
            </div>
          )}

          {/* Status info */}
          <div className="space-y-2">
            <div className="bg-slate-100/50 dark:bg-slate-800/50 rounded-lg px-3 py-2 border border-slate-300/50 dark:border-slate-700/50">
              <div className="flex items-center gap-2">
                <Clock className="h-3.5 w-3.5 text-slate-500" />
                <p className="text-xs text-slate-500">Last sync</p>
              </div>
              <p className="text-sm text-slate-600 dark:text-slate-300 mt-0.5">
                {syncStatus.last_sync_at
                  ? new Date(syncStatus.last_sync_at).toLocaleString()
                  : "No syncs yet"}
              </p>
              <p className="text-[11px] text-slate-500 mt-1">
                {syncStatus.events_available.toLocaleString()} events available
                {syncStatus.events_pulled_total > 0
                  ? ` · ${syncStatus.events_pulled_total.toLocaleString()} pulled in total`
                  : ""}
              </p>
            </div>

            {syncStatus.last_error && (
              <div
                className="bg-red-500/10 rounded-lg px-3 py-2 border border-red-500/20"
                role="alert"
              >
                <p className="text-xs text-red-400 line-clamp-3">
                  {syncStatus.last_error}
                </p>
              </div>
            )}
          </div>

          {/* Sync Now button */}
          <button
            type="button"
            onClick={handleSyncNow}
            disabled={isSyncing || isSaving || isOffline || needsCountryReselect}
            className={clsx(
              "flex items-center justify-center gap-1.5 w-full px-4 py-2 rounded-lg text-sm font-medium",
              "bg-blue-600 text-white hover:bg-blue-500",
              "transition-colors",
              "focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500",
              "disabled:opacity-50 disabled:cursor-not-allowed"
            )}
          >
            {isSyncing ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            ) : (
              <RefreshCw className="h-4 w-4" aria-hidden="true" />
            )}
            {isSyncing ? "Syncing..." : "Sync Now"}
          </button>
        </div>
      )}
    </div>
  );
}
