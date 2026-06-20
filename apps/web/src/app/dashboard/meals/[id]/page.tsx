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
} from "@/lib/meal-format";
import { PageTransition } from "@/components/ui/page-transition";
import { AnimatedCard } from "@/components/ui/animated-card";
import { MealPhoto } from "@/components/meals/meal-photo";
import {
  SourceBadge,
  IdentityConfirmedBadge,
  MealSafetyQualifier,
  MealGroundingStatus,
  MealAssumedPortion,
  MealNutritionFacts,
  MealNutritionDisclaimer,
  MealErrorPanel,
} from "@/components/meals/meal-ui";
import {
  MealCorrectionSection,
  MealIdentitySection,
} from "@/components/meals/meal-edit";
import { MealCommonFoodSection } from "@/components/meals/common-food-actions";
import { MealAuditPanel } from "@/components/meals/meal-audit";

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

  // A correction / identity-confirmation returns the refreshed record; swap it in
  // so the carb band, source badge, and grounding attribution re-render in place.
  // Guard on the route id: this route segment re-runs its loader on navigation
  // without remounting, so a response that resolves after the user moved to a
  // different meal must not overwrite the now-active record with stale data.
  const handleUpdated = useCallback(
    (updated: FoodRecord) => {
      if (updated.id !== id) return;
      setRecord(updated);
      setError(null);
    },
    [id]
  );

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
  const facts = record.nutrition_facts;
  const hasNutrition = !!facts && (facts.macros.length > 0 || !!facts.net_carbs);

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
            <MealGroundingStatus record={record} />
            <MealCorrectionSection record={record} onUpdated={handleUpdated} />
          </div>
        </AnimatedCard>

        {/* Confirming/correcting *what the food is* is a distinct action from
            carb correction (the Story 50.H2 split between fixing carbs and
            confirming identity): it is what opens external authoritative
            grounding, so a misidentification is never certified. */}
        <AnimatedCard delay={0.05}>
          <div className="rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-6 space-y-3">
            <h2 className="text-sm font-semibold text-slate-900 dark:text-white">
              What is this?
            </h2>
            <MealIdentitySection record={record} onUpdated={handleUpdated} />
          </div>
        </AnimatedCard>

        {/* Personalize: save this meal as a reusable baseline, or link it to one
            you already keep. A baseline is the user's curated truth, but still a
            description of the food — never a dose. */}
        <AnimatedCard delay={0.075}>
          <div className="rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-6 space-y-3">
            <div className="flex items-center justify-between gap-2">
              <h2 className="text-sm font-semibold text-slate-900 dark:text-white">
                Common foods
              </h2>
              <Link
                href="/dashboard/meals/common-foods"
                data-testid="meal-manage-common-foods"
                className="text-xs text-blue-600 dark:text-blue-400 hover:underline"
              >
                Manage
              </Link>
            </div>
            <MealCommonFoodSection record={record} onUpdated={handleUpdated} />
          </div>
        </AnimatedCard>

        {/* "How this was estimated": the deterministic provenance trail the audit
            endpoint records — per-sample reads, empirical dispersion, and the
            precedence decision. Descriptive only; it hides itself when meal
            intelligence is off (a flag-off server hides the record above, so we
            never get here). */}
        <AnimatedCard delay={0.1}>
          <MealAuditPanel record={record} />
        </AnimatedCard>

        {facts?.portion && (
          <AnimatedCard delay={0.125}>
            <MealAssumedPortion portion={facts.portion} />
          </AnimatedCard>
        )}

        {hasNutrition && facts && (
          <AnimatedCard delay={0.15}>
            <MealNutritionFacts facts={facts} />
          </AnimatedCard>
        )}

        {facts?.disclaimer && (
          <MealNutritionDisclaimer disclaimer={facts.disclaimer} />
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
