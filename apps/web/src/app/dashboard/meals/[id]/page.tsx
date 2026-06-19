"use client";

/**
 * Meal detail.
 *
 * Shows one food record: the (placeholder) photo, identity, carb range, the
 * empirical-dispersion confidence band, read-only macros, and provenance. There
 * is deliberately no dose/insulin element; the server-cleared safety qualifier
 * carries the never-dose framing. Delete reuses the native-confirm UX.
 */

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { ArrowLeft, Loader2, Trash2 } from "lucide-react";
import {
  getFoodRecord,
  deleteFoodRecord,
  type FoodRecord,
} from "@/lib/api";
import { classifyMealError, type MealErrorInfo } from "@/lib/meal-errors";
import {
  effectiveCarbRange,
  formatCarbRange,
  confidenceLabel,
  mealTitle,
  macroEntries,
} from "@/lib/meal-format";
import { PageTransition } from "@/components/ui/page-transition";
import { AnimatedCard } from "@/components/ui/animated-card";
import { MealPhoto } from "@/components/meals/meal-photo";
import {
  SourceBadge,
  IdentityConfirmedBadge,
  MealSafetyQualifier,
  MealErrorPanel,
} from "@/components/meals/meal-ui";

function BackLink() {
  return (
    <Link
      href="/dashboard/meals"
      className="inline-flex items-center gap-1.5 text-sm text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white"
    >
      <ArrowLeft className="h-4 w-4" />
      Back to Meals
    </Link>
  );
}

export default function MealDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params?.id;
  const router = useRouter();

  const [record, setRecord] = useState<FoodRecord | null>(null);
  const [loading, setLoading] = useState(true);
  const [blockedInfo, setBlockedInfo] = useState<MealErrorInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    if (!id) return;
    // Guard against a stale response applying after the id changes or unmount.
    let cancelled = false;
    setLoading(true);
    setError(null);
    // Clear any prior meal so a stale record can't render under a new id.
    setRecord(null);
    setBlockedInfo(null);
    getFoodRecord(id)
      .then((data) => {
        if (cancelled) return;
        setRecord(data);
        setBlockedInfo(null);
      })
      .catch((err) => {
        if (cancelled) return;
        const info = classifyMealError(err);
        if (info.retryable) {
          setError(info.message);
          setRecord(null);
        } else {
          setBlockedInfo(info);
          setRecord(null);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  const handleDelete = useCallback(async () => {
    if (!record || deleting) return;
    if (
      !window.confirm(
        `Delete this meal log${
          mealTitle(record) ? ` (${mealTitle(record)})` : ""
        }? This also removes its photo and cannot be undone.`
      )
    ) {
      return;
    }
    setDeleting(true);
    setError(null);
    try {
      await deleteFoodRecord(record.id);
      router.push("/dashboard/meals");
    } catch (err) {
      setError(classifyMealError(err).message);
      setDeleting(false);
    }
  }, [record, deleting, router]);

  if (loading) {
    return (
      <div
        role="status"
        aria-live="polite"
        className="flex flex-col h-full items-center justify-center"
      >
        <Loader2 className="h-8 w-8 animate-spin text-blue-400" />
        <p className="mt-4 text-slate-500 dark:text-slate-400">Loading meal...</p>
      </div>
    );
  }

  if (blockedInfo) {
    return (
      <PageTransition>
        <div className="max-w-2xl mx-auto space-y-6 p-6">
          <BackLink />
          <MealErrorPanel info={blockedInfo} />
        </div>
      </PageTransition>
    );
  }

  if (!record) {
    return (
      <PageTransition>
        <div className="max-w-2xl mx-auto space-y-6 p-6">
          <BackLink />
          <p className="text-slate-500 dark:text-slate-400">
            {error || "This meal could not be loaded."}
          </p>
        </div>
      </PageTransition>
    );
  }

  const range = effectiveCarbRange(record);
  const macros = macroEntries(record.corrected_nutrition_json ?? record.nutrition_json);

  return (
    <PageTransition>
      <div className="max-w-2xl mx-auto space-y-6 p-6">
        <div className="flex items-center justify-between">
          <BackLink />
          <button
            type="button"
            onClick={handleDelete}
            disabled={deleting}
            data-testid="meal-delete"
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-lg text-red-600 dark:text-red-400 hover:bg-red-500/10 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {deleting ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Trash2 className="h-4 w-4" />
            )}
            Delete
          </button>
        </div>

        {error && (
          <div
            role="alert"
            className="bg-red-500/10 border border-red-500/20 text-red-700 dark:text-red-400 px-4 py-3 rounded-lg text-sm"
          >
            {error}
          </div>
        )}

        <AnimatedCard>
          <div className="rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-6 space-y-4">
            <MealPhoto recordId={record.id} size="lg" />

            <div className="space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="text-2xl font-bold text-slate-900 dark:text-white">
                  {mealTitle(record)}
                </h1>
                {record.identity_confirmed && <IdentityConfirmedBadge />}
              </div>
              <p className="text-sm text-slate-500 dark:text-slate-400">
                {new Date(record.meal_timestamp).toLocaleString()}
              </p>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <span
                data-testid="meal-carb-range"
                className="text-xl font-semibold text-slate-900 dark:text-white"
              >
                {formatCarbRange(range.low, range.high)}
              </span>
              <span
                data-testid="meal-confidence"
                className="text-sm text-slate-500 dark:text-slate-400"
              >
                {confidenceLabel(record.confidence)}
              </span>
              <SourceBadge source={record.source} />
            </div>

            {range.corrected && (
              <p className="text-sm text-slate-500 dark:text-slate-400">
                You corrected this. AI estimated{" "}
                {formatCarbRange(record.carbs_low, record.carbs_high)}.
              </p>
            )}

            <MealSafetyQualifier qualifier={record.safety_qualifier} />
          </div>
        </AnimatedCard>

        {macros.length > 0 && (
          <AnimatedCard delay={0.05}>
            <div className="rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-6 space-y-3">
              <h2 className="text-sm font-semibold text-slate-900 dark:text-white">
                Estimated nutrition
              </h2>
              <dl className="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-4">
                {macros.map((macro) => (
                  <div key={macro.key} data-testid="meal-macro">
                    <dt className="text-xs text-slate-500 dark:text-slate-400">
                      {macro.label}
                    </dt>
                    <dd className="text-sm font-medium text-slate-900 dark:text-white">
                      {macro.value}
                    </dd>
                  </div>
                ))}
              </dl>
            </div>
          </AnimatedCard>
        )}

        {(record.ai_model || record.ai_provider) && (
          <p className="text-xs text-slate-400 dark:text-slate-500 text-center">
            Estimated by {record.ai_model || "AI"}
            {record.ai_provider ? ` · ${record.ai_provider}` : ""}
          </p>
        )}
      </div>
    </PageTransition>
  );
}
