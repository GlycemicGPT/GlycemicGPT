"use client";

/**
 * Save-as / link-to common-food actions for the meal detail view, bringing the
 * web app to mobile parity with the personalization loop:
 *
 *  - "Save as common food" promotes this record to a named baseline (the server
 *    uses the record's corrected values when present, else the AI estimate, and
 *    dedupes by name) and links the record to it.
 *  - "Link to common food" attaches this record to one of the user's existing
 *    baselines.
 *
 * A common food is the user's curated truth for a food they eat often, but it is
 * still a *description* of the food, never a dose: nothing here is fed to IoB /
 * treatment_safety / carb-ratio math, and the never-dose framing stays attached.
 */

import { useCallback, useEffect, useId, useState } from "react";
import { BookmarkPlus, Check, Link2, Loader2 } from "lucide-react";
import {
  type CommonFood,
  type FoodRecord,
  getFoodRecord,
  linkRecordToCommonFood,
  listCommonFoods,
  saveRecordAsCommonFood,
} from "@/lib/api";
import { describeCommonFoodError, NEVER_DOSE_BASELINE_NOTE } from "@/lib/common-food-format";
import { mealTitle } from "@/lib/meal-format";

interface SectionProps {
  record: FoodRecord;
  /** Called with the refreshed record so the detail view re-renders the link state. */
  onUpdated: (record: FoodRecord) => void;
}

type Mode = "idle" | "save" | "link";

/**
 * Promote/link a record to a common-food baseline. Two distinct actions behind
 * one card; both leave the carb estimate untouched and never imply a dose.
 */
export function MealCommonFoodSection({ record, onUpdated }: SectionProps) {
  const [mode, setMode] = useState<Mode>("idle");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const errorId = useId();

  // Save-as state.
  const [name, setName] = useState("");

  // Link state: the user's existing baselines, loaded lazily when the picker opens.
  const [baselines, setBaselines] = useState<CommonFood[] | null>(null);
  const [loadingBaselines, setLoadingBaselines] = useState(false);
  const [selectedId, setSelectedId] = useState("");

  const reset = useCallback(() => {
    setMode("idle");
    setError(null);
  }, []);

  const openSave = useCallback(() => {
    // The AI food_description is unbounded; clamp the prefill to the server's
    // 120-char name cap (which the input's maxLength only enforces for typing).
    setName(mealTitle(record).slice(0, 120));
    setError(null);
    setSuccess(null);
    setMode("save");
  }, [record]);

  const openLink = useCallback(() => {
    setError(null);
    setSuccess(null);
    setSelectedId("");
    setMode("link");
  }, []);

  // Reset the section's transient state when the detail view switches to a
  // different meal. This route re-runs its loader on navigation rather than
  // remounting, so a success/error/open editor from a prior meal must not linger
  // on the next one. Re-rendering with the same record (e.g. after a save) keeps
  // record.id stable, so the success message it just set survives.
  useEffect(() => {
    setMode("idle");
    setSuccess(null);
    setError(null);
  }, [record.id]);

  // Load the baselines for the link picker on demand. Re-runs if the mode toggles
  // back to "link", so a baseline saved meanwhile shows up without a full reload.
  useEffect(() => {
    if (mode !== "link") return;
    let cancelled = false;
    setLoadingBaselines(true);
    setError(null);
    listCommonFoods(200, 0)
      .then((data) => {
        if (cancelled) return;
        setBaselines(data.common_foods);
        // Default the picker to the currently-linked baseline when present.
        const current = data.common_foods.find((f) => f.id === record.common_food_id);
        setSelectedId(current?.id ?? data.common_foods[0]?.id ?? "");
      })
      .catch((err) => {
        if (cancelled) return;
        // Leave baselines null on error so the picker shows the error message,
        // not the misleading "no common foods yet" empty state.
        setError(describeCommonFoodError(err));
      })
      .finally(() => {
        if (!cancelled) setLoadingBaselines(false);
      });
    return () => {
      cancelled = true;
    };
  }, [mode, record.common_food_id]);

  const submitSave = useCallback(async () => {
    const trimmed = name.trim();
    if (!trimmed) {
      setError("Enter a name for this common food.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const saved = await saveRecordAsCommonFood(record.id, trimmed);
      // The promotion links the record server-side. Re-fetch so the detail view
      // reflects the link from the source of truth — uniform with the correction
      // and identity flows, which also swap in a server-returned record (and so
      // never write a stale closure snapshot back over a concurrent edit). A
      // refresh blip is non-fatal: the save already succeeded.
      try {
        onUpdated(await getFoodRecord(record.id));
      } catch {
        /* keep the success state; the link shows on the next load */
      }
      setSuccess(`Saved “${saved.name}” to your common foods.`);
      setMode("idle");
    } catch (err) {
      setError(describeCommonFoodError(err));
    } finally {
      setSaving(false);
    }
  }, [name, record.id, onUpdated]);

  const submitLink = useCallback(async () => {
    if (!selectedId) {
      setError("Pick a common food to link to.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const updated = await linkRecordToCommonFood(record.id, selectedId);
      onUpdated(updated);
      const linked = baselines?.find((f) => f.id === selectedId);
      setSuccess(`Linked to “${linked?.name ?? "your common food"}”.`);
      setMode("idle");
    } catch (err) {
      setError(describeCommonFoodError(err));
    } finally {
      setSaving(false);
    }
  }, [selectedId, record.id, onUpdated, baselines]);

  return (
    <div data-testid="meal-common-food-section" className="space-y-3">
      {record.common_food_id && (
        <p
          data-testid="meal-common-food-linked"
          className="flex items-center gap-1.5 text-sm text-slate-600 dark:text-slate-300"
        >
          <Check className="h-4 w-4 text-emerald-600 dark:text-emerald-400" />
          Linked to one of your common foods.
        </p>
      )}

      {success && (
        <p
          role="status"
          data-testid="meal-common-food-success"
          className="text-sm text-emerald-700 dark:text-emerald-400"
        >
          {success}
        </p>
      )}

      {mode === "idle" && (
        <div className="flex flex-wrap gap-3">
          <button
            type="button"
            onClick={openSave}
            data-testid="meal-save-as-common-food"
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-lg border border-slate-200 dark:border-slate-700 text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
          >
            <BookmarkPlus className="h-4 w-4" />
            Save as common food
          </button>
          <button
            type="button"
            onClick={openLink}
            data-testid="meal-link-common-food"
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-lg border border-slate-200 dark:border-slate-700 text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
          >
            <Link2 className="h-4 w-4" />
            Link to common food
          </button>
        </div>
      )}

      {mode === "save" && (
        <div className="rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-800/40 p-5 space-y-4">
          <label className="block text-xs text-slate-500 dark:text-slate-400">
            Common food name
            <input
              type="text"
              value={name}
              maxLength={120}
              onChange={(e) => setName(e.target.value)}
              data-testid="meal-save-as-name"
              aria-invalid={!!error}
              aria-describedby={error ? errorId : undefined}
              className="mt-1 w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-2 text-sm text-slate-900 dark:text-white focus:border-blue-400 focus:outline-none"
            />
          </label>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            Saves this meal’s carbs as a reusable baseline. Saving under a name you
            already use updates that baseline instead of adding a duplicate.
          </p>
          {error && (
            <p
              role="alert"
              id={errorId}
              data-testid="meal-save-as-error"
              className="text-xs text-red-600 dark:text-red-400"
            >
              {error}
            </p>
          )}
          <div className="flex gap-3">
            <button
              type="button"
              onClick={reset}
              disabled={saving}
              data-testid="meal-save-as-cancel"
              className="flex-1 px-3 py-2 text-sm rounded-lg border border-slate-300 dark:border-slate-700 text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-50 transition-colors"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={submitSave}
              disabled={saving || !name.trim()}
              data-testid="meal-save-as-submit"
              className="flex-1 inline-flex items-center justify-center gap-1.5 px-3 py-2 text-sm rounded-lg bg-blue-600 hover:bg-blue-700 text-white disabled:opacity-50 transition-colors"
            >
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              {saving ? "Saving…" : "Save"}
            </button>
          </div>
        </div>
      )}

      {mode === "link" && (
        <div className="rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-800/40 p-5 space-y-4">
          {loadingBaselines ? (
            <p
              role="status"
              data-testid="meal-link-loading"
              className="flex items-center gap-2 text-sm text-slate-500 dark:text-slate-400"
            >
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading your common foods…
            </p>
          ) : baselines && baselines.length > 0 ? (
            <label className="block text-xs text-slate-500 dark:text-slate-400">
              Link to
              <select
                value={selectedId}
                onChange={(e) => setSelectedId(e.target.value)}
                data-testid="meal-link-select"
                aria-invalid={!!error}
                aria-describedby={error ? errorId : undefined}
                className="mt-1 w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-2 text-sm text-slate-900 dark:text-white focus:border-blue-400 focus:outline-none"
              >
                {baselines.map((food) => (
                  <option key={food.id} value={food.id}>
                    {food.name}
                  </option>
                ))}
              </select>
            </label>
          ) : baselines && baselines.length === 0 ? (
            <p
              data-testid="meal-link-empty"
              className="text-sm text-slate-500 dark:text-slate-400"
            >
              You don’t have any common foods yet. Use “Save as common food” to
              create one.
            </p>
          ) : null}
          {error && (
            <p
              role="alert"
              id={errorId}
              data-testid="meal-link-error"
              className="text-xs text-red-600 dark:text-red-400"
            >
              {error}
            </p>
          )}
          <div className="flex gap-3">
            <button
              type="button"
              onClick={reset}
              disabled={saving}
              data-testid="meal-link-cancel"
              className="flex-1 px-3 py-2 text-sm rounded-lg border border-slate-300 dark:border-slate-700 text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-50 transition-colors"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={submitLink}
              disabled={saving || loadingBaselines || !selectedId}
              data-testid="meal-link-submit"
              className="flex-1 inline-flex items-center justify-center gap-1.5 px-3 py-2 text-sm rounded-lg bg-blue-600 hover:bg-blue-700 text-white disabled:opacity-50 transition-colors"
            >
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              {saving ? "Linking…" : "Link"}
            </button>
          </div>
        </div>
      )}

      <p
        data-testid="meal-common-food-note"
        className="text-xs text-slate-400 dark:text-slate-500"
      >
        {NEVER_DOSE_BASELINE_NOTE}
      </p>
    </div>
  );
}
