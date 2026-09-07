"use client";

import { useEffect, useMemo, useRef } from "react";
import { useBolusReview, type BolusReviewPeriod } from "@/hooks/use-bolus-review";
import { useGlucoseHistory } from "@/hooks/use-glucose-history";
import { usePumpEvents } from "@/hooks/use-pump-events";
import { PERIOD_TO_MS, type ChartTimePeriod } from "@/lib/chart-periods";
import { getSelectionKey } from "@/lib/glucose/history-selection";
import { twMerge } from "@/lib/ui/twMerge";
import { normalizeGlucoseThresholds } from "@/lib/glucose-classification";
import { useOptionalDashboardTimeRange } from "@/components/DashboardTimeRangeProvider";
import {
  buildGlucoseForecastPoints,
  getForecastEndMs,
  isForecastOverlayEligible,
} from "@/components/GlucoseForecast";
import {
  normalizeInsulinDoseTimeline,
  normalizePumpTimeline,
} from "@/components/InsulinTimeline/insulin-timeline-data";
import { DesktopMergedGlucoseTrendChart } from "./DesktopMergedGlucoseTrendChart";
import type {
  MergedChartModel,
  MergedGlucoseTrendChartProps,
} from "./MergedGlucoseTrendChart.types";
import { MobileMergedGlucoseTrendChart } from "./MobileMergedGlucoseTrendChart";
import { transformMergedGlucoseReadings } from "./merged-chart-model";

function insulinPeriod(period: ChartTimePeriod): BolusReviewPeriod {
  if (period === "3d" || period === "7d" || period === "14d" || period === "30d") {
    return period;
  }

  return "24h";
}

function isMultiDay(domain: [number, number]): boolean {
  return domain[1] - domain[0] >= 3 * 24 * 60 * 60 * 1000;
}

export function MergedGlucoseTrendChart({
  className,
  forecast,
  hasConfiguredPump = false,
  refreshKey,
  thresholds,
  unit = "mgdl",
}: MergedGlucoseTrendChartProps) {
  const dashboardTimeRange = useOptionalDashboardTimeRange();
  const glucose = useGlucoseHistory(
    "3h",
    dashboardTimeRange?.currentWindow
  );
  const insulin = useBolusReview(
    insulinPeriod(glucose.period),
    dashboardTimeRange?.currentWindow,
    500
  );
  const pump = usePumpEvents(
    glucose.period,
    dashboardTimeRange?.currentWindow
  );
  const refetchGlucose = glucose.refetch;
  const refetchInsulin = insulin.refetch;
  const refetchPump = pump.refetch;
  const previousRefreshKey = useRef(refreshKey);
  const currentWindow = dashboardTimeRange?.currentWindow;
  const previousWindow = useRef(currentWindow);

  useEffect(() => {
    const windowChanged = currentWindow !== previousWindow.current;
    previousWindow.current = currentWindow;
    if (
      refreshKey === undefined ||
      refreshKey <= 0 ||
      refreshKey === previousRefreshKey.current
    ) {
      return;
    }

    previousRefreshKey.current = refreshKey;
    // History hooks already fetch when their window changes.
    if (windowChanged) return;
    refetchGlucose();
    refetchInsulin();
    refetchPump();
  }, [currentWindow, refetchGlucose, refetchInsulin, refetchPump, refreshKey]);

  const points = useMemo(
    () => transformMergedGlucoseReadings(glucose.readings),
    [glucose.readings]
  );
  const doseTimeline = useMemo(
    () => normalizeInsulinDoseTimeline(insulin.data?.boluses ?? []),
    [insulin.data?.boluses]
  );
  const pumpTimeline = useMemo(
    () => normalizePumpTimeline(pump.events),
    [pump.events]
  );
  const doses = useMemo(
    () => [
      ...doseTimeline.rapidDoses,
      ...doseTimeline.longActingBasalInjections,
    ].sort((left, right) => left.timestampMs - right.timestampMs),
    [doseTimeline]
  );
  const latestTimestamp = points[points.length - 1]?.timestampMs ?? 0;
  const baseFullDomain = useMemo<[number, number]>(() => {
    const currentWindow = dashboardTimeRange?.currentWindow;
    if (currentWindow) {
      const from = new Date(currentWindow.from).getTime();
      const to = new Date(currentWindow.to).getTime();
      if (Number.isFinite(from) && Number.isFinite(to) && to > from) {
        return [from, to];
      }
    }

    const now = Math.max(Date.now(), latestTimestamp);
    return [now - PERIOD_TO_MS[glucose.period], now];
  }, [dashboardTimeRange?.currentWindow, glucose.period, latestTimestamp]);
  const forecastEligible = isForecastOverlayEligible(baseFullDomain);
  const forecastPoints = useMemo(
    () =>
      buildGlucoseForecastPoints({
        anchors: points,
        domain: baseFullDomain,
        forecast,
      }),
    [baseFullDomain, forecast, points],
  );
  const forecastEndMs = getForecastEndMs(forecastPoints);
  const rangeSelectionKey = dashboardTimeRange
    ? getSelectionKey(dashboardTimeRange.selection)
    : `period:${glucose.period}`;
  const fullDomain = useMemo<[number, number]>(
    () => [
      baseFullDomain[0],
      forecastEndMs === null
        ? baseFullDomain[1]
        : Math.max(baseFullDomain[1], forecastEndMs),
    ],
    [baseFullDomain, forecastEndMs],
  );
  const resolvedThresholds = useMemo(
    () => normalizeGlucoseThresholds(thresholds),
    [thresholds],
  );
  const hasPump =
    hasConfiguredPump ||
    pump.hasPumpHistory ||
    pumpTimeline.basalSegments.length > 0 ||
    pumpTimeline.activityIntervals.length > 0 ||
    pumpTimeline.suspensionIntervals.length > 0;
  const model = useMemo<MergedChartModel>(
    () => ({
      activityIntervals: pumpTimeline.activityIntervals,
      basalSegments: pumpTimeline.basalSegments,
      doses,
      forecast,
      forecastEligible,
      forecastPoints,
      fullDomain,
      hasPump,
      isMultiDay: isMultiDay(fullDomain),
      points,
      rangeSelectionKey,
      statuses: [
        {
          error: glucose.error,
          isLoading: glucose.isLoading,
          label: "glucose readings",
          onRetry: refetchGlucose,
        },
        {
          error: insulin.error,
          isLoading: insulin.isLoading,
          label: "insulin doses",
          onRetry: refetchInsulin,
        },
        {
          error: pump.error,
          isLoading: pump.isLoading,
          label: "pump data",
          onRetry: refetchPump,
        },
      ],
      suspensionIntervals: pumpTimeline.suspensionIntervals,
      thresholds: resolvedThresholds,
      unit,
    }),
    [
      doses,
      forecast,
      forecastEligible,
      forecastPoints,
      fullDomain,
      glucose.error,
      glucose.isLoading,
      hasPump,
      insulin.error,
      insulin.isLoading,
      points,
      pump.error,
      pump.isLoading,
      pumpTimeline.activityIntervals,
      pumpTimeline.basalSegments,
      pumpTimeline.suspensionIntervals,
      rangeSelectionKey,
      resolvedThresholds,
      refetchGlucose,
      refetchInsulin,
      refetchPump,
      unit,
    ]
  );

  return (
    <div className={twMerge("min-w-0", className)} data-testid="merged-glucose-trend-chart">
      <MobileMergedGlucoseTrendChart className="md:hidden" model={model} />
      <DesktopMergedGlucoseTrendChart className="hidden md:block" model={model} />
    </div>
  );
}
