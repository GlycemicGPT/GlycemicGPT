"use client";

/**
 * GlucoseTrendChart Component
 *
 * Dexcom-style glucose trend chart with colored dots, target range band,
 * bolus delivery markers, basal rate area, and time period selector.
 */

import { useMemo, useEffect, useRef, useState, useCallback } from "react";
import {
  ResponsiveContainer,
  ComposedChart,
  Scatter,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceArea,
  Cell,
} from "recharts";
import { ZoomIn, ZoomOut } from "lucide-react";
import clsx from "clsx";
import type { MouseHandlerDataParam } from "recharts/types/synchronisation/types";
import { type GlucoseHistoryReading, type PumpEventReading } from "@/lib/api";
import { lttbDownsample } from "@/lib/downsample";
import { type ChartTimePeriod, PERIOD_TO_MS, isMultiDay } from "@/lib/chart-periods";
import { GLUCOSE_THRESHOLDS } from "./glucose-hero";
import { useGlucoseHistory } from "@/hooks/use-glucose-history";
import { usePumpEvents } from "@/hooks/use-pump-events";
import { TREND_ARROWS, TREND_DESCRIPTIONS, type TrendDirection } from "./trend-arrow";
import { mapBackendTrendToFrontend } from "@/hooks/use-glucose-stream";

// --- Color mapping by glucose classification ---

export function getPointColor(
  value: number,
  thresholds?: { urgentLow: number; low: number; high: number; urgentHigh: number }
): string {
  const t = thresholds ?? {
    urgentLow: GLUCOSE_THRESHOLDS.URGENT_LOW,
    low: GLUCOSE_THRESHOLDS.LOW,
    high: GLUCOSE_THRESHOLDS.HIGH,
    urgentHigh: GLUCOSE_THRESHOLDS.URGENT_HIGH,
  };
  if (value < t.urgentLow) return "#dc2626"; // red-600
  if (value < t.low) return "#f59e0b"; // amber-500
  if (value <= t.high) return "#22c55e"; // green-500
  if (value <= t.urgentHigh) return "#f59e0b"; // amber-500
  return "#dc2626"; // red-600
}

// --- Time period buttons ---

const PERIODS: { value: ChartTimePeriod; label: string }[] = [
  { value: "3h", label: "3H" },
  { value: "6h", label: "6H" },
  { value: "12h", label: "12H" },
  { value: "24h", label: "24H" },
  { value: "3d", label: "3D" },
  { value: "7d", label: "7D" },
  { value: "14d", label: "14D" },
  { value: "30d", label: "30D" },
];

export { PERIOD_TO_MS };

// Max visual points for chart rendering (LTTB target)
const MAX_CHART_POINTS = 500;
// Max bolus markers to display (keeps largest when exceeded)
const MAX_BOLUS_MARKERS = 50;
// Minimum zoom window (15 minutes) to prevent accidental micro-zooms
const MIN_ZOOM_MS = 15 * 60 * 1000;

// --- Chart data point ---

interface ChartPoint {
  timestamp: number;
  value: number;
  color: string;
  iso: string;
  trend: TrendDirection;
  trendRate: number | null;
}

function transformReadings(
  readings: GlucoseHistoryReading[],
  thresholds?: { urgentLow: number; low: number; high: number; urgentHigh: number }
): ChartPoint[] {
  // Filter to physiological bounds (20-500 mg/dL) -- matches SSE validation
  const sorted = readings
    .filter((r) => r.value >= 20 && r.value <= 500)
    .map((r) => ({
      timestamp: new Date(r.reading_timestamp).getTime(),
      value: r.value,
      color: getPointColor(r.value, thresholds),
      iso: r.reading_timestamp,
      trend: mapBackendTrendToFrontend(r.trend),
      trendRate: r.trend_rate,
    }))
    .sort((a, b) => a.timestamp - b.timestamp);

  // Apply LTTB downsampling for large datasets (multi-day views)
  // LTTB selects original objects so extra fields survive downsampling
  return lttbDownsample(sorted, MAX_CHART_POINTS);
}

// --- Pump event data transformations ---

interface BolusPoint {
  timestamp: number;
  units: number;
  isAutomated: boolean;
  isCorrection: boolean;
  label: string;
  pumpActivityMode: string | null;
  iobAtEvent: number | null;
  bgAtEvent: number | null;
}

interface BasalPoint {
  timestamp: number;
  rate: number;
  value: number; // alias for rate -- LTTB compatibility
  isAutomated: boolean;
  pumpActivityMode: string | null;
  basalAdjustmentPct: number | null;
}

// Pump-agnostic mode colors (matches mobile ChartColors)
const MODE_COLORS: Record<string, string> = {
  sleep: "#7E57C2",      // Purple
  exercise: "#FF9800",   // Orange
  activity: "#FF9800",   // Orange (alias for pumps that call it "activity")
  automated: "#00BCD4",  // Teal
  manual: "#78909C",     // Blue-grey
};

// Pump-agnostic mode display labels
const MODE_LABELS: Record<string, string> = {
  sleep: "Sleep",
  exercise: "Activity",
  activity: "Activity",
};

function getBasalModeColor(mode: string | null, isAutomated: boolean): string {
  if (mode && mode !== "none" && MODE_COLORS[mode]) return MODE_COLORS[mode];
  return isAutomated ? MODE_COLORS.automated : MODE_COLORS.manual;
}

function getBasalModeLabel(mode: string | null, isAutomated: boolean): string {
  if (mode && mode !== "none" && MODE_LABELS[mode]) return MODE_LABELS[mode];
  return isAutomated ? "Automated" : "Manual";
}

/** Convert hex color to rgba with alpha (avoids fragile hex+alpha string concatenation) */
function hexToRgba(hex: string, alpha: number): string {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

const MAX_BOLUS_UNITS = 25; // align with backend safety limits
const MAX_BASAL_U_PER_HR = 15; // align with backend safety limits
const MIN_GLUCOSE_MGDL = 20;
const MAX_GLUCOSE_MGDL = 500;

function transformBolusEvents(events: PumpEventReading[]): BolusPoint[] {
  return events
    .filter(
      (e) =>
        (e.event_type === "bolus" || e.event_type === "correction") &&
        e.units != null &&
        e.units > 0 &&
        e.units <= MAX_BOLUS_UNITS,
    )
    .map((e) => ({
      timestamp: new Date(e.event_timestamp).getTime(),
      units: e.units!,
      isAutomated: e.is_automated,
      isCorrection: e.event_type === "correction",
      label: `${e.units!.toFixed(1)}u`,
      pumpActivityMode: e.pump_activity_mode,
      iobAtEvent: e.iob_at_event,
      bgAtEvent:
        typeof e.bg_at_event === "number" &&
        e.bg_at_event >= MIN_GLUCOSE_MGDL &&
        e.bg_at_event <= MAX_GLUCOSE_MGDL
          ? e.bg_at_event
          : null,
    }))
    .sort((a, b) => a.timestamp - b.timestamp);
}

function transformBasalEvents(events: PumpEventReading[]): BasalPoint[] {
  return events
    .filter(
      (e) =>
        e.event_type === "basal" &&
        e.units != null &&
        e.units >= 0 &&
        e.units <= MAX_BASAL_U_PER_HR,
    )
    .map((e) => ({
      timestamp: new Date(e.event_timestamp).getTime(),
      rate: e.units!,
      value: e.units!, // LTTB needs `value`
      isAutomated: e.is_automated,
      pumpActivityMode: e.pump_activity_mode,
      basalAdjustmentPct: e.basal_adjustment_pct,
    }))
    .sort((a, b) => a.timestamp - b.timestamp);
}

// --- Custom tooltip ---

function ChartTooltip({
  active,
  payload,
  multiDay,
}: {
  active?: boolean;
  payload?: Array<{ payload: Record<string, unknown> }>;
  multiDay?: boolean;
}) {
  if (!active || !payload?.length) return null;
  const point = payload[0].payload;
  if (!point) return null;

  const formatTime = (ts: number | string) => {
    const d = new Date(ts);
    if (multiDay) {
      return d.toLocaleDateString([], { month: "short", day: "numeric" }) +
        " " + d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
    }
    return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  };

  // Bolus scatter point (has `units` field but no `rate`)
  if ("units" in point && typeof point.units === "number" && !("rate" in point)) {
    const isAuto = typeof point.isAutomated === "boolean" ? point.isAutomated : false;
    const bolusType = isAuto ? "Auto Correction" : "Manual Bolus";
    const typeColor = isAuto ? "#3b82f6" : "#8b5cf6";
    const mode = typeof point.pumpActivityMode === "string" ? point.pumpActivityMode : null;
    const iob = typeof point.iobAtEvent === "number" ? point.iobAtEvent : null;
    const bg = typeof point.bgAtEvent === "number" ? point.bgAtEvent : null;
    const ts = typeof point.timestamp === "number" ? point.timestamp : null;
    return (
      <div className="bg-slate-100 dark:bg-slate-800 border border-slate-300 dark:border-slate-700 rounded-lg px-3 py-2 text-sm shadow-lg max-w-[200px]">
        <p className="font-semibold" style={{ color: typeColor }}>
          {point.units.toFixed(1)}u {bolusType}
        </p>
        {/* "standard" guard: pre-migration data may still have this value */}
        {mode && mode !== "none" && mode !== "standard" && (
          <p className="text-slate-500 dark:text-slate-400 text-xs">{getBasalModeLabel(mode, isAuto)}</p>
        )}
        {iob != null && (
          <p className="text-slate-500 dark:text-slate-400 text-xs">IoB: {iob.toFixed(1)}u</p>
        )}
        {bg != null && (
          <p className="text-slate-500 dark:text-slate-400 text-xs">BG: {bg} mg/dL</p>
        )}
        {ts != null && <p className="text-slate-500 dark:text-slate-400 text-xs">{formatTime(ts)}</p>}
      </div>
    );
  }

  // Basal data point (has `rate` field)
  if ("rate" in point && typeof point.rate === "number") {
    const mode = typeof point.pumpActivityMode === "string" ? point.pumpActivityMode : null;
    const isAuto = typeof point.isAutomated === "boolean" ? point.isAutomated : false;
    const modeColor = getBasalModeColor(mode, isAuto);
    const modeLabel = getBasalModeLabel(mode, isAuto);
    const adjustPct = typeof point.basalAdjustmentPct === "number" ? point.basalAdjustmentPct : null;
    const ts = typeof point.timestamp === "number" ? point.timestamp : null;
    return (
      <div className="bg-slate-100 dark:bg-slate-800 border border-slate-300 dark:border-slate-700 rounded-lg px-3 py-2 text-sm shadow-lg">
        <p className="font-semibold" style={{ color: modeColor }}>
          Basal: {point.rate.toFixed(2)} u/hr
        </p>
        <p className="text-slate-500 dark:text-slate-400 text-xs">{modeLabel}</p>
        {adjustPct != null && adjustPct !== 0 && (
          <p className="text-slate-500 dark:text-slate-400 text-xs">
            {adjustPct > 0 ? "+" : ""}{adjustPct}% from profile
          </p>
        )}
        {ts != null && <p className="text-slate-500 dark:text-slate-400 text-xs">{formatTime(ts)}</p>}
      </div>
    );
  }

  // Glucose data point (has `iso` and `value` fields)
  if (!point.iso || typeof point.value !== "number") return null;
  const trend = point.trend as TrendDirection | undefined;
  const trendArrow = trend ? TREND_ARROWS[trend] : null;
  const trendLabel = trend ? TREND_DESCRIPTIONS[trend] : null;
  return (
    <div className="bg-slate-100 dark:bg-slate-800 border border-slate-300 dark:border-slate-700 rounded-lg px-3 py-2 text-sm shadow-lg">
      <p className="font-semibold" style={{ color: point.color as string }}>
        {point.value} mg/dL
        {trendArrow && trendArrow !== "?" && (
          <span className="ml-1">{trendArrow}</span>
        )}
      </p>
      {trendLabel && trendLabel !== "unknown trend" && (
        <p className="text-slate-500 dark:text-slate-400 text-xs capitalize">{trendLabel}</p>
      )}
      <p className="text-slate-500 dark:text-slate-400 text-xs">{formatTime(point.iso as string)}</p>
    </div>
  );
}

// --- Time period selector ---

interface PeriodSelectorProps {
  selected: ChartTimePeriod;
  onSelect: (p: ChartTimePeriod) => void;
}

function PeriodSelector({ selected, onSelect }: PeriodSelectorProps) {
  return (
    <div
      className="flex gap-1 bg-slate-100 dark:bg-slate-800 rounded-lg p-1"
      role="radiogroup"
      aria-label="Time period"
    >
      {PERIODS.map(({ value, label }) => (
        <button
          key={value}
          type="button"
          role="radio"
          aria-checked={selected === value}
          onClick={() => onSelect(value)}
          className={clsx(
            "px-3 py-1 text-sm font-medium rounded-md transition-colors",
            selected === value
              ? "bg-slate-200 text-slate-900 dark:bg-slate-700 dark:text-white"
              : "text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200"
          )}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

// --- X-axis tick formatter ---

function formatXTick(epoch: number, multiDay: boolean): string {
  const d = new Date(epoch);
  if (multiDay) {
    return d.toLocaleDateString([], { month: "short", day: "numeric" });
  }
  return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

// --- Brush slider for zoom pan ---

// Keyboard step sizes for brush slider arrow key navigation
const KEY_STEP_MS = 5 * 60 * 1000;       // 5 minutes per arrow key
const KEY_STEP_SHIFT_MS = 30 * 60 * 1000; // 30 minutes with Shift

interface BrushSliderProps {
  fullDomain: [number, number];
  zoomDomain: [number, number] | null;
  onZoomChange: (d: [number, number] | null) => void;
}

function BrushSlider({ fullDomain, zoomDomain, onZoomChange }: BrushSliderProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [dragType, setDragType] = useState<"left" | "right" | "pan" | null>(null);
  const dragStartRef = useRef<{ clientX: number; domain: [number, number] }>({
    clientX: 0,
    domain: [0, 0],
  });
  // Keep zoom in a ref so drag handlers always see latest value (FIX #1: stale closure)
  const zoomRef = useRef(zoomDomain ?? fullDomain);
  zoomRef.current = zoomDomain ?? fullDomain;

  const range = fullDomain[1] - fullDomain[0];
  // FIX #2: Guard against division by zero
  const safeRange = range > 0 ? range : 1;
  const zoom = zoomDomain ?? fullDomain;
  const leftPct = ((zoom[0] - fullDomain[0]) / safeRange) * 100;
  const widthPct = ((zoom[1] - zoom[0]) / safeRange) * 100;

  const clientXToTimestamp = useCallback(
    (clientX: number): number => {
      const el = containerRef.current;
      if (!el) return fullDomain[0];
      const rect = el.getBoundingClientRect();
      const frac = Math.max(0, Math.min(1, (clientX - rect.left) / Math.max(1, rect.width)));
      return fullDomain[0] + frac * safeRange;
    },
    [fullDomain, safeRange],
  );

  const handlePointerDown = useCallback(
    (type: "left" | "right" | "pan", e: React.MouseEvent | React.TouchEvent) => {
      e.preventDefault();
      e.stopPropagation();
      const clientX = "touches" in e ? e.touches[0]?.clientX : e.clientX;
      if (clientX == null) return;
      setDragType(type);
      dragStartRef.current = { clientX, domain: [...zoomRef.current] as [number, number] };
    },
    [],
  );

  const handleHandleKeyDown = useCallback(
    (edge: "left" | "right", e: React.KeyboardEvent) => {
      if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
      e.preventDefault();
      const step = e.shiftKey ? KEY_STEP_SHIFT_MS : KEY_STEP_MS;
      const delta = e.key === "ArrowRight" ? step : -step;
      const current = zoomRef.current;
      if (edge === "left") {
        const newLeft = Math.max(fullDomain[0], Math.min(current[0] + delta, current[1] - MIN_ZOOM_MS));
        onZoomChange([newLeft, current[1]]);
      } else {
        const newRight = Math.min(fullDomain[1], Math.max(current[1] + delta, current[0] + MIN_ZOOM_MS));
        onZoomChange([current[0], newRight]);
      }
    },
    [fullDomain, onZoomChange],
  );

  useEffect(() => {
    if (!dragType) return;

    const onMove = (e: MouseEvent | TouchEvent) => {
      if ("touches" in e) e.preventDefault(); // Prevent page scroll during brush drag
      const touch = "touches" in e ? (e.touches[0] ?? e.changedTouches?.[0]) : null;
      const clientX = touch ? touch.clientX : (e as MouseEvent).clientX;
      if (clientX == null) return;
      const ts = clientXToTimestamp(clientX);
      const start = dragStartRef.current;
      const currentZoom = zoomRef.current; // FIX #1: read from ref, not closure

      if (dragType === "left") {
        const newLeft = Math.max(fullDomain[0], Math.min(ts, currentZoom[1] - MIN_ZOOM_MS));
        onZoomChange([newLeft, currentZoom[1]]);
      } else if (dragType === "right") {
        const newRight = Math.min(fullDomain[1], Math.max(ts, currentZoom[0] + MIN_ZOOM_MS));
        onZoomChange([currentZoom[0], newRight]);
      } else if (dragType === "pan") {
        const delta = ts - clientXToTimestamp(start.clientX);
        const span = start.domain[1] - start.domain[0];
        let newLeft = start.domain[0] + delta;
        let newRight = start.domain[1] + delta;
        if (newLeft < fullDomain[0]) {
          newLeft = fullDomain[0];
          newRight = fullDomain[0] + span;
        }
        if (newRight > fullDomain[1]) {
          newRight = fullDomain[1];
          newLeft = fullDomain[1] - span;
        }
        onZoomChange([newLeft, newRight]);
      }
    };

    const onUp = () => setDragType(null);

    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    window.addEventListener("touchmove", onMove, { passive: false });
    window.addEventListener("touchend", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
      window.removeEventListener("touchmove", onMove);
      window.removeEventListener("touchend", onUp);
    };
  }, [dragType, fullDomain, clientXToTimestamp, onZoomChange]);

  if (!zoomDomain) return null;

  return (
    <div
      ref={containerRef}
      className="relative h-6 mt-2 bg-slate-100 dark:bg-slate-800 rounded select-none"
      aria-label="Zoom brush slider"
    >
      {/* Selected region */}
      <div
        className="absolute top-0 h-full bg-slate-600 rounded-sm"
        style={{
          left: `${leftPct}%`,
          width: `${widthPct}%`,
          cursor: dragType === "pan" ? "grabbing" : "grab",
        }}
        onMouseDown={(e) => handlePointerDown("pan", e)}
        onTouchStart={(e) => handlePointerDown("pan", e)}
      >
        {/* Left handle -- focusable with keyboard support */}
        <div
          role="slider"
          tabIndex={0}
          aria-label="Adjust zoom start"
          aria-valuemin={fullDomain[0]}
          aria-valuemax={fullDomain[1]}
          aria-valuenow={zoom[0]}
          className="absolute left-0 top-0 h-full w-4 flex justify-start focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 rounded-l-sm"
          style={{ cursor: "col-resize", marginLeft: "-4px" }}
          onMouseDown={(e) => handlePointerDown("left", e)}
          onTouchStart={(e) => handlePointerDown("left", e)}
          onKeyDown={(e) => handleHandleKeyDown("left", e)}
        >
          <div className="h-full w-2 bg-slate-400 rounded-l-sm hover:bg-slate-300 transition-colors" />
        </div>
        {/* Right handle -- focusable with keyboard support */}
        <div
          role="slider"
          tabIndex={0}
          aria-label="Adjust zoom end"
          aria-valuemin={fullDomain[0]}
          aria-valuemax={fullDomain[1]}
          aria-valuenow={zoom[1]}
          className="absolute right-0 top-0 h-full w-4 flex justify-end focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 rounded-r-sm"
          style={{ cursor: "col-resize", marginRight: "-4px" }}
          onMouseDown={(e) => handlePointerDown("right", e)}
          onTouchStart={(e) => handlePointerDown("right", e)}
          onKeyDown={(e) => handleHandleKeyDown("right", e)}
        >
          <div className="h-full w-2 bg-slate-400 rounded-r-sm hover:bg-slate-300 transition-colors" />
        </div>
      </div>
    </div>
  );
}

// --- Custom bolus marker for Scatter shape ---

// Recharts Scatter shape prop types are loosely typed -- narrow as much as possible
function renderBolusMarker(props: { cx?: number; cy?: number; payload?: Record<string, unknown> }) {
  const { cx, cy, payload } = props;
  if (cx == null || cy == null || !payload) return <g />;
  const p = payload as unknown as BolusPoint;
  const isAuto = p.isAutomated;
  const color = isAuto ? "#3b82f6" : "#8b5cf6";
  const r = 5;
  return (
    <g>
      {isAuto ? (
        <polygon
          points={`${cx},${cy - r} ${cx + r},${cy} ${cx},${cy + r} ${cx - r},${cy}`}
          fill={color}
          opacity={0.9}
        />
      ) : (
        <circle cx={cx} cy={cy} r={r} fill={color} opacity={0.9} />
      )}
      <text
        x={cx}
        y={cy - r - 3}
        textAnchor="middle"
        fill={color}
        fontSize={9}
        fontWeight={600}
      >
        {p.label}
      </text>
      {isAuto && (
        <text
          x={cx}
          y={cy - r - 13}
          textAnchor="middle"
          fill={color}
          fontSize={7}
          opacity={0.8}
        >
          AUTO
        </text>
      )}
    </g>
  );
}

// --- Main component ---

export interface GlucoseTrendChartProps {
  /** Signal to trigger a refetch (e.g., from SSE glucose update) */
  refreshKey?: number;
  className?: string;
  /** Dynamic glucose thresholds from user settings */
  thresholds?: {
    urgentLow: number;
    low: number;
    high: number;
    urgentHigh: number;
  };
}

export function GlucoseTrendChart({
  refreshKey,
  className,
  thresholds,
}: GlucoseTrendChartProps) {
  const { readings, isLoading, error, period, setPeriod, refetch } =
    useGlucoseHistory("3h");
  const { events: pumpEvents, refetch: refetchPump } = usePumpEvents(period);

  // Zoom state
  const [zoomDomain, setZoomDomain] = useState<[number, number] | null>(null);
  const [selectionStart, setSelectionStart] = useState<number | null>(null);
  const [selectionEnd, setSelectionEnd] = useState<number | null>(null);
  const chartAreaRef = useRef<HTMLDivElement>(null);

  // Refetch when refreshKey changes (new SSE data arrived)
  const prevRefreshKeyRef = useRef(refreshKey);
  useEffect(() => {
    if (
      refreshKey !== undefined &&
      refreshKey > 0 &&
      refreshKey !== prevRefreshKeyRef.current
    ) {
      prevRefreshKeyRef.current = refreshKey;
      refetch();
      refetchPump();
    }
  }, [refreshKey, refetch, refetchPump]);

  const multiDay = isMultiDay(period);
  const data = useMemo(() => transformReadings(readings, thresholds), [readings, thresholds]);
  const bolusData = useMemo(() => transformBolusEvents(pumpEvents), [pumpEvents]);
  const basalData = useMemo(() => {
    const points = transformBasalEvents(pumpEvents);
    // NOTE: Do NOT LTTB-downsample basal data. LTTB selects points based on
    // rate value changes and would silently drop mode transitions (e.g., auto
    // -> sleep) when the rate doesn't change. We keep all points to preserve
    // accurate mode overlay coloring. The per-segment ReferenceArea rendering
    // naturally clips to the visible domain.
    return points;
  }, [pumpEvents]);

  const displayBolus = useMemo(() => {
    if (bolusData.length <= MAX_BOLUS_MARKERS) return bolusData;
    // Keep the largest boluses when there are too many markers
    return [...bolusData].sort((a, b) => b.units - a.units).slice(0, MAX_BOLUS_MARKERS);
  }, [bolusData]);

  // Compute which bolus types and basal modes are present (for legend)
  const bolusTypesPresent = useMemo(() => {
    const types = new Set<string>();
    for (const b of displayBolus) {
      if (b.isAutomated) types.add("auto_correction");
      else types.add("manual_bolus");
    }
    return types;
  }, [displayBolus]);

  const basalModesPresent = useMemo(() => {
    const modes = new Set<string>();
    for (const b of basalData) {
      const m = b.pumpActivityMode;
      if (m === "sleep") modes.add("sleep");
      else if (m === "exercise" || m === "activity") modes.add("exercise");
      else if (b.isAutomated) modes.add("automated");
      else modes.add("manual");
    }
    return modes;
  }, [basalData]);

  // Full time window for the selected period.
  // Depends on `data` so it recomputes with fresh Date.now() on refetch.
  const fullDomain = useMemo(() => {
    const now = Date.now();
    return [now - PERIOD_TO_MS[period], now] as [number, number];
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [period, data]);

  // When zoomed, use the zoom domain; otherwise show the full period
  const xDomain = zoomDomain ?? fullDomain;

  // Refs for zoom interaction state (declared early so callbacks can reference them)
  const gridElRef = useRef<Element | null>(null);
  const selectionStartRef = useRef<number | null>(null);
  // Keep current domain in a ref so pixelToTimestamp always reads the latest value
  const currentDomainRef = useRef(zoomDomain ?? fullDomain);
  currentDomainRef.current = zoomDomain ?? fullDomain;

  // Wrap setPeriod to reset zoom on period change
  const handlePeriodChange = useCallback(
    (p: ChartTimePeriod) => {
      setPeriod(p);
      setZoomDomain(null);
      setSelectionStart(null);
      setSelectionEnd(null);
      selectionStartRef.current = null;
      gridElRef.current = null; // Invalidate cached grid element
    },
    [setPeriod],
  );

  // Cache grid element ref + read domain from ref to avoid stale closures
  const pixelToTimestamp = useCallback(
    (clientX: number): number | null => {
      const el = chartAreaRef.current;
      if (!el) return null;
      if (!gridElRef.current || !gridElRef.current.isConnected) {
        gridElRef.current = el.querySelector(".recharts-cartesian-grid");
      }
      if (!gridElRef.current) return null;
      const rect = gridElRef.current.getBoundingClientRect();
      const domain = currentDomainRef.current;
      const fraction = Math.max(0, Math.min(1, (clientX - rect.left) / Math.max(1, rect.width)));
      return domain[0] + fraction * (domain[1] - domain[0]);
    },
    [], // Reads from refs -- no closure dependencies needed
  );

  // Extract clientX from either mouse or touch native events (with empty-touches guard)
  const getClientX = useCallback((event: React.SyntheticEvent): number | null => {
    const native = event?.nativeEvent;
    if (!native) return null;
    if ("touches" in native) {
      const te = native as TouchEvent;
      const touch = te.touches[0] ?? te.changedTouches?.[0];
      return touch?.clientX ?? null;
    }
    if ("clientX" in native) return (native as MouseEvent).clientX;
    return null;
  }, []);

  const handleChartMouseDown = useCallback(
    (_nextState: MouseHandlerDataParam, event: React.SyntheticEvent) => {
      const clientX = getClientX(event);
      if (clientX == null) return;
      const ts = pixelToTimestamp(clientX);
      if (ts != null) {
        selectionStartRef.current = ts;
        setSelectionStart(ts);
        setSelectionEnd(ts);
      }
    },
    [pixelToTimestamp, getClientX],
  );

  // FIX #3: Early return when not dragging avoids unnecessary work on every pixel move
  const handleChartMouseMove = useCallback(
    (_nextState: MouseHandlerDataParam, event: React.SyntheticEvent) => {
      if (selectionStartRef.current == null) return;
      const clientX = getClientX(event);
      if (clientX == null) return;
      const ts = pixelToTimestamp(clientX);
      if (ts != null) setSelectionEnd(ts);
    },
    [pixelToTimestamp, getClientX],
  );

  // Shared cleanup: finalize zoom selection and clear drag state
  const finalizeSelection = useCallback(
    (clientX: number | null) => {
      const startTs = selectionStartRef.current;
      if (startTs != null && clientX != null) {
        const endTs = pixelToTimestamp(clientX);
        if (endTs != null) {
          const full = currentDomainRef.current;
          const lo = Math.max(full[0], Math.min(startTs, endTs));
          const hi = Math.min(full[1], Math.max(startTs, endTs));
          if (hi - lo >= MIN_ZOOM_MS) {
            setZoomDomain([lo, hi]);
          }
        }
      }
      selectionStartRef.current = null;
      setSelectionStart(null);
      setSelectionEnd(null);
    },
    [pixelToTimestamp],
  );

  const handleChartMouseUp = useCallback(
    (_nextState: MouseHandlerDataParam, event: React.SyntheticEvent) => {
      finalizeSelection(getClientX(event));
    },
    [finalizeSelection, getClientX],
  );

  // Global window listener: clear drag-selection if pointer-up occurs outside chart
  useEffect(() => {
    if (selectionStartRef.current == null) return;
    const onWindowUp = (e: MouseEvent | TouchEvent) => {
      const touch = "changedTouches" in e ? e.changedTouches[0] : null;
      const clientX = touch ? touch.clientX : "clientX" in e ? e.clientX : null;
      finalizeSelection(clientX);
    };
    window.addEventListener("mouseup", onWindowUp);
    window.addEventListener("touchend", onWindowUp);
    return () => {
      window.removeEventListener("mouseup", onWindowUp);
      window.removeEventListener("touchend", onWindowUp);
    };
  }, [finalizeSelection, selectionStart]);

  const handleChartDoubleClick = useCallback(
    (_nextState: MouseHandlerDataParam, _event: React.SyntheticEvent) => {
      setZoomDomain(null);
    },
    [],
  );

  // FIX #7: Disable tooltip during drag selection to avoid interference
  const isDragging = selectionStart != null;

  // Y-axis domain: show reasonable range, expand to fit data
  const yDomain = useMemo(() => {
    if (data.length === 0) return [40, 300];
    let min = data[0].value;
    let max = data[0].value;
    for (const d of data) {
      if (d.value < min) min = d.value;
      if (d.value > max) max = d.value;
    }
    return [Math.min(40, min - 10), Math.max(300, max + 10)];
  }, [data]);

  // Bolus scatter data with y-position for chart rendering
  // Memoized to avoid recreating array on every render (adversarial fix #1)
  const bolusScatterData = useMemo(() => {
    // Place bolus markers at 95% of the y-range to avoid overlapping glucose dots
    const yOffset = (yDomain[1] - yDomain[0]) * 0.05;
    const bolusY = yDomain[1] - yOffset;
    return displayBolus.map((b) => ({ ...b, value: bolusY }));
  }, [displayBolus, yDomain]);

  // Insulin Y-axis domain for basal area (right side)
  const insulinDomain = useMemo(() => {
    if (basalData.length === 0) return [0, 3];
    const maxRate = basalData.reduce((m, b) => Math.max(m, b.rate), 0);
    // Scale so basal occupies roughly bottom 25% of chart
    return [0, Math.max(3, maxRate * 4)];
  }, [basalData]);

  // Loading skeleton
  if (isLoading && data.length === 0) {
    return (
      <div
        className={clsx(
          "bg-white dark:bg-slate-900 rounded-xl p-6 border border-slate-200 dark:border-slate-800",
          className
        )}
        role="region"
        aria-label="Loading glucose trend chart"
        aria-busy="true"
        data-testid="glucose-trend-chart"
      >
        <div className="flex items-center justify-between mb-4">
          <div className="h-6 w-40 bg-slate-700 rounded animate-pulse" />
          <div className="h-8 w-48 bg-slate-700 rounded animate-pulse" />
        </div>
        <div className="h-64 bg-slate-100 dark:bg-slate-800 rounded animate-pulse" />
      </div>
    );
  }

  // Error state
  if (error && data.length === 0) {
    return (
      <div
        className={clsx(
          "bg-white dark:bg-slate-900 rounded-xl p-6 border border-slate-200 dark:border-slate-800",
          className
        )}
        role="region"
        aria-label="Glucose trend chart"
        data-testid="glucose-trend-chart"
      >
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-200">
            Glucose Trend
          </h2>
          <PeriodSelector selected={period} onSelect={handlePeriodChange} />
        </div>
        <div className="h-64 flex flex-col items-center justify-center text-slate-500 dark:text-slate-400 gap-3">
          <p>Unable to load glucose history</p>
          <button
            type="button"
            onClick={refetch}
            className="px-4 py-2 text-sm font-medium rounded-lg bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-700 hover:text-white transition-colors"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  // Empty state
  if (data.length === 0) {
    return (
      <div
        className={clsx(
          "bg-white dark:bg-slate-900 rounded-xl p-6 border border-slate-200 dark:border-slate-800",
          className
        )}
        role="region"
        aria-label="Glucose trend chart"
        data-testid="glucose-trend-chart"
      >
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-200">
            Glucose Trend
          </h2>
          <PeriodSelector selected={period} onSelect={handlePeriodChange} />
        </div>
        <div className="h-64 flex items-center justify-center text-slate-500 dark:text-slate-400">
          <p>No glucose readings yet</p>
        </div>
      </div>
    );
  }

  const lowThreshold = thresholds?.low ?? GLUCOSE_THRESHOLDS.LOW;
  const highThreshold = thresholds?.high ?? GLUCOSE_THRESHOLDS.HIGH;
  const targetLabel = `${lowThreshold}-${highThreshold} Target`;

  return (
    <div
      className={clsx(
        "bg-white dark:bg-slate-900 rounded-xl p-6 border border-slate-200 dark:border-slate-800",
        className
      )}
      role="region"
      aria-label={`Glucose trend chart, ${period} view`}
      data-testid="glucose-trend-chart"
    >
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-200">Glucose Trend</h2>
          {zoomDomain ? (
            <button
              type="button"
              onClick={() => setZoomDomain(null)}
              className="flex items-center gap-1 px-2 py-1 text-xs text-slate-500 dark:text-slate-400 hover:text-white bg-slate-100 dark:bg-slate-800 hover:bg-slate-700 rounded-md transition-colors"
              aria-label="Reset zoom"
            >
              <ZoomOut size={14} /> Reset Zoom
            </button>
          ) : (
            <span className="flex items-center gap-1 text-xs text-slate-500 dark:text-slate-400">
              <ZoomIn size={12} /> Drag chart to zoom
            </span>
          )}
        </div>
        <PeriodSelector selected={period} onSelect={handlePeriodChange} />
      </div>

      {/* Chart -- crosshair cursor signals drag-to-zoom */}
      <div ref={chartAreaRef} className={clsx("h-64 md:h-72 lg:h-80", isDragging ? "cursor-col-resize" : "cursor-crosshair")}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart
            margin={{ top: 10, right: 10, bottom: 0, left: -10 }}
            onMouseDown={handleChartMouseDown}
            onMouseMove={handleChartMouseMove}
            onMouseUp={handleChartMouseUp}
            onDoubleClick={handleChartDoubleClick}
            onTouchStart={handleChartMouseDown}
            onTouchMove={handleChartMouseMove}
            onTouchEnd={handleChartMouseUp}
          >
            <CartesianGrid
              stroke="#334155"
              strokeDasharray="3 3"
              vertical={false}
            />

            {/* Target range band */}
            <ReferenceArea
              yAxisId="glucose"
              y1={lowThreshold}
              y2={highThreshold}
              fill="#22c55e"
              fillOpacity={0.08}
              stroke="none"
            />

            <XAxis
              dataKey="timestamp"
              type="number"
              domain={xDomain}
              allowDataOverflow={!!zoomDomain}
              tickFormatter={(v: number) => formatXTick(v, multiDay)}
              tick={{ fill: "#94a3b8", fontSize: 12 }}
              axisLine={{ stroke: "#475569" }}
              tickLine={{ stroke: "#475569" }}
              allowDuplicatedCategory={false}
            />
            <YAxis
              yAxisId="glucose"
              dataKey="value"
              type="number"
              domain={yDomain}
              tick={{ fill: "#94a3b8", fontSize: 12 }}
              axisLine={{ stroke: "#475569" }}
              tickLine={{ stroke: "#475569" }}
            />
            <YAxis
              yAxisId="insulin"
              orientation="right"
              domain={insulinDomain}
              hide
            />

            {/* Mode overlay bands -- full-height colored bands for sleep/exercise modes */}
            {basalData.map((b, i) => {
              const m = b.pumpActivityMode;
              if (m !== "sleep" && m !== "exercise" && m !== "activity") return null;
              const nextTs = i + 1 < basalData.length ? basalData[i + 1].timestamp : xDomain[1];
              const color = m === "sleep" ? MODE_COLORS.sleep : MODE_COLORS.exercise;
              return (
                <ReferenceArea
                  key={`mode-${b.timestamp}`}
                  yAxisId="glucose"
                  x1={b.timestamp}
                  x2={nextTs}
                  y1={yDomain[0]}
                  y2={yDomain[1]}
                  fill={color}
                  fillOpacity={0.06}
                  stroke="none"
                />
              );
            })}

            {/* Basal rate segments -- color-coded by pump mode */}
            {basalData.map((b, i) => {
              const nextTs = i + 1 < basalData.length ? basalData[i + 1].timestamp : xDomain[1];
              const color = getBasalModeColor(b.pumpActivityMode, b.isAutomated);
              return (
                <ReferenceArea
                  key={`basal-${b.timestamp}`}
                  yAxisId="insulin"
                  x1={b.timestamp}
                  x2={nextTs}
                  y1={0}
                  y2={b.rate}
                  fill={color}
                  fillOpacity={0.15}
                  stroke={color}
                  strokeOpacity={0.6}
                  strokeWidth={1}
                />
              );
            })}

            {/* Glucose scatter points -- smaller dots for multi-day views */}
            <Scatter yAxisId="glucose" data={data} shape="circle" isAnimationActive={false}>
              {data.map((entry, index) => (
                <Cell key={`cell-${index}`} fill={entry.color} r={multiDay ? 2 : 4} />
              ))}
            </Scatter>

            {/* Bolus markers as hoverable scatter points near chart top */}
            {bolusScatterData.length > 0 && (
              <Scatter
                yAxisId="glucose"
                data={bolusScatterData}
                shape={renderBolusMarker}
                isAnimationActive={false}
              />
            )}

            {/* Drag-select zoom overlay */}
            {selectionStart != null && selectionEnd != null && (
              <ReferenceArea
                yAxisId="glucose"
                x1={Math.min(selectionStart, selectionEnd)}
                x2={Math.max(selectionStart, selectionEnd)}
                fill="#3b82f6"
                fillOpacity={0.15}
                stroke="#3b82f6"
                strokeOpacity={0.4}
              />
            )}

            <Tooltip
              content={isDragging ? () => null : <ChartTooltip multiDay={multiDay} />}
              cursor={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      {/* Brush slider for zoom pan */}
      <BrushSlider
        fullDomain={fullDomain}
        zoomDomain={zoomDomain}
        onZoomChange={setZoomDomain}
      />

      {/* Legend */}
      <div className="flex flex-wrap items-center justify-center gap-4 mt-3 text-xs text-slate-500 dark:text-slate-400">
        <span className="flex items-center gap-1">
          <span
            className="w-2 h-2 rounded-full bg-green-500 inline-block"
            aria-hidden="true"
          />
          {targetLabel}
        </span>
        <span className="flex items-center gap-1">
          <span
            className="w-2 h-2 rounded-full bg-amber-500 inline-block"
            aria-hidden="true"
          />
          High/Low
        </span>
        <span className="flex items-center gap-1">
          <span
            className="w-2 h-2 rounded-full bg-red-600 inline-block"
            aria-hidden="true"
          />
          Urgent
        </span>
        {/* Bolus type legend entries */}
        {bolusTypesPresent.has("auto_correction") && (
          <span className="flex items-center gap-1">
            <svg width="10" height="10" aria-hidden="true" className="inline-block">
              <polygon points="5,0 10,5 5,10 0,5" fill="#3b82f6" />
            </svg>
            Auto Correction
          </span>
        )}
        {bolusTypesPresent.has("manual_bolus") && (
          <span className="flex items-center gap-1">
            <span
              className="w-2.5 h-2.5 rounded-full inline-block"
              style={{ backgroundColor: "#8b5cf6" }}
              aria-hidden="true"
            />
            Manual Bolus
          </span>
        )}
        {/* Basal mode legend entries */}
        {basalModesPresent.has("automated") && (
          <span className="flex items-center gap-1">
            <span
              className="w-3 h-2 inline-block"
              style={{ backgroundColor: hexToRgba(MODE_COLORS.automated, 0.15), border: `1px solid ${MODE_COLORS.automated}` }}
              aria-hidden="true"
            />
            Automated
          </span>
        )}
        {basalModesPresent.has("manual") && (
          <span className="flex items-center gap-1">
            <span
              className="w-3 h-2 inline-block"
              style={{ backgroundColor: hexToRgba(MODE_COLORS.manual, 0.15), border: `1px solid ${MODE_COLORS.manual}` }}
              aria-hidden="true"
            />
            Manual
          </span>
        )}
        {basalModesPresent.has("sleep") && (
          <span className="flex items-center gap-1">
            <span
              className="w-3 h-2 inline-block"
              style={{ backgroundColor: hexToRgba(MODE_COLORS.sleep, 0.15), border: `1px solid ${MODE_COLORS.sleep}` }}
              aria-hidden="true"
            />
            Sleep
          </span>
        )}
        {basalModesPresent.has("exercise") && (
          <span className="flex items-center gap-1">
            <span
              className="w-3 h-2 inline-block"
              style={{ backgroundColor: hexToRgba(MODE_COLORS.exercise, 0.15), border: `1px solid ${MODE_COLORS.exercise}` }}
              aria-hidden="true"
            />
            Activity
          </span>
        )}
      </div>
    </div>
  );
}

export default GlucoseTrendChart;
