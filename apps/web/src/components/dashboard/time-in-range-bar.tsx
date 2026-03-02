"use client";

/**
 * TimeInRangeBar Component
 *
 * Story 4.4 / 30.4 consolidated: 5-bucket clinical TIR horizontal stacked bar
 * with previous-period comparison and delta indicator.
 */

import { motion, useReducedMotion } from "framer-motion";
import clsx from "clsx";

import type { TirBucket } from "@/lib/api";

/** Time period options for the display */
export type TimePeriod = "24h" | "3d" | "7d" | "14d" | "30d";

export interface TimeInRangeBarProps {
  /** 5-bucket TIR data (null when no data yet) */
  buckets: TirBucket[] | null;
  /** Total readings in current period */
  readingsCount: number;
  /** Previous-period buckets for comparison (null to hide) */
  previousBuckets: TirBucket[] | null;
  /** Previous-period readings count */
  previousReadingsCount: number | null;
  /** Error message to display */
  error: string | null;
  /** Time period label (default: 24h) */
  period?: TimePeriod;
  /** Target range description (default: "70-180 mg/dL") */
  targetRange?: string;
  /** Whether data is loading */
  isLoading?: boolean;
  /** Callback when user selects a different period */
  onPeriodChange?: (period: TimePeriod) => void;
  /** Additional CSS classes */
  className?: string;
}

/** Period display labels */
export const PERIOD_LABELS: Record<TimePeriod, string> = {
  "24h": "24 Hours",
  "3d": "3 Days",
  "7d": "7 Days",
  "14d": "14 Days",
  "30d": "30 Days",
};

/** Ordered list of periods for the selector */
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

/** Canonical bucket order (bottom-to-top clinical convention) */
const BUCKET_ORDER = ["urgent_low", "low", "in_range", "high", "urgent_high"];

/**
 * Sanitize a single bucket pct value (guard against NaN/Infinity/negative).
 */
function sanitizePct(value: number): number {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) {
    return 0;
  }
  return Math.min(value, 100);
}

/**
 * Sanitize all buckets in an array.
 */
function sanitizeBuckets(buckets: TirBucket[]): TirBucket[] {
  return buckets.map((b) => ({ ...b, pct: sanitizePct(b.pct) }));
}

/**
 * Normalize bucket percentages so they sum to 100.
 * Sanitizes inputs first so callers don't need to pre-sanitize.
 * in_range absorbs rounding differences.
 */
export function normalizeBuckets(buckets: TirBucket[]): TirBucket[] {
  // Fix #3: self-sanitize so exported function is safe for external callers
  const safe = buckets.map((b) => ({ ...b, pct: sanitizePct(b.pct) }));
  const total = safe.reduce((sum, b) => sum + b.pct, 0);

  if (total === 0) return safe;
  if (Math.abs(total - 100) < 0.01) return safe;

  const factor = 100 / total;
  const scaled = safe.map((b) => ({
    ...b,
    pct: Math.round(b.pct * factor * 10) / 10,
  }));

  // Adjust in_range to absorb rounding error
  const inRangeIdx = scaled.findIndex((b) => b.label === "in_range");
  if (inRangeIdx >= 0) {
    const others = scaled.reduce(
      (sum, b, i) => (i === inRangeIdx ? sum : sum + b.pct),
      0
    );
    scaled[inRangeIdx] = {
      ...scaled[inRangeIdx],
      pct: Math.max(0, Math.round((100 - others) * 10) / 10),
    };
  }

  return scaled;
}

/**
 * Order buckets into canonical clinical order, filtering to only known labels.
 * Returns only buckets whose labels appear in BUCKET_ORDER.
 */
function orderBuckets(buckets: TirBucket[]): TirBucket[] {
  // Fix #2: no non-null assertion; unknown/missing labels handled gracefully
  return BUCKET_ORDER.reduce<TirBucket[]>((acc, label) => {
    const bucket = buckets.find((b) => b.label === label);
    if (bucket) acc.push(bucket);
    return acc;
  }, []);
}

/**
 * Format percentage for display.
 * Note: 100% is a valid output (exact 100.0 from API). Values 99.5-99.9
 * display as ">99%" to avoid implying perfect range time.
 */
export function formatPercentage(value: number): string {
  if (value === 0) return "0%";
  if (value > 0 && value < 0.5) return "<1%";
  if (value >= 99.5 && value < 100) return ">99%";
  return `${Math.round(value)}%`;
}

/**
 * Get quality assessment based on time in range.
 */
export function getQualityAssessment(inRangePercent: number): {
  label: string;
  colorClass: string;
} {
  if (inRangePercent >= 70) {
    return { label: "Excellent", colorClass: "text-green-400" };
  }
  if (inRangePercent >= 50) {
    return { label: "Good", colorClass: "text-amber-400" };
  }
  return { label: "Needs Improvement", colorClass: "text-red-400" };
}

export function TimeInRangeBar({
  buckets,
  readingsCount,
  previousBuckets,
  previousReadingsCount,
  error,
  period = "24h",
  targetRange = "70-180 mg/dL",
  isLoading = false,
  onPeriodChange,
  className,
}: TimeInRangeBarProps) {
  const prefersReducedMotion = useReducedMotion();

  // Loading skeleton
  if (isLoading) {
    return (
      <div
        className={clsx(
          "bg-slate-900 rounded-xl p-6 border border-slate-800 animate-pulse",
          className
        )}
        data-testid="time-in-range-bar"
        role="region"
        aria-label="Loading time in range data"
        aria-busy="true"
      >
        <div className="flex items-center justify-between mb-4">
          <div className="h-6 w-32 bg-slate-700 rounded" />
          <div className="h-6 w-20 bg-slate-700 rounded" />
        </div>
        <div className="h-8 bg-slate-700 rounded-full" />
        <div className="flex justify-center gap-4 mt-3">
          {[1, 2, 3, 4, 5].map((i) => (
            <div key={i} className="h-4 w-16 bg-slate-700 rounded" />
          ))}
        </div>
      </div>
    );
  }

  // Error state
  if (error) {
    return (
      <div
        className={clsx(
          "bg-slate-900 rounded-xl p-6 border border-slate-800",
          className
        )}
        data-testid="time-in-range-bar"
        role="region"
        aria-label="Time in range"
      >
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold">Time in Range</h2>
          {onPeriodChange && (
            <PeriodSelector period={period} onPeriodChange={onPeriodChange} />
          )}
        </div>
        <p
          className="text-red-400 text-center py-8"
          data-testid="error-message"
          role="alert"
        >
          {error}
        </p>
      </div>
    );
  }

  // No-data state
  if (!buckets || readingsCount === 0) {
    return (
      <div
        className={clsx(
          "bg-slate-900 rounded-xl p-6 border border-slate-800",
          className
        )}
        data-testid="time-in-range-bar"
        role="region"
        aria-label="Time in range"
      >
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold">Time in Range</h2>
          {onPeriodChange && (
            <PeriodSelector period={period} onPeriodChange={onPeriodChange} />
          )}
        </div>
        <p
          className="text-slate-500 text-center py-8"
          data-testid="no-data-message"
        >
          No glucose data available for this period.
        </p>
      </div>
    );
  }

  // Sanitize and normalize
  const safeBuckets = normalizeBuckets(sanitizeBuckets(buckets));
  const safePrevBuckets = previousBuckets
    ? normalizeBuckets(sanitizeBuckets(previousBuckets))
    : null;

  // Fix #2: order without non-null assertion
  const ordered = orderBuckets(safeBuckets);
  const orderedPrev = safePrevBuckets ? orderBuckets(safePrevBuckets) : null;

  const inRangePct =
    ordered.find((b) => b.label === "in_range")?.pct ?? 0;
  const quality = getQualityAssessment(inRangePct);

  // Delta vs previous period (sub-1% changes intentionally hidden via rounding)
  const prevInRangePct = safePrevBuckets?.find(
    (b) => b.label === "in_range"
  )?.pct;
  const delta =
    prevInRangePct != null ? Math.round(inRangePct - prevInRangePct) : null;

  const periodLabel = PERIOD_LABELS[period];

  // Build aria description
  const ariaDescription = `Time in range for ${periodLabel}: ${ordered
    .map((b) => `${BUCKET_LABELS[b.label]} ${formatPercentage(b.pct)}`)
    .join(", ")}. ${readingsCount} readings. Target: ${targetRange}.`;

  // Animation variants
  const barVariants = {
    hidden: { scaleX: 0 },
    visible: { scaleX: 1, transition: { duration: 0.6, ease: "easeOut" } },
  };

  const shouldAnimate = !prefersReducedMotion;

  const currentBar = (
    <div
      className="h-8 rounded-full overflow-hidden flex bg-slate-700"
      role="img"
      aria-label={ariaDescription}
    >
      {ordered.map((b, idx) => {
        if (b.pct === 0) return null;
        const isFirst = ordered.findIndex((x) => x.pct > 0) === idx;
        const isLast =
          ordered.length -
            1 -
            [...ordered].reverse().findIndex((x) => x.pct > 0) ===
          idx;
        return (
          <div
            key={b.label}
            className={clsx(
              "h-full flex items-center justify-center transition-all duration-300",
              isFirst && "rounded-l-full",
              isLast && "rounded-r-full"
            )}
            style={{
              width: `${b.pct}%`,
              backgroundColor: BUCKET_COLORS[b.label],
            }}
            title={`${BUCKET_LABELS[b.label]}: ${formatPercentage(b.pct)}`}
          >
            {b.pct >= 10 && (
              <span className="text-xs font-medium text-white/90 drop-shadow-sm">
                {formatPercentage(b.pct)}
              </span>
            )}
          </div>
        );
      })}
    </div>
  );

  // Fix #10: use opacity class on parent container instead of per-segment inline opacity
  const previousBar = orderedPrev ? (
    <div
      className="h-3 rounded-full overflow-hidden flex bg-slate-800 mt-1 opacity-40"
      data-testid="previous-period-bar"
      aria-label="Previous period comparison"
    >
      {orderedPrev.map((b, idx) => {
        if (b.pct === 0) return null;
        const isFirst = orderedPrev.findIndex((x) => x.pct > 0) === idx;
        const isLast =
          orderedPrev.length -
            1 -
            [...orderedPrev].reverse().findIndex((x) => x.pct > 0) ===
          idx;
        return (
          <div
            key={b.label}
            className={clsx(
              "h-full",
              isFirst && "rounded-l-full",
              isLast && "rounded-r-full"
            )}
            style={{
              width: `${b.pct}%`,
              backgroundColor: BUCKET_COLORS[b.label],
            }}
          />
        );
      })}
    </div>
  ) : null;

  return (
    // Fix #7: add role="region" and aria-label to main render path
    <div
      className={clsx(
        "bg-slate-900 rounded-xl p-6 border border-slate-800",
        className
      )}
      data-testid="time-in-range-bar"
      role="region"
      aria-label="Time in range"
    >
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <h2 className="text-lg font-semibold">Time in Range</h2>
          <span className={clsx("text-sm font-medium", quality.colorClass)}>
            {quality.label}
          </span>
          {delta !== null && delta !== 0 && (
            <span
              className={clsx(
                "text-sm font-medium",
                delta > 0 ? "text-green-400" : "text-red-400"
              )}
              data-testid="delta-indicator"
            >
              {delta > 0 ? "+" : ""}
              {delta}%
            </span>
          )}
        </div>
        {onPeriodChange ? (
          <PeriodSelector period={period} onPeriodChange={onPeriodChange} />
        ) : (
          <span
            className="text-sm text-slate-400 bg-slate-800 px-2 py-1 rounded"
            data-testid="period-label"
          >
            {periodLabel}
          </span>
        )}
      </div>

      {/* Bar */}
      {shouldAnimate ? (
        <motion.div
          initial="hidden"
          animate="visible"
          variants={barVariants}
          style={{ originX: 0 }}
        >
          {currentBar}
          {previousBar}
        </motion.div>
      ) : (
        <>
          {currentBar}
          {previousBar}
        </>
      )}

      {/* Legend -- 5 items, flex-wrap for narrow screens */}
      <div
        className="flex flex-wrap justify-center gap-x-4 gap-y-2 mt-3"
        data-testid="range-legend"
      >
        {ordered.map((b) => (
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

      {/* Target range & readings */}
      <p className="text-slate-500 text-xs mt-3 text-center">
        Target: {targetRange}
        {" \u00B7 "}
        {readingsCount} readings
        {previousReadingsCount != null &&
          ` (prev: ${previousReadingsCount})`}
      </p>
    </div>
  );
}

/** Period selector radio group */
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
      data-testid="period-selector"
    >
      {PERIOD_OPTIONS.map((p) => (
        <button
          key={p}
          role="radio"
          aria-checked={p === period}
          aria-label={PERIOD_LABELS[p]}
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

export default TimeInRangeBar;
