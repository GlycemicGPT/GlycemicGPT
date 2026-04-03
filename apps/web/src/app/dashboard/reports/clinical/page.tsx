"use client";

/**
 * Clinical Report Page
 *
 * Dedicated full-page report similar to Tandem t:connect or Dexcom Clarity.
 * Date range controls are at the top (hidden on print). The report body
 * renders below -- on screen it lives inside the dashboard layout (sidebar
 * visible) but the existing globals.css print rules hide sidebar/header
 * automatically, producing a clean printable document.
 *
 * Sections:
 * 1. Patient & Device Info (user profile, pump/CGM)
 * 2. Platform Settings (glucose ranges, label mappings)
 * 3. CGM Summary with estimated A1C
 * 4. Time in Range (5-bucket + targets)
 * 5. Ambulatory Glucose Profile (AGP) - percentile bands
 * 6. Glucose Trend (scatter chart)
 * 7. Daily Glucose Overlay (spaghetti plot)
 * 8. Hypoglycemia Analysis
 * 9. Overnight Pattern (10pm-6am)
 * 10. Insulin Delivery
 * 11. Active Pump Settings (basal, carb ratio, CF, targets)
 * 12. Bolus Events table
 * 13. Sensor Coverage & Gaps
 * 14. Medical disclaimer footer
 */

import { useState, useEffect, useMemo, useCallback, useRef } from "react";
import {
  Loader2,
  AlertCircle,
  Printer,
  FileText,
  Calendar,
  ArrowLeft,
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
  AreaChart,
  Area,
  LineChart,
  Line,
} from "recharts";
import Link from "next/link";
import {
  getGlucoseHistoryByDateRange,
  getGlucoseStatsByDateRange,
  getTimeInRangeDetailByDateRange,
  getInsulinSummaryByDateRange,
  getBolusReviewByDateRange,
  getCurrentUser,
  getPluginDeclarations,
  getPumpProfile,
  getTargetGlucoseRange,
  getAnalyticsConfig,
  type GlucoseHistoryReading,
  type GlucoseStats,
  type TimeInRangeDetailStats,
  type TirBucket,
  type InsulinSummaryResponse,
  type BolusReviewItem,
  type CurrentUserResponse,
  type PluginDeclarationResponse,
  type PumpProfileSummaryResponse,
  type PumpProfileSegment,
  type TargetGlucoseRangeResponse,
  type AnalyticsConfigResponse,
  type DisplayLabel,
} from "@/lib/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ReportData {
  readings: GlucoseHistoryReading[];
  cgmStats: GlucoseStats | null;
  tirStats: TimeInRangeDetailStats | null;
  insulin: InsulinSummaryResponse | null;
  boluses: BolusReviewItem[];
  totalBolusCount: number;
  user: CurrentUserResponse | null;
  plugin: PluginDeclarationResponse | null;
  pumpProfile: PumpProfileSummaryResponse | null;
  glucoseRange: TargetGlucoseRangeResponse | null;
  analyticsConfig: AnalyticsConfigResponse | null;
  warnings: string[];
}

interface AgpBucket {
  hour: number;
  p10: number;
  p25: number;
  p50: number;
  p75: number;
  p90: number;
  count: number;
}

interface HypoEvent {
  start: Date;
  end: Date;
  durationMinutes: number;
  nadir: number;
  isUrgent: boolean;
}

interface SensorGap {
  start: Date;
  end: Date;
  durationMinutes: number;
}

// ---------------------------------------------------------------------------
// Date helpers
// ---------------------------------------------------------------------------

function todayDateString(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function daysAgoDateString(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function formatDisplayDate(date: string): string {
  const d = new Date(`${date}T12:00:00`);
  return d.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function daysBetween(start: string, end: string): number {
  const s = new Date(`${start}T00:00:00`);
  const e = new Date(`${end}T00:00:00`);
  return Math.round((e.getTime() - s.getTime()) / 86400000);
}

function formatHour(hour: number): string {
  if (hour === 0) return "12 AM";
  if (hour === 12) return "12 PM";
  return hour < 12 ? `${hour} AM` : `${hour - 12} PM`;
}

// ---------------------------------------------------------------------------
// Data fetching
// ---------------------------------------------------------------------------

const SECTION_NAMES = [
  "Glucose History",
  "CGM Stats",
  "Time in Range",
  "Insulin Summary",
  "Bolus Events",
  "User Profile",
  "Device Info",
  "Pump Settings",
  "Glucose Range",
  "Analytics Config",
] as const;

async function fetchReportData(
  startDate: string,
  endDate: string,
): Promise<ReportData> {
  // Use local midnight so the date range matches the user's selected dates
  // regardless of timezone (input type="date" returns local date strings)
  const startLocal = new Date(`${startDate}T00:00:00`);
  const startISO = startLocal.toISOString();
  const endLocal = new Date(`${endDate}T00:00:00`);
  endLocal.setDate(endLocal.getDate() + 1);
  const endISO = endLocal.toISOString();

  // 288 readings/day (5-min intervals) + headroom for overlap
  const periodDays = Math.max(
    1,
    Math.round((endLocal.getTime() - startLocal.getTime()) / 86400000),
  );
  const readingsLimit = periodDays * 300;

  const results = await Promise.allSettled([
    getGlucoseHistoryByDateRange(startISO, endISO, readingsLimit),
    getGlucoseStatsByDateRange(startISO, endISO),
    getTimeInRangeDetailByDateRange(startISO, endISO),
    getInsulinSummaryByDateRange(startISO, endISO),
    getBolusReviewByDateRange(startISO, endISO, 50),
    getCurrentUser(),
    getPluginDeclarations(),
    getPumpProfile(),
    getTargetGlucoseRange(),
    getAnalyticsConfig(),
  ]);

  const warnings: string[] = [];
  // Only warn on core data sections (indices 0-4). Indices 5+ are
  // profile/device/settings fetches that fail gracefully with defaults.
  for (let i = 0; i < 5; i++) {
    if (results[i].status === "rejected") {
      warnings.push(`${SECTION_NAMES[i]} data could not be loaded`);
    }
  }

  const bolusResult =
    results[4].status === "fulfilled" ? results[4].value : null;

  return {
    readings:
      results[0].status === "fulfilled" ? results[0].value.readings : [],
    cgmStats: results[1].status === "fulfilled" ? results[1].value : null,
    tirStats: results[2].status === "fulfilled" ? results[2].value : null,
    insulin: results[3].status === "fulfilled" ? results[3].value : null,
    boluses: bolusResult?.boluses ?? [],
    totalBolusCount: bolusResult?.total_count ?? 0,
    user: results[5].status === "fulfilled" ? results[5].value : null,
    plugin: results[6].status === "fulfilled" ? results[6].value : null,
    pumpProfile: results[7].status === "fulfilled" ? results[7].value : null,
    glucoseRange: results[8].status === "fulfilled" ? results[8].value : null,
    analyticsConfig: results[9].status === "fulfilled" ? results[9].value : null,
    warnings,
  };
}

// ---------------------------------------------------------------------------
// Computation helpers
// ---------------------------------------------------------------------------

function computeAgpBuckets(readings: GlucoseHistoryReading[]): AgpBucket[] {
  // getHours() returns browser-local time, which is intentional: patients
  // view reports in their own timezone, matching how they experience their day.
  const hourBuckets: number[][] = Array.from({ length: 24 }, () => []);
  for (const r of readings) {
    const d = new Date(r.reading_timestamp);
    hourBuckets[d.getHours()].push(r.value);
  }
  return hourBuckets.map((values, hour) => {
    if (values.length === 0) {
      return { hour, p10: 0, p25: 0, p50: 0, p75: 0, p90: 0, count: 0 };
    }
    const sorted = [...values].sort((a, b) => a - b);
    const pct = (p: number) => {
      const idx = (sorted.length - 1) * p;
      const lo = Math.floor(idx);
      const hi = Math.ceil(idx);
      if (lo === hi) return sorted[lo];
      const frac = idx - lo;
      return sorted[lo] * (1 - frac) + sorted[hi] * frac;
    };
    return {
      hour,
      p10: pct(0.1),
      p25: pct(0.25),
      p50: pct(0.5),
      p75: pct(0.75),
      p90: pct(0.9),
      count: values.length,
    };
  });
}

function detectHypoEvents(
  readings: GlucoseHistoryReading[],
  lowThreshold: number,
  urgentLowThreshold: number,
): HypoEvent[] {
  const sorted = [...readings].sort(
    (a, b) =>
      new Date(a.reading_timestamp).getTime() -
      new Date(b.reading_timestamp).getTime(),
  );

  const events: HypoEvent[] = [];
  let inEvent = false;
  let eventStart: Date | null = null;
  let nadir = Infinity;
  let isUrgent = false;

  for (let i = 0; i < sorted.length; i++) {
    const r = sorted[i];
    const ts = new Date(r.reading_timestamp);

    if (r.value < lowThreshold) {
      if (!inEvent) {
        inEvent = true;
        eventStart = ts;
        nadir = r.value;
        isUrgent = r.value < urgentLowThreshold;
      } else {
        if (r.value < nadir) nadir = r.value;
        if (r.value < urgentLowThreshold) isUrgent = true;
      }
    } else if (inEvent && eventStart) {
      const duration = (ts.getTime() - eventStart.getTime()) / 60000;
      if (duration >= 5) {
        events.push({
          start: eventStart,
          end: ts,
          durationMinutes: Math.round(duration),
          nadir,
          isUrgent,
        });
      }
      inEvent = false;
      eventStart = null;
      nadir = Infinity;
      isUrgent = false;
    }
  }
  // Close open event
  if (inEvent && eventStart && sorted.length > 0) {
    const lastTs = new Date(sorted[sorted.length - 1].reading_timestamp);
    const duration = (lastTs.getTime() - eventStart.getTime()) / 60000;
    if (duration >= 5) {
      events.push({
        start: eventStart,
        end: lastTs,
        durationMinutes: Math.round(duration),
        nadir,
        isUrgent,
      });
    }
  }

  return events;
}

function computeOvernightStats(
  readings: GlucoseHistoryReading[],
  lowThreshold: number,
  highThreshold: number,
): { avg: number; count: number; lowPct: number; highPct: number; inRangePct: number } | null {
  const overnight = readings.filter((r) => {
    const h = new Date(r.reading_timestamp).getHours();
    return h >= 22 || h < 6;
  });
  if (overnight.length === 0) return null;
  const sum = overnight.reduce((s, r) => s + r.value, 0);
  const lowCount = overnight.filter((r) => r.value < lowThreshold).length;
  const highCount = overnight.filter((r) => r.value > highThreshold).length;
  const inRange = overnight.length - lowCount - highCount;
  return {
    avg: Math.round(sum / overnight.length),
    count: overnight.length,
    lowPct: Math.round((lowCount / overnight.length) * 100),
    highPct: Math.round((highCount / overnight.length) * 100),
    inRangePct: Math.round((inRange / overnight.length) * 100),
  };
}

function detectSensorGaps(readings: GlucoseHistoryReading[]): SensorGap[] {
  if (readings.length < 2) return [];
  const sorted = [...readings].sort(
    (a, b) =>
      new Date(a.reading_timestamp).getTime() -
      new Date(b.reading_timestamp).getTime(),
  );
  const gaps: SensorGap[] = [];
  const GAP_THRESHOLD_MIN = 20; // >20 min gap = sensor gap

  for (let i = 1; i < sorted.length; i++) {
    const prev = new Date(sorted[i - 1].reading_timestamp);
    const curr = new Date(sorted[i].reading_timestamp);
    const diffMin = (curr.getTime() - prev.getTime()) / 60000;
    if (diffMin > GAP_THRESHOLD_MIN) {
      gaps.push({
        start: prev,
        end: curr,
        durationMinutes: Math.round(diffMin),
      });
    }
  }
  return gaps;
}

function buildDailyOverlay(
  readings: GlucoseHistoryReading[],
): { minuteOfDay: number; value: number; day: string }[] {
  return readings.map((r) => {
    const d = new Date(r.reading_timestamp);
    return {
      minuteOfDay: d.getHours() * 60 + d.getMinutes(),
      value: r.value,
      day: d.toLocaleDateString([], { month: "short", day: "numeric" }),
    };
  });
}

// ---------------------------------------------------------------------------
// Chart components
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

function getPointColor(value: number, low: number, high: number, urgentLow = 54, urgentHigh = 250): string {
  if (value < urgentLow) return "#dc2626";
  if (value < low) return "#f59e0b";
  if (value > urgentHigh) return "#dc2626";
  if (value > high) return "#f97316";
  return "#22c55e";
}

function GlucoseChartTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ payload: ChartPoint }>;
}) {
  if (!active || !payload?.[0]) return null;
  const point = payload[0].payload;
  const time = new Date(point.timestamp).toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
  return (
    <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg px-3 py-2 shadow-lg print:hidden">
      <p className="text-xs text-slate-500 dark:text-slate-400">{time}</p>
      <p className="text-sm font-semibold text-slate-900 dark:text-white">
        {point.value} mg/dL
      </p>
    </div>
  );
}

function makeScatterRenderer(low: number, high: number, urgentLow = 54, urgentHigh = 250) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return function renderScatterPoint(props: any) {
    const { cx, cy, payload } = props;
    if (cx == null || cy == null) return null;
    const value = (payload as ChartPoint | undefined)?.value ?? 100;
    return (
      <circle
        cx={cx}
        cy={cy}
        r={2}
        fill={getPointColor(value, low, high, urgentLow, urgentHigh)}
        opacity={0.7}
      />
    );
  };
}

function ReportGlucoseChart({
  readings,
  startDate,
  endDate,
  low,
  high,
  urgentLow = 54,
  urgentHigh = 250,
}: {
  readings: GlucoseHistoryReading[];
  startDate: string;
  endDate: string;
  low: number;
  high: number;
  urgentLow?: number;
  urgentHigh?: number;
}) {
  const points = useMemo(() => transformReadings(readings), [readings]);
  const renderPoint = useMemo(
    () => makeScatterRenderer(low, high, urgentLow, urgentHigh),
    [low, high, urgentLow, urgentHigh],
  );

  const domainStart = new Date(`${startDate}T00:00:00`).getTime();
  const domainEnd =
    new Date(`${endDate}T00:00:00`).getTime() + 24 * 60 * 60 * 1000;
  const days = daysBetween(startDate, endDate);

  const ticks = useMemo(() => {
    const result: number[] = [];
    const step = days <= 7 ? 1 : days <= 14 ? 2 : days <= 21 ? 3 : 5;
    const d = new Date(`${startDate}T00:00:00`);
    while (d.getTime() <= domainEnd) {
      result.push(d.getTime());
      d.setDate(d.getDate() + step);
    }
    return result;
  }, [startDate, domainEnd, days]);

  const chartSummary = useMemo(() => {
    if (points.length === 0) return "";
    const avg = Math.round(
      points.reduce((s, p) => s + p.value, 0) / points.length,
    );
    const startLabel = new Date(domainStart).toLocaleDateString([], {
      month: "short",
      day: "numeric",
    });
    const endLabel = new Date(domainEnd).toLocaleDateString([], {
      month: "short",
      day: "numeric",
    });
    return `Glucose trend chart showing ${points.length} readings from ${startLabel} to ${endLabel}, average ${avg} mg/dL`;
  }, [points, domainStart, domainEnd]);

  if (points.length === 0) {
    return (
      <div className="flex items-center justify-center h-48 text-slate-500 text-sm">
        No glucose data for this period.
      </div>
    );
  }

  return (
    <div role="img" aria-label={chartSummary}>
      <ResponsiveContainer width="100%" height={280}>
        <ScatterChart margin={{ top: 10, right: 20, bottom: 20, left: 10 }}>
          <CartesianGrid
            strokeDasharray="3 3"
            stroke="#e2e8f0"
            opacity={0.5}
          />
          <XAxis
            type="number"
            dataKey="time"
            domain={[domainStart, domainEnd]}
            ticks={ticks}
            tickFormatter={(ts: number) => {
              const d = new Date(ts);
              return d.toLocaleDateString([], {
                month: "short",
                day: "numeric",
              });
            }}
            tick={{ fontSize: 10, fill: "#94a3b8" }}
          />
          <YAxis
            type="number"
            dataKey="value"
            domain={[40, 350]}
            ticks={[urgentLow, low, high, urgentHigh]}
            tick={{ fontSize: 10, fill: "#94a3b8" }}
            width={35}
          />
          <ReferenceArea y1={low} y2={high} fill="#22c55e" fillOpacity={0.08} />
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
          <RechartsTooltip content={<GlucoseChartTooltip />} cursor={false} />
          <Scatter data={points} shape={renderPoint} />
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  );
}

function AgpChartSection({
  buckets,
  low,
  high,
  urgentLow = 54,
  urgentHigh = 250,
}: {
  buckets: AgpBucket[];
  low: number;
  high: number;
  urgentLow?: number;
  urgentHigh?: number;
}) {
  const data = useMemo(() => {
    const filtered = buckets.filter((b) => b.count > 0);
    if (filtered.length === 0) return [];
    return filtered.map((b) => ({
      hour: b.hour,
      base: Math.round(b.p10),
      band_p10_p25: Math.max(0, Math.round(b.p25 - b.p10)),
      band_p25_p50: Math.max(0, Math.round(b.p50 - b.p25)),
      band_p50_p75: Math.max(0, Math.round(b.p75 - b.p50)),
      band_p75_p90: Math.max(0, Math.round(b.p90 - b.p75)),
      p50: b.p50,
    }));
  }, [buckets]);

  if (data.length === 0) {
    return (
      <p className="text-sm text-slate-500">
        Not enough data for AGP analysis.
      </p>
    );
  }

  return (
    <div
      role="img"
      aria-label="Ambulatory Glucose Profile showing median and percentile bands over 24 hours"
    >
      <ResponsiveContainer width="100%" height={260}>
        <AreaChart data={data} margin={{ top: 10, right: 20, bottom: 20, left: 10 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" opacity={0.5} />
          <XAxis
            dataKey="hour"
            ticks={[0, 3, 6, 9, 12, 15, 18, 21]}
            tickFormatter={(h: number) => formatHour(h)}
            tick={{ fontSize: 10, fill: "#94a3b8" }}
          />
          <YAxis
            domain={[40, 350]}
            ticks={[urgentLow, low, high, urgentHigh]}
            tick={{ fontSize: 10, fill: "#94a3b8" }}
            width={35}
          />
          <ReferenceArea y1={low} y2={high} fill="#22c55e" fillOpacity={0.06} />
          <ReferenceLine
            y={low}
            stroke="#f59e0b"
            strokeDasharray="4 4"
            strokeOpacity={0.5}
          />
          <ReferenceLine
            y={high}
            stroke="#f97316"
            strokeDasharray="4 4"
            strokeOpacity={0.5}
          />
          {/* Stacked bands: transparent base at p10, then band deltas */}
          <Area type="monotone" dataKey="base" stackId="agp" stroke="none" fill="transparent" />
          <Area type="monotone" dataKey="band_p10_p25" stackId="agp" stroke="none" fill="rgba(59, 130, 246, 0.15)" />
          <Area type="monotone" dataKey="band_p25_p50" stackId="agp" stroke="none" fill="rgba(59, 130, 246, 0.30)" />
          <Area type="monotone" dataKey="band_p50_p75" stackId="agp" stroke="none" fill="rgba(59, 130, 246, 0.30)" />
          <Area type="monotone" dataKey="band_p75_p90" stackId="agp" stroke="none" fill="rgba(59, 130, 246, 0.15)" />
          {/* Median line (not stacked) */}
          <Area type="monotone" dataKey="p50" stroke="rgb(59, 130, 246)" strokeWidth={2} fill="none" />
        </AreaChart>
      </ResponsiveContainer>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500 mt-1">
        <span>
          <span className="inline-block w-3 h-0.5 bg-blue-500 mr-1 align-middle" />
          Median (p50)
        </span>
        <span>
          <span className="inline-block w-3 h-2 mr-1 align-middle rounded-sm" style={{ backgroundColor: "rgba(59, 130, 246, 0.30)" }} />
          25th-75th percentile
        </span>
        <span>
          <span className="inline-block w-3 h-2 mr-1 align-middle rounded-sm" style={{ backgroundColor: "rgba(59, 130, 246, 0.15)" }} />
          10th-90th percentile
        </span>
      </div>
    </div>
  );
}

function DailyOverlayChart({
  readings,
  low,
  high,
  urgentLow = 54,
  urgentHigh = 250,
}: {
  readings: GlucoseHistoryReading[];
  low: number;
  high: number;
  urgentLow?: number;
  urgentHigh?: number;
}) {
  const MAX_OVERLAY_DAYS = 14;
  const overlayData = useMemo(() => buildDailyOverlay(readings), [readings]);
  const days = useMemo(() => {
    const daySet = new Set(overlayData.map((p) => p.day));
    const all = Array.from(daySet);
    // Cap to most recent days for performance (each day = 1 SVG path)
    return all.length > MAX_OVERLAY_DAYS
      ? all.slice(all.length - MAX_OVERLAY_DAYS)
      : all;
  }, [overlayData]);

  // Group by day for line chart
  const chartData = useMemo(() => {
    // Accumulate values per (bucket, day) to average collisions
    const accum = new Map<string, { sum: number; count: number }>();
    const minuteSet = new Set<number>();
    for (const point of overlayData) {
      const bucket = Math.round(point.minuteOfDay / 5) * 5;
      minuteSet.add(bucket);
      const key = `${bucket}|${point.day}`;
      const prev = accum.get(key);
      if (prev) {
        prev.sum += point.value;
        prev.count++;
      } else {
        accum.set(key, { sum: point.value, count: 1 });
      }
    }
    const minuteMap = new Map<number, Record<string, number>>();
    for (const bucket of minuteSet) {
      minuteMap.set(bucket, { minuteOfDay: bucket });
    }
    for (const [key, { sum, count }] of accum) {
      const [bucketStr, ...dayParts] = key.split("|");
      const day = dayParts.join("|");
      const entry = minuteMap.get(Number(bucketStr))!;
      entry[day] = Math.round(sum / count);
    }
    return Array.from(minuteMap.values()).sort(
      (a, b) => a.minuteOfDay - b.minuteOfDay,
    );
  }, [overlayData]);

  if (days.length === 0) {
    return <p className="text-sm text-slate-500">No data for daily overlay.</p>;
  }

  const COLORS = [
    "#3b82f6", "#ef4444", "#22c55e", "#f59e0b", "#8b5cf6",
    "#ec4899", "#14b8a6", "#f97316", "#6366f1", "#06b6d4",
    "#84cc16", "#e11d48", "#0ea5e9", "#d946ef", "#10b981",
    "#fb923c", "#a855f7", "#f43f5e", "#2dd4bf", "#fbbf24",
    "#7c3aed", "#059669", "#dc2626", "#0284c7", "#c026d3",
    "#65a30d", "#e879f9", "#38bdf8", "#4ade80", "#facc15",
    "#818cf8",
  ];

  return (
    <div
      role="img"
      aria-label={`Daily glucose overlay showing ${days.length} days overlaid on a 24-hour clock`}
    >
      <ResponsiveContainer width="100%" height={260}>
        <LineChart data={chartData} margin={{ top: 10, right: 20, bottom: 20, left: 10 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" opacity={0.5} />
          <XAxis
            dataKey="minuteOfDay"
            type="number"
            domain={[0, 1440]}
            ticks={[0, 180, 360, 540, 720, 900, 1080, 1260]}
            tickFormatter={(m: number) => formatHour(Math.floor(m / 60))}
            tick={{ fontSize: 10, fill: "#94a3b8" }}
          />
          <YAxis
            domain={[40, 350]}
            ticks={[urgentLow, low, high, urgentHigh]}
            tick={{ fontSize: 10, fill: "#94a3b8" }}
            width={35}
          />
          <ReferenceArea y1={low} y2={high} fill="#22c55e" fillOpacity={0.06} />
          {days.map((day, i) => (
            <Line
              key={day}
              type="monotone"
              dataKey={day}
              stroke={COLORS[i % COLORS.length]}
              strokeWidth={1}
              dot={false}
              opacity={0.5}
              connectNulls={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
      <p className="text-xs text-slate-400 print:text-slate-500 mt-1">
        Each line represents one day. {days.length} day
        {days.length !== 1 ? "s" : ""} overlaid on a 24-hour clock.
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Report sections
// ---------------------------------------------------------------------------

const TIR_COLORS: Record<string, string> = {
  urgent_low: "#dc2626",
  low: "#f59e0b",
  in_range: "#22c55e",
  high: "#f97316",
  urgent_high: "#ef4444",
};

const TIR_LABELS: Record<string, string> = {
  urgent_low: "Very Low",
  low: "Low",
  in_range: "In Range",
  high: "High",
  urgent_high: "Very High",
};

const TIR_TARGETS: Record<string, string> = {
  urgent_low: "<1%",
  low: "<4%",
  in_range: ">70%",
  high: "<25%",
  urgent_high: "<5%",
};

function PatientDeviceHeader({
  user,
  plugin,
  cgmSource,
  dateRange,
  generatedAt,
}: {
  user: CurrentUserResponse | null;
  plugin: PluginDeclarationResponse | null;
  cgmSource: string | null;
  dateRange: string;
  generatedAt: string | null;
}) {
  const patientName = user?.display_name || user?.email || "Unknown Patient";
  const pumpInfo = plugin
    ? `${plugin.plugin_name} v${plugin.plugin_version}`
    : null;

  return (
    <div className="space-y-3">
      <div className="flex justify-between items-start">
        <div>
          <h2 className="text-xl font-bold text-slate-900 dark:text-white print:text-black print:text-2xl">
            GlycemicGPT Clinical Report
          </h2>
          <p className="text-sm text-slate-500 print:text-slate-600 mt-1">
            {dateRange}
          </p>
          {generatedAt && (
            <p className="text-xs text-slate-400 print:text-slate-500 mt-0.5">
              Generated {generatedAt}
            </p>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-2 border-t border-slate-200 dark:border-slate-700 print:border-slate-300">
        <div>
          <p className="text-xs text-slate-500 print:text-slate-600 uppercase tracking-wider mb-0.5">
            Patient
          </p>
          <p className="text-sm font-medium text-slate-900 dark:text-white print:text-black">
            {patientName}
          </p>
        </div>
        <div>
          <p className="text-xs text-slate-500 print:text-slate-600 uppercase tracking-wider mb-0.5">
            Devices
          </p>
          <p className="text-sm font-medium text-slate-900 dark:text-white print:text-black">
            {[pumpInfo, cgmSource].filter(Boolean).join(" + ") ||
              "No device info available"}
          </p>
        </div>
      </div>
    </div>
  );
}

function CgmStatsSection({ stats }: { stats: GlucoseStats }) {
  const eA1C = stats.gmi;

  return (
    <div className="space-y-4">
      {/* Prominent eA1C card */}
      <div className="flex items-center gap-6">
        <div className="text-center">
          <p className="text-xs text-slate-500 print:text-slate-600 uppercase tracking-wider">
            Estimated A1C (GMI)
          </p>
          <p className="text-4xl font-bold text-slate-900 dark:text-white print:text-black mt-1">
            {eA1C}%
          </p>
        </div>
        <div className="text-center">
          <p className="text-xs text-slate-500 print:text-slate-600 uppercase tracking-wider">
            Average Glucose
          </p>
          <p className="text-4xl font-bold text-slate-900 dark:text-white print:text-black mt-1">
            {Math.round(stats.mean_glucose)}
            <span className="text-lg font-normal ml-1">mg/dL</span>
          </p>
        </div>
        <div className="text-center">
          <p className="text-xs text-slate-500 print:text-slate-600 uppercase tracking-wider">
            Variability (CV)
          </p>
          <p className="text-4xl font-bold text-slate-900 dark:text-white print:text-black mt-1">
            {stats.cv_pct}%
            <span className="text-sm font-normal ml-1 text-slate-400">
              {stats.cv_pct < 36 ? "Stable" : "Variable"}
            </span>
          </p>
        </div>
      </div>

      {/* Detail table */}
      <table className="w-full text-sm">
        <tbody>
          {[
            {
              label: "Standard Deviation",
              value: `${Math.round(stats.std_dev)} mg/dL`,
            },
            {
              label: "CGM Active Time",
              value: `${stats.cgm_active_pct}%`,
            },
            {
              label: "Total Readings",
              value: stats.readings_count.toLocaleString(),
            },
          ].map((row) => (
            <tr
              key={row.label}
              className="border-b border-slate-200 dark:border-slate-700 print:border-slate-300"
            >
              <td className="py-2 text-slate-600 dark:text-slate-400 print:text-slate-600">
                {row.label}
              </td>
              <td className="py-2 text-right font-medium text-slate-900 dark:text-white print:text-black">
                {row.value}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TirSection({ tir }: { tir: TimeInRangeDetailStats }) {
  const t = tir.thresholds;
  const orderedLabels = [
    "urgent_low",
    "low",
    "in_range",
    "high",
    "urgent_high",
  ] as const;
  const orderedBuckets = orderedLabels
    .map((label) => tir.buckets.find((b) => b.label === label))
    .filter((b): b is TirBucket => !!b);

  function rangeLabel(bucket: string): string {
    switch (bucket) {
      case "urgent_low":
        return `<${t.urgent_low}`;
      case "low":
        return `${t.urgent_low}-${t.low}`;
      case "in_range":
        return `${t.low}-${t.high}`;
      case "high":
        return `${t.high}-${t.urgent_high}`;
      case "urgent_high":
        return `>${t.urgent_high}`;
      default:
        return "";
    }
  }

  return (
    <div className="space-y-4">
      <div
        className="flex h-8 rounded-full overflow-hidden"
        role="img"
        aria-label="Time in range distribution"
      >
        {orderedBuckets.map((bucket) =>
          bucket.pct > 0 ? (
            <div
              key={bucket.label}
              style={{
                width: `${bucket.pct}%`,
                backgroundColor: TIR_COLORS[bucket.label],
              }}
              title={`${TIR_LABELS[bucket.label]}: ${bucket.pct}%`}
            />
          ) : null,
        )}
      </div>

      <table className="w-full text-sm">
        <thead>
          <tr className="border-b-2 border-slate-300 dark:border-slate-600 print:border-slate-400">
            <th className="py-1.5 text-left text-xs font-semibold text-slate-500 print:text-slate-600 uppercase tracking-wider">
              Range
            </th>
            <th className="py-1.5 text-left text-xs font-semibold text-slate-500 print:text-slate-600 uppercase tracking-wider">
              mg/dL
            </th>
            <th className="py-1.5 text-right text-xs font-semibold text-slate-500 print:text-slate-600 uppercase tracking-wider">
              % Time
            </th>
            <th className="py-1.5 text-right text-xs font-semibold text-slate-500 print:text-slate-600 uppercase tracking-wider">
              Target
            </th>
          </tr>
        </thead>
        <tbody>
          {orderedBuckets.map((bucket) => {
            const isTarget =
              bucket.label === "in_range"
                ? bucket.pct >= 70
                : bucket.label === "urgent_low"
                  ? bucket.pct < 1
                  : bucket.label === "low"
                    ? bucket.pct < 4
                    : bucket.label === "high"
                      ? bucket.pct < 25
                      : bucket.pct < 5;
            return (
              <tr
                key={bucket.label}
                className="border-b border-slate-200 dark:border-slate-700 print:border-slate-300"
              >
                <td className="py-2 flex items-center gap-2">
                  <span
                    className="inline-block w-3 h-3 rounded-sm"
                    style={{ backgroundColor: TIR_COLORS[bucket.label] }}
                  />
                  <span className="text-slate-700 dark:text-slate-300 print:text-slate-700">
                    {TIR_LABELS[bucket.label]}
                  </span>
                </td>
                <td className="py-2 text-slate-500 print:text-slate-500">
                  {rangeLabel(bucket.label)}
                </td>
                <td className="py-2 text-right font-semibold text-slate-900 dark:text-white print:text-black">
                  {bucket.pct}%
                </td>
                <td className="py-2 text-right">
                  <span
                    className={
                      isTarget
                        ? "text-green-600 print:text-green-700"
                        : "text-red-500 print:text-red-600"
                    }
                  >
                    {TIR_TARGETS[bucket.label]}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="text-xs text-slate-400 print:text-slate-500">
        Based on {tir.readings_count.toLocaleString()} readings. Clinical
        targets per International Consensus (Battelino et al. 2019).
      </p>
    </div>
  );
}

function HypoSection({
  events,
  periodDays,
  low = 70,
  urgentLow = 54,
}: {
  events: HypoEvent[];
  periodDays: number;
  low?: number;
  urgentLow?: number;
}) {
  const urgentEvents = events.filter((e) => e.isUrgent);
  const totalDuration = events.reduce((s, e) => s + e.durationMinutes, 0);
  const avgDuration =
    events.length > 0 ? Math.round(totalDuration / events.length) : 0;
  const eventsPerWeek =
    periodDays > 0 ? ((events.length / periodDays) * 7).toFixed(1) : "0";
  const lowestNadir = events.length > 0 ? Math.min(...events.map((e) => e.nadir)) : null;

  // Time-of-day distribution
  const hourCounts = Array(24).fill(0);
  for (const e of events) {
    hourCounts[e.start.getHours()]++;
  }
  const peakHour =
    events.length > 0
      ? hourCounts.indexOf(Math.max(...hourCounts))
      : -1;

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <div>
          <p className="text-xs text-slate-500 print:text-slate-600 mb-1">
            Low Events (&lt;{low})
          </p>
          <p className="text-2xl font-bold text-slate-900 dark:text-white print:text-black">
            {events.length}
          </p>
          <p className="text-xs text-slate-400">{eventsPerWeek}/week</p>
        </div>
        <div>
          <p className="text-xs text-slate-500 print:text-slate-600 mb-1">
            Urgent Lows (&lt;{urgentLow})
          </p>
          <p className={`text-2xl font-bold ${urgentEvents.length > 0 ? "text-red-600" : "text-slate-900 dark:text-white print:text-black"}`}>
            {urgentEvents.length}
          </p>
        </div>
        <div>
          <p className="text-xs text-slate-500 print:text-slate-600 mb-1">
            Avg Duration
          </p>
          <p className="text-2xl font-bold text-slate-900 dark:text-white print:text-black">
            {avgDuration}<span className="text-sm font-normal ml-1">min</span>
          </p>
        </div>
        <div>
          <p className="text-xs text-slate-500 print:text-slate-600 mb-1">
            Lowest Reading
          </p>
          <p className="text-2xl font-bold text-slate-900 dark:text-white print:text-black">
            {lowestNadir ?? "---"}
            {lowestNadir != null && (
              <span className="text-sm font-normal ml-1">mg/dL</span>
            )}
          </p>
        </div>
      </div>
      {peakHour >= 0 && events.length > 0 && (
        <p className="text-xs text-slate-400 print:text-slate-500">
          Most frequent low time: {formatHour(peakHour)}.
          Total time below range: {totalDuration} minutes.
        </p>
      )}
      {events.length === 0 && (
        <p className="text-sm text-green-600 print:text-green-700">
          No hypoglycemic events detected in this period.
        </p>
      )}
    </div>
  );
}

function OvernightSection({
  stats,
}: {
  stats: { avg: number; count: number; lowPct: number; highPct: number; inRangePct: number };
}) {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
      <div>
        <p className="text-xs text-slate-500 print:text-slate-600 mb-1">
          Overnight Avg (10PM-6AM)
        </p>
        <p className="text-2xl font-bold text-slate-900 dark:text-white print:text-black">
          {stats.avg}
          <span className="text-sm font-normal ml-1">mg/dL</span>
        </p>
      </div>
      <div>
        <p className="text-xs text-slate-500 print:text-slate-600 mb-1">
          In Range
        </p>
        <p className="text-2xl font-bold text-green-600 print:text-green-700">
          {stats.inRangePct}%
        </p>
      </div>
      <div>
        <p className="text-xs text-slate-500 print:text-slate-600 mb-1">
          Below Range
        </p>
        <p className={`text-2xl font-bold ${stats.lowPct > 0 ? "text-amber-500" : "text-slate-900 dark:text-white print:text-black"}`}>
          {stats.lowPct}%
        </p>
      </div>
      <div>
        <p className="text-xs text-slate-500 print:text-slate-600 mb-1">
          Above Range
        </p>
        <p className={`text-2xl font-bold ${stats.highPct > 25 ? "text-orange-500" : "text-slate-900 dark:text-white print:text-black"}`}>
          {stats.highPct}%
        </p>
      </div>
      <p className="text-xs text-slate-400 print:text-slate-500 col-span-full">
        Based on {stats.count.toLocaleString()} overnight readings (10:00 PM -
        6:00 AM).
      </p>
    </div>
  );
}

function InsulinSection({ insulin }: { insulin: InsulinSummaryResponse }) {
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <div>
          <p className="text-xs text-slate-500 print:text-slate-600 mb-1">
            Total Daily Dose (avg)
          </p>
          <p className="text-xl font-bold text-slate-900 dark:text-white print:text-black">
            {insulin.tdd.toFixed(1)}{" "}
            <span className="text-sm font-normal">U</span>
          </p>
        </div>
        <div>
          <p className="text-xs text-slate-500 print:text-slate-600 mb-1">
            Basal (avg/day)
          </p>
          <p className="text-xl font-bold text-slate-900 dark:text-white print:text-black">
            {insulin.basal_units.toFixed(1)} U
            <span className="text-sm font-normal text-slate-400 ml-1">
              ({insulin.basal_pct}%)
            </span>
          </p>
        </div>
        <div>
          <p className="text-xs text-slate-500 print:text-slate-600 mb-1">
            Bolus (avg/day)
          </p>
          <p className="text-xl font-bold text-slate-900 dark:text-white print:text-black">
            {insulin.bolus_units.toFixed(1)} U
            <span className="text-sm font-normal text-slate-400 ml-1">
              ({insulin.bolus_pct}%)
            </span>
          </p>
        </div>
        <div>
          <p className="text-xs text-slate-500 print:text-slate-600 mb-1">
            Boluses (total)
          </p>
          <p className="text-xl font-bold text-slate-900 dark:text-white print:text-black">
            {insulin.bolus_count}
            {insulin.correction_count > 0 && (
              <span className="text-sm font-normal text-slate-400 ml-1">
                ({insulin.correction_count} correction)
              </span>
            )}
          </p>
        </div>
      </div>
      <div className="flex h-4 rounded-full overflow-hidden">
        <div
          style={{ width: `${insulin.basal_pct}%`, backgroundColor: "#6366f1" }}
          title={`Basal: ${insulin.basal_pct}%`}
        />
        <div
          style={{ width: `${insulin.bolus_pct}%`, backgroundColor: "#3b82f6" }}
          title={`Bolus: ${insulin.bolus_pct}%`}
        />
      </div>
      <div className="flex gap-4 text-xs">
        <div className="flex items-center gap-1.5">
          <span className="inline-block w-2.5 h-2.5 rounded-sm bg-indigo-500" />
          <span className="text-slate-600 dark:text-slate-300 print:text-slate-600">
            Basal {insulin.basal_pct}%
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="inline-block w-2.5 h-2.5 rounded-sm bg-blue-500" />
          <span className="text-slate-600 dark:text-slate-300 print:text-slate-600">
            Bolus {insulin.bolus_pct}%
          </span>
        </div>
      </div>
      <p className="text-xs text-slate-400 print:text-slate-500">
        Daily averages over {insulin.period_days} day
        {insulin.period_days !== 1 ? "s" : ""}.
      </p>
    </div>
  );
}

function PumpSettingsSection({
  profile,
}: {
  profile: PumpProfileSummaryResponse;
}) {
  const segments = profile.segments;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-4 text-sm">
        <div>
          <span className="text-slate-500 print:text-slate-600">Profile:</span>{" "}
          <span className="font-medium text-slate-900 dark:text-white print:text-black">
            {profile.profile_name}
          </span>
        </div>
        {profile.dia_minutes && (
          <div>
            <span className="text-slate-500 print:text-slate-600">
              Insulin Duration:
            </span>{" "}
            <span className="font-medium text-slate-900 dark:text-white print:text-black">
              {(profile.dia_minutes / 60).toFixed(1)} hrs
            </span>
          </div>
        )}
        {profile.max_bolus_units && (
          <div>
            <span className="text-slate-500 print:text-slate-600">
              Max Bolus:
            </span>{" "}
            <span className="font-medium text-slate-900 dark:text-white print:text-black">
              {profile.max_bolus_units} U
            </span>
          </div>
        )}
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b-2 border-slate-300 dark:border-slate-600 print:border-slate-400">
              <th className="py-1.5 px-2 text-left text-xs font-semibold text-slate-500 print:text-slate-600 uppercase tracking-wider">
                Time
              </th>
              <th className="py-1.5 px-2 text-right text-xs font-semibold text-slate-500 print:text-slate-600 uppercase tracking-wider">
                Basal (U/hr)
              </th>
              <th className="py-1.5 px-2 text-right text-xs font-semibold text-slate-500 print:text-slate-600 uppercase tracking-wider">
                Carb Ratio (g/U)
              </th>
              <th className="py-1.5 px-2 text-right text-xs font-semibold text-slate-500 print:text-slate-600 uppercase tracking-wider">
                Correction (mg/dL/U)
              </th>
              <th className="py-1.5 px-2 text-right text-xs font-semibold text-slate-500 print:text-slate-600 uppercase tracking-wider">
                Target BG
              </th>
            </tr>
          </thead>
          <tbody>
            {segments.map((seg: PumpProfileSegment, i: number) => (
              <tr
                key={`${seg.time}-${i}`}
                className="border-b border-slate-200 dark:border-slate-700 print:border-slate-300"
              >
                <td className="py-1.5 px-2 text-slate-600 dark:text-slate-300 print:text-slate-700 font-medium">
                  {seg.time}
                </td>
                <td className="py-1.5 px-2 text-right text-slate-900 dark:text-white print:text-black">
                  {seg.basal_rate.toFixed(2)}
                </td>
                <td className="py-1.5 px-2 text-right text-slate-900 dark:text-white print:text-black">
                  {seg.carb_ratio != null ? seg.carb_ratio.toFixed(1) : "---"}
                </td>
                <td className="py-1.5 px-2 text-right text-slate-900 dark:text-white print:text-black">
                  {seg.correction_factor != null
                    ? Math.round(seg.correction_factor)
                    : "---"}
                </td>
                <td className="py-1.5 px-2 text-right text-slate-900 dark:text-white print:text-black">
                  {seg.target_bg ?? "---"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-slate-400 print:text-slate-500">
        Last synced:{" "}
        {new Date(profile.synced_at).toLocaleString([], {
          month: "short",
          day: "numeric",
          year: "numeric",
          hour: "numeric",
          minute: "2-digit",
        })}
      </p>
    </div>
  );
}

function BolusTable({
  boluses,
  totalCount,
}: {
  boluses: BolusReviewItem[];
  totalCount: number;
}) {
  if (boluses.length === 0) {
    return (
      <p className="text-sm text-slate-500">
        No bolus events for this period.
      </p>
    );
  }

  return (
    <div className="space-y-2">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b-2 border-slate-300 dark:border-slate-600 print:border-slate-400">
              <th className="py-1.5 px-2 text-left text-xs font-semibold text-slate-500 print:text-slate-600 uppercase tracking-wider">
                Date/Time
              </th>
              <th className="py-1.5 px-2 text-right text-xs font-semibold text-slate-500 print:text-slate-600 uppercase tracking-wider">
                Units
              </th>
              <th className="py-1.5 px-2 text-center text-xs font-semibold text-slate-500 print:text-slate-600 uppercase tracking-wider">
                Type
              </th>
              <th className="py-1.5 px-2 text-left text-xs font-semibold text-slate-500 print:text-slate-600 uppercase tracking-wider">
                Reason
              </th>
              <th className="py-1.5 px-2 text-right text-xs font-semibold text-slate-500 print:text-slate-600 uppercase tracking-wider">
                BG
              </th>
              <th className="py-1.5 px-2 text-right text-xs font-semibold text-slate-500 print:text-slate-600 uppercase tracking-wider">
                IoB
              </th>
            </tr>
          </thead>
          <tbody>
            {boluses.map((b, i) => {
              const modeLabel: Record<string, string> = {
                SLEEP: "Sleep Mode",
                EXERCISE: "Exercise Mode",
              };
              const reasonLabel = b.is_automated
                ? (b.control_iq_reason || "Auto-correction")
                : (b.pump_activity_mode && b.pump_activity_mode !== "NONE"
                    ? modeLabel[b.pump_activity_mode] ?? b.pump_activity_mode
                    : "Manual");
              return (
                <tr
                  key={`${b.event_timestamp}-${i}`}
                  className="border-b border-slate-200 dark:border-slate-700 print:border-slate-300"
                >
                  <td className="py-1.5 px-2 text-slate-600 dark:text-slate-300 print:text-slate-700 whitespace-nowrap">
                    {new Date(b.event_timestamp).toLocaleString([], {
                      month: "short",
                      day: "numeric",
                      hour: "numeric",
                      minute: "2-digit",
                    })}
                  </td>
                  <td className="py-1.5 px-2 text-right font-medium text-slate-900 dark:text-white print:text-black">
                    {b.units.toFixed(2)} U
                  </td>
                  <td className="py-1.5 px-2 text-center">
                    {b.is_automated ? (
                      <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium bg-violet-100 text-violet-700 print:bg-violet-50 print:text-violet-800">
                        Auto
                      </span>
                    ) : (
                      <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium bg-slate-100 text-slate-600 print:bg-slate-50 print:text-slate-700">
                        Manual
                      </span>
                    )}
                  </td>
                  <td className="py-1.5 px-2 text-left text-xs text-slate-500 dark:text-slate-400 print:text-slate-600">
                    {reasonLabel}
                  </td>
                  <td className="py-1.5 px-2 text-right text-slate-600 dark:text-slate-300 print:text-slate-700">
                    {b.bg_at_event != null
                      ? `${Math.round(b.bg_at_event)}`
                      : "---"}
                  </td>
                  <td className="py-1.5 px-2 text-right text-slate-600 dark:text-slate-300 print:text-slate-700">
                    {b.iob_at_event != null
                      ? `${b.iob_at_event.toFixed(1)} U`
                      : "---"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {totalCount > boluses.length && (
        <p className="text-xs text-slate-400 print:text-slate-500">
          Showing most recent {boluses.length} of {totalCount} bolus events.
        </p>
      )}
    </div>
  );
}

function SensorCoverageSection({
  gaps,
  readings,
  periodDays,
  cgmActivePct,
}: {
  gaps: SensorGap[];
  readings: GlucoseHistoryReading[];
  periodDays: number;
  cgmActivePct: number | null;
}) {
  const totalGapMinutes = gaps.reduce((s, g) => s + g.durationMinutes, 0);
  const totalPeriodMinutes = periodDays * 24 * 60;
  // Prefer server-computed CGM active %, fall back to readings-based estimate
  const coveragePct = cgmActivePct != null
    ? Math.round(cgmActivePct)
    : totalPeriodMinutes > 0
      ? Math.min(
          100,
          Math.round((readings.length * 5 * 100) / totalPeriodMinutes),
        )
      : 0;
  const longestGap =
    gaps.length > 0 ? Math.max(...gaps.map((g) => g.durationMinutes)) : 0;

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <div>
          <p className="text-xs text-slate-500 print:text-slate-600 mb-1">
            Sensor Coverage
          </p>
          <p className="text-2xl font-bold text-slate-900 dark:text-white print:text-black">
            {coveragePct}%
          </p>
        </div>
        <div>
          <p className="text-xs text-slate-500 print:text-slate-600 mb-1">
            Total Readings
          </p>
          <p className="text-2xl font-bold text-slate-900 dark:text-white print:text-black">
            {readings.length.toLocaleString()}
          </p>
        </div>
        <div>
          <p className="text-xs text-slate-500 print:text-slate-600 mb-1">
            Sensor Gaps (&gt;20min)
          </p>
          <p className="text-2xl font-bold text-slate-900 dark:text-white print:text-black">
            {gaps.length}
          </p>
        </div>
        <div>
          <p className="text-xs text-slate-500 print:text-slate-600 mb-1">
            Longest Gap
          </p>
          <p className="text-2xl font-bold text-slate-900 dark:text-white print:text-black">
            {longestGap > 60
              ? `${Math.floor(longestGap / 60)}h ${longestGap % 60}m`
              : longestGap > 0
                ? `${longestGap}m`
                : "None"}
          </p>
        </div>
      </div>
      {totalGapMinutes > 0 && (
        <p className="text-xs text-slate-400 print:text-slate-500">
          Total gap time: {Math.floor(totalGapMinutes / 60)}h{" "}
          {totalGapMinutes % 60}m across {gaps.length} gap
          {gaps.length !== 1 ? "s" : ""}.
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section wrapper
// ---------------------------------------------------------------------------

const SECTION_CLASS =
  "bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-6 print:border-0 print:rounded-none print:border-b print:border-slate-300 print:p-4 print:break-inside-avoid";

function ReportSection({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className={SECTION_CLASS}>
      <h3 className="text-sm font-semibold text-slate-500 dark:text-slate-400 print:text-slate-600 uppercase tracking-wider mb-3">
        {title}
      </h3>
      {children}
    </div>
  );
}

function PlatformSettingsSection({
  glucoseRange,
  plugin,
  analyticsConfig,
}: {
  glucoseRange: { urgentLow: number; low: number; high: number; urgentHigh: number };
  plugin: PluginDeclarationResponse | null;
  analyticsConfig: AnalyticsConfigResponse | null;
}) {
  const displayLabels = analyticsConfig?.display_labels ?? null;

  return (
    <div className="space-y-4">
      {/* Glucose Thresholds */}
      <div>
        <h4 className="text-xs font-semibold text-slate-500 print:text-slate-600 uppercase tracking-wider mb-2">
          Glucose Target Ranges
        </h4>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
          <div>
            <p className="text-xs text-slate-400">Urgent Low</p>
            <p className="font-medium text-red-600 print:text-red-700">&lt;{glucoseRange.urgentLow} mg/dL</p>
          </div>
          <div>
            <p className="text-xs text-slate-400">Low</p>
            <p className="font-medium text-amber-500">{glucoseRange.urgentLow}-{glucoseRange.low} mg/dL</p>
          </div>
          <div>
            <p className="text-xs text-slate-400">Target Range</p>
            <p className="font-medium text-green-600 print:text-green-700">{glucoseRange.low}-{glucoseRange.high} mg/dL</p>
          </div>
          <div>
            <p className="text-xs text-slate-400">High</p>
            <p className="font-medium text-orange-500">&gt;{glucoseRange.high} mg/dL</p>
          </div>
        </div>
      </div>

      {/* Label Mappings (only if plugin + display labels exist) */}
      {plugin && displayLabels && displayLabels.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold text-slate-500 print:text-slate-600 uppercase tracking-wider mb-2">
            Bolus Category Labels
          </h4>
          <p className="text-xs text-slate-400 mb-2">
            How custom display labels map to {plugin.plugin_name} pump categories
          </p>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b-2 border-slate-300 dark:border-slate-600 print:border-slate-400">
                <th className="py-1 px-2 text-left text-xs font-semibold text-slate-500 print:text-slate-600 uppercase tracking-wider">
                  Display Label
                </th>
                <th className="py-1 px-2 text-left text-xs font-semibold text-slate-500 print:text-slate-600 uppercase tracking-wider">
                  Pump Source
                </th>
              </tr>
            </thead>
            <tbody>
              {[...displayLabels]
                .sort((a: DisplayLabel, b: DisplayLabel) => a.sort_order - b.sort_order)
                .map((dl: DisplayLabel) => (
                  <tr
                    key={dl.id}
                    className="border-b border-slate-200 dark:border-slate-700 print:border-slate-300"
                  >
                    <td className="py-1 px-2 text-slate-700 dark:text-slate-300 print:text-slate-700">
                      {dl.label}
                    </td>
                    <td className="py-1 px-2 text-slate-500 print:text-slate-500">
                      {dl.pump_source || "---"}
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page component
// ---------------------------------------------------------------------------

const PRESETS = [
  { label: "7 Days", days: 7 },
  { label: "14 Days", days: 14 },
  { label: "30 Days", days: 30 },
];

export default function ClinicalReportPage() {
  const [startDate, setStartDate] = useState(daysAgoDateString(13));
  const [endDate, setEndDate] = useState(todayDateString());
  const [selectedPreset, setSelectedPreset] = useState<number | null>(14);
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reportData, setReportData] = useState<ReportData | null>(null);
  const [generatedAt, setGeneratedAt] = useState<string | null>(null);
  const [reportStartDate, setReportStartDate] = useState<string | null>(null);
  const [reportEndDate, setReportEndDate] = useState<string | null>(null);
  const didAutoGenerate = useRef(false);
  const requestIdRef = useRef(0);

  const numDays = useMemo(
    () => daysBetween(startDate, endDate) + 1,
    [startDate, endDate],
  );
  const isValid = numDays >= 1 && numDays <= 31;
  const reportDays =
    reportStartDate && reportEndDate
      ? daysBetween(reportStartDate, reportEndDate) + 1
      : 0;

  // Derive CGM source from readings (e.g., "dexcom" -> "Dexcom CGM")
  const cgmSource = useMemo(() => {
    if (!reportData || reportData.readings.length === 0) return null;
    const sources = new Set(reportData.readings.map((r) => r.source));
    const labels: string[] = [];
    for (const s of sources) {
      const lower = s.toLowerCase();
      if (lower.includes("dexcom")) labels.push("Dexcom CGM");
      else if (lower.includes("libre")) labels.push("FreeStyle Libre CGM");
      else if (lower.includes("medtronic")) labels.push("Medtronic CGM");
      else labels.push(`${s} CGM`);
    }
    return labels.join(", ") || null;
  }, [reportData]);

  // Unified glucose thresholds: prefer TIR stats (period-specific), fall back to user settings, then defaults
  const thresholds = useMemo(() => {
    const tir = reportData?.tirStats?.thresholds;
    const range = reportData?.glucoseRange;
    return {
      urgentLow: tir?.urgent_low ?? range?.urgent_low ?? 54,
      low: tir?.low ?? range?.low_target ?? 70,
      high: tir?.high ?? range?.high_target ?? 180,
      urgentHigh: tir?.urgent_high ?? range?.urgent_high ?? 250,
    };
  }, [reportData]);

  // Computed analyses
  const agpBuckets = useMemo(
    () => (reportData ? computeAgpBuckets(reportData.readings) : []),
    [reportData],
  );
  const hypoEvents = useMemo(() => {
    if (!reportData || reportData.readings.length === 0) return [];
    return detectHypoEvents(reportData.readings, thresholds.low, thresholds.urgentLow);
  }, [reportData, thresholds]);
  const overnightStats = useMemo(() => {
    if (!reportData || reportData.readings.length === 0) return null;
    return computeOvernightStats(reportData.readings, thresholds.low, thresholds.high);
  }, [reportData, thresholds]);
  const sensorGaps = useMemo(
    () => (reportData ? detectSensorGaps(reportData.readings) : []),
    [reportData],
  );

  const handlePreset = useCallback((days: number) => {
    setStartDate(daysAgoDateString(days - 1));
    setEndDate(todayDateString());
    setSelectedPreset(days);
  }, []);

  const handleGenerate = useCallback(async () => {
    if (!isValid) return;
    const currentRequestId = ++requestIdRef.current;
    setIsGenerating(true);
    setError(null);
    setReportData(null);
    try {
      const data = await fetchReportData(startDate, endDate);
      if (currentRequestId !== requestIdRef.current) return;
      setReportData(data);
      setReportStartDate(startDate);
      setReportEndDate(endDate);
      setGeneratedAt(
        new Date().toLocaleString([], {
          year: "numeric",
          month: "long",
          day: "numeric",
          hour: "numeric",
          minute: "2-digit",
        }),
      );
    } catch (err) {
      if (currentRequestId !== requestIdRef.current) return;
      setError(
        err instanceof Error ? err.message : "Failed to generate report",
      );
    } finally {
      if (currentRequestId === requestIdRef.current) {
        setIsGenerating(false);
      }
    }
  }, [startDate, endDate, isValid]);

  const handlePrint = useCallback(() => {
    window.print();
  }, []);

  // Auto-generate on first load with default 14-day range
  useEffect(() => {
    if (didAutoGenerate.current) return;
    didAutoGenerate.current = true;
    let cancelled = false;
    const start = daysAgoDateString(13);
    const end = todayDateString();
    setIsGenerating(true);
    fetchReportData(start, end)
      .then((data) => {
        if (cancelled) return;
        setReportData(data);
        setReportStartDate(start);
        setReportEndDate(end);
        setGeneratedAt(
          new Date().toLocaleString([], {
            year: "numeric",
            month: "long",
            day: "numeric",
            hour: "numeric",
            minute: "2-digit",
          }),
        );
      })
      .catch((err) => {
        if (cancelled) return;
        setError(
          err instanceof Error ? err.message : "Failed to generate report",
        );
      })
      .finally(() => {
        if (!cancelled) {
          setIsGenerating(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="space-y-6">
      {/* Controls bar -- hidden on print */}
      <div className="print:hidden">
        <Link
          href="/dashboard/settings/data"
          className="inline-flex items-center gap-1.5 text-sm text-slate-400 hover:text-slate-200 mb-4"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to Data Settings
        </Link>

        <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-6">
          <div className="flex items-center gap-3 mb-4">
            <div className="p-2 bg-blue-500/10 rounded-lg">
              <FileText className="h-5 w-5 text-blue-400" />
            </div>
            <div>
              <h1 className="text-lg font-semibold text-slate-900 dark:text-white">
                Clinical Report
              </h1>
              <p className="text-sm text-slate-500 dark:text-slate-400">
                Generate a printable report for your healthcare provider
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-end gap-4">
            {/* Presets */}
            <div className="flex gap-2">
              {PRESETS.map((preset) => (
                <button
                  key={preset.days}
                  type="button"
                  onClick={() => handlePreset(preset.days)}
                  className={`px-3 py-1.5 text-sm rounded-lg border transition-colors ${
                    selectedPreset === preset.days
                      ? "border-blue-500 bg-blue-500/10 text-blue-600 dark:text-blue-400"
                      : "border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800"
                  }`}
                >
                  {preset.label}
                </button>
              ))}
            </div>

            {/* Date range */}
            <div className="flex items-center gap-2">
              <Calendar className="h-4 w-4 text-slate-400" />
              <input
                id="report-start"
                type="date"
                aria-label="Report start date"
                value={startDate}
                max={endDate}
                onChange={(e) => {
                  if (e.target.value) {
                    setStartDate(e.target.value);
                    setSelectedPreset(null);
                  }
                }}
                className="px-3 py-1.5 text-sm rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none"
              />
              <span className="text-sm text-slate-400">to</span>
              <input
                id="report-end"
                type="date"
                aria-label="Report end date"
                value={endDate}
                min={startDate}
                max={todayDateString()}
                onChange={(e) => {
                  if (e.target.value) {
                    setEndDate(e.target.value);
                    setSelectedPreset(null);
                  }
                }}
                className="px-3 py-1.5 text-sm rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none"
              />
              <span className="text-xs text-slate-400">
                {numDays}d
                {!isValid && (
                  <span className="text-red-400 ml-1">
                    {numDays > 31 ? "(max 31 days)" : "(invalid range)"}
                  </span>
                )}
              </span>
            </div>

            {/* Generate */}
            <button
              type="button"
              onClick={handleGenerate}
              disabled={!isValid || isGenerating}
              className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-600/50 text-white text-sm font-medium rounded-lg transition-colors disabled:cursor-not-allowed"
            >
              {isGenerating ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <FileText className="h-4 w-4" />
              )}
              {isGenerating ? "Generating..." : "Generate Report"}
            </button>

            {/* Print */}
            {reportData && (
              <button
                type="button"
                onClick={handlePrint}
                className="inline-flex items-center gap-2 px-4 py-2 bg-green-600 hover:bg-green-700 text-white text-sm font-medium rounded-lg transition-colors"
              >
                <Printer className="h-4 w-4" />
                Print / Save PDF
              </button>
            )}
          </div>

          {error && (
            <div className="flex items-center gap-2 text-sm text-red-400 mt-3">
              <AlertCircle className="h-4 w-4" />
              {error}
            </div>
          )}
        </div>
      </div>

      {/* Loading state */}
      {isGenerating && !reportData && (
        <div className="flex flex-col items-center justify-center py-20 print:hidden">
          <Loader2 className="h-8 w-8 animate-spin text-blue-500 mb-3" />
          <p className="text-sm text-slate-400">Generating your report...</p>
        </div>
      )}

      {/* Report body -- this is what prints */}
      {reportData && reportStartDate && reportEndDate && (
        <div className="space-y-4 print:space-y-2">
          {/* Print-only branding header */}
          <div className="hidden print:flex items-center gap-3 mb-4">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/logo.png" alt="GlycemicGPT" width={40} height={40} className="rounded-lg" />
            <div>
              <p className="text-lg font-bold text-black">GlycemicGPT</p>
              <p className="text-xs text-slate-500">AI-Powered Diabetes Management Platform</p>
            </div>
          </div>

          {/* 1. Report header with patient & device info */}
          <div className={`${SECTION_CLASS} print:p-0 print:pb-4 print:mb-2`}>
            <PatientDeviceHeader
              user={reportData.user}
              plugin={reportData.plugin}
              cgmSource={cgmSource}
              dateRange={`${formatDisplayDate(reportStartDate)} \u2013 ${formatDisplayDate(reportEndDate)} (${reportDays} day${reportDays !== 1 ? "s" : ""})`}
              generatedAt={generatedAt}
            />
          </div>

          {/* Partial failure warnings */}
          {reportData.warnings.length > 0 && (
            <div className="bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-300 dark:border-yellow-700 rounded-xl p-4 print:border print:border-yellow-400 print:bg-yellow-50">
              <div className="flex items-start gap-2">
                <AlertCircle className="h-4 w-4 text-yellow-600 dark:text-yellow-400 mt-0.5 shrink-0" />
                <div>
                  <p className="text-sm font-medium text-yellow-800 dark:text-yellow-300">
                    Incomplete Report
                  </p>
                  <ul className="text-xs text-yellow-700 dark:text-yellow-400 mt-1 list-disc list-inside">
                    {reportData.warnings.map((w) => (
                      <li key={w}>{w}</li>
                    ))}
                  </ul>
                </div>
              </div>
            </div>
          )}

          {/* Platform Settings */}
          <ReportSection title="Platform Settings">
            <PlatformSettingsSection
              glucoseRange={thresholds}
              plugin={reportData.plugin}
              analyticsConfig={reportData.analyticsConfig}
            />
          </ReportSection>

          {/* 2. CGM Summary with prominent eA1C */}
          {reportData.cgmStats &&
            reportData.cgmStats.readings_count > 0 && (
              <ReportSection title="CGM Summary">
                <CgmStatsSection stats={reportData.cgmStats} />
              </ReportSection>
            )}

          {/* 3. Time in Range */}
          {reportData.tirStats &&
            reportData.tirStats.readings_count > 0 && (
              <ReportSection title="Time in Range">
                <TirSection tir={reportData.tirStats} />
              </ReportSection>
            )}

          {/* 4. Ambulatory Glucose Profile (AGP) */}
          {agpBuckets.some((b) => b.count > 0) && (
            <ReportSection title="Ambulatory Glucose Profile (AGP)">
              <AgpChartSection
                buckets={agpBuckets}
                low={thresholds.low}
                high={thresholds.high}
                urgentLow={thresholds.urgentLow}
                urgentHigh={thresholds.urgentHigh}
              />
            </ReportSection>
          )}

          {/* 5. Glucose Trend */}
          {reportData.readings.length > 0 && (
            <ReportSection title="Glucose Trend">
              <ReportGlucoseChart
                readings={reportData.readings}
                startDate={reportStartDate}
                endDate={reportEndDate}
                low={thresholds.low}
                high={thresholds.high}
                urgentLow={thresholds.urgentLow}
                urgentHigh={thresholds.urgentHigh}
              />
            </ReportSection>
          )}

          {/* 6. Daily Glucose Overlay */}
          {reportData.readings.length > 0 && reportDays >= 2 && (
            <ReportSection title="Daily Glucose Overlay">
              <DailyOverlayChart
                readings={reportData.readings}
                low={thresholds.low}
                high={thresholds.high}
                urgentLow={thresholds.urgentLow}
                urgentHigh={thresholds.urgentHigh}
              />
            </ReportSection>
          )}

          {/* 7. Hypoglycemia Analysis */}
          {reportData.readings.length > 0 && (
            <ReportSection title="Hypoglycemia Analysis">
              <HypoSection events={hypoEvents} periodDays={reportDays} low={thresholds.low} urgentLow={thresholds.urgentLow} />
            </ReportSection>
          )}

          {/* 8. Overnight Pattern */}
          {overnightStats && (
            <ReportSection title="Overnight Pattern (10 PM - 6 AM)">
              <OvernightSection stats={overnightStats} />
            </ReportSection>
          )}

          {/* 9. Insulin Delivery */}
          {reportData.insulin &&
            (reportData.insulin.tdd > 0 ||
              reportData.insulin.bolus_count > 0) && (
              <ReportSection title="Insulin Delivery">
                <InsulinSection insulin={reportData.insulin} />
              </ReportSection>
            )}

          {/* 10. Active Pump Settings */}
          {reportData.pumpProfile && (
            <ReportSection title="Active Pump Settings">
              <PumpSettingsSection profile={reportData.pumpProfile} />
            </ReportSection>
          )}

          {/* 11. Bolus Events */}
          {reportData.boluses.length > 0 && (
            <ReportSection title="Bolus Events">
              <BolusTable
                boluses={reportData.boluses}
                totalCount={reportData.totalBolusCount}
              />
            </ReportSection>
          )}

          {/* 12. Sensor Coverage */}
          {reportData.readings.length > 0 && (
            <ReportSection title="Sensor Coverage">
              <SensorCoverageSection
                gaps={sensorGaps}
                readings={reportData.readings}
                periodDays={reportDays}
                cgmActivePct={reportData.cgmStats?.cgm_active_pct ?? null}
              />
            </ReportSection>
          )}

          {/* 13. Footer */}
          <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-4 print:border-0 print:rounded-none print:p-2 print:mt-4">
            <p className="text-xs text-slate-400 print:text-slate-500 text-center">
              This report is generated from data collected by GlycemicGPT and is
              intended for informational purposes only. It is not a substitute
              for professional medical advice, diagnosis, or treatment. Always
              consult with a qualified healthcare provider.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
