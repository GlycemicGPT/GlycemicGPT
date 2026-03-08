"use client";

/**
 * Story 30.8: Reports Page with Daily Timeline
 *
 * A date-selectable daily report showing glucose chart, CGM stats, TIR,
 * insulin summary, and bolus events for a single day. Printable layout.
 */

import { useCallback, useMemo, useState } from "react";
import {
  ChevronLeft,
  ChevronRight,
  Printer,
  AlertCircle,
  Loader2,
  Activity,
  BarChart3,
  Syringe,
  ListOrdered,
  Calendar,
} from "lucide-react";
import {
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip as RechartsTooltip,
  ReferenceLine,
  ReferenceArea,
  ResponsiveContainer,
} from "recharts";
import { useDailyReport } from "@/hooks/use-daily-report";
import { PageTransition } from "@/components/ui/page-transition";
import { AnimatedCard } from "@/components/ui/animated-card";
import type {
  GlucoseHistoryReading,
  GlucoseStats,
  TirBucket,
  TimeInRangeDetailStats,
  InsulinSummaryResponse,
  BolusReviewItem,
} from "@/lib/api";

// ---------------------------------------------------------------------------
// Date helpers
// ---------------------------------------------------------------------------

function todayDateString(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function shiftDate(date: string, days: number): string {
  const d = new Date(`${date}T12:00:00`);
  d.setDate(d.getDate() + days);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function formatDisplayDate(date: string): string {
  const d = new Date(`${date}T12:00:00`);
  return d.toLocaleDateString(undefined, {
    weekday: "long",
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

function isToday(date: string): boolean {
  return date === todayDateString();
}

// ---------------------------------------------------------------------------
// Glucose scatter chart (simplified 24h view)
// ---------------------------------------------------------------------------

interface ChartPoint {
  time: number;
  value: number;
  timestamp: string;
}

function transformReadings(readings: GlucoseHistoryReading[]): ChartPoint[] {
  return readings
    .map((r) => ({
      time: new Date(r.reading_timestamp).getTime(),
      value: r.value,
      timestamp: r.reading_timestamp,
    }))
    .sort((a, b) => a.time - b.time);
}

function getPointColor(value: number, low: number, high: number): string {
  if (value < 54) return "#ef4444";
  if (value < low) return "#f59e0b";
  if (value > 300) return "#ef4444";
  if (value > high) return "#f97316";
  return "#22c55e";
}

function GlucoseChartTooltip({ active, payload }: { active?: boolean; payload?: Array<{ payload: ChartPoint }> }) {
  if (!active || !payload?.[0]) return null;
  const point = payload[0].payload;
  const time = new Date(point.timestamp).toLocaleTimeString([], {
    hour: "numeric",
    minute: "2-digit",
  });
  return (
    <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg px-3 py-2 shadow-lg">
      <p className="text-xs text-slate-500 dark:text-slate-400">{time}</p>
      <p className="text-sm font-semibold text-slate-900 dark:text-white">
        {point.value} mg/dL
      </p>
    </div>
  );
}

function makeScatterRenderer(low: number, high: number) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return function renderScatterPoint(props: any) {
    const { cx, cy, payload } = props;
    if (cx == null || cy == null) return null;
    const value = (payload as ChartPoint | undefined)?.value ?? 100;
    return (
      <circle
        cx={cx}
        cy={cy}
        r={3}
        fill={getPointColor(value, low, high)}
        opacity={0.85}
      />
    );
  };
}

function DailyGlucoseChart({
  readings,
  date,
  low = 70,
  high = 180,
}: {
  readings: GlucoseHistoryReading[];
  date: string;
  low?: number;
  high?: number;
}) {
  const points = useMemo(() => transformReadings(readings), [readings]);
  const renderPoint = useMemo(() => makeScatterRenderer(low, high), [low, high]);

  // Day boundaries for x-axis
  const dayStart = new Date(`${date}T00:00:00`).getTime();
  const dayEnd = new Date(`${date}T00:00:00`).getTime() + 24 * 60 * 60 * 1000;

  const ticks = useMemo(() => {
    const result: number[] = [];
    for (let h = 0; h <= 24; h += 3) {
      const d = new Date(`${date}T00:00:00`);
      d.setHours(h);
      result.push(d.getTime());
    }
    return result;
  }, [date]);

  if (points.length === 0) {
    return (
      <div className="flex items-center justify-center h-64 text-slate-500 dark:text-slate-400 text-sm">
        No glucose data for this date.
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={300}>
      <ScatterChart margin={{ top: 10, right: 20, bottom: 20, left: 10 }}>
        <CartesianGrid
          strokeDasharray="3 3"
          stroke="var(--chart-grid, #e2e8f0)"
          opacity={0.5}
        />
        <XAxis
          type="number"
          dataKey="time"
          domain={[dayStart, dayEnd]}
          ticks={ticks}
          tickFormatter={(ts: number) => {
            const d = new Date(ts);
            const h = d.getHours();
            if (h === 0) return "12 AM";
            if (h === 12) return "12 PM";
            return h > 12 ? `${h - 12} PM` : `${h} AM`;
          }}
          tick={{ fontSize: 11, fill: "var(--chart-text, #94a3b8)" }}
        />
        <YAxis
          type="number"
          dataKey="value"
          domain={[40, 350]}
          ticks={[low, high, 250, 300]}
          tick={{ fontSize: 11, fill: "var(--chart-text, #94a3b8)" }}
          width={40}
        />
        <ReferenceArea
          y1={low}
          y2={high}
          fill="#22c55e"
          fillOpacity={0.08}
        />
        <ReferenceLine
          y={low}
          stroke="#f59e0b"
          strokeDasharray="4 4"
          strokeOpacity={0.6}
        />
        <ReferenceLine
          y={high}
          stroke="#f97316"
          strokeDasharray="4 4"
          strokeOpacity={0.6}
        />
        <RechartsTooltip
          content={<GlucoseChartTooltip />}
          cursor={false}
        />
        <Scatter
          data={points}
          shape={renderPoint}
        />
      </ScatterChart>
    </ResponsiveContainer>
  );
}

// ---------------------------------------------------------------------------
// CGM Stats Section
// ---------------------------------------------------------------------------

function CgmStatsSection({ stats }: { stats: GlucoseStats | null }) {
  if (!stats || stats.readings_count === 0) {
    return (
      <p className="text-sm text-slate-500 dark:text-slate-400">
        No CGM data available for this date.
      </p>
    );
  }

  const items = [
    { label: "Avg Glucose", value: `${Math.round(stats.mean_glucose)}`, unit: "mg/dL" },
    { label: "Std Dev", value: `${Math.round(stats.std_dev)}`, unit: "mg/dL" },
    { label: "CV%", value: `${stats.cv_pct}%`, unit: stats.cv_pct < 36 ? "Stable" : "Variable" },
    { label: "GMI (est. A1C)", value: `${stats.gmi}%`, unit: "" },
    { label: "CGM Active", value: `${stats.cgm_active_pct}%`, unit: "" },
    { label: "Readings", value: `${stats.readings_count}`, unit: "" },
  ];

  return (
    <div className="grid grid-cols-3 sm:grid-cols-6 gap-4">
      {items.map((item) => (
        <div key={item.label} className="text-center">
          <p className="text-xs text-slate-500 dark:text-slate-400 mb-1">
            {item.label}
          </p>
          <p className="text-lg font-bold text-slate-900 dark:text-white">
            {item.value}
          </p>
          {item.unit && (
            <p className="text-xs text-slate-400 dark:text-slate-500">
              {item.unit}
            </p>
          )}
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// TIR Bar Section
// ---------------------------------------------------------------------------

const TIR_COLORS: Record<string, string> = {
  urgent_low: "#dc2626",
  low: "#f59e0b",
  in_range: "#22c55e",
  high: "#f97316",
  urgent_high: "#ef4444",
};

function tirLabel(
  bucket: string,
  thresholds: { urgent_low: number; low: number; high: number; urgent_high: number },
): string {
  switch (bucket) {
    case "urgent_low": return `Urgent Low (<${thresholds.urgent_low})`;
    case "low": return `Low (${thresholds.urgent_low}-${thresholds.low})`;
    case "in_range": return `In Range (${thresholds.low}-${thresholds.high})`;
    case "high": return `High (${thresholds.high}-${thresholds.urgent_high})`;
    case "urgent_high": return `Very High (>${thresholds.urgent_high})`;
    default: return bucket;
  }
}

function TirSection({ tir }: { tir: TimeInRangeDetailStats | null }) {
  if (!tir || tir.readings_count === 0) {
    return (
      <p className="text-sm text-slate-500 dark:text-slate-400">
        No TIR data available for this date.
      </p>
    );
  }

  const t = tir.thresholds;
  const orderedLabels = ["urgent_low", "low", "in_range", "high", "urgent_high"];
  const orderedBuckets = orderedLabels
    .map((label) => tir.buckets.find((b) => b.label === label))
    .filter((b): b is TirBucket => !!b);

  return (
    <div className="space-y-3">
      {/* Stacked horizontal bar */}
      <div className="flex h-6 rounded-full overflow-hidden" role="img" aria-label="Time in range bar chart">
        {orderedBuckets.map((bucket) =>
          bucket.pct > 0 ? (
            <div
              key={bucket.label}
              role="img"
              aria-label={`${tirLabel(bucket.label, t)}: ${bucket.pct}%`}
              style={{
                width: `${bucket.pct}%`,
                backgroundColor: TIR_COLORS[bucket.label],
              }}
              title={`${tirLabel(bucket.label, t)}: ${bucket.pct}%`}
            />
          ) : null
        )}
      </div>
      {/* Legend */}
      <div className="flex flex-wrap gap-x-4 gap-y-1">
        {orderedBuckets.map((bucket) => (
          <div key={bucket.label} className="flex items-center gap-1.5 text-xs">
            <span
              className="inline-block w-2.5 h-2.5 rounded-sm"
              style={{ backgroundColor: TIR_COLORS[bucket.label] }}
            />
            <span className="text-slate-600 dark:text-slate-300">
              {tirLabel(bucket.label, t)}:
            </span>
            <span className="font-medium text-slate-900 dark:text-white">
              {bucket.pct}%
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Insulin Summary Section
// ---------------------------------------------------------------------------

function InsulinSection({
  insulin,
}: {
  insulin: InsulinSummaryResponse | null;
}) {
  if (!insulin || (insulin.tdd === 0 && insulin.bolus_count === 0)) {
    return (
      <p className="text-sm text-slate-500 dark:text-slate-400">
        No insulin data available for this date.
      </p>
    );
  }

  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
      <div>
        <p className="text-xs text-slate-500 dark:text-slate-400 mb-1">TDD</p>
        <p className="text-lg font-bold text-slate-900 dark:text-white">
          {insulin.tdd.toFixed(1)} <span className="text-sm font-normal">U</span>
        </p>
      </div>
      <div>
        <p className="text-xs text-slate-500 dark:text-slate-400 mb-1">
          Basal
        </p>
        <p className="text-lg font-bold text-slate-900 dark:text-white">
          {insulin.basal_units.toFixed(1)} U
          <span className="text-sm font-normal text-slate-400 ml-1">
            ({insulin.basal_pct}%)
          </span>
        </p>
      </div>
      <div>
        <p className="text-xs text-slate-500 dark:text-slate-400 mb-1">
          Bolus
        </p>
        <p className="text-lg font-bold text-slate-900 dark:text-white">
          {insulin.bolus_units.toFixed(1)} U
          <span className="text-sm font-normal text-slate-400 ml-1">
            ({insulin.bolus_pct}%)
          </span>
        </p>
      </div>
      <div>
        <p className="text-xs text-slate-500 dark:text-slate-400 mb-1">
          Boluses
        </p>
        <p className="text-lg font-bold text-slate-900 dark:text-white">
          {insulin.bolus_count}
          {insulin.correction_count > 0 && (
            <span className="text-sm font-normal text-slate-400 ml-1">
              ({insulin.correction_count} corr)
            </span>
          )}
        </p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Bolus Table Section
// ---------------------------------------------------------------------------

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString([], {
      hour: "numeric",
      minute: "2-digit",
    });
  } catch {
    return "---";
  }
}

function BolusSection({ boluses }: { boluses: BolusReviewItem[] }) {
  if (boluses.length === 0) {
    return (
      <p className="text-sm text-slate-500 dark:text-slate-400">
        No bolus events for this date.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left">
        <thead>
          <tr className="border-b border-slate-300 dark:border-slate-700">
            <th className="px-3 py-2 text-xs font-medium text-slate-500 dark:text-slate-400">
              Time
            </th>
            <th className="px-3 py-2 text-xs font-medium text-slate-500 dark:text-slate-400">
              Units
            </th>
            <th className="px-3 py-2 text-xs font-medium text-slate-500 dark:text-slate-400">
              Type
            </th>
            <th className="px-3 py-2 text-xs font-medium text-slate-500 dark:text-slate-400">
              BG
            </th>
            <th className="px-3 py-2 text-xs font-medium text-slate-500 dark:text-slate-400">
              IoB
            </th>
          </tr>
        </thead>
        <tbody>
          {boluses.map((b, i) => (
            <tr
              key={`${b.event_timestamp}-${i}`}
              className="border-b border-slate-200/50 dark:border-slate-800/50"
            >
              <td className="px-3 py-2 text-sm text-slate-600 dark:text-slate-300">
                {formatTime(b.event_timestamp)}
              </td>
              <td className="px-3 py-2 text-sm font-medium text-slate-900 dark:text-white">
                {b.units.toFixed(2)} U
              </td>
              <td className="px-3 py-2">
                {b.is_automated ? (
                  <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-violet-500/20 text-violet-700 dark:text-violet-300">
                    Auto
                  </span>
                ) : (
                  <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-slate-200/50 dark:bg-slate-700/50 text-slate-600 dark:text-slate-400">
                    Manual
                  </span>
                )}
              </td>
              <td className="px-3 py-2 text-sm text-slate-600 dark:text-slate-300">
                {b.bg_at_event != null ? `${Math.round(b.bg_at_event)}` : "---"}
              </td>
              <td className="px-3 py-2 text-sm text-slate-600 dark:text-slate-300">
                {b.iob_at_event != null
                  ? `${b.iob_at_event.toFixed(1)} U`
                  : "---"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section wrapper
// ---------------------------------------------------------------------------

function ReportSection({
  icon: Icon,
  title,
  children,
  delay = 0,
}: {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  children: React.ReactNode;
  delay?: number;
}) {
  return (
    <AnimatedCard delay={delay}>
      <section className="bg-white dark:bg-slate-900 rounded-xl p-6 border border-slate-200 dark:border-slate-800 print:border print:shadow-none">
        <div className="flex items-center gap-3 mb-4">
          <div className="p-2 bg-blue-500/10 rounded-lg print:hidden">
            <Icon className="h-5 w-5 text-blue-500" aria-hidden="true" />
          </div>
          <h2 className="text-slate-900 dark:text-white font-semibold">
            {title}
          </h2>
        </div>
        {children}
      </section>
    </AnimatedCard>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function ReportsPage() {
  const [selectedDate, setSelectedDate] = useState(todayDateString);
  const { data, isLoading, error, refetch } = useDailyReport(selectedDate);

  const goBack = useCallback(
    () => setSelectedDate((d) => shiftDate(d, -1)),
    []
  );
  const goForward = useCallback(
    () =>
      setSelectedDate((d) => {
        const next = shiftDate(d, 1);
        return next <= todayDateString() ? next : d;
      }),
    []
  );
  const goToday = useCallback(() => setSelectedDate(todayDateString()), []);

  const canGoForward = !isToday(selectedDate);

  return (
    <PageTransition>
      <div className="space-y-6 print:space-y-4">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-slate-900 dark:text-white">
              Daily Report
            </h1>
            <p className="text-slate-500 dark:text-slate-400 text-sm">
              {formatDisplayDate(selectedDate)}
            </p>
          </div>
          <div className="flex items-center gap-2 print:hidden">
            <button
              type="button"
              onClick={goBack}
              className="p-2 rounded-lg border border-slate-200 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-600 dark:text-slate-300 transition-colors"
              aria-label="Previous day"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            <div className="relative">
              <Calendar className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400 pointer-events-none" />
              <input
                type="date"
                value={selectedDate}
                max={todayDateString()}
                onChange={(e) => {
                  if (e.target.value) setSelectedDate(e.target.value);
                }}
                aria-label="Select report date"
                className="pl-10 pr-3 py-2 text-sm rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none"
              />
            </div>
            <button
              type="button"
              onClick={goForward}
              disabled={!canGoForward}
              className="p-2 rounded-lg border border-slate-200 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-600 dark:text-slate-300 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
              aria-label="Next day"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
            {!isToday(selectedDate) && (
              <button
                type="button"
                onClick={goToday}
                className="px-3 py-2 text-xs font-medium rounded-lg border border-slate-200 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-600 dark:text-slate-300 transition-colors"
              >
                Today
              </button>
            )}
            <button
              type="button"
              onClick={() => window.print()}
              className="p-2 rounded-lg border border-slate-200 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-600 dark:text-slate-300 transition-colors"
              aria-label="Print report"
            >
              <Printer className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* Print-only header */}
        <div className="hidden print:block text-center mb-4">
          <h1 className="text-xl font-bold">
            GlycemicGPT Daily Report
          </h1>
          <p className="text-sm text-slate-500">
            {formatDisplayDate(selectedDate)}
          </p>
          <p className="text-xs text-slate-400 mt-1">
            Generated {new Date().toLocaleString()}
          </p>
        </div>

        {/* Loading state */}
        {isLoading && (
          <div className="flex items-center justify-center py-20" role="status" aria-live="polite">
            <Loader2 className="h-6 w-6 animate-spin text-blue-500" />
            <span className="ml-3 text-slate-500 dark:text-slate-400">
              Loading report...
            </span>
          </div>
        )}

        {/* Error state */}
        {error && !isLoading && (
          <div className="bg-white dark:bg-slate-900 rounded-xl p-8 border border-slate-200 dark:border-slate-800 text-center">
            <AlertCircle className="h-8 w-8 text-red-400 mx-auto mb-3" />
            <p className="text-slate-900 dark:text-white font-medium mb-2">
              Failed to load report
            </p>
            <p className="text-slate-500 dark:text-slate-400 text-sm mb-4 max-w-md mx-auto truncate">
              {error}
            </p>
            <button
              type="button"
              onClick={refetch}
              className="text-blue-500 hover:text-blue-400 text-sm font-medium"
            >
              Retry
            </button>
          </div>
        )}

        {/* Report content */}
        {data && !isLoading && (
          <>
            <ReportSection icon={Activity} title="Glucose Trend" delay={0}>
              <DailyGlucoseChart
                readings={data.glucoseReadings}
                date={selectedDate}
                low={data.tirStats?.thresholds.low}
                high={data.tirStats?.thresholds.high}
              />
            </ReportSection>

            <ReportSection icon={BarChart3} title="CGM Summary" delay={0.05}>
              <CgmStatsSection stats={data.cgmStats} />
            </ReportSection>

            <ReportSection
              icon={BarChart3}
              title="Time in Range"
              delay={0.1}
            >
              <TirSection tir={data.tirStats} />
            </ReportSection>

            <ReportSection
              icon={Syringe}
              title="Insulin Delivery"
              delay={0.15}
            >
              <InsulinSection insulin={data.insulinSummary} />
            </ReportSection>

            <ReportSection
              icon={ListOrdered}
              title="Bolus Events"
              delay={0.2}
            >
              <BolusSection
                boluses={data.bolusReview?.boluses ?? []}
              />
            </ReportSection>
          </>
        )}
      </div>
    </PageTransition>
  );
}
