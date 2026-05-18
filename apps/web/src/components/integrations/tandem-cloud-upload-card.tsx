"use client";

import { useState, useEffect, useCallback } from "react";
import {
  Loader2,
  Check,
  CloudUpload,
  Clock,
  Upload,
  AlertTriangle,
  RotateCcw,
} from "lucide-react";
import clsx from "clsx";
import {
  getTandemUploadStatus,
  resetTandemUpload,
  triggerTandemUpload,
  updateTandemUploadSettings,
  type TandemUploadStatusResponse,
} from "@/lib/api";
import { TANDEM_COUNTRY_LABELS } from "@/lib/tandem-countries";

export function TandemCloudUploadCard({ isOffline }: { isOffline: boolean }) {
  const [isLoading, setIsLoading] = useState(true);
  const [uploadStatus, setUploadStatus] =
    useState<TandemUploadStatusResponse | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [isResetting, setIsResetting] = useState(false);
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
      const status = await getTandemUploadStatus();
      setUploadStatus(status);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to load upload status"
      );
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  const handleToggle = async (enabled: boolean) => {
    if (!uploadStatus) return;
    setIsSaving(true);
    setError(null);
    try {
      const result = await updateTandemUploadSettings({
        enabled,
        interval_minutes: uploadStatus.upload_interval_minutes,
      });
      setUploadStatus(result);
      setSuccess(enabled ? "Cloud upload enabled" : "Cloud upload disabled");
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to update settings"
      );
    } finally {
      setIsSaving(false);
    }
  };

  const handleIntervalChange = async (interval: number) => {
    if (!uploadStatus) return;
    setIsSaving(true);
    setError(null);
    try {
      const result = await updateTandemUploadSettings({
        enabled: uploadStatus.enabled,
        interval_minutes: interval,
      });
      setUploadStatus(result);
      setSuccess(`Upload interval set to ${interval} minutes`);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to update interval"
      );
    } finally {
      setIsSaving(false);
    }
  };

  const handleUploadNow = async () => {
    setIsUploading(true);
    setError(null);
    try {
      const result = await triggerTandemUpload();
      setSuccess(result.message);
      await fetchStatus();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to trigger upload"
      );
    } finally {
      setIsUploading(false);
    }
  };

  const handleReset = async () => {
    if (!window.confirm(
      "This will re-queue every stored pump event for upload, including ones " +
      "Tandem already has on file. Tandem dedupes by sequence number so " +
      "duplicates are safe, but the next upload will be larger than usual. " +
      "Continue?"
    )) {
      return;
    }
    setIsResetting(true);
    setError(null);
    try {
      const result = await resetTandemUpload();
      setSuccess(result.message);
      await fetchStatus();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to reset upload state"
      );
    } finally {
      setIsResetting(false);
    }
  };

  if (isLoading) {
    return (
      <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-6">
        <div className="flex items-center gap-3">
          <Loader2 className="h-5 w-5 text-blue-400 animate-spin" />
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Loading cloud upload settings...
          </p>
        </div>
      </div>
    );
  }

  const needsCountryReselect = uploadStatus?.needs_country_reselect ?? false;
  const country = uploadStatus?.country ?? null;
  const countryLabel = country
    ? TANDEM_COUNTRY_LABELS[country] ?? country
    : null;

  return (
    <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-6">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-slate-700/50">
            <CloudUpload className="h-5 w-5 text-blue-400" />
          </div>
          <div>
            <h2 className="text-lg font-semibold">Tandem Cloud Upload</h2>
            <p className="text-xs text-slate-500">
              {countryLabel
                ? `Uploading to Tandem (${countryLabel})`
                : "Upload pump data to t:connect for your endocrinologist"}
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={() => handleToggle(!uploadStatus?.enabled)}
          disabled={
            isSaving || isOffline || !uploadStatus || needsCountryReselect
          }
          className={clsx(
            "relative inline-flex h-6 w-11 items-center rounded-full transition-colors",
            "focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500",
            "disabled:opacity-50 disabled:cursor-not-allowed",
            uploadStatus?.enabled ? "bg-blue-600" : "bg-slate-600"
          )}
          role="switch"
          aria-checked={uploadStatus?.enabled ?? false}
          aria-label="Toggle cloud upload"
        >
          <span
            className={clsx(
              "inline-block h-4 w-4 transform rounded-full bg-white transition-transform",
              uploadStatus?.enabled ? "translate-x-6" : "translate-x-1"
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
                format. Re-connect Tandem above and pick your country so
                uploads can route to the correct Tandem cloud backend.
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

      {uploadStatus?.enabled && (
        <div className="space-y-4">
          {/* Interval selector */}
          <div>
            <label className="block text-sm font-medium text-slate-600 dark:text-slate-300 mb-2">
              Upload Interval
            </label>
            <div className="flex gap-2">
              {[5, 10, 15].map((mins) => (
                <button
                  key={mins}
                  type="button"
                  onClick={() => handleIntervalChange(mins)}
                  disabled={isSaving || isOffline}
                  className={clsx(
                    "px-4 py-1.5 rounded-lg text-sm font-medium transition-colors",
                    "focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500",
                    "disabled:opacity-50 disabled:cursor-not-allowed",
                    uploadStatus.upload_interval_minutes === mins
                      ? "bg-blue-600 text-white"
                      : "bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700 border border-slate-300 dark:border-slate-700"
                  )}
                  aria-pressed={uploadStatus.upload_interval_minutes === mins}
                >
                  {mins} min
                </button>
              ))}
            </div>
          </div>

          {/* Status info */}
          <div className="space-y-2">
            <div className="bg-slate-100/50 dark:bg-slate-800/50 rounded-lg px-3 py-2 border border-slate-300/50 dark:border-slate-700/50">
              <div className="flex items-center gap-2">
                <Clock className="h-3.5 w-3.5 text-slate-500" />
                <p className="text-xs text-slate-500">Last upload</p>
              </div>
              <p className="text-sm text-slate-600 dark:text-slate-300 mt-0.5">
                {uploadStatus.last_upload_at
                  ? new Date(uploadStatus.last_upload_at).toLocaleString()
                  : "No uploads yet"}
              </p>
            </div>

            {uploadStatus.last_upload_status === "error" &&
              uploadStatus.last_error && (
                <div
                  className="bg-red-500/10 rounded-lg px-3 py-2 border border-red-500/20"
                  role="alert"
                >
                  <p className="text-xs text-red-400 line-clamp-3">
                    {uploadStatus.last_error}
                  </p>
                </div>
              )}
          </div>

          {/* Upload Now button */}
          <button
            type="button"
            onClick={handleUploadNow}
            disabled={
              isUploading || isSaving || isResetting || isOffline ||
              needsCountryReselect
            }
            className={clsx(
              "flex items-center justify-center gap-1.5 w-full px-4 py-2 rounded-lg text-sm font-medium",
              "bg-blue-600 text-white hover:bg-blue-500",
              "transition-colors",
              "focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500",
              "disabled:opacity-50 disabled:cursor-not-allowed"
            )}
          >
            {isUploading ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            ) : (
              <Upload className="h-4 w-4" aria-hidden="true" />
            )}
            {isUploading ? "Uploading..." : "Upload Now"}
          </button>
        </div>
      )}

      {/* Pending-count banner: shown whether uploads are enabled or not so
          users with stuck queues can see them even when toggled off (e.g.
          legacy-region users whose Enable button is blocked). */}
      {(uploadStatus?.pending_raw_events ?? 0) > 0 && (
        <div
          className={clsx(
            "bg-amber-500/10 rounded-lg px-3 py-2 border border-amber-500/20",
            uploadStatus?.enabled ? "mt-4" : ""
          )}
        >
          <p className="text-xs text-amber-400">
            {uploadStatus!.pending_raw_events.toLocaleString()} events pending
            upload
          </p>
        </div>
      )}

      {/* Reset state — recovery for stuck uploads. Always rendered so users
          with disabled uploads (e.g. legacy-region users who can't re-enable
          until they pick a country) can still recover stuck state. */}
      <div className="mt-4 pt-3 border-t border-slate-200 dark:border-slate-800">
        <button
          type="button"
          onClick={handleReset}
          disabled={isResetting || isUploading || isSaving || isOffline}
          className={clsx(
            "flex items-center justify-center gap-1.5 w-full px-4 py-2 rounded-lg text-xs font-medium",
            "bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300",
            "hover:bg-slate-200 dark:hover:bg-slate-700",
            "border border-slate-300 dark:border-slate-700",
            "transition-colors",
            "focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500",
            "disabled:opacity-50 disabled:cursor-not-allowed"
          )}
        >
          {isResetting ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
          ) : (
            <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
          )}
          {isResetting ? "Resetting..." : "Reset upload state & re-queue events"}
        </button>
        <p className="text-[11px] text-slate-500 mt-1.5 leading-snug">
          Use this if pending events stay stuck after pressing Upload Now,
          after a pump re-pair or counter reset, or after re-selecting your
          country. Tandem dedupes by sequence number so re-uploading is safe.
        </p>
      </div>
    </div>
  );
}
