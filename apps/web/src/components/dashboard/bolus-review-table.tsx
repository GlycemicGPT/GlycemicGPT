"use client";

/**
 * Bolus Review Table
 *
 * Story 30.7: Displays a scrollable table of recent bolus events with
 * type badges, BG/IoB context, and Control-IQ reason. Period-selectable.
 */

import { useRef } from "react";
import { AlertCircle, ListOrdered } from "lucide-react";
import {
  useBolusReview,
  type BolusReviewPeriod,
  BOLUS_PERIOD_LABELS,
} from "@/hooks/use-bolus-review";
import type { BolusReviewItem } from "@/lib/api";

export interface BolusReviewTableProps {
  className?: string;
}

const PERIOD_OPTIONS: { value: BolusReviewPeriod; label: string }[] = [
  { value: "24h", label: "24H" },
  { value: "3d", label: "3D" },
  { value: "7d", label: "7D" },
  { value: "14d", label: "14D" },
  { value: "30d", label: "30D" },
];

function formatDateTime(iso: string): string {
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return "---";
    return d.toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
      hour12: true,
    });
  } catch {
    return "---";
  }
}

function SkeletonRow() {
  return (
    <tr className="border-b border-slate-200/50 dark:border-slate-800/50">
      {Array.from({ length: 6 }).map((_, i) => (
        <td key={i} className="px-4 py-3">
          <div className="animate-pulse h-4 bg-slate-200 dark:bg-slate-700 rounded w-16" />
        </td>
      ))}
    </tr>
  );
}

const MAX_BOLUS_DISPLAY = 50;
const BG_MIN = 20;
const BG_MAX = 500;

function formatUnits(value: number | null | undefined, decimals: number): string {
  if (value == null || !Number.isFinite(value) || value < 0) return "---";
  if (value > MAX_BOLUS_DISPLAY) return `>${MAX_BOLUS_DISPLAY}`;
  return `${value.toFixed(decimals)} U`;
}

function formatBg(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "---";
  const clamped = Math.min(BG_MAX, Math.max(BG_MIN, Math.round(value)));
  return `${clamped} mg/dL`;
}

function BolusRow({ bolus }: { bolus: BolusReviewItem }) {
  return (
    <tr
      className="border-b border-slate-200/50 dark:border-slate-800/50 hover:bg-slate-100/30 dark:hover:bg-slate-800/30 transition-colors"
      aria-label={`Bolus at ${formatDateTime(bolus.event_timestamp)}, ${formatUnits(bolus.units, 2)}, ${bolus.is_automated ? "automated" : "manual"}`}
    >
      <td className="px-4 py-3 text-sm text-slate-600 dark:text-slate-300 whitespace-nowrap">
        {formatDateTime(bolus.event_timestamp)}
      </td>
      <td className="px-4 py-3 text-sm text-slate-900 dark:text-white font-medium whitespace-nowrap">
        {formatUnits(bolus.units, 2)}
      </td>
      <td className="px-4 py-3 whitespace-nowrap">
        {bolus.is_automated ? (
          <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-violet-500/20 text-violet-700 dark:text-violet-300">
            Auto
          </span>
        ) : (
          <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-slate-200/50 dark:bg-slate-700/50 text-slate-600 dark:text-slate-400">
            Manual
          </span>
        )}
      </td>
      <td className="px-4 py-3 text-sm text-slate-600 dark:text-slate-300 whitespace-nowrap">
        {formatBg(bolus.bg_at_event)}
      </td>
      <td className="px-4 py-3 text-sm text-slate-600 dark:text-slate-300 whitespace-nowrap">
        {formatUnits(bolus.iob_at_event, 1)}
      </td>
      <td className="px-4 py-3 text-sm text-slate-500 dark:text-slate-400 whitespace-nowrap max-w-[200px] truncate">
        {bolus.is_automated
          ? (bolus.control_iq_reason || "Automated correction")
          : ""}
      </td>
    </tr>
  );
}

export function BolusReviewTable({ className }: BolusReviewTableProps) {
  const { data, isLoading, error, period, setPeriod, refetch } = useBolusReview();
  const periodLabel = BOLUS_PERIOD_LABELS[period] ?? period;
  const buttonsRef = useRef<(HTMLButtonElement | null)[]>([]);

  const handlePeriodKeyDown = (e: React.KeyboardEvent, index: number) => {
    let newIndex = index;
    if (e.key === "ArrowRight" || e.key === "ArrowDown") {
      e.preventDefault();
      newIndex = (index + 1) % PERIOD_OPTIONS.length;
    } else if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
      e.preventDefault();
      newIndex = (index - 1 + PERIOD_OPTIONS.length) % PERIOD_OPTIONS.length;
    } else if (e.key === "Home") {
      e.preventDefault();
      newIndex = 0;
    } else if (e.key === "End") {
      e.preventDefault();
      newIndex = PERIOD_OPTIONS.length - 1;
    } else {
      return;
    }
    setPeriod(PERIOD_OPTIONS[newIndex].value);
    buttonsRef.current[newIndex]?.focus();
  };

  const noData = !data || !data.boluses || data.boluses.length === 0;

  const periodSelector = (
    <div className="flex gap-1" role="radiogroup" aria-label="Bolus review time period">
      {PERIOD_OPTIONS.map((opt, i) => (
        <button
          key={opt.value}
          ref={(el) => { buttonsRef.current[i] = el; }}
          role="radio"
          aria-checked={period === opt.value}
          aria-label={BOLUS_PERIOD_LABELS[opt.value]}
          tabIndex={period === opt.value ? 0 : -1}
          onClick={() => setPeriod(opt.value)}
          onKeyDown={(e) => handlePeriodKeyDown(e, i)}
          className={`px-2.5 py-1 text-xs font-medium rounded-md transition-colors outline-none focus-visible:ring-2 focus-visible:ring-violet-400 focus-visible:ring-offset-2 focus-visible:ring-offset-white dark:focus-visible:ring-offset-slate-900 ${
            period === opt.value
              ? "bg-violet-600 text-white"
              : "text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-slate-800"
          }`}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );

  return (
    <section
      aria-labelledby="bolus-review-heading"
      aria-busy={isLoading}
      data-testid="bolus-review"
      className={`bg-white dark:bg-slate-900 rounded-xl p-6 border border-slate-200 dark:border-slate-800 ${className ?? ""}`}
    >
      {/* Header with period selector */}
      <div className="flex items-center justify-between mb-5">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-violet-500/10 rounded-lg">
            <ListOrdered className="h-5 w-5 text-violet-400" aria-hidden="true" />
          </div>
          <h2 id="bolus-review-heading" className="text-slate-900 dark:text-white font-semibold">
            Recent Boluses
            <span className="text-slate-500 dark:text-slate-400 text-sm font-normal ml-2">
              {periodLabel}
            </span>
          </h2>
        </div>
        {periodSelector}
      </div>

      {/* Table content */}
      {isLoading ? (
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-slate-300 dark:border-slate-700">
                <th scope="col" className="px-4 py-2 text-xs font-medium text-slate-500 dark:text-slate-400">Time</th>
                <th scope="col" className="px-4 py-2 text-xs font-medium text-slate-500 dark:text-slate-400">Units</th>
                <th scope="col" className="px-4 py-2 text-xs font-medium text-slate-500 dark:text-slate-400">Type</th>
                <th scope="col" className="px-4 py-2 text-xs font-medium text-slate-500 dark:text-slate-400">BG</th>
                <th scope="col" className="px-4 py-2 text-xs font-medium text-slate-500 dark:text-slate-400">IoB</th>
                <th scope="col" className="px-4 py-2 text-xs font-medium text-slate-500 dark:text-slate-400">Reason</th>
              </tr>
            </thead>
            <tbody>
              {Array.from({ length: 5 }).map((_, i) => (
                <SkeletonRow key={i} />
              ))}
            </tbody>
          </table>
        </div>
      ) : error ? (
        <div className="text-center py-4">
          <div className="flex items-center gap-2 text-red-400 text-sm justify-center mb-3" role="alert">
            <AlertCircle className="h-4 w-4" aria-hidden="true" />
            <p>Failed to load bolus data.</p>
          </div>
          <p className="text-slate-500 dark:text-slate-400 text-xs mb-3 max-w-md truncate">{error}</p>
          <button
            type="button"
            onClick={refetch}
            className="text-violet-400 hover:text-violet-300 text-sm font-medium outline-none focus-visible:ring-2 focus-visible:ring-violet-400 focus-visible:ring-offset-2 focus-visible:ring-offset-white dark:focus-visible:ring-offset-slate-900 rounded"
          >
            Retry
          </button>
        </div>
      ) : noData ? (
        <p className="text-slate-500 dark:text-slate-400 text-sm text-center py-4">
          No bolus events recorded for this period.
        </p>
      ) : (
        <div className="overflow-x-auto max-h-96 overflow-y-auto">
          <table className="w-full text-left">
            <thead className="sticky top-0 bg-white dark:bg-slate-900">
              <tr className="border-b border-slate-300 dark:border-slate-700">
                <th scope="col" className="px-4 py-2 text-xs font-medium text-slate-500 dark:text-slate-400">Time</th>
                <th scope="col" className="px-4 py-2 text-xs font-medium text-slate-500 dark:text-slate-400">Units</th>
                <th scope="col" className="px-4 py-2 text-xs font-medium text-slate-500 dark:text-slate-400">Type</th>
                <th scope="col" className="px-4 py-2 text-xs font-medium text-slate-500 dark:text-slate-400">BG</th>
                <th scope="col" className="px-4 py-2 text-xs font-medium text-slate-500 dark:text-slate-400">IoB</th>
                <th scope="col" className="px-4 py-2 text-xs font-medium text-slate-500 dark:text-slate-400">Reason</th>
              </tr>
            </thead>
            <tbody>
              {data.boluses.map((bolus, i) => (
                <BolusRow key={`${bolus.event_timestamp}-${i}`} bolus={bolus} />
              ))}
            </tbody>
          </table>
          {data.total_count > data.boluses.length && (
            <p className="text-slate-500 dark:text-slate-400 text-xs text-center mt-3">
              Showing {data.boluses.length} of {data.total_count} bolus events
            </p>
          )}
        </div>
      )}
    </section>
  );
}
