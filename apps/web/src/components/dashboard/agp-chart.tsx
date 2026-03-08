"use client";

/**
 * AGP Chart Component
 *
 * Story 30.5: Ambulatory Glucose Profile (AGP) percentile band chart.
 * Shows glucose patterns over a 24-hour day using p10/p25/p50/p75/p90
 * percentile bands, rendered as stacked areas with a median line overlay.
 */

import { useMemo, useRef } from "react";
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
} from "recharts";
import clsx from "clsx";
import {
  useGlucosePercentiles,
  type AgpPeriod,
  AGP_PERIOD_LABELS,
} from "@/hooks/use-glucose-percentiles";
import type { AGPBucket } from "@/lib/api";

// --- Constants ---

const TEAL = "rgb(20, 184, 166)";
const TEAL_OUTER = "rgba(20, 184, 166, 0.15)";
const TEAL_INNER = "rgba(20, 184, 166, 0.30)";

/** Clamp a glucose mg/dL value to physiological bounds. */
const clampMgdl = (v: number): number => Math.max(20, Math.min(500, v));

const AGP_PERIODS: { value: AgpPeriod; label: string }[] = [
  { value: "7d", label: "7D" },
  { value: "14d", label: "14D" },
  { value: "30d", label: "30D" },
  { value: "90d", label: "90D" },
];

// --- Props ---

export interface AgpChartProps {
  className?: string;
  thresholds?: { urgentLow: number; low: number; high: number; urgentHigh: number };
}

// --- Data transformation ---

interface AgpChartPoint {
  hour: number;
  label: string;
  base: number;
  band_p10_p25: number;
  band_p25_p50: number;
  band_p50_p75: number;
  band_p75_p90: number;
  // Raw values for tooltip
  p10: number;
  p25: number;
  p50: number;
  p75: number;
  p90: number;
  count: number;
}

export function formatHour(hour: number): string {
  const h = Math.max(0, Math.min(23, Math.round(hour)));
  if (h === 0) return "12 AM";
  if (h === 12) return "12 PM";
  if (h < 12) return `${h} AM`;
  return `${h - 12} PM`;
}

export function transformBuckets(buckets: AGPBucket[]): AgpChartPoint[] {
  return buckets.map((b) => {
    const p10 = clampMgdl(b.p10);
    const p25 = clampMgdl(b.p25);
    const p50 = clampMgdl(b.p50);
    const p75 = clampMgdl(b.p75);
    const p90 = clampMgdl(b.p90);
    return {
      hour: b.hour,
      label: formatHour(b.hour),
      base: Math.round(p10),
      band_p10_p25: Math.max(0, Math.round(p25 - p10)),
      band_p25_p50: Math.max(0, Math.round(p50 - p25)),
      band_p50_p75: Math.max(0, Math.round(p75 - p50)),
      band_p75_p90: Math.max(0, Math.round(p90 - p75)),
      p10,
      p25,
      p50,
      p75,
      p90,
      count: b.count,
    };
  });
}

// --- Custom tooltip ---

function AgpTooltipContent({
  active,
  payload,
}: {
  active?: boolean;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  payload?: Array<{ payload: any }>;
}) {
  if (!active || !payload?.length) return null;
  const d = payload[0]?.payload as AgpChartPoint | undefined;
  if (!d) return null;
  if (d.count === 0) {
    return (
      <div className="bg-slate-100 dark:bg-slate-800 border border-slate-300 dark:border-slate-700 rounded-lg px-3 py-2 text-xs shadow-lg">
        <p className="font-semibold text-slate-200 mb-1">{d.label}</p>
        <p className="text-slate-500 dark:text-slate-400">No data for this hour</p>
      </div>
    );
  }
  return (
    <div className="bg-slate-100 dark:bg-slate-800 border border-slate-300 dark:border-slate-700 rounded-lg px-3 py-2 text-xs shadow-lg">
      <p className="font-semibold text-slate-200 mb-1">{d.label}</p>
      <p className="text-teal-400">Median: {Math.round(d.p50)} mg/dL</p>
      <p className="text-slate-600 dark:text-slate-300">25th-75th: {Math.round(d.p25)}-{Math.round(d.p75)} mg/dL</p>
      <p className="text-slate-500 dark:text-slate-400">10th-90th: {Math.round(d.p10)}-{Math.round(d.p90)} mg/dL</p>
      <p className="text-slate-500 dark:text-slate-500 mt-1">{d.count} readings</p>
    </div>
  );
}

// --- Period selector ---

function PeriodSelector({
  period,
  onPeriodChange,
}: {
  period: AgpPeriod;
  onPeriodChange: (p: AgpPeriod) => void;
}) {
  const buttonsRef = useRef<(HTMLButtonElement | null)[]>([]);
  const len = AGP_PERIODS.length;

  const handleKeyDown = (e: React.KeyboardEvent, index: number) => {
    let newIndex: number | null = null;
    if (e.key === "ArrowRight" || e.key === "ArrowDown") {
      e.preventDefault();
      newIndex = (index + 1) % len;
    } else if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
      e.preventDefault();
      newIndex = (index - 1 + len) % len;
    } else if (e.key === "Home") {
      e.preventDefault();
      newIndex = 0;
    } else if (e.key === "End") {
      e.preventDefault();
      newIndex = len - 1;
    }
    if (newIndex != null) {
      onPeriodChange(AGP_PERIODS[newIndex].value);
      buttonsRef.current[newIndex]?.focus();
    }
  };

  return (
    <div
      role="radiogroup"
      aria-label="AGP time period"
      className="flex gap-1"
    >
      {AGP_PERIODS.map((p, index) => (
        <button
          key={p.value}
          ref={(el) => { buttonsRef.current[index] = el; }}
          type="button"
          role="radio"
          aria-checked={period === p.value}
          aria-label={AGP_PERIOD_LABELS[p.value]}
          tabIndex={period === p.value ? 0 : -1}
          onClick={() => onPeriodChange(p.value)}
          onKeyDown={(e) => handleKeyDown(e, index)}
          className={clsx(
            "px-3 py-1 text-xs font-medium rounded-md transition-colors outline-none focus-visible:ring-2 focus-visible:ring-teal-400 focus-visible:ring-offset-2 focus-visible:ring-offset-white dark:focus-visible:ring-offset-slate-900",
            period === p.value
              ? "bg-teal-500/20 text-teal-400 border border-teal-500/40"
              : "text-slate-500 dark:text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 border border-transparent"
          )}
        >
          {p.label}
        </button>
      ))}
    </div>
  );
}

// --- Main component ---

export function AgpChart({ className, thresholds }: AgpChartProps) {
  const {
    data,
    isLoading,
    error,
    period,
    setPeriod,
    refetch,
  } = useGlucosePercentiles("14d");

  const low = clampMgdl(thresholds?.low ?? 70);
  const high = clampMgdl(thresholds?.high ?? 180);

  const chartData = useMemo(() => {
    if (!data?.buckets?.length) return [];
    return transformBuckets(data.buckets);
  }, [data]);

  // Calculate Y-axis domain: default [40, 300], expand if data exceeds
  const yDomain = useMemo((): [number, number] => {
    if (!chartData.length) return [40, 300];
    let min = 40;
    let max = 300;
    for (const p of chartData) {
      if (p.p10 < min) min = p.p10;
      if (p.p90 > max) max = p.p90;
    }
    return [Math.max(0, Math.floor(min / 10) * 10), Math.ceil(max / 10) * 10];
  }, [chartData]);

  // Loading state
  if (isLoading && !data) {
    return (
      <section
        data-testid="agp-chart"
        aria-label="Loading AGP chart"
        aria-busy="true"
        className={clsx(
          "bg-white dark:bg-slate-900 rounded-xl p-6 border border-slate-200 dark:border-slate-800",
          className
        )}
      >
        <div className="flex items-center justify-between mb-4">
          <div className="h-6 w-48 bg-slate-100 dark:bg-slate-800 rounded animate-pulse" />
          <div className="flex gap-1">
            {[1, 2, 3, 4].map((i) => (
              <div key={i} className="h-7 w-10 bg-slate-100 dark:bg-slate-800 rounded animate-pulse" />
            ))}
          </div>
        </div>
        <div className="h-64 bg-slate-100 dark:bg-slate-800 rounded animate-pulse" />
      </section>
    );
  }

  // Error state
  if (error && !data) {
    return (
      <section
        data-testid="agp-chart"
        aria-label="AGP chart error"
        className={clsx(
          "bg-white dark:bg-slate-900 rounded-xl p-6 border border-slate-200 dark:border-slate-800",
          className
        )}
      >
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-slate-200">
            Ambulatory Glucose Profile
          </h2>
          <PeriodSelector period={period} onPeriodChange={setPeriod} />
        </div>
        <div className="flex flex-col items-center justify-center h-64 text-center">
          <p className="text-red-400 mb-2">Unable to load AGP data</p>
          <p className="text-slate-500 dark:text-slate-500 text-xs mb-2">{error}</p>
          <button
            type="button"
            onClick={refetch}
            className="text-teal-400 hover:text-teal-300 text-sm underline outline-none focus-visible:ring-2 focus-visible:ring-teal-400 focus-visible:ring-offset-2 focus-visible:ring-offset-white dark:focus-visible:ring-offset-slate-900 rounded"
          >
            Retry
          </button>
        </div>
      </section>
    );
  }

  // No data state
  if (!chartData.length) {
    return (
      <section
        data-testid="agp-chart"
        aria-label="AGP chart empty"
        className={clsx(
          "bg-white dark:bg-slate-900 rounded-xl p-6 border border-slate-200 dark:border-slate-800",
          className
        )}
      >
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-slate-200">
            Ambulatory Glucose Profile
          </h2>
          <PeriodSelector period={period} onPeriodChange={setPeriod} />
        </div>
        <div className="flex items-center justify-center h-64">
          <p className="text-slate-500 dark:text-slate-400">
            Not enough glucose data for AGP analysis (minimum 7 days needed)
          </p>
        </div>
      </section>
    );
  }

  // Data state
  return (
    <section
      data-testid="agp-chart"
      aria-label={`Ambulatory Glucose Profile, ${AGP_PERIOD_LABELS[period]} view`}
      className={clsx(
        "bg-white dark:bg-slate-900 rounded-xl p-6 border border-slate-200 dark:border-slate-800",
        className
      )}
    >
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-lg font-semibold text-slate-200">
            Ambulatory Glucose Profile
          </h2>
          <p className="text-xs text-slate-500 dark:text-slate-400" aria-live="polite">
            {data?.readings_count?.toLocaleString() ?? 0} readings
            {data?.is_truncated && (
              <span className="text-amber-400 ml-1" data-testid="agp-truncation-warning">
                (data truncated to available range)
              </span>
            )}
          </p>
        </div>
        <PeriodSelector period={period} onPeriodChange={setPeriod} />
      </div>

      {/* Chart */}
      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={chartData} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false} />
            <XAxis
              dataKey="hour"
              type="number"
              domain={[0, 23]}
              ticks={[0, 3, 6, 9, 12, 15, 18, 21]}
              tickFormatter={formatHour}
              tick={{ fill: "#94a3b8", fontSize: 11 }}
              axisLine={{ stroke: "#475569" }}
              tickLine={{ stroke: "#475569" }}
            />
            <YAxis
              domain={yDomain}
              tick={{ fill: "#94a3b8", fontSize: 11 }}
              axisLine={{ stroke: "#475569" }}
              tickLine={{ stroke: "#475569" }}
              label={{
                value: "mg/dL",
                angle: -90,
                position: "insideLeft",
                style: { fill: "#64748b", fontSize: 11 },
              }}
            />
            <Tooltip content={<AgpTooltipContent />} />

            {/* Target range reference lines */}
            <ReferenceLine
              y={low}
              stroke="#22c55e"
              strokeDasharray="4 4"
              strokeWidth={1}
            />
            <ReferenceLine
              y={high}
              stroke="#22c55e"
              strokeDasharray="4 4"
              strokeWidth={1}
            />

            {/* Stacked bands: transparent base lifts to p10 */}
            <Area
              type="monotone"
              dataKey="base"
              stackId="agp"
              stroke="none"
              fill="transparent"
              isAnimationActive={false}
            />
            <Area
              type="monotone"
              dataKey="band_p10_p25"
              stackId="agp"
              stroke="none"
              fill={TEAL_OUTER}
              isAnimationActive={false}
            />
            <Area
              type="monotone"
              dataKey="band_p25_p50"
              stackId="agp"
              stroke="none"
              fill={TEAL_INNER}
              isAnimationActive={false}
            />
            <Area
              type="monotone"
              dataKey="band_p50_p75"
              stackId="agp"
              stroke="none"
              fill={TEAL_INNER}
              isAnimationActive={false}
            />
            <Area
              type="monotone"
              dataKey="band_p75_p90"
              stackId="agp"
              stroke="none"
              fill={TEAL_OUTER}
              isAnimationActive={false}
            />

            {/* Median line (non-stacked, rendered on top) */}
            <Area
              type="monotone"
              dataKey="p50"
              stroke={TEAL}
              strokeWidth={2}
              fill="none"
              dot={false}
              isAnimationActive={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      {/* Legend */}
      <div className="flex flex-wrap items-center gap-4 mt-3 text-xs text-slate-500 dark:text-slate-400" aria-label="Chart legend">
        <span className="flex items-center gap-1.5">
          <span className="w-5 h-0.5 rounded" style={{ backgroundColor: TEAL }} aria-hidden="true" />
          Median
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-4 h-3 rounded-sm" style={{ backgroundColor: TEAL_INNER }} aria-hidden="true" />
          25th-75th pctl
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-4 h-3 rounded-sm" style={{ backgroundColor: TEAL_OUTER }} aria-hidden="true" />
          10th-90th pctl
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-5 h-0 border-t border-dashed border-green-500" aria-hidden="true" />
          Target range
        </span>
      </div>
    </section>
  );
}
