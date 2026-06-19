"use client";

/**
 * CgmSourcePicker (Story 43.10)
 *
 * Dropdown for choosing which CGM source drives the dashboard charts
 * and stats when a user has more than one CGM-providing integration
 * (e.g. Dexcom Share AND a Loop-via-Nightscout connection that reposts
 * the same sensor). Backed by `GET /api/integrations/cgm` for the
 * current state + `PUT /api/integrations/cgm/source` for the write.
 *
 * UI rules:
 * - Auto-hide when the user has zero or one CGM source
 *   (`multiple_sources === false`). A single source is always primary
 *   and there is nothing to dedupe, so the picker would only clutter.
 * - Selecting a source promotes it to primary and demotes the rest to
 *   secondary; the read endpoints then count only the primary by default.
 */

import { useCgmSources } from "@/hooks/use-cgm";
import { updatePrimaryCgmSource } from "@/lib/api";
import clsx from "clsx";
import { useCallback, useId, useState } from "react";

const HELP_TEXT =
  "You have more than one CGM source connected. This determines which one " +
  "drives your charts and stats. Keep both connected for redundancy; only " +
  "the primary displays at a time so your AGP and Time-in-Range aren't doubled.";

const inputCls = clsx(
  "w-full rounded-lg border px-3 py-2 text-sm",
  "bg-white dark:bg-slate-800",
  "border-slate-300 dark:border-slate-700",
  "text-slate-700 dark:text-slate-200",
  "focus:outline-hidden focus:ring-2 focus:ring-blue-500",
  "disabled:opacity-50 disabled:cursor-not-allowed"
);

export function CgmSourcePicker() {
  const { cgm, isLoading, error, refresh } = useCgmSources();
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const selectId = useId();

  const handleChange = useCallback(
    async (e: React.ChangeEvent<HTMLSelectElement>) => {
      const next = e.target.value;
      setIsSaving(true);
      setSaveError(null);
      try {
        await updatePrimaryCgmSource(next);
        // Re-read so every source's role reflects the new pick (the PUT
        // only echoes the chosen primary). Keep isSaving through the
        // refresh so a rapid double-change can't PUT a stale value.
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
  if (isLoading && cgm === null) {
    return (
      <div
        className="p-4 rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900"
        aria-busy="true"
      >
        <div className="h-4 w-32 bg-slate-200 dark:bg-slate-700 rounded-sm animate-pulse" />
      </div>
    );
  }

  // Quiet error on initial load -- avoid guessing at sources we couldn't fetch.
  if (error !== null && cgm === null) {
    return (
      <div className="p-4 rounded-lg border border-red-200 dark:border-red-900 bg-red-50/40 dark:bg-red-900/10 text-sm text-red-700 dark:text-red-300">
        Could not load CGM settings. Try refreshing the page.
      </div>
    );
  }

  if (cgm === null) {
    return null;
  }

  // Hide entirely unless the user has more than one CGM source.
  if (!cgm.multiple_sources) {
    return null;
  }

  return (
    <div
      className="p-4 rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900"
      data-testid="cgm-source-picker"
    >
      <label
        htmlFor={selectId}
        className="block text-sm font-medium text-slate-700 dark:text-slate-200"
      >
        Primary CGM source
      </label>
      <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
        {HELP_TEXT}
      </p>
      <select
        id={selectId}
        value={cgm.primary_source ?? ""}
        onChange={handleChange}
        disabled={isSaving}
        className={clsx(inputCls, "mt-3")}
        aria-describedby={saveError ? `${selectId}-err` : undefined}
      >
        {cgm.primary_source === null && (
          <option value="" disabled>
            Select a primary source
          </option>
        )}
        {cgm.sources.map((src) => (
          <option key={src.source} value={src.source}>
            {src.label}
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
    </div>
  );
}
