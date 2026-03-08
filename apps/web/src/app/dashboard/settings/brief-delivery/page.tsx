"use client";

/**
 * Story 9.2: Brief Delivery Configuration
 *
 * Allows users to configure when and how they receive daily briefs.
 * Settings include delivery time, timezone, delivery channel, and enable/disable toggle.
 */

import { useState, useEffect, useCallback, useMemo } from "react";
import {
  Clock,
  Loader2,
  AlertTriangle,
  Check,
  ArrowLeft,
  RotateCcw,
} from "lucide-react";
import Link from "next/link";
import clsx from "clsx";
import {
  getBriefDeliveryConfig,
  updateBriefDeliveryConfig,
  type BriefDeliveryConfigResponse,
} from "@/lib/api";
import { OfflineBanner } from "@/components/ui/offline-banner";

const DEFAULTS = {
  enabled: true,
  delivery_time: "07:00:00",
  timezone: "UTC",
  channel: "both" as const,
};

const CHANNEL_OPTIONS = [
  { value: "both", label: "Web + Telegram" },
  { value: "web_only", label: "Web Only" },
  { value: "telegram", label: "Telegram Only" },
] as const;

const COMMON_TIMEZONES = [
  "UTC",
  "America/New_York",
  "America/Chicago",
  "America/Denver",
  "America/Los_Angeles",
  "America/Anchorage",
  "Pacific/Honolulu",
  "Europe/London",
  "Europe/Paris",
  "Europe/Berlin",
  "Asia/Tokyo",
  "Asia/Shanghai",
  "Australia/Sydney",
];

export default function BriefDeliveryPage() {
  const [config, setConfig] = useState<BriefDeliveryConfigResponse | null>(
    null
  );
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [isOffline, setIsOffline] = useState(false);

  // Form state
  const [enabled, setEnabled] = useState(true);
  const [deliveryTime, setDeliveryTime] = useState("07:00");
  const [timezone, setTimezone] = useState("UTC");
  const [channel, setChannel] = useState<"web_only" | "telegram" | "both">(
    "both"
  );

  // Build timezone options, including saved timezone if not in common list
  const timezoneOptions = useMemo(() => {
    if (timezone && !COMMON_TIMEZONES.includes(timezone)) {
      return [...COMMON_TIMEZONES, timezone].sort();
    }
    return COMMON_TIMEZONES;
  }, [timezone]);

  // Auto-clear success message after 5 seconds
  useEffect(() => {
    if (!success) return;
    const timer = setTimeout(() => setSuccess(null), 5000);
    return () => clearTimeout(timer);
  }, [success]);

  const fetchConfig = useCallback(async () => {
    try {
      setError(null);
      const data = await getBriefDeliveryConfig();
      setConfig(data);
      setEnabled(data.enabled);
      // delivery_time comes as "HH:MM:SS", we need "HH:MM" for <input type="time">
      setDeliveryTime(data.delivery_time.slice(0, 5));
      setTimezone(data.timezone);
      setChannel(data.channel);
      setIsOffline(false);
    } catch (err) {
      if (!(err instanceof Error && err.message.includes("401"))) {
        setIsOffline(true);
      }
      // Use defaults as baseline so the form is still functional
      setConfig({
        enabled: DEFAULTS.enabled,
        delivery_time: DEFAULTS.delivery_time,
        timezone: DEFAULTS.timezone,
        channel: DEFAULTS.channel,
      } as BriefDeliveryConfigResponse);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchConfig();
  }, [fetchConfig]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSaving(true);
    setError(null);
    setSuccess(null);

    try {
      // Only send fields that actually changed
      const payload: Record<string, unknown> = {};
      if (config && enabled !== config.enabled) payload.enabled = enabled;
      if (config && deliveryTime + ":00" !== config.delivery_time)
        payload.delivery_time = deliveryTime + ":00";
      if (config && timezone !== config.timezone) payload.timezone = timezone;
      if (config && channel !== config.channel) payload.channel = channel;

      const updated = await updateBriefDeliveryConfig(
        payload as Parameters<typeof updateBriefDeliveryConfig>[0]
      );
      setConfig(updated);
      setSuccess("Brief delivery configuration updated successfully");
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Failed to update brief delivery configuration"
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
      const updated = await updateBriefDeliveryConfig({
        enabled: DEFAULTS.enabled,
        delivery_time: DEFAULTS.delivery_time,
        timezone: DEFAULTS.timezone,
        channel: DEFAULTS.channel,
      });
      setConfig(updated);
      setEnabled(DEFAULTS.enabled);
      setDeliveryTime(DEFAULTS.delivery_time.slice(0, 5));
      setTimezone(DEFAULTS.timezone);
      setChannel(DEFAULTS.channel);
      setSuccess("Brief delivery configuration reset to defaults");
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Failed to reset brief delivery configuration"
      );
    } finally {
      setIsSaving(false);
    }
  };

  const hasChanges =
    config &&
    (enabled !== config.enabled ||
      deliveryTime + ":00" !== config.delivery_time ||
      timezone !== config.timezone ||
      channel !== config.channel);

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
        <h1 className="text-2xl font-bold">Daily Brief Delivery</h1>
        <p className="text-slate-500 dark:text-slate-400">
          Configure when and how you receive your daily glucose briefs
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
          aria-label="Loading brief delivery configuration"
        >
          <Loader2 className="h-8 w-8 text-blue-400 animate-spin mx-auto mb-3" />
          <p className="text-slate-500 dark:text-slate-400">Loading delivery configuration...</p>
        </div>
      )}

      {/* Configuration form */}
      {!isLoading && (
        <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-6">
          <div className="flex items-center gap-3 mb-6">
            <div className="p-2 bg-blue-500/10 rounded-lg">
              <Clock className="h-5 w-5 text-blue-400" />
            </div>
            <div>
              <h2 className="text-lg font-semibold">Delivery Settings</h2>
              <p className="text-xs text-slate-500">
                Control your daily brief schedule and delivery channel
              </p>
            </div>
          </div>

          <form onSubmit={handleSubmit} className="space-y-6">
            {/* Enable/Disable toggle */}
            <div className="flex items-center justify-between">
              <div>
                <label
                  htmlFor="enabled"
                  className="text-sm font-medium text-slate-600 dark:text-slate-300"
                >
                  Enable Daily Briefs
                </label>
                <p className="text-xs text-slate-500">
                  Receive automated daily glucose analysis
                </p>
              </div>
              <button
                id="enabled"
                type="button"
                role="switch"
                aria-checked={enabled}
                onClick={() => setEnabled(!enabled)}
                disabled={isSaving}
                className={clsx(
                  "relative inline-flex h-6 w-11 shrink-0 rounded-full border-2 border-transparent",
                  "transition-colors duration-200 ease-in-out",
                  "focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500",
                  "disabled:opacity-50 disabled:cursor-not-allowed",
                  enabled ? "bg-blue-600" : "bg-slate-300 dark:bg-slate-700"
                )}
              >
                <span
                  className={clsx(
                    "pointer-events-none inline-block h-5 w-5 rounded-full bg-white shadow",
                    "transform transition duration-200 ease-in-out",
                    enabled ? "translate-x-5" : "translate-x-0"
                  )}
                />
              </button>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
              {/* Delivery time */}
              <div>
                <label
                  htmlFor="delivery-time"
                  className="block text-sm font-medium text-slate-600 dark:text-slate-300 mb-1"
                >
                  Delivery Time
                </label>
                <input
                  id="delivery-time"
                  type="time"
                  value={deliveryTime}
                  onChange={(e) => setDeliveryTime(e.target.value)}
                  disabled={isSaving}
                  className={clsx(
                    "w-full rounded-lg border px-3 py-2 text-sm",
                    "bg-slate-100 dark:bg-slate-800 border-slate-300 dark:border-slate-700 text-slate-900 dark:text-slate-200",
                    "focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent",
                    "disabled:opacity-50 disabled:cursor-not-allowed"
                  )}
                  aria-describedby="delivery-time-hint"
                />
                <p
                  id="delivery-time-hint"
                  className="text-xs text-slate-500 mt-1"
                >
                  Default: 07:00 AM
                </p>
              </div>

              {/* Timezone */}
              <div>
                <label
                  htmlFor="timezone"
                  className="block text-sm font-medium text-slate-600 dark:text-slate-300 mb-1"
                >
                  Timezone
                </label>
                <select
                  id="timezone"
                  value={timezone}
                  onChange={(e) => setTimezone(e.target.value)}
                  disabled={isSaving}
                  className={clsx(
                    "w-full rounded-lg border px-3 py-2 text-sm",
                    "bg-slate-100 dark:bg-slate-800 border-slate-300 dark:border-slate-700 text-slate-900 dark:text-slate-200",
                    "focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent",
                    "disabled:opacity-50 disabled:cursor-not-allowed"
                  )}
                  aria-describedby="timezone-hint"
                >
                  {timezoneOptions.map((tz) => (
                    <option key={tz} value={tz}>
                      {tz.replace(/_/g, " ")}
                    </option>
                  ))}
                </select>
                <p id="timezone-hint" className="text-xs text-slate-500 mt-1">
                  Default: UTC
                </p>
              </div>
            </div>

            {/* Channel selection */}
            <div>
              <label className="block text-sm font-medium text-slate-600 dark:text-slate-300 mb-2">
                Delivery Channel
              </label>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                {CHANNEL_OPTIONS.map((opt) => (
                  <button
                    key={opt.value}
                    type="button"
                    aria-pressed={channel === opt.value}
                    onClick={() => setChannel(opt.value)}
                    disabled={isSaving}
                    className={clsx(
                      "px-4 py-3 rounded-lg border text-sm font-medium text-center",
                      "transition-colors",
                      "focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500",
                      "disabled:opacity-50 disabled:cursor-not-allowed",
                      channel === opt.value
                        ? "bg-blue-600/20 border-blue-500 text-blue-400"
                        : "bg-slate-100 dark:bg-slate-800 border-slate-300 dark:border-slate-700 text-slate-500 dark:text-slate-400 hover:border-slate-400 dark:hover:border-slate-600"
                    )}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
              <p className="text-xs text-slate-500 mt-1">
                Default: Web + Telegram
              </p>
            </div>

            {/* Preview */}
            {!isLoading && (
              <div className="bg-slate-100/50 dark:bg-slate-800/50 rounded-lg p-4 border border-slate-300/50 dark:border-slate-700/50">
                <p className="text-xs text-slate-500 mb-2">Preview</p>
                <p className="text-lg font-semibold text-blue-400">
                  {enabled ? "Enabled" : "Disabled"} &middot; {deliveryTime}{" "}
                  {timezone.replace(/_/g, " ")} &middot;{" "}
                  {CHANNEL_OPTIONS.find((o) => o.value === channel)?.label}
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
                  (config.enabled === DEFAULTS.enabled &&
                    config.delivery_time === DEFAULTS.delivery_time &&
                    config.timezone === DEFAULTS.timezone &&
                    config.channel === DEFAULTS.channel)
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
          Daily briefs provide an AI-generated summary of your glucose data from
          the previous 24 hours. They are delivered at the scheduled time in your
          selected timezone. Telegram delivery requires a linked Telegram account.
        </p>
      </div>
    </div>
  );
}
