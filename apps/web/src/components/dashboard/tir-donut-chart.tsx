"use client";

/**
 * TirDonutChart Component
 *
 * Story 30.4: 5-bucket clinical TIR donut chart with previous-period comparison.
 * Uses Recharts PieChart with two concentric rings: outer = current, inner = previous.
 */

import { useMemo } from "react";
import { PieChart, Pie, Cell, ResponsiveContainer } from "recharts";
import clsx from "clsx";

import type { TirBucket } from "@/lib/api";
import { formatPercentage, PERIOD_LABELS } from "./time-in-range-bar";
import type { TimePeriod } from "./time-in-range-bar";

export interface TirDonutChartProps {
  buckets: TirBucket[] | null;
  readingsCount: number;
  previousBuckets: TirBucket[] | null;
  previousReadingsCount: number | null;
  isLoading?: boolean;
  period?: TimePeriod;
  onPeriodChange?: (period: TimePeriod) => void;
  className?: string;
}

const PERIOD_OPTIONS: TimePeriod[] = ["24h", "3d", "7d", "14d", "30d"];

/** Clinical TIR colors matching Tandem Source / Dexcom Clarity */
const BUCKET_COLORS: Record<string, string> = {
  urgent_low: "#dc2626",
  low: "#f59e0b",
  in_range: "#22c55e",
  high: "#f97316",
  urgent_high: "#991b1b",
};

const BUCKET_LABELS: Record<string, string> = {
  urgent_low: "Urgent Low",
  low: "Low",
  in_range: "In Range",
  high: "High",
  urgent_high: "Urgent High",
};

/** Sanitize a single bucket pct value (guard against NaN/Infinity/negative). */
function sanitizePct(value: number): number {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) {
    return 0;
  }
  return Math.min(value, 100);
}

/** Sanitize all buckets in an array. */
function sanitizeBuckets(buckets: TirBucket[]): TirBucket[] {
  return buckets.map((b) => ({ ...b, pct: sanitizePct(b.pct) }));
}

/** Build Recharts Pie data from TIR buckets. Zero-pct buckets render as 0. */
function toPieData(buckets: TirBucket[]) {
  return buckets.map((b) => ({
    name: b.label,
    value: b.pct > 0 ? b.pct : 0,
    color: BUCKET_COLORS[b.label] ?? "#6b7280",
    pct: b.pct,
  }));
}

export function TirDonutChart({
  buckets,
  readingsCount,
  previousBuckets,
  previousReadingsCount,
  isLoading = false,
  period = "24h",
  onPeriodChange,
  className,
}: TirDonutChartProps) {
  // Loading skeleton
  if (isLoading) {
    return (
      <div
        className={clsx(
          "bg-slate-900 rounded-xl p-6 border border-slate-800 animate-pulse",
          className
        )}
        data-testid="tir-donut-chart"
        role="region"
        aria-label="Loading time in range donut chart"
        aria-busy="true"
      >
        <div className="flex items-center justify-between mb-4">
          <div className="h-6 w-48 bg-slate-700 rounded" />
          <div className="h-6 w-20 bg-slate-700 rounded" />
        </div>
        <div className="flex justify-center">
          <div className="w-64 h-64 bg-slate-700 rounded-full" />
        </div>
        <div className="flex justify-center gap-4 mt-4">
          {[1, 2, 3, 4, 5].map((i) => (
            <div key={i} className="h-4 w-16 bg-slate-700 rounded" />
          ))}
        </div>
      </div>
    );
  }

  // No data state
  if (!buckets || readingsCount === 0) {
    return (
      <div
        className={clsx(
          "bg-slate-900 rounded-xl p-6 border border-slate-800",
          className
        )}
        data-testid="tir-donut-chart"
      >
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold">Time in Range</h2>
          {onPeriodChange && (
            <PeriodSelector
              period={period}
              onPeriodChange={onPeriodChange}
            />
          )}
        </div>
        <p className="text-slate-500 text-center py-12" data-testid="no-data-message">
          No glucose data available for this period.
        </p>
      </div>
    );
  }

  const safeBuckets = sanitizeBuckets(buckets);
  const safePrevBuckets = previousBuckets
    ? sanitizeBuckets(previousBuckets)
    : null;

  return (
    <TirDonutChartInner
      buckets={safeBuckets}
      readingsCount={readingsCount}
      previousBuckets={safePrevBuckets}
      previousReadingsCount={previousReadingsCount}
      period={period}
      onPeriodChange={onPeriodChange}
      className={className}
    />
  );
}

/** Inner component that renders when data is present. */
function TirDonutChartInner({
  buckets,
  readingsCount,
  previousBuckets,
  previousReadingsCount,
  period,
  onPeriodChange,
  className,
}: {
  buckets: TirBucket[];
  readingsCount: number;
  previousBuckets: TirBucket[] | null;
  previousReadingsCount: number | null;
  period: TimePeriod;
  onPeriodChange?: (period: TimePeriod) => void;
  className?: string;
}) {
  const currentData = useMemo(() => toPieData(buckets), [buckets]);
  const previousData = useMemo(
    () => (previousBuckets ? toPieData(previousBuckets) : null),
    [previousBuckets]
  );

  // Find in-range bucket for center display
  const inRangeBucket = buckets.find((b) => b.label === "in_range");
  const inRangePct = inRangeBucket?.pct ?? 0;

  // Calculate delta vs previous
  const prevInRange = previousBuckets?.find(
    (b) => b.label === "in_range"
  )?.pct;
  const delta =
    prevInRange != null ? Math.round(inRangePct - prevInRange) : null;

  // Build aria description
  const ariaLabel = `Time in range donut chart for ${PERIOD_LABELS[period]}: ${buckets
    .map((b) => `${BUCKET_LABELS[b.label]} ${formatPercentage(b.pct)}`)
    .join(", ")}. ${readingsCount} readings.`;

  return (
    <div
      className={clsx(
        "bg-slate-900 rounded-xl p-6 border border-slate-800",
        className
      )}
      data-testid="tir-donut-chart"
    >
      {/* Header with period selector */}
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold">Time in Range</h2>
        {onPeriodChange && (
          <PeriodSelector period={period} onPeriodChange={onPeriodChange} />
        )}
      </div>

      {/* Donut chart */}
      <div
        className="relative h-72"
        role="img"
        aria-label={ariaLabel}
      >
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            {/* Previous period (inner ring) */}
            {previousData && (
              <Pie
                data={previousData}
                dataKey="value"
                cx="50%"
                cy="50%"
                innerRadius="38%"
                outerRadius="52%"
                startAngle={90}
                endAngle={-270}
                isAnimationActive={true}
                stroke="none"
              >
                {previousData.map((entry, idx) => (
                  <Cell
                    key={`prev-${idx}`}
                    fill={entry.color}
                    fillOpacity={0.4}
                  />
                ))}
              </Pie>
            )}

            {/* Current period (outer ring) */}
            <Pie
              data={currentData}
              dataKey="value"
              cx="50%"
              cy="50%"
              innerRadius={previousData ? "56%" : "50%"}
              outerRadius="80%"
              startAngle={90}
              endAngle={-270}
              isAnimationActive={true}
              stroke="none"
            >
              {currentData.map((entry, idx) => (
                <Cell key={`curr-${idx}`} fill={entry.color} />
              ))}
            </Pie>
          </PieChart>
        </ResponsiveContainer>

        {/* Center overlay */}
        <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
          <span
            className={clsx(
              "text-3xl font-bold",
              inRangePct >= 70 ? "text-green-400" :
              inRangePct >= 50 ? "text-amber-400" :
              "text-red-400"
            )}
            data-testid="in-range-center"
          >
            {formatPercentage(inRangePct)}
          </span>
          <span className="text-xs text-slate-400">In Range</span>
          {delta !== null && delta !== 0 && (
            <span
              className={clsx(
                "text-sm font-medium mt-1",
                delta > 0 ? "text-green-400" : "text-red-400"
              )}
              data-testid="delta-indicator"
            >
              {delta > 0 ? "+" : ""}
              {delta}%
            </span>
          )}
        </div>
      </div>

      {/* Legend */}
      <div
        className="flex flex-wrap justify-center gap-x-4 gap-y-2 mt-4"
        data-testid="tir-legend"
      >
        {buckets.map((b) => (
          <div key={b.label} className="flex items-center gap-1.5">
            <div
              className="w-2.5 h-2.5 rounded-full flex-shrink-0"
              style={{ backgroundColor: BUCKET_COLORS[b.label] }}
              aria-hidden="true"
            />
            <span className="text-xs text-slate-300">
              {BUCKET_LABELS[b.label]}
            </span>
            <span className="text-xs text-slate-500">
              {formatPercentage(b.pct)}
            </span>
          </div>
        ))}
      </div>

      {/* Readings count */}
      <p className="text-slate-500 text-xs mt-3 text-center">
        {readingsCount} readings
        {previousReadingsCount != null &&
          ` (prev: ${previousReadingsCount})`}
      </p>
    </div>
  );
}

/** Period selector radio group (reuses pattern from TimeInRangeBar). */
function PeriodSelector({
  period,
  onPeriodChange,
}: {
  period: TimePeriod;
  onPeriodChange: (period: TimePeriod) => void;
}) {
  return (
    <div
      className="flex gap-1 bg-slate-800 rounded-lg p-1"
      role="radiogroup"
      aria-label="Time period"
      data-testid="donut-period-selector"
    >
      {PERIOD_OPTIONS.map((p) => (
        <button
          key={p}
          role="radio"
          aria-checked={p === period}
          onClick={() => onPeriodChange(p)}
          className={clsx(
            "px-2 py-1 text-xs font-medium rounded transition-colors",
            p === period
              ? "bg-blue-600 text-white"
              : "text-slate-400 hover:text-slate-200"
          )}
        >
          {p.toUpperCase()}
        </button>
      ))}
    </div>
  );
}

export default TirDonutChart;
