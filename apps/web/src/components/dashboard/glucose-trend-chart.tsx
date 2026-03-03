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
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceArea,
  ReferenceLine,
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
}

function transformReadings(
  readings: GlucoseHistoryReading[],
  thresholds?: { urgentLow: number; low: number; high: number; urgentHigh: number }
): ChartPoint[] {
  const sorted = readings
    .map((r) => ({
      timestamp: new Date(r.reading_timestamp).getTime(),
      value: r.value,
      color: getPointColor(r.value, thresholds),
      iso: r.reading_timestamp,
    }))
    .sort((a, b) => a.timestamp - b.timestamp);

  // Apply LTTB downsampling for large datasets (multi-day views)
  return lttbDownsample(sorted, MAX_CHART_POINTS);
}

// --- Pump event data transformations ---

interface BolusPoint {
  timestamp: number;
  units: number;
  isAutomated: boolean;
  isCorrection: boolean;
  label: string;
}

interface BasalPoint {
  timestamp: number;
  rate: number;
  value: number; // alias for rate -- LTTB compatibility
}

function transformBolusEvents(events: PumpEventReading[]): BolusPoint[] {
  return events
    .filter((e) => (e.event_type === "bolus" || e.event_type === "correction") && e.units != null && e.units > 0)
    .map((e) => ({
      timestamp: new Date(e.event_timestamp).getTime(),
      units: e.units!,
      isAutomated: e.is_automated,
      isCorrection: e.event_type === "correction",
      label: `${e.units!.toFixed(1)}u`,
    }))
    .sort((a, b) => a.timestamp - b.timestamp);
}

function transformBasalEvents(events: PumpEventReading[]): BasalPoint[] {
  return events
    .filter((e) => e.event_type === "basal" && e.units != null)
    .map((e) => ({
      timestamp: new Date(e.event_timestamp).getTime(),
      rate: e.units!,
      value: e.units!, // LTTB needs `value`
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

  // Basal data point (has `rate` field)
  if ("rate" in point && typeof point.rate === "number") {
    return (
      <div className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm shadow-lg">
        <p className="font-semibold text-blue-400">
          Basal: {point.rate.toFixed(2)} u/hr
        </p>
        <p className="text-slate-400 text-xs">{formatTime(point.timestamp as number)}</p>
      </div>
    );
  }

  // Glucose data point (has `iso` and `value` fields)
  if (!point.iso || typeof point.value !== "number") return null;
  return (
    <div className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm shadow-lg">
      <p className="font-semibold" style={{ color: point.color as string }}>
        {point.value} mg/dL
      </p>
      <p className="text-slate-400 text-xs">{formatTime(point.iso as string)}</p>
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
      className="flex gap-1 bg-slate-800 rounded-lg p-1"
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
              ? "bg-slate-700 text-white"
              : "text-slate-400 hover:text-slate-200"
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

  useEffect(() => {
    if (!dragType) return;

    const onMove = (e: MouseEvent | TouchEvent) => {
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
      className="relative h-6 mt-2 bg-slate-800 rounded select-none"
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
        {/* Left handle -- FIX #9: 16px touch target via padding, 8px visual */}
        <div
          className="absolute left-0 top-0 h-full w-4 flex justify-start"
          style={{ cursor: "col-resize", marginLeft: "-4px" }}
          onMouseDown={(e) => handlePointerDown("left", e)}
          onTouchStart={(e) => handlePointerDown("left", e)}
        >
          <div className="h-full w-2 bg-slate-400 rounded-l-sm hover:bg-slate-300 transition-colors" />
        </div>
        {/* Right handle -- FIX #9: 16px touch target via padding, 8px visual */}
        <div
          className="absolute right-0 top-0 h-full w-4 flex justify-end"
          style={{ cursor: "col-resize", marginRight: "-4px" }}
          onMouseDown={(e) => handlePointerDown("right", e)}
          onTouchStart={(e) => handlePointerDown("right", e)}
        >
          <div className="h-full w-2 bg-slate-400 rounded-r-sm hover:bg-slate-300 transition-colors" />
        </div>
      </div>
    </div>
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
    // Downsample basal for multi-day views to avoid SVG overload
    return lttbDownsample(points, MAX_CHART_POINTS);
  }, [pumpEvents]);

  const displayBolus = useMemo(() => {
    if (bolusData.length <= MAX_BOLUS_MARKERS) return bolusData;
    // Keep the largest boluses when there are too many markers
    return [...bolusData].sort((a, b) => b.units - a.units).slice(0, MAX_BOLUS_MARKERS);
  }, [bolusData]);

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

  // Compute final zoom from refs + event directly to avoid stale closure issues
  const handleChartMouseUp = useCallback(
    (_nextState: MouseHandlerDataParam, event: React.SyntheticEvent) => {
      const startTs = selectionStartRef.current;
      if (startTs != null) {
        const clientX = getClientX(event);
        const endTs = clientX != null ? pixelToTimestamp(clientX) : null;
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
    [pixelToTimestamp, getClientX],
  );

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
          "bg-slate-900 rounded-xl p-6 border border-slate-800",
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
        <div className="h-64 bg-slate-800 rounded animate-pulse" />
      </div>
    );
  }

  // Error state
  if (error && data.length === 0) {
    return (
      <div
        className={clsx(
          "bg-slate-900 rounded-xl p-6 border border-slate-800",
          className
        )}
        role="region"
        aria-label="Glucose trend chart"
        data-testid="glucose-trend-chart"
      >
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-slate-200">
            Glucose Trend
          </h2>
          <PeriodSelector selected={period} onSelect={handlePeriodChange} />
        </div>
        <div className="h-64 flex flex-col items-center justify-center text-slate-500 gap-3">
          <p>Unable to load glucose history</p>
          <button
            type="button"
            onClick={refetch}
            className="px-4 py-2 text-sm font-medium rounded-lg bg-slate-800 text-slate-300 hover:bg-slate-700 hover:text-white transition-colors"
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
          "bg-slate-900 rounded-xl p-6 border border-slate-800",
          className
        )}
        role="region"
        aria-label="Glucose trend chart"
        data-testid="glucose-trend-chart"
      >
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-slate-200">
            Glucose Trend
          </h2>
          <PeriodSelector selected={period} onSelect={handlePeriodChange} />
        </div>
        <div className="h-64 flex items-center justify-center text-slate-500">
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
        "bg-slate-900 rounded-xl p-6 border border-slate-800",
        className
      )}
      role="region"
      aria-label={`Glucose trend chart, ${period} view`}
      data-testid="glucose-trend-chart"
    >
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <h2 className="text-lg font-semibold text-slate-200">Glucose Trend</h2>
          {zoomDomain ? (
            <button
              type="button"
              onClick={() => setZoomDomain(null)}
              className="flex items-center gap-1 px-2 py-1 text-xs text-slate-400 hover:text-white bg-slate-800 hover:bg-slate-700 rounded-md transition-colors"
              aria-label="Reset zoom"
            >
              <ZoomOut size={14} /> Reset Zoom
            </button>
          ) : (
            <span className="flex items-center gap-1 text-xs text-slate-500">
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

            {/* Basal rate area (bottom portion of chart) */}
            {basalData.length > 0 && (
              <Area
                yAxisId="insulin"
                data={basalData}
                dataKey="rate"
                type="stepAfter"
                fill="rgba(59,130,246,0.15)"
                stroke="rgb(59,130,246)"
                strokeWidth={1}
                dot={false}
                isAnimationActive={false}
              />
            )}

            {/* Glucose scatter points -- smaller dots for multi-day views */}
            <Scatter yAxisId="glucose" data={data} shape="circle" isAnimationActive={false}>
              {data.map((entry, index) => (
                <Cell key={`cell-${index}`} fill={entry.color} r={multiDay ? 2 : 4} />
              ))}
            </Scatter>

            {/* Bolus delivery markers (capped for multi-day readability) */}
            {displayBolus.map((b, i) => (
              <ReferenceLine
                key={`bolus-${b.timestamp}-${i}`}
                yAxisId="glucose"
                x={b.timestamp}
                stroke={b.isCorrection ? "#3b82f6" : "#8b5cf6"}
                strokeDasharray="4 3"
                strokeWidth={1.5}
                label={{
                  value: b.label,
                  position: "top",
                  fill: b.isCorrection ? "#3b82f6" : "#8b5cf6",
                  fontSize: 10,
                  fontWeight: 600,
                }}
              />
            ))}

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
      <div className="flex flex-wrap items-center justify-center gap-4 mt-3 text-xs text-slate-500">
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
        {displayBolus.length > 0 && (
          <span className="flex items-center gap-1">
            <span
              className="w-3 h-0 border-t-2 border-dashed border-violet-500 inline-block"
              aria-hidden="true"
            />
            Bolus
          </span>
        )}
        {basalData.length > 0 && (
          <span className="flex items-center gap-1">
            <span
              className="w-3 h-2 bg-blue-500/20 border border-blue-500 inline-block"
              aria-hidden="true"
            />
            Basal
          </span>
        )}
      </div>
    </div>
  );
}

export default GlucoseTrendChart;
