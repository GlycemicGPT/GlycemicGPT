"use client";

/**
 * ForecastSourcePicker (Story 43.12 PR 4)
 *
 * Dropdown for choosing which closed-loop's BG forecast to draw on
 * the dashboard chart. Backed by `GET /api/integrations/forecast` for
 * the current state + `available_sources`, and `PUT
 * /api/integrations/forecast/source` for the write.
 *
 * UI rules (per design doc Section 3):
 * - Auto-hide when the user has no forecast-publishing integration
 *   (`available_sources` is empty). The picker is meaningless then
 *   and surfacing it confuses users.
 * - "Auto" is the default: picks the only available source; renders
 *   nothing when multiple are available (the user must pick).
 * - "None" opts out. Used by users who don't want any forecast line.
 * - Each engine in `available_sources` is listed by friendly name
 *   via `prettySourceName` (shared with PR 6's hero card badge).
 *
 * Hover help text is copied from the design doc so the wording is
 * traceable to a single source of truth.
 */

import { prettySourceName } from "@/components/dashboard/glucose-hero";
import { useForecast } from "@/hooks/use-forecast";
import {
  type ForecastSourcePreference,
  updateForecastSource,
} from "@/lib/api";
import clsx from "clsx";
import { useCallback, useId, useState } from "react";

const HELP_TEXT =
  "Some integrations (Loop, AAPS, Trio, OpenAPS) publish their algorithm's BG forecasts. " +
  "This setting picks which forecast to draw on your glucose chart. " +
  "GlycemicGPT does not generate predictions itself yet.";

const inputCls = clsx(
  "w-full rounded-lg border px-3 py-2 text-sm",
  "bg-white dark:bg-slate-800",
  "border-slate-300 dark:border-slate-700",
  "text-slate-700 dark:text-slate-200",
  "focus:outline-none focus:ring-2 focus:ring-blue-500",
  "disabled:opacity-50 disabled:cursor-not-allowed"
);

export function ForecastSourcePicker() {
  const { forecast, isLoading, error, refresh } = useForecast();
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const selectId = useId();

  const handleChange = useCallback(
    async (e: React.ChangeEvent<HTMLSelectElement>) => {
      const next = e.target.value as ForecastSourcePreference;
      setIsSaving(true);
      setSaveError(null);
      try {
        await updateForecastSource(next);
        // Re-read the full state so `effective_source` /
        // `forecast_unavailable_reason` reflect the new pick
        // (the PUT response only returns `source_preference`).
        // Keep `isSaving` true through the refresh -- otherwise a
        // rapid double-change can PUT a stale preference between the
        // first PUT and the first refresh response.
        await refresh();
      } catch (err) {
        setSaveError(
          err instanceof Error ? err.message : "Failed to save preference"
        );
      } finally {
        setIsSaving(false);
      }
    },
    [refresh]
  );

  // Loading state -- preserve layout space so the section doesn't pop in.
  if (isLoading && forecast === null) {
    return (
      <div
        className="p-4 rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900"
        aria-busy="true"
      >
        <div className="h-4 w-32 bg-slate-200 dark:bg-slate-700 rounded animate-pulse" />
      </div>
    );
  }

  // Network error on initial load -- show a quiet error, no picker.
  // Avoids guessing at what to render when we don't know what sources
  // are available.
  if (error !== null && forecast === null) {
    return (
      <div className="p-4 rounded-lg border border-red-200 dark:border-red-900 bg-red-50/40 dark:bg-red-900/10 text-sm text-red-700 dark:text-red-300">
        Could not load forecast settings. Try refreshing the page.
      </div>
    );
  }

  if (forecast === null) {
    return null;
  }

  // Hide entirely when no source has published a forecast in the
  // last 24h. The picker is meaningless in this state and adding a
  // disabled-dropdown UI just clutters the page.
  if (forecast.available_sources.length === 0) {
    return null;
  }

  return (
    <div
      className="p-4 rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900"
      data-testid="forecast-source-picker"
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <label
            htmlFor={selectId}
            className="block text-sm font-medium text-slate-700 dark:text-slate-200"
          >
            Forecast source
          </label>
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
            {HELP_TEXT}
          </p>
        </div>
      </div>
      <select
        id={selectId}
        value={forecast.source_preference}
        onChange={handleChange}
        disabled={isSaving}
        className={clsx(inputCls, "mt-3")}
        aria-describedby={saveError ? `${selectId}-err` : undefined}
      >
        <option value="auto">Auto (default)</option>
        <option value="none">None (don&apos;t show)</option>
        {forecast.available_sources.map((engine) => (
          <option key={engine} value={engine}>
            {prettySourceName(engine)}
          </option>
        ))}
      </select>
      {saveError !== null && (
        <p
          id={`${selectId}-err`}
          className="mt-2 text-sm text-red-600 dark:text-red-400"
          role="alert"
        >
          {saveError}
        </p>
      )}
      {/* Status hint when the chosen state would render nothing on the
          chart -- mirrors the same dispatch the chart legend uses so
          the user gets the explanation in both places. */}
      {forecast.forecast_unavailable_reason !== null && (
        <PickerStatusHint
          reason={forecast.forecast_unavailable_reason}
          preference={forecast.source_preference}
        />
      )}
    </div>
  );
}

interface PickerStatusHintProps {
  reason: NonNullable<
    import("@/lib/api").ForecastReadResponse["forecast_unavailable_reason"]
  >;
  preference: ForecastSourcePreference;
}

/**
 * One-liner showing why no chart line is drawing right now. The chart
 * legend has its own version of this message; the picker version is
 * scoped to "explain what your current pick means in plain words."
 */
function PickerStatusHint({ reason, preference }: PickerStatusHintProps) {
  const message = (() => {
    switch (reason) {
      case "opted_out":
        return "Forecast overlay is off.";
      case "needs_pick":
        return "Multiple sources available -- pick one to see its forecast.";
      case "no_sources":
        // Shouldn't reach this branch because the picker is hidden
        // when available_sources is empty, but kept for completeness.
        return null;
      case "source_silent":
        return `Your ${
          preference === "auto" || preference === "none"
            ? "source"
            : prettySourceName(preference)
        } hasn't published a forecast recently.`;
      case "stale":
        return "Your forecast data is older than 30 minutes -- no overlay until fresher data arrives.";
    }
  })();
  if (message === null) return null;
  return (
    <p
      className="mt-2 text-xs text-slate-500 dark:text-slate-400"
      data-testid="forecast-picker-hint"
    >
      {message}
    </p>
  );
}
