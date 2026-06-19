"use client";

/**
 * Common foods management.
 *
 * Lists the user's saved carb/nutrition baselines (most recently updated first),
 * and lets them rename, re-baseline the carb range, or delete a baseline -- web
 * parity with mobile. Modelled on the Settings multi-page structure (back link +
 * card + inline edit form) and the Meals list (pagination + feature-off state).
 *
 * Owner-scoped + flag-gated server-side; the whole surface is hidden behind a
 * clear feature-off state when meal intelligence is off (never a raw 404). A
 * baseline is the user's curated truth, but still a description of a food, never
 * a dose -- the never-dose qualifier stays attached.
 */

import { useState, useEffect, useCallback, useId, useRef } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  BookMarked,
  Loader2,
  Pencil,
  Trash2,
  Check,
} from "lucide-react";
import {
  listCommonFoods,
  updateCommonFood,
  deleteCommonFood,
  type CommonFood,
} from "@/lib/api";
import { classifyMealError, type MealErrorInfo } from "@/lib/meal-errors";
import {
  describeCommonFoodError,
  NEVER_DOSE_BASELINE_NOTE,
} from "@/lib/common-food-format";
import {
  formatCarbRange,
  parseCarbInputs,
  CARB_GRAMS_MIN,
  CARB_GRAMS_MAX,
} from "@/lib/meal-format";
import { PageTransition } from "@/components/ui/page-transition";
import { AnimatedCard } from "@/components/ui/animated-card";
import { MealSafetyQualifier, MealErrorPanel } from "@/components/meals/meal-ui";

const PAGE_SIZE = 50;

interface EditState {
  name: string;
  low: string;
  high: string;
}

function CommonFoodRow({
  food,
  delay,
  onEdited,
  onDeleted,
}: {
  food: CommonFood;
  delay: number;
  onEdited: () => void;
  onDeleted: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<EditState>({ name: "", low: "", high: "" });
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const errorId = useId();

  const open = useCallback(() => {
    setDraft({
      name: food.name,
      low: String(Math.round(food.carbs_low)),
      high: String(Math.round(food.carbs_high)),
    });
    setError(null);
    setEditing(true);
  }, [food.name, food.carbs_low, food.carbs_high]);

  const cancel = useCallback(() => {
    setEditing(false);
    setError(null);
  }, []);

  const save = useCallback(async () => {
    const trimmedName = draft.name.trim();
    if (!trimmedName) {
      setError("Enter a name for this common food.");
      return;
    }
    const parsed = parseCarbInputs(draft.low, draft.high);
    if (!parsed.ok) {
      setError(parsed.reason);
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await updateCommonFood(food.id, {
        name: trimmedName,
        carbs_low: parsed.low,
        carbs_high: parsed.high,
      });
      setEditing(false);
      onEdited();
    } catch (err) {
      setError(describeCommonFoodError(err));
    } finally {
      setSaving(false);
    }
  }, [draft, food.id, onEdited]);

  const remove = useCallback(async () => {
    if (
      !window.confirm(
        `Delete the common food “${food.name}”? Meals linked to it stay logged — they’re just unlinked from this baseline.`
      )
    ) {
      return;
    }
    setDeleting(true);
    setError(null);
    try {
      await deleteCommonFood(food.id);
      onDeleted();
    } catch (err) {
      setError(describeCommonFoodError(err));
      setDeleting(false);
    }
  }, [food.id, food.name, onDeleted]);

  if (editing) {
    return (
      <AnimatedCard delay={delay}>
        <div
          data-testid="common-food-editor"
          className="rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-800/40 p-5 space-y-4"
        >
          <label className="block text-xs text-slate-500 dark:text-slate-400">
            Name
            <input
              type="text"
              value={draft.name}
              maxLength={120}
              onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))}
              data-testid="common-food-edit-name"
              aria-invalid={!!error}
              aria-describedby={error ? errorId : undefined}
              className="mt-1 w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-2 text-sm text-slate-900 dark:text-white focus:border-blue-400 focus:outline-none"
            />
          </label>
          <div className="flex gap-3">
            <label className="flex-1 text-xs text-slate-500 dark:text-slate-400">
              Low (g)
              <input
                type="number"
                inputMode="numeric"
                min={CARB_GRAMS_MIN}
                max={CARB_GRAMS_MAX}
                value={draft.low}
                onChange={(e) => setDraft((d) => ({ ...d, low: e.target.value }))}
                data-testid="common-food-edit-low"
                aria-invalid={!!error}
                aria-describedby={error ? errorId : undefined}
                className="mt-1 w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-2 text-sm text-slate-900 dark:text-white focus:border-blue-400 focus:outline-none"
              />
            </label>
            <label className="flex-1 text-xs text-slate-500 dark:text-slate-400">
              High (g)
              <input
                type="number"
                inputMode="numeric"
                min={CARB_GRAMS_MIN}
                max={CARB_GRAMS_MAX}
                value={draft.high}
                onChange={(e) => setDraft((d) => ({ ...d, high: e.target.value }))}
                data-testid="common-food-edit-high"
                aria-invalid={!!error}
                aria-describedby={error ? errorId : undefined}
                className="mt-1 w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-2 text-sm text-slate-900 dark:text-white focus:border-blue-400 focus:outline-none"
              />
            </label>
          </div>
          {error && (
            <p
              role="alert"
              id={errorId}
              data-testid="common-food-edit-error"
              className="text-xs text-red-600 dark:text-red-400"
            >
              {error}
            </p>
          )}
          <div className="flex gap-3">
            <button
              type="button"
              onClick={cancel}
              disabled={saving}
              data-testid="common-food-edit-cancel"
              className="flex-1 px-3 py-2 text-sm rounded-lg border border-slate-300 dark:border-slate-700 text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-50 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={save}
              disabled={saving}
              data-testid="common-food-edit-save"
              className="flex-1 inline-flex items-center justify-center gap-1.5 px-3 py-2 text-sm rounded-lg bg-blue-600 hover:bg-blue-700 text-white disabled:opacity-50 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
            >
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
              {saving ? "Saving…" : "Save"}
            </button>
          </div>
        </div>
      </AnimatedCard>
    );
  }

  return (
    <AnimatedCard delay={delay}>
      <div
        data-testid="common-food-row"
        className="flex items-center justify-between gap-3 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-4"
      >
        <div className="min-w-0">
          <h3
            data-testid="common-food-name"
            className="font-medium text-slate-900 dark:text-white truncate"
          >
            {food.name}
          </h3>
          <p className="flex flex-wrap items-center gap-2 text-sm">
            <span
              data-testid="common-food-range"
              className="font-semibold text-slate-900 dark:text-white"
            >
              {formatCarbRange(food.carbs_low, food.carbs_high)}
            </span>
            <span className="text-xs text-slate-500 dark:text-slate-400">
              Updated {new Date(food.updated_at).toLocaleDateString()}
            </span>
          </p>
          {error && (
            <p
              role="alert"
              data-testid="common-food-row-error"
              className="mt-1 text-xs text-red-600 dark:text-red-400"
            >
              {error}
            </p>
          )}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <button
            type="button"
            onClick={open}
            data-testid="common-food-edit"
            aria-label={`Edit ${food.name}`}
            className="p-2 rounded-lg text-slate-500 dark:text-slate-400 hover:text-slate-800 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
          >
            <Pencil className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={remove}
            disabled={deleting}
            data-testid="common-food-delete"
            aria-label={`Delete ${food.name}`}
            className="p-2 rounded-lg text-slate-500 dark:text-slate-400 hover:text-red-600 dark:hover:text-red-400 hover:bg-red-500/10 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-red-500 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {deleting ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Trash2 className="h-4 w-4" />
            )}
          </button>
        </div>
      </div>
    </AnimatedCard>
  );
}

export default function CommonFoodsPage() {
  const [foods, setFoods] = useState<CommonFood[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  // A non-retryable dead end (feature off) replaces the list entirely.
  const [blockedInfo, setBlockedInfo] = useState<MealErrorInfo | null>(null);
  // Guards against out-of-order resolution: only the latest fetch may apply.
  const requestIdRef = useRef(0);

  const loadData = useCallback(async (pageNum: number) => {
    const requestId = ++requestIdRef.current;
    setLoading(true);
    setError(null);
    try {
      const data = await listCommonFoods(PAGE_SIZE, (pageNum - 1) * PAGE_SIZE);
      if (requestId !== requestIdRef.current) return;
      setFoods(data.common_foods);
      setTotal(data.total);
      setBlockedInfo(null);
    } catch (err) {
      if (requestId !== requestIdRef.current) return;
      const info = classifyMealError(err);
      if (info.retryable) {
        setError(info.message);
      } else {
        setBlockedInfo(info);
        setFoods([]);
        setTotal(0);
      }
    } finally {
      if (requestId === requestIdRef.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData(page);
  }, [loadData, page]);

  // Auto-dismiss the success banner so it never lingers across reloads.
  useEffect(() => {
    if (!success) return;
    const timer = setTimeout(() => setSuccess(null), 5000);
    return () => clearTimeout(timer);
  }, [success]);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const handleEdited = useCallback(() => {
    setSuccess("Common food updated.");
    loadData(page);
  }, [loadData, page]);

  const handleDeleted = useCallback(() => {
    setSuccess("Common food deleted. Any meals linked to it stay logged.");
    // Stepping back a page when the last row on a non-first page is removed lets
    // the page effect reload; otherwise reload the current page in place.
    if (foods.length === 1 && page > 1) {
      setPage((p) => p - 1);
    } else {
      loadData(page);
    }
  }, [foods.length, page, loadData]);

  if (loading && foods.length === 0 && !blockedInfo) {
    return (
      <div
        role="status"
        aria-live="polite"
        className="flex flex-col h-full items-center justify-center"
      >
        <Loader2 className="h-8 w-8 animate-spin text-blue-400" />
        <p className="mt-4 text-slate-500 dark:text-slate-400">
          Loading common foods...
        </p>
      </div>
    );
  }

  return (
    <PageTransition>
      <div className="max-w-2xl mx-auto space-y-6 p-6">
        {/* Header */}
        <div>
          <Link
            href="/dashboard/meals"
            className="inline-flex items-center gap-1.5 text-sm text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white mb-2"
          >
            <ArrowLeft className="h-4 w-4" />
            Back to Meals
          </Link>
          <div className="flex items-center gap-3">
            <BookMarked className="h-7 w-7 text-blue-400" />
            <div>
              <h1 className="text-2xl font-bold text-slate-900 dark:text-white">
                Common foods
              </h1>
              <p className="text-slate-500 dark:text-slate-400 text-sm">
                {blockedInfo
                  ? "Your saved food baselines"
                  : `${total} saved baseline${total === 1 ? "" : "s"}`}
              </p>
            </div>
          </div>
        </div>

        {/* Status messages */}
        {error && (
          <div
            role="alert"
            className="bg-red-500/10 border border-red-500/20 text-red-700 dark:text-red-400 px-4 py-3 rounded-lg text-sm"
          >
            {error}
          </div>
        )}
        {success && (
          <div
            role="status"
            className="bg-green-500/10 border border-green-500/20 text-green-700 dark:text-green-400 px-4 py-3 rounded-lg text-sm"
          >
            {success}
          </div>
        )}

        {blockedInfo ? (
          <MealErrorPanel info={blockedInfo} />
        ) : (
          <>
            {/* AC6: a baseline is the user's curated truth, but still descriptive
                — never a dose target. */}
            <MealSafetyQualifier
              qualifier={NEVER_DOSE_BASELINE_NOTE}
            />

            {foods.length === 0 ? (
              <div
                data-testid="common-food-empty"
                className="text-center py-16 bg-slate-100/50 dark:bg-slate-800/30 rounded-lg"
              >
                <BookMarked className="h-14 w-14 text-slate-400 dark:text-slate-600 mx-auto mb-4" />
                <h2 className="text-lg font-medium text-slate-900 dark:text-white mb-2">
                  No common foods yet
                </h2>
                <p className="text-slate-500 dark:text-slate-400 max-w-md mx-auto">
                  Open a logged meal and choose “Save as common food” to create a
                  reusable baseline.
                </p>
              </div>
            ) : (
              <div className="space-y-3">
                {foods.map((food, i) => (
                  <CommonFoodRow
                    key={food.id}
                    food={food}
                    delay={Math.min(i * 0.03, 0.3)}
                    onEdited={handleEdited}
                    onDeleted={handleDeleted}
                  />
                ))}
              </div>
            )}

            {/* Pagination */}
            {totalPages > 1 && (
              <div className="flex items-center justify-center gap-3 pt-2">
                <button
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page <= 1 || loading}
                  className="px-3 py-1.5 bg-slate-200 dark:bg-slate-800 hover:bg-slate-300 dark:hover:bg-slate-700 text-slate-900 dark:text-white text-sm rounded disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  Previous
                </button>
                <span className="text-sm text-slate-500 dark:text-slate-400">
                  Page {page} of {totalPages}
                </span>
                <button
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={page >= totalPages || loading}
                  className="px-3 py-1.5 bg-slate-200 dark:bg-slate-800 hover:bg-slate-300 dark:hover:bg-slate-700 text-slate-900 dark:text-white text-sm rounded disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  Next
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </PageTransition>
  );
}
