"use client";

/**
 * Meals list.
 *
 * Lists the user's food records (most recent first) and hosts the web meal
 * upload. Modelled on the Knowledge Base page (list -> detail -> delete ->
 * pagination). Owner-scoped + flag-gated server-side; a feature-off response is
 * rendered as a clear state, never a raw 404.
 */

import { useState, useEffect, useCallback, useRef } from "react";
import Link from "next/link";
import { UtensilsCrossed, Loader2, ChevronRight } from "lucide-react";
import { listFoodRecords, type FoodRecord } from "@/lib/api";
import { classifyMealError, type MealErrorInfo } from "@/lib/meal-errors";
import {
  effectiveCarbRange,
  formatCarbRange,
  confidenceLabel,
  mealTitle,
} from "@/lib/meal-format";
import { PageTransition } from "@/components/ui/page-transition";
import { AnimatedCard } from "@/components/ui/animated-card";
import { MealUpload } from "@/components/meals/meal-upload";
import { MealPhoto } from "@/components/meals/meal-photo";
import {
  SourceBadge,
  IdentityConfirmedBadge,
  MealSafetyQualifier,
  MealErrorPanel,
} from "@/components/meals/meal-ui";

const PAGE_SIZE = 50;

function MealRow({ record, delay }: { record: FoodRecord; delay: number }) {
  const range = effectiveCarbRange(record);
  return (
    <AnimatedCard delay={delay}>
      <Link
        href={`/dashboard/meals/${record.id}`}
        data-testid="meal-card"
        className="flex gap-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-4 hover:border-blue-400 dark:hover:border-blue-500/50 transition-colors"
      >
        <MealPhoto recordId={record.id} size="sm" />
        <div className="flex-1 min-w-0 space-y-2">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <h3 className="font-medium text-slate-900 dark:text-white truncate">
                {mealTitle(record)}
              </h3>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                {new Date(record.meal_timestamp).toLocaleString()}
              </p>
            </div>
            <ChevronRight className="h-4 w-4 flex-shrink-0 text-slate-400" />
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <span
              data-testid="meal-carb-range"
              className="text-sm font-semibold text-slate-900 dark:text-white"
            >
              {formatCarbRange(range.low, range.high)}
            </span>
            <span className="text-xs text-slate-500 dark:text-slate-400">
              {confidenceLabel(record.confidence)}
            </span>
            <SourceBadge source={record.source} />
            {record.identity_confirmed && <IdentityConfirmedBadge />}
          </div>

          <MealSafetyQualifier qualifier={record.safety_qualifier} />
        </div>
      </Link>
    </AnimatedCard>
  );
}

export default function MealsPage() {
  const [records, setRecords] = useState<FoodRecord[]>([]);
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
      const data = await listFoodRecords(PAGE_SIZE, (pageNum - 1) * PAGE_SIZE);
      if (requestId !== requestIdRef.current) return;
      setRecords(data.records);
      setTotal(data.total);
      setBlockedInfo(null);
    } catch (err) {
      if (requestId !== requestIdRef.current) return;
      const info = classifyMealError(err);
      if (info.retryable) {
        setError(info.message);
      } else {
        setBlockedInfo(info);
        setRecords([]);
        setTotal(0);
      }
    } finally {
      if (requestId === requestIdRef.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData(page);
  }, [loadData, page]);

  // Auto-dismiss the upload success banner so it never lingers across reloads.
  useEffect(() => {
    if (!success) return;
    const timer = setTimeout(() => setSuccess(null), 5000);
    return () => clearTimeout(timer);
  }, [success]);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const handleUploaded = useCallback(
    (record: FoodRecord) => {
      setSuccess(`Logged: ${mealTitle(record)}`);
      setBlockedInfo(null);
      if (page === 1) {
        loadData(1);
      } else {
        setPage(1);
      }
    },
    [page, loadData]
  );

  if (loading && records.length === 0 && !blockedInfo) {
    return (
      <div
        role="status"
        aria-live="polite"
        className="flex flex-col h-full items-center justify-center"
      >
        <Loader2 className="h-8 w-8 animate-spin text-blue-400" />
        <p className="mt-4 text-slate-500 dark:text-slate-400">Loading meals...</p>
      </div>
    );
  }

  return (
    <PageTransition>
      <div className="max-w-4xl mx-auto space-y-6 p-6">
        {/* Header */}
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex items-center gap-3">
            <UtensilsCrossed className="h-7 w-7 text-blue-400" />
            <div>
              <h1 className="text-2xl font-bold text-slate-900 dark:text-white">
                Meals
              </h1>
              <p className="text-slate-500 dark:text-slate-400 text-sm">
                {blockedInfo
                  ? "Your meal photo log"
                  : `${total} logged meal${total === 1 ? "" : "s"}`}
              </p>
            </div>
          </div>
          {!blockedInfo && (
            <MealUpload
              onUploaded={handleUploaded}
              onFeatureOff={() => loadData(1)}
            />
          )}
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

        {/* Feature-off (or other non-retryable) dead end */}
        {blockedInfo ? (
          <MealErrorPanel info={blockedInfo} />
        ) : records.length === 0 ? (
          <div
            data-testid="meal-empty"
            className="text-center py-16 bg-slate-100/50 dark:bg-slate-800/30 rounded-lg"
          >
            <UtensilsCrossed className="h-14 w-14 text-slate-400 dark:text-slate-600 mx-auto mb-4" />
            <h2 className="text-lg font-medium text-slate-900 dark:text-white mb-2">
              No meals logged yet
            </h2>
            <p className="text-slate-500 dark:text-slate-400 max-w-md mx-auto">
              Use “Log a meal” to add a photo and get a rough AI carb estimate.
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            {records.map((record, i) => (
              <MealRow
                key={record.id}
                record={record}
                delay={Math.min(i * 0.03, 0.3)}
              />
            ))}
          </div>
        )}

        {/* Pagination */}
        {!blockedInfo && totalPages > 1 && (
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
      </div>
    </PageTransition>
  );
}
