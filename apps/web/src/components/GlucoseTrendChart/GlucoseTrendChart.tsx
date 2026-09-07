"use client";

import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";
import uPlot from "uplot";
import { Button } from "@/base/Button";
import { Icon } from "@/base/Icon";
import type { GlucoseHistoryReading } from "@/lib/api";
import { type ChartTimePeriod, PERIOD_TO_MS } from "@/lib/chart-periods";
import { serializeTimeRangeClipboardValue } from "@/lib/glucose/time-range-clipboard";
import { getSelectionKey } from "@/lib/glucose/history-selection";
import {
  formatGlucose,
  mgdlToMmol,
  mmolToMgdl,
  unitLabel,
  type GlucoseUnit,
} from "@/lib/glucose-units";
import {
  classifyGlucose,
  isValidGlucoseMgdl,
  normalizeGlucoseThresholds,
  type GlucoseThresholds,
} from "@/lib/glucose-classification";
import { twMerge } from "@/lib/ui/twMerge";
import { useGlucoseHistory } from "@/hooks/use-glucose-history";
import { usePumpEvents } from "@/hooks/use-pump-events";
import {
  useBolusReview,
  type BolusReviewPeriod,
} from "@/hooks/use-bolus-review";
import { useOptionalDashboardTimeRange } from "@/components/DashboardTimeRangeProvider";
import {
  TREND_ARROWS,
  TREND_DESCRIPTIONS,
  type TrendDirection,
} from "@/components/TrendArrow";
import { mapBackendTrendToFrontend } from "@/hooks/use-glucose-stream";
import {
  CHART_Y_AXIS_SIZE_PX,
  drawAlternatingDayBands,
  formatSharedTimeTick,
  getSharedTimeSplits,
} from "@/lib/charts/chart-axis";
import {
  getContinuousGlucosePairs,
  getIsolatedGlucosePoints,
} from "@/lib/charts/glucose-continuity";
import {
  resolveChartPalette,
  type ChartPalette,
} from "@/lib/charts/chart-theme";
import { ChartLegendSwatch } from "@/components/ChartLegendSwatch";
import { ChartSectionHeader } from "@/components/ChartSectionHeader";
import {
  GlucoseForecastLegend,
  buildGlucoseForecastPoints,
  getForecastEndMs,
  isForecastOverlayEligible,
  type GlucoseForecastPoint,
} from "@/components/GlucoseForecast";
import {
  getDoseLabel,
  getDoseSwatchClassName,
  getDoseUnits,
  InsulinOnBoardTimeline,
  InsulinDoseTimeline,
  PumpActivityModeTimeline,
  PumpBasalRateTimeline,
} from "@/components/InsulinTimeline/ExpandedInsulinTimeline";
import type {
  ExpandedTimelineHover,
  InsulinDoseEvent,
} from "@/components/InsulinTimeline/ExpandedInsulinTimeline.types";
import {
  normalizeInsulinDoseTimeline,
  normalizeInsulinOnBoardTimeline,
  normalizePumpTimeline,
  type InsulinOnBoardSample,
} from "@/components/InsulinTimeline/insulin-timeline-data";
import {
  createChartZoomInteraction,
  finishChartZoomSelection,
  type ChartZoomChangeHandler,
  updateLocalHorizontalCursor,
} from "@/lib/charts/chart-zoom";
import styles from "./GlucoseTrendChart.module.css";
import type { GlucoseTrendChartProps } from "./GlucoseTrendChart.types";

const CHART_TARGET_COLOR = "var(--color-signal-check-fill)";
const CHART_WARNING_COLOR = "var(--color-signal-warning-fill)";
const CHART_ERROR_COLOR = "var(--color-signal-error-fill)";
const DEFAULT_Y_DOMAIN: [number, number] = [40, 300];
const AUTO_LINE_MIN_POINT_SPACING_PX = 5;
const POINT_RADIUS = 3;
const LINE_WIDTH = 2;
const HOVER_TIMESTAMP_TOLERANCE_MS = 3 * 60 * 1000;
const MULTI_DAY_MIN_DURATION_MS = 3 * 24 * 60 * 60 * 1000;

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

function getInsulinPeriod(period: ChartTimePeriod): BolusReviewPeriod {
  switch (period) {
    case "3d":
      return "3d";
    case "7d":
      return "7d";
    case "14d":
      return "14d";
    case "30d":
      return "30d";
    default:
      return "24h";
  }
}

interface ChartPoint {
  timestamp: number;
  value: number;
  trend: TrendDirection;
  trendRate: number | null;
}

export interface GlucoseLinePoint {
  x: number;
  y: number;
  value: number;
}

export interface GlucoseLineSegment {
  from: GlucoseLinePoint;
  to: GlucoseLinePoint;
  value: number;
}

interface RangeStatus {
  label: string;
  swatchClassName: string;
}

interface GlucoseTimelineHover {
  timestamp: number;
  point: ChartPoint | null;
}

interface CombinedTimelineHover {
  timestamp: number;
  glucose: ChartPoint | null;
  doses: InsulinDoseEvent[];
  insulinOnBoardSample: InsulinOnBoardSample | null;
}

interface UplotGlucoseTrendProps {
  ariaLabel: string;
  cursorSyncKey: string;
  data: ChartPoint[];
  fadeTopAxis: boolean;
  forecastPoints: GlucoseForecastPoint[];
  xDomain: [number, number];
  yDomain: [number, number];
  urgentLowThreshold: number;
  lowThreshold: number;
  highThreshold: number;
  urgentHighThreshold: number;
  unit: GlucoseUnit;
  multiDay: boolean;
  showXAxis: boolean;
  onHoverChange: (hover: GlucoseTimelineHover | null) => void;
  onZoomChange: ChartZoomChangeHandler;
}

export function getPointColor(
  value: number,
  thresholds?: GlucoseThresholds,
): string {
  const range = classifyGlucose(value, normalizeGlucoseThresholds(thresholds));
  if (range === "urgentLow" || range === "urgentHigh") {
    return CHART_ERROR_COLOR;
  }
  if (range === "low" || range === "high") {
    return CHART_WARNING_COLOR;
  }
  return CHART_TARGET_COLOR;
}

function transformReadings(readings: GlucoseHistoryReading[]): ChartPoint[] {
  return readings
    .filter((reading) => isValidGlucoseMgdl(reading.value))
    .map((reading) => ({
      timestamp: new Date(reading.reading_timestamp).getTime(),
      value: reading.value,
      trend: mapBackendTrendToFrontend(reading.trend),
      trendRate: reading.trend_rate,
    }))
    .filter((point) => Number.isFinite(point.timestamp))
    .sort((a, b) => a.timestamp - b.timestamp);
}

function resolveRenderMode(
  dataLength: number,
  width: number,
): "line" | "points" {
  if (
    dataLength > Math.max(1, Math.floor(width / AUTO_LINE_MIN_POINT_SPACING_PX))
  ) {
    return "line";
  }

  return "points";
}

function interpolateLinePoint(
  from: GlucoseLinePoint,
  to: GlucoseLinePoint,
  t: number,
): GlucoseLinePoint {
  return {
    x: from.x + (to.x - from.x) * t,
    y: from.y + (to.y - from.y) * t,
    value: from.value + (to.value - from.value) * t,
  };
}

export function getGlucoseLineSegments(
  points: GlucoseLinePoint[],
  urgentLowThreshold: number,
  lowThreshold: number,
  highThreshold: number,
  urgentHighThreshold: number,
): GlucoseLineSegment[] {
  const segments: GlucoseLineSegment[] = [];

  for (const [from, to] of getContinuousGlucosePairs(
    points,
    (point) => point.x * 1000,
  )) {
    if (
      !Number.isFinite(from.x) ||
      !Number.isFinite(from.y) ||
      !Number.isFinite(to.x) ||
      !Number.isFinite(to.y)
    ) {
      continue;
    }

    const valueDelta = to.value - from.value;
    const crossings =
      valueDelta === 0
        ? []
        : [
            urgentLowThreshold,
            lowThreshold,
            highThreshold,
            urgentHighThreshold,
          ]
            .filter(
              (threshold) =>
                (from.value < threshold && to.value > threshold) ||
                (from.value > threshold && to.value < threshold),
            )
            .map((threshold) => (threshold - from.value) / valueDelta)
            .filter((t) => t > 0 && t < 1)
            .sort((a, b) => a - b);

    const breakpoints = [0, ...crossings, 1];

    for (
      let breakpointIndex = 0;
      breakpointIndex < breakpoints.length - 1;
      breakpointIndex += 1
    ) {
      const fromT = breakpoints[breakpointIndex];
      const toT = breakpoints[breakpointIndex + 1];
      const midpointT = fromT + (toT - fromT) / 2;

      segments.push({
        from: interpolateLinePoint(from, to, fromT),
        to: interpolateLinePoint(from, to, toT),
        value: interpolateLinePoint(from, to, midpointT).value,
      });
    }
  }

  return segments;
}

function getPointCanvasColor(
  value: number,
  thresholds: GlucoseThresholds,
  palette: ChartPalette,
): string {
  const range = classifyGlucose(value, thresholds);
  if (range === "urgentLow" || range === "urgentHigh") return palette.error;
  if (range === "low" || range === "high") return palette.warning;
  return palette.target;
}

function getRangeStatus(
  value: number,
  thresholds: GlucoseThresholds,
  unit: GlucoseUnit,
): RangeStatus {
  const range = classifyGlucose(value, thresholds);
  if (range === "urgentLow" || range === "urgentHigh") {
    return {
      label: "Urgent",
      swatchClassName:
        "border border-signal-error-fill bg-signal-error-fill/15",
    };
  }

  if (range === "low" || range === "high") {
    return {
      label: "High/Low",
      swatchClassName:
        "border border-signal-warning-fill bg-signal-warning-fill/15",
    };
  }

  return {
    label: `${formatGlucose(thresholds.low, unit)}-${formatGlucose(thresholds.high, unit)} ${unitLabel(unit)} Target`,
    swatchClassName: "border border-signal-check-fill bg-signal-check-fill/15",
  };
}

function GlucoseRangeLegend({
  forecast,
  forecastEligible,
  forecastPoints,
  highThreshold,
  lowThreshold,
  unit,
  urgentHighThreshold,
  urgentLowThreshold,
}: {
  forecast: GlucoseTrendChartProps["forecast"];
  forecastEligible: boolean;
  forecastPoints: readonly GlucoseForecastPoint[];
  highThreshold: number;
  lowThreshold: number;
  unit: GlucoseUnit;
  urgentHighThreshold: number;
  urgentLowThreshold: number;
}) {
  const high = formatGlucose(highThreshold, unit);
  const low = formatGlucose(lowThreshold, unit);
  const urgentHigh = formatGlucose(urgentHighThreshold, unit);
  const urgentLow = formatGlucose(urgentLowThreshold, unit);

  return (
    <span
      className="flex flex-wrap items-center gap-3"
      aria-label="Glucose range legend"
      role="group"
    >
      <span className="inline-flex items-center gap-1.5">
        <ChartLegendSwatch className="border border-signal-check-fill bg-signal-check-fill/15" />
        Target {low} to {high}
      </span>
      <span className="inline-flex items-center gap-1.5">
        <ChartLegendSwatch className="border border-signal-warning-fill bg-signal-warning-fill/15" />
        High {">"} {high} / Low {"<"} {low}
      </span>
      <span className="inline-flex items-center gap-1.5">
        <ChartLegendSwatch className="border border-signal-error-fill bg-signal-error-fill/15" />
        Urgent high {">"} {urgentHigh} / Urgent low {"<"} {urgentLow}
      </span>
      <GlucoseForecastLegend
        eligible={forecastEligible}
        forecast={forecast}
        points={forecastPoints}
      />
    </span>
  );
}

function drawTargetRange(
  chart: uPlot,
  lowThreshold: number,
  highThreshold: number,
  palette: ChartPalette,
): void {
  const yLow = chart.valToPos(lowThreshold, "y", true);
  const yHigh = chart.valToPos(highThreshold, "y", true);
  const top = Math.min(yHigh, yLow);
  const height = Math.abs(yLow - yHigh);

  if (height <= 0) {
    return;
  }

  chart.ctx.save();
  chart.ctx.globalAlpha = 0.08;
  chart.ctx.fillStyle = palette.target;
  chart.ctx.fillRect(chart.bbox.left, top, chart.bbox.width, height);
  chart.ctx.restore();
}

function drawThresholdLines(
  chart: uPlot,
  lowThreshold: number,
  highThreshold: number,
  palette: ChartPalette,
): void {
  const left = chart.bbox.left;
  const right = chart.bbox.left + chart.bbox.width;

  chart.ctx.save();
  chart.ctx.setLineDash([4, 4]);
  chart.ctx.lineWidth = 1;

  for (const threshold of [lowThreshold, highThreshold]) {
    const y = chart.valToPos(threshold, "y", true);
    chart.ctx.strokeStyle = palette.warning;
    chart.ctx.beginPath();
    chart.ctx.moveTo(left, y);
    chart.ctx.lineTo(right, y);
    chart.ctx.stroke();
  }

  chart.ctx.restore();
}

function drawGlucoseLineSegments(
  chart: uPlot,
  segments: GlucoseLineSegment[],
  thresholds: {
    urgentLow: number;
    low: number;
    high: number;
    urgentHigh: number;
  },
  palette: ChartPalette,
): void {
  const pixelRatio =
    typeof window === "undefined" ? 1 : window.devicePixelRatio || 1;

  chart.ctx.save();
  chart.ctx.lineCap = "round";
  chart.ctx.lineJoin = "round";
  chart.ctx.lineWidth = LINE_WIDTH * pixelRatio;

  for (const segment of segments) {
    const fromX = chart.valToPos(segment.from.x, "x", true);
    const fromY = chart.valToPos(segment.from.y, "y", true);
    const toX = chart.valToPos(segment.to.x, "x", true);
    const toY = chart.valToPos(segment.to.y, "y", true);

    if (
      !Number.isFinite(fromX) ||
      !Number.isFinite(fromY) ||
      !Number.isFinite(toX) ||
      !Number.isFinite(toY)
    ) {
      continue;
    }

    chart.ctx.strokeStyle = getPointCanvasColor(
      segment.value,
      thresholds,
      palette,
    );
    chart.ctx.beginPath();
    chart.ctx.moveTo(fromX, fromY);
    chart.ctx.lineTo(toX, toY);
    chart.ctx.stroke();
  }

  chart.ctx.restore();
}

function drawReadingPoints(
  chart: uPlot,
  points: readonly ChartPoint[],
  thresholds: {
    urgentLow: number;
    low: number;
    high: number;
    urgentHigh: number;
  },
  palette: ChartPalette,
): void {
  const pixelRatio =
    typeof window === "undefined" ? 1 : window.devicePixelRatio || 1;

  chart.ctx.save();

  for (const point of points) {
    const x = chart.valToPos(point.timestamp / 1000, "x", true);
    const y = chart.valToPos(point.value, "y", true);

    if (![x, y].every(Number.isFinite)) {
      continue;
    }

    chart.ctx.fillStyle = getPointCanvasColor(
      point.value,
      thresholds,
      palette,
    );
    chart.ctx.beginPath();
    chart.ctx.arc(x, y, POINT_RADIUS * pixelRatio, 0, Math.PI * 2);
    chart.ctx.fill();
  }

  chart.ctx.restore();
}

function drawForecastLine(
  chart: uPlot,
  points: readonly GlucoseForecastPoint[],
  palette: ChartPalette,
): void {
  if (points.length < 2) {
    return;
  }

  const pixelRatio =
    typeof window === "undefined" ? 1 : window.devicePixelRatio || 1;

  chart.ctx.save();
  chart.ctx.globalAlpha = 0.9;
  chart.ctx.lineCap = "round";
  chart.ctx.lineJoin = "round";
  chart.ctx.lineWidth = LINE_WIDTH * pixelRatio;
  chart.ctx.setLineDash([5 * pixelRatio, 4 * pixelRatio]);
  chart.ctx.strokeStyle = palette.glucoseForecast;
  chart.ctx.beginPath();

  points.forEach((point, index) => {
    const x = chart.valToPos(point.timestampMs / 1000, "x", true);
    const y = chart.valToPos(point.valueMgDl, "y", true);

    if (!Number.isFinite(x) || !Number.isFinite(y)) {
      return;
    }

    if (index === 0) {
      chart.ctx.moveTo(x, y);
    } else {
      chart.ctx.lineTo(x, y);
    }
  });

  chart.ctx.stroke();
  chart.ctx.restore();
}

function formatTooltipTime(timestamp: number, multiDay: boolean): string {
  const date = new Date(timestamp);

  if (multiDay) {
    return `${date.toLocaleDateString([], { month: "short", day: "numeric" })} ${date.toLocaleTimeString(
      [],
      {
        hour: "numeric",
        minute: "2-digit",
      },
    )}`;
  }

  return date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function PeriodSelector({
  selected,
  onSelect,
}: {
  selected: ChartTimePeriod;
  onSelect: (period: ChartTimePeriod) => void;
}) {
  return (
    <div
      className="flex w-full max-w-full gap-1 overflow-x-auto rounded-panel bg-surface-secondary p-1 sm:w-auto"
      role="group"
      aria-label="Time period"
    >
      {PERIODS.map(({ value, label }) => (
        <Button
          key={value}
          type="button"
          aria-pressed={selected === value}
          onClick={() => onSelect(value)}
          className={twMerge(
            "shrink-0 rounded-panel px-2.5 py-1 font_body_3 transition-colors sm:px-3",
            selected === value
              ? "bg-surface-tertiary text-foreground-primary"
              : "text-foreground-primary",
          )}
        >
          {label}
        </Button>
      ))}
    </div>
  );
}

function UplotGlucoseTrend({
  ariaLabel,
  cursorSyncKey,
  data,
  fadeTopAxis,
  forecastPoints,
  xDomain,
  yDomain,
  urgentLowThreshold,
  lowThreshold,
  highThreshold,
  urgentHighThreshold,
  unit,
  multiDay,
  showXAxis,
  onHoverChange,
  onZoomChange,
}: UplotGlucoseTrendProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<uPlot | null>(null);
  const dataRef = useRef(data);
  const onHoverChangeRef = useRef(onHoverChange);
  const onZoomChangeRef = useRef(onZoomChange);
  const [dimensions, setDimensions] = useState({ width: 0, height: 0 });
  const [themeRevision, setThemeRevision] = useState(0);

  useEffect(() => {
    dataRef.current = data;
    onHoverChangeRef.current = onHoverChange;
    onZoomChangeRef.current = onZoomChange;
  }, [data, onHoverChange, onZoomChange]);

  useEffect(() => {
    const element = containerRef.current;

    if (!element) {
      return undefined;
    }

    const updateDimensions = () => {
      const nextWidth = Math.floor(element.clientWidth);
      const nextHeight = Math.floor(element.clientHeight);

      if (nextWidth > 0 && nextHeight > 0) {
        setDimensions((current) =>
          current.width === nextWidth && current.height === nextHeight
            ? current
            : { width: nextWidth, height: nextHeight },
        );
      }
    };

    updateDimensions();

    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", updateDimensions);
      return () => window.removeEventListener("resize", updateDimensions);
    }

    const observer = new ResizeObserver(updateDimensions);
    observer.observe(element);

    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (typeof MutationObserver === "undefined") {
      return undefined;
    }

    const element = containerRef.current;
    if (!element) {
      return undefined;
    }

    let previousPaletteKey = JSON.stringify(resolveChartPalette(element));
    const observer = new MutationObserver(() => {
      const nextPaletteKey = JSON.stringify(resolveChartPalette(element));
      if (nextPaletteKey === previousPaletteKey) {
        return;
      }

      previousPaletteKey = nextPaletteKey;
      setThemeRevision((current) => current + 1);
    });

    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["class", "style"],
    });

    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const element = containerRef.current;

    if (!element || dimensions.width <= 0 || dimensions.height <= 0) {
      return undefined;
    }

    element.textContent = "";

    const xs = data.map((point) => point.timestamp / 1000);
    const ys = data.map((point) => point.value);
    const lineSegments = getGlucoseLineSegments(
      data.map((point) => ({
        x: point.timestamp / 1000,
        y: point.value,
        value: point.value,
      })),
      urgentLowThreshold,
      lowThreshold,
      highThreshold,
      urgentHighThreshold,
    );
    const effectiveRenderMode = resolveRenderMode(
      data.length,
      dimensions.width,
    );
    const readingPoints =
      effectiveRenderMode === "points"
        ? data
        : getIsolatedGlucosePoints(data, (point) => point.timestamp);
    const palette = resolveChartPalette(element);
    const thresholds = {
      urgentLow: urgentLowThreshold,
      low: lowThreshold,
      high: highThreshold,
      urgentHigh: urgentHighThreshold,
    };
    const options: uPlot.Options = {
      width: dimensions.width,
      height: dimensions.height,
      padding: [0, 0, 0, 0],
      legend: { show: false },
      ...createChartZoomInteraction(cursorSyncKey, true),
      scales: {
        x: {
          time: true,
          range: [xDomain[0] / 1000, xDomain[1] / 1000],
        },
        y: {
          range: yDomain,
        },
      },
      axes: [
        {
          show: true,
          size: showXAxis ? 40 : 0,
          gap: 0,
          stroke: showXAxis ? palette.tick : palette.transparent,
          grid: { stroke: palette.grid },
          ticks: showXAxis
            ? { show: true, stroke: palette.axis }
            : { show: false },
          splits: getSharedTimeSplits,
          values: (_chart, values) =>
            showXAxis
              ? values.map((value) => formatSharedTimeTick(value, multiDay))
              : [],
        },
        {
          size: CHART_Y_AXIS_SIZE_PX,
          stroke: palette.tick,
          grid: { stroke: palette.grid },
          ticks: { stroke: palette.axis },
          splits:
            unit === "mmol"
              ? (_chart, _axisIndex, scaleMin, scaleMax, increment) =>
                  getWholeMmolAxisSplits(scaleMin, scaleMax, increment)
              : undefined,
          values: (_chart, values) =>
            values.map((value) =>
              unit === "mmol"
                ? Math.round(mgdlToMmol(value)).toString()
                : formatGlucose(value, unit),
            ),
        },
      ],
      series: [
        {},
        {
          stroke: palette.transparent,
          width: 1,
          points: { show: false },
          spanGaps: false,
        },
      ],
      hooks: {
        drawClear: [
          (chart) => {
            if (multiDay) {
              drawAlternatingDayBands(chart, palette.surfaceSecondary);
            }
          },
        ],
        draw: [
          (chart) => {
            drawTargetRange(chart, lowThreshold, highThreshold, palette);
            drawGlucoseLineSegments(chart, lineSegments, thresholds, palette);
            drawForecastLine(chart, forecastPoints, palette);
            drawThresholdLines(chart, lowThreshold, highThreshold, palette);
            drawReadingPoints(
              chart,
              readingPoints,
              thresholds,
              palette,
            );
          },
        ],
        setCursor: [
          (chart) => {
            updateLocalHorizontalCursor(chart);
            const cursorLeft = chart.cursor.left;

            if (cursorLeft == null || cursorLeft < 0) {
              onHoverChangeRef.current(null);
              return;
            }

            const timestamp = chart.posToVal(cursorLeft, "x") * 1000;
            const index = chart.cursor.idx;
            const nearestPoint =
              typeof index === "number"
                ? (dataRef.current[index] ?? null)
                : null;
            const point =
              nearestPoint &&
              Math.abs(nearestPoint.timestamp - timestamp) <=
                HOVER_TIMESTAMP_TOLERANCE_MS
                ? nearestPoint
                : null;
            onHoverChangeRef.current({
              timestamp,
              point,
            });
          },
        ],
        setSelect: [
          (chart) => {
            const domain = finishChartZoomSelection(chart);
            if (domain) onZoomChangeRef.current(domain);
          },
        ],
        ready: [
          (chart) => {
            chart.over.addEventListener("dblclick", () => {
              onZoomChangeRef.current?.(null);
            });
          },
        ],
      },
    };

    const chart = new uPlot(options, [xs, ys], element);
    chartRef.current = chart;

    return () => {
      chartRef.current = null;
      chart.destroy();
    };
  }, [
    data,
    cursorSyncKey,
    dimensions.height,
    dimensions.width,
    forecastPoints,
    highThreshold,
    lowThreshold,
    multiDay,
    showXAxis,
    themeRevision,
    urgentHighThreshold,
    urgentLowThreshold,
    unit,
    xDomain,
    yDomain,
  ]);

  // TODO: Revisit keyboard timeline inspection if it becomes a product need.
  return (
    <div
      className="relative h-56 min-w-0 sm:h-64 md:h-72 lg:h-80"
      role="img"
      aria-label={ariaLabel}
    >
      <div
        ref={containerRef}
        aria-hidden="true"
        className={twMerge(
          styles.uplotFrame,
          fadeTopAxis && styles.yAxisTopFade,
          fadeTopAxis && styles.yAxisBottomFade,
          "h-full min-w-0 cursor-crosshair [&_.u-select]:bg-signal-info-fill/15 [&_.u-select]:border [&_.u-select]:border-signal-info-fill/40",
        )}
      />
    </div>
  );
}

export function getWholeMmolAxisSplits(
  scaleMin: number,
  scaleMax: number,
  incrementMgdl: number,
): number[] {
  if (!Number.isFinite(incrementMgdl) || incrementMgdl <= 0) {
    return [];
  }

  const incrementMmol = Math.max(1, Math.ceil(mgdlToMmol(incrementMgdl)));
  const scaleMinMmol = mgdlToMmol(scaleMin);
  const scaleMaxMmol = mgdlToMmol(scaleMax);
  const firstSplitMmol =
    Math.ceil(scaleMinMmol / incrementMmol) * incrementMmol;
  const splits: number[] = [];

  for (
    let value = firstSplitMmol;
    value <= scaleMaxMmol;
    value += incrementMmol
  ) {
    splits.push(mmolToMgdl(value));
  }

  return splits;
}

function resolveGlucoseYDomain(
  points: ChartPoint[],
  forecastPoints: readonly GlucoseForecastPoint[],
  lowThreshold: number,
  highThreshold: number,
): [number, number] {
  let min = Math.min(lowThreshold, highThreshold);
  let max = Math.max(lowThreshold, highThreshold);

  for (const point of points) {
    min = Math.min(min, point.value);
    max = Math.max(max, point.value);
  }

  for (const point of forecastPoints) {
    min = Math.min(min, point.valueMgDl);
    max = Math.max(max, point.valueMgDl);
  }

  return [
    Math.min(DEFAULT_Y_DOMAIN[0], min - 10),
    Math.max(DEFAULT_Y_DOMAIN[1], max + 10),
  ];
}

export function isMultiDayChartDomain(
  xDomain: readonly [number, number],
): boolean {
  return xDomain[1] - xDomain[0] >= MULTI_DAY_MIN_DURATION_MS;
}

/** Render glucose and insulin history with synchronized time bounds and persistent live zoom. */
export function GlucoseTrendChart({
  refreshKey,
  className,
  hasConfiguredPump = false,
  thresholds,
  forecast,
  unit = "mgdl",
  embedded = false,
}: GlucoseTrendChartProps) {
  const dashboardTimeRange = useOptionalDashboardTimeRange();
  const cursorSyncKey = useId();
  const { readings, isLoading, error, period, setPeriod, refetch } =
    useGlucoseHistory("3h", dashboardTimeRange?.currentWindow);
  const {
    data: insulinReview,
    isLoading: isInsulinLoading,
    error: insulinError,
    setPeriod: setInsulinPeriod,
    refetch: refetchInsulin,
  } = useBolusReview(
    getInsulinPeriod(period),
    dashboardTimeRange?.currentWindow,
    500,
  );
  const {
    events: pumpEvents,
    hasPumpHistory,
    isLoading: isPumpLoading,
    error: pumpError,
    isPossiblyTruncated,
    refetch: refetchPump,
  } = usePumpEvents(period, dashboardTimeRange?.currentWindow);
  const [zoomDomain, setZoomDomain] = useState<[number, number] | null>(null);
  const [copyError, setCopyError] = useState<string | null>(null);
  const [timelineHover, setTimelineHover] =
    useState<CombinedTimelineHover | null>(null);
  const prevRefreshKeyRef = useRef(refreshKey);
  const currentWindow = dashboardTimeRange?.currentWindow;
  const previousWindowRef = useRef(currentWindow);

  useEffect(() => {
    const windowChanged = currentWindow !== previousWindowRef.current;
    previousWindowRef.current = currentWindow;
    if (
      refreshKey !== undefined &&
      refreshKey > 0 &&
      refreshKey !== prevRefreshKeyRef.current
    ) {
      prevRefreshKeyRef.current = refreshKey;
      // History hooks already fetch when their window changes.
      if (windowChanged) return;
      refetch();
      refetchInsulin();
      refetchPump();
    }
  }, [refreshKey, currentWindow, refetch, refetchInsulin, refetchPump]);

  const rangeSelectionKey = dashboardTimeRange
    ? getSelectionKey(dashboardTimeRange.selection)
    : `period:${period}`;
  useEffect(() => {
    setZoomDomain(null);
    setCopyError(null);
    setTimelineHover(null);
  }, [rangeSelectionKey]);

  const data = useMemo(() => transformReadings(readings), [readings]);
  const doseTimelineData = useMemo(
    () => normalizeInsulinDoseTimeline(insulinReview?.boluses ?? []),
    [insulinReview?.boluses],
  );
  const pumpTimelineData = useMemo(
    () => normalizePumpTimeline(pumpEvents),
    [pumpEvents],
  );
  const insulinOnBoardSamples = useMemo(
    () => normalizeInsulinOnBoardTimeline(pumpEvents),
    [pumpEvents],
  );
  const doseEvents = useMemo<InsulinDoseEvent[]>(
    () => [
      ...doseTimelineData.rapidDoses,
      ...doseTimelineData.longActingBasalInjections,
    ],
    [doseTimelineData],
  );
  const latestReadingTimestamp =
    data.length > 0 ? data[data.length - 1].timestamp : 0;
  const baseFullDomain = useMemo<[number, number]>(() => {
    if (dashboardTimeRange?.currentWindow) {
      return [
        new Date(dashboardTimeRange.currentWindow.from).getTime(),
        new Date(dashboardTimeRange.currentWindow.to).getTime(),
      ];
    }

    const now = Math.max(Date.now(), latestReadingTimestamp);
    return [now - PERIOD_TO_MS[period], now];
  }, [dashboardTimeRange?.currentWindow, period, latestReadingTimestamp]);
  const forecastEligible = isForecastOverlayEligible(baseFullDomain);
  const forecastPoints = useMemo(
    () =>
      buildGlucoseForecastPoints({
        anchors: data.map((point) => ({
          timestampMs: point.timestamp,
          valueMgDl: point.value,
        })),
        domain: baseFullDomain,
        forecast,
      }),
    [baseFullDomain, data, forecast],
  );
  const forecastEndMs = getForecastEndMs(forecastPoints);
  const fullDomain = useMemo<[number, number]>(
    () => [
      baseFullDomain[0],
      forecastEndMs === null
        ? baseFullDomain[1]
        : Math.max(baseFullDomain[1], forecastEndMs),
    ],
    [baseFullDomain, forecastEndMs],
  );
  const xDomain = zoomDomain ?? fullDomain;
  const multiDay = isMultiDayChartDomain(xDomain);
  const hasVisibleDoseData = doseEvents.some(
    (dose) => dose.timestampMs >= xDomain[0] && dose.timestampMs <= xDomain[1],
  );
  const hasVisiblePumpBasalData = pumpTimelineData.basalSegments.some(
    (segment) => segment.endMs > xDomain[0] && segment.startMs < xDomain[1],
  );
  const hasVisibleInsulinOnBoardData = insulinOnBoardSamples.some(
    (sample) =>
      sample.timestampMs >= xDomain[0] && sample.timestampMs <= xDomain[1],
  );
  const hasVisibleActivityModeData = pumpTimelineData.activityIntervals.some(
    (interval) => interval.endMs > xDomain[0] && interval.startMs < xDomain[1],
  );
  const hasVisibleSuspensionData = pumpTimelineData.suspensionIntervals.some(
    (interval) => interval.endMs > xDomain[0] && interval.startMs < xDomain[1],
  );
  const showDoseTimeline =
    isInsulinLoading || Boolean(insulinError) || hasVisibleDoseData;
  const showPumpBasalTimeline =
    isPumpLoading ||
    Boolean(pumpError) ||
    hasVisiblePumpBasalData ||
    (isPossiblyTruncated && (hasPumpHistory || hasConfiguredPump));
  const showInsulinOnBoardTimeline = hasVisibleInsulinOnBoardData;
  const showActivityTimeline =
    !pumpError && (hasVisibleActivityModeData || hasVisibleSuspensionData);
  const showGlucoseXAxis =
    !showInsulinOnBoardTimeline &&
    !showPumpBasalTimeline &&
    !showActivityTimeline;
  const resolvedThresholds = normalizeGlucoseThresholds(thresholds);
  const urgentLowThreshold = resolvedThresholds.urgentLow;
  const lowThreshold = resolvedThresholds.low;
  const highThreshold = resolvedThresholds.high;
  const urgentHighThreshold = resolvedThresholds.urgentHigh;
  const yDomain = useMemo(
    () =>
      resolveGlucoseYDomain(
        data,
        forecastPoints,
        lowThreshold,
        highThreshold,
      ),
    [data, forecastPoints, highThreshold, lowThreshold],
  );
  const hoverRangeStatus = timelineHover?.glucose
    ? getRangeStatus(
        timelineHover.glucose.value,
        {
          urgentLow: urgentLowThreshold,
          low: lowThreshold,
          high: highThreshold,
          urgentHigh: urgentHighThreshold,
        },
        unit,
      )
    : null;
  const hoverBasalSegment = timelineHover
    ? (pumpTimelineData.basalSegments.find(
        (segment) =>
          timelineHover.timestamp >= segment.startMs &&
          timelineHover.timestamp < segment.endMs,
      ) ?? null)
    : null;
  const hoverActivityInterval = timelineHover
    ? (pumpTimelineData.activityIntervals.find(
        (interval) =>
          timelineHover.timestamp >= interval.startMs &&
          timelineHover.timestamp < interval.endMs,
      ) ?? null)
    : null;
  const hoverSuspensionInterval = timelineHover
    ? (pumpTimelineData.suspensionIntervals.find(
        (interval) =>
          timelineHover.timestamp >= interval.startMs &&
          timelineHover.timestamp < interval.endMs,
      ) ?? null)
    : null;
  const containerClassName = twMerge(
    embedded
      ? "min-w-0 overflow-hidden px-2 py-4 sm:p-6"
      : "min-w-0 overflow-hidden rounded-panel border border-border-default bg-surface-primary p-4 sm:p-6",
    className,
  );

  const handlePeriodChange = useCallback(
    (nextPeriod: ChartTimePeriod) => {
      setPeriod(nextPeriod);
      setInsulinPeriod(getInsulinPeriod(nextPeriod));
      setZoomDomain(null);
      setTimelineHover(null);
    },
    [setInsulinPeriod, setPeriod],
  );

  const copyZoomRange = useCallback(async () => {
    if (!zoomDomain) {
      return;
    }

    try {
      await navigator.clipboard.writeText(
        serializeTimeRangeClipboardValue({
          from: new Date(zoomDomain[0]).toISOString(),
          to: new Date(zoomDomain[1]).toISOString(),
        }),
      );
      setCopyError(null);
    } catch {
      setCopyError("Could not copy zoom range.");
    }
  }, [zoomDomain]);

  const handleGlucoseHover = useCallback(
    (hover: GlucoseTimelineHover | null) => {
      if (!hover) {
        setTimelineHover(null);
        return;
      }

      setTimelineHover((current) => ({
        timestamp: hover.timestamp,
        glucose: hover.point,
        doses:
          current &&
          Math.abs(current.timestamp - hover.timestamp) <=
            HOVER_TIMESTAMP_TOLERANCE_MS
            ? current.doses
            : [],
        insulinOnBoardSample:
          current &&
          Math.abs(current.timestamp - hover.timestamp) <=
            HOVER_TIMESTAMP_TOLERANCE_MS
            ? current.insulinOnBoardSample
            : null,
      }));
    },
    [],
  );

  const handleDoseTimelineHover = useCallback(
    (hover: ExpandedTimelineHover | null) => {
      if (!hover) {
        setTimelineHover(null);
        return;
      }

      setTimelineHover((current) => ({
        timestamp: hover.timestamp,
        glucose:
          current &&
          Math.abs(current.timestamp - hover.timestamp) <=
            HOVER_TIMESTAMP_TOLERANCE_MS
            ? current.glucose
            : null,
        doses: hover.doses,
        insulinOnBoardSample:
          current &&
          Math.abs(current.timestamp - hover.timestamp) <=
            HOVER_TIMESTAMP_TOLERANCE_MS
            ? current.insulinOnBoardSample
            : null,
      }));
    },
    [],
  );

  const handleInsulinOnBoardHover = useCallback(
    (hover: ExpandedTimelineHover | null) => {
      if (!hover) {
        setTimelineHover(null);
        return;
      }

      setTimelineHover((current) => ({
        timestamp: hover.timestamp,
        glucose:
          current &&
          Math.abs(current.timestamp - hover.timestamp) <=
            HOVER_TIMESTAMP_TOLERANCE_MS
            ? current.glucose
            : null,
        doses:
          current &&
          Math.abs(current.timestamp - hover.timestamp) <=
            HOVER_TIMESTAMP_TOLERANCE_MS
            ? current.doses
            : [],
        insulinOnBoardSample: hover.insulinOnBoardSample ?? null,
      }));
    },
    [],
  );

  const handlePumpTimelineHover = useCallback(
    (hover: ExpandedTimelineHover | null) => {
      if (!hover) {
        setTimelineHover(null);
        return;
      }

      setTimelineHover((current) => ({
        timestamp: hover.timestamp,
        glucose:
          current &&
          Math.abs(current.timestamp - hover.timestamp) <=
            HOVER_TIMESTAMP_TOLERANCE_MS
            ? current.glucose
            : null,
        doses:
          current &&
          Math.abs(current.timestamp - hover.timestamp) <=
            HOVER_TIMESTAMP_TOLERANCE_MS
            ? current.doses
            : [],
        insulinOnBoardSample:
          current &&
          Math.abs(current.timestamp - hover.timestamp) <=
            HOVER_TIMESTAMP_TOLERANCE_MS
            ? current.insulinOnBoardSample
            : null,
      }));
    },
    [],
  );

  const hoverFraction = timelineHover
    ? (timelineHover.timestamp - xDomain[0]) /
      Math.max(1, xDomain[1] - xDomain[0])
    : 0;
  const combinedTooltip = timelineHover ? (
    <div
      className={twMerge(
        "pointer-events-none absolute top-2 z-20 w-60 rounded-panel border border-border-hover bg-surface-primary px-3 py-2 shadow-lg",
        hoverFraction > 0.65 ? "left-2" : "right-2",
      )}
      role="tooltip"
      data-testid="combined-timeline-tooltip"
    >
      <p className="font_metric_caption text-foreground-secondary">
        {formatTooltipTime(timelineHover.timestamp, multiDay)}
      </p>
      {timelineHover.glucose ? (
        <div className="mt-1">
          <p className="font_header_4 text-foreground-primary">
            {formatGlucose(timelineHover.glucose.value, unit)} {unitLabel(unit)}
            {TREND_ARROWS[timelineHover.glucose.trend] &&
            TREND_ARROWS[timelineHover.glucose.trend] !== "?" ? (
              <span className="ml-1">
                {TREND_ARROWS[timelineHover.glucose.trend]}
              </span>
            ) : null}
          </p>
          {TREND_DESCRIPTIONS[timelineHover.glucose.trend] !==
          "unknown trend" ? (
            <p className="font_metric_caption capitalize text-foreground-secondary">
              {TREND_DESCRIPTIONS[timelineHover.glucose.trend]}
            </p>
          ) : null}
          {hoverRangeStatus ? (
            <p className="mt-1 flex items-center gap-1.5 font_metric_caption text-foreground-secondary">
              <ChartLegendSwatch className={hoverRangeStatus.swatchClassName} />
              {hoverRangeStatus.label}
            </p>
          ) : null}
        </div>
      ) : (
        <p className="mt-1 font_metric_caption text-foreground-secondary">
          No glucose reading at this time
        </p>
      )}
      {showInsulinOnBoardTimeline ? (
        <>
          <div className="my-2 border-t border-border-default" />
          {timelineHover.insulinOnBoardSample ? (
            <div>
              <p className="flex items-center gap-1.5 font_header_4 text-foreground-primary">
                <ChartLegendSwatch className="border border-signal-info-fill bg-signal-info-fill/15" />
                {timelineHover.insulinOnBoardSample.valueUnits.toFixed(2)} U
              </p>
              <p className="font_metric_caption text-foreground-primary">
                Insulin on board
              </p>
              <p className="font_metric_caption text-foreground-secondary">
                Sample time:{" "}
                <time
                  dateTime={new Date(
                    timelineHover.insulinOnBoardSample.timestampMs,
                  ).toISOString()}
                >
                  {formatTooltipTime(
                    timelineHover.insulinOnBoardSample.timestampMs,
                    multiDay,
                  )}
                </time>
              </p>
            </div>
          ) : (
            <p className="font_metric_caption text-foreground-secondary">
              No reported IoB sample at this time
            </p>
          )}
        </>
      ) : null}
      {showDoseTimeline ? (
        <>
          <div className="my-2 border-t border-border-default" />
          {timelineHover.doses.length > 0 ? (
            <div className="space-y-2">
              {timelineHover.doses.map((dose, index) => (
                <div
                  key={`${dose.kind}-${dose.timestampMs}-${getDoseUnits(dose)}-${index}`}
                  className={
                    index > 0
                      ? "border-t border-border-default pt-2"
                      : undefined
                  }
                >
                  <p className="flex items-center gap-1.5 font_header_4 text-foreground-primary">
                    <ChartLegendSwatch
                      className={getDoseSwatchClassName(dose)}
                    />
                    {getDoseUnits(dose).toFixed(2)} U
                  </p>
                  <p className="font_metric_caption text-foreground-primary">
                    {getDoseLabel(dose)}
                  </p>
                  <p className="font_metric_caption text-foreground-secondary">
                    Dose time:{" "}
                    <time dateTime={new Date(dose.timestampMs).toISOString()}>
                      {formatTooltipTime(dose.timestampMs, multiDay)}
                    </time>
                  </p>
                </div>
              ))}
            </div>
          ) : (
            <p className="font_metric_caption text-foreground-secondary">
              No insulin dose near this time
            </p>
          )}
        </>
      ) : null}
      {showPumpBasalTimeline ? (
        <>
          <div className="my-2 border-t border-border-default" />
          {hoverBasalSegment ? (
            <div>
              <p className="flex items-center gap-1.5 font_header_4 text-foreground-primary">
                <ChartLegendSwatch className="border border-data-insulin-basal bg-data-insulin-basal/15" />
                {hoverBasalSegment.rateUnitsPerHour.toFixed(2)} U/hr
              </p>
              <p className="font_metric_caption text-foreground-primary">
                {hoverBasalSegment.deliveryState === "suspended"
                  ? "Pump suspended"
                  : hoverBasalSegment.isAutomated
                    ? "Automated basal"
                    : "Manual basal"}
              </p>
              {hoverBasalSegment.basalAdjustmentPercent != null ? (
                <p className="font_metric_caption text-foreground-secondary">
                  {hoverBasalSegment.basalAdjustmentPercent > 0 ? "+" : ""}
                  {hoverBasalSegment.basalAdjustmentPercent}% adjustment
                </p>
              ) : null}
            </div>
          ) : (
            <p className="font_metric_caption text-foreground-secondary">
              No confirmed pump basal at this time
            </p>
          )}
        </>
      ) : null}
      {showActivityTimeline ? (
        <>
          <div className="my-2 border-t border-border-default" />
          <p className="flex items-center gap-1.5 font_metric_caption text-foreground-primary">
            {hoverActivityInterval ? (
              <ChartLegendSwatch
                className={twMerge(
                  hoverActivityInterval.mode === "sleep"
                    ? "border border-data-insulin-mode-sleep bg-data-insulin-mode-sleep/15"
                    : "border border-data-insulin-mode-exercise bg-data-insulin-mode-exercise/15",
                )}
              />
            ) : null}
            {hoverActivityInterval
              ? hoverActivityInterval.mode === "sleep"
                ? "Sleep mode"
                : "Exercise mode"
              : "Standard mode"}
          </p>
          {hoverSuspensionInterval ? (
            <div className="mt-1 font_metric_caption">
              <p className="flex items-center gap-1.5 text-signal-error-text">
                <ChartLegendSwatch className="border border-signal-error-fill bg-signal-error-fill/15" />
                Pump suspended
              </p>
              <p className="text-foreground-secondary">
                Suspend:{" "}
                {formatTooltipTime(hoverSuspensionInterval.startMs, multiDay)}
              </p>
              <p className="text-foreground-secondary">
                Resume:{" "}
                {hoverSuspensionInterval.hasConfirmedResume
                  ? formatTooltipTime(hoverSuspensionInterval.endMs, multiDay)
                  : "Not confirmed"}
              </p>
            </div>
          ) : null}
        </>
      ) : null}
    </div>
  ) : null;

  const doseTimeline = showDoseTimeline ? (
    <InsulinDoseTimeline
      cursorSyncKey={cursorSyncKey}
      error={insulinError}
      isLoading={isInsulinLoading}
      longActingBasalInjections={doseTimelineData.longActingBasalInjections}
      multiDay={multiDay}
      onHoverChange={handleDoseTimelineHover}
      onRetry={refetchInsulin}
      onZoomChange={setZoomDomain}
      rapidDoses={doseTimelineData.rapidDoses}
      sectionHeaderSeparator={embedded}
      showXAxis={false}
      xDomain={xDomain}
    />
  ) : null;
  const insulinOnBoardTimeline = showInsulinOnBoardTimeline ? (
    <InsulinOnBoardTimeline
      cursorSyncKey={cursorSyncKey}
      multiDay={multiDay}
      onHoverChange={handleInsulinOnBoardHover}
      onZoomChange={setZoomDomain}
      samples={insulinOnBoardSamples}
      sectionHeaderSeparator={embedded}
      showXAxis={!showPumpBasalTimeline && !showActivityTimeline}
      xDomain={xDomain}
    />
  ) : null;
  const pumpBasalTimeline = showPumpBasalTimeline ? (
    <PumpBasalRateTimeline
      cursorSyncKey={cursorSyncKey}
      error={pumpError}
      isLoading={isPumpLoading}
      isPossiblyTruncated={isPossiblyTruncated}
      multiDay={multiDay}
      onHoverChange={handlePumpTimelineHover}
      onRetry={refetchPump}
      onZoomChange={setZoomDomain}
      sectionHeaderSeparator={embedded}
      segments={pumpTimelineData.basalSegments}
      showXAxis={!showActivityTimeline}
      xDomain={xDomain}
    />
  ) : null;
  const activityTimeline = showActivityTimeline ? (
    <PumpActivityModeTimeline
      cursorSyncKey={cursorSyncKey}
      intervals={pumpTimelineData.activityIntervals}
      multiDay={multiDay}
      onHoverChange={handlePumpTimelineHover}
      onZoomChange={setZoomDomain}
      sectionHeaderSeparator={embedded}
      showXAxis
      suspensionIntervals={pumpTimelineData.suspensionIntervals}
      xDomain={xDomain}
    />
  ) : null;
  const glucoseSectionHeader = embedded ? (
    <ChartSectionHeader
      details={
        <GlucoseRangeLegend
          forecast={forecast}
          forecastEligible={forecastEligible}
          forecastPoints={forecastPoints}
          highThreshold={highThreshold}
          lowThreshold={lowThreshold}
          unit={unit}
          urgentHighThreshold={urgentHighThreshold}
          urgentLowThreshold={urgentLowThreshold}
        />
      }
      heading="Glucose"
      separator
      unit={unitLabel(unit)}
    />
  ) : null;

  if (isLoading && data.length === 0) {
    return (
      <div
        className={containerClassName}
        role="region"
        aria-label="Loading glucose trend chart"
        aria-busy="true"
        data-testid="glucose-trend-chart"
      >
        <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="h-6 w-40 animate-pulse rounded-panel bg-surface-tertiary" />
          <div className="h-8 w-48 animate-pulse rounded-panel bg-surface-tertiary" />
        </div>
        <div className="relative">
          {doseTimeline}
          {glucoseSectionHeader}
          <div className="h-64 animate-pulse rounded-panel bg-surface-secondary" />
          {insulinOnBoardTimeline}
          {pumpBasalTimeline}
          {activityTimeline}
          {combinedTooltip}
        </div>
      </div>
    );
  }

  if (error && data.length === 0) {
    return (
      <div
        className={containerClassName}
        role="region"
        aria-label="Glucose trend chart"
        data-testid="glucose-trend-chart"
      >
        <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          {embedded ? null : (
            <h2 className="font_header_4 text-foreground-primary">
              Glucose Trend
            </h2>
          )}
          {embedded ? null : (
            <GlucoseForecastLegend
              eligible={forecastEligible}
              forecast={forecast}
              points={forecastPoints}
            />
          )}
          {dashboardTimeRange ? null : (
            <PeriodSelector selected={period} onSelect={handlePeriodChange} />
          )}
        </div>
        <div className="relative">
          {doseTimeline}
          {glucoseSectionHeader}
          <div className="flex h-64 flex-col items-center justify-center gap-3 text-foreground-secondary">
            <p>Unable to load glucose history</p>
            <Button
              type="button"
              onClick={refetch}
              className="rounded-panel bg-surface-secondary px-4 py-2 font_body_3 text-foreground-primary transition-colors hover:bg-surface-tertiary"
            >
              Retry
            </Button>
          </div>
          {insulinOnBoardTimeline}
          {pumpBasalTimeline}
          {activityTimeline}
          {combinedTooltip}
        </div>
      </div>
    );
  }

  if (data.length === 0) {
    return (
      <div
        className={containerClassName}
        role="region"
        aria-label="Glucose trend chart"
        data-testid="glucose-trend-chart"
      >
        <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          {embedded ? null : (
            <h2 className="font_header_4 text-foreground-primary">
              Glucose Trend
            </h2>
          )}
          {dashboardTimeRange ? null : (
            <PeriodSelector selected={period} onSelect={handlePeriodChange} />
          )}
        </div>
        <div className="relative">
          {doseTimeline}
          {glucoseSectionHeader}
          <div className="flex h-64 items-center justify-center text-foreground-secondary">
            <p>No glucose readings yet</p>
          </div>
          {insulinOnBoardTimeline}
          {pumpBasalTimeline}
          {activityTimeline}
          {combinedTooltip}
        </div>
      </div>
    );
  }

  return (
    <div
      className={containerClassName}
      role="region"
      aria-label={`Glucose trend chart, ${dashboardTimeRange?.label ?? period} view`}
      data-testid="glucose-trend-chart"
    >
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex flex-wrap items-center gap-2">
          {embedded ? null : (
            <h2 className="font_header_4 text-foreground-primary">
              Glucose Trend
            </h2>
          )}
          {zoomDomain ? (
            <>
              <Button
                type="button"
                onClick={copyZoomRange}
                className="flex items-center gap-1 rounded-panel bg-surface-secondary px-2 py-1 font_metric_caption text-foreground-primary transition-colors hover:bg-surface-tertiary"
                aria-label="Copy zoom time range"
              >
                <Icon icon="copy" decorative className="h-3.5 w-3.5" />
                Copy Time Range
              </Button>
              <Button
                type="button"
                onClick={() => setZoomDomain(null)}
                className="flex items-center gap-1 rounded-panel bg-surface-secondary px-2 py-1 font_metric_caption text-foreground-primary transition-colors hover:bg-surface-tertiary"
                aria-label="Reset zoom"
              >
                <Icon icon="zoom-out" decorative className="h-3.5 w-3.5" />
                Reset Time Range
              </Button>
            </>
          ) : null}
        </div>
        {dashboardTimeRange ? null : (
          <PeriodSelector selected={period} onSelect={handlePeriodChange} />
        )}
      </div>
      {copyError ? (
        <p
          className="mb-2 font_metric_caption text-signal-warning-text"
          role="alert"
        >
          {copyError}
        </p>
      ) : null}
      <div className="relative">
        {doseTimeline}
        {glucoseSectionHeader}
        <UplotGlucoseTrend
          ariaLabel={`Glucose readings for ${dashboardTimeRange?.label ?? period}`}
          cursorSyncKey={cursorSyncKey}
          data={data}
          fadeTopAxis={embedded}
          forecastPoints={forecastPoints}
          xDomain={xDomain}
          yDomain={yDomain}
          urgentLowThreshold={urgentLowThreshold}
          lowThreshold={lowThreshold}
          highThreshold={highThreshold}
          urgentHighThreshold={urgentHighThreshold}
          unit={unit}
          multiDay={multiDay}
          showXAxis={showGlucoseXAxis}
          onHoverChange={handleGlucoseHover}
          onZoomChange={setZoomDomain}
        />
        {insulinOnBoardTimeline}
        {pumpBasalTimeline}
        {activityTimeline}
        {combinedTooltip}
      </div>
    </div>
  );
}

export default GlucoseTrendChart;
