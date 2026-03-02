"use client";

/**
 * Dashboard Page
 *
 * Story 4.1: Dashboard Layout & Navigation
 * Story 4.2: GlucoseHero Component
 * Story 4.4: Time in Range Bar Component
 * Story 4.5: Real-Time Updates via SSE
 * Story 4.6: Dashboard Accessibility
 * Story 8.3: Role-based routing (caregivers redirect to /dashboard/caregiver)
 * Main dashboard view showing glucose data and metrics.
 *
 * Accessibility features:
 * - Main landmark for skip link navigation
 * - Proper heading hierarchy (h1 for page, h2 for sections)
 * - Logical tab order
 */

import { useEffect, useState, useRef } from "react";
import { useRouter } from "next/navigation";
import { Activity, Clock } from "lucide-react";

import {
  GlucoseHero,
  TimeInRangeBar,
  ConnectionStatusBanner,
  GlucoseTrendChart,
  CgmSummaryStats,
  AgpChart,
  PERIOD_LABELS,
} from "@/components/dashboard";
import { useGlucoseStreamContext, useUserContext } from "@/providers";
import { useTimeInRangeDetailStats } from "@/hooks/use-time-in-range-stats";
import { useGlucoseStats } from "@/hooks/use-glucose-stats";
import { useGlucoseRange } from "@/hooks/use-glucose-range";
import { usePumpStatus } from "@/hooks/use-pump-status";

export default function DashboardPage() {
  const router = useRouter();
  const { user, isLoading: isUserLoading } = useUserContext();

  // All hooks must be called before any early return
  const {
    glucose,
    isLive,
    isReconnecting,
    error,
    reconnect,
  } = useGlucoseStreamContext();

  // Chart refresh: throttle to once per 5 minutes when new SSE data arrives
  const [chartRefreshKey, setChartRefreshKey] = useState(0);
  const lastRefreshRef = useRef(0);

  useEffect(() => {
    if (glucose?.reading_timestamp) {
      const now = Date.now();
      if (now - lastRefreshRef.current > 5 * 60 * 1000) {
        lastRefreshRef.current = now;
        setChartRefreshKey((k) => k + 1);
      }
    }
  }, [glucose?.reading_timestamp]);

  // Fetch user's configured glucose range thresholds
  const glucoseThresholds = useGlucoseRange();
  const targetRange = `${glucoseThresholds.low}-${glucoseThresholds.high} mg/dL`;

  // Fetch latest pump status (basal, battery, reservoir) for hero card
  const pumpStatus = usePumpStatus(chartRefreshKey);

  // Redirect caregivers to the caregiver-specific dashboard (Story 8.3)
  useEffect(() => {
    if (user?.role === "caregiver") {
      router.replace("/dashboard/caregiver");
    }
  }, [user, router]);

  // Story 30.4 consolidated: single hook for 5-bucket TIR detail stats
  const {
    stats: tirStats,
    isLoading: tirLoading,
    error: tirError,
    period: tirPeriod,
    setPeriod: setTirPeriod,
  } = useTimeInRangeDetailStats("24h");

  // Story 30.3: Fetch CGM summary stats from API
  const {
    stats: cgmStats,
    isLoading: cgmLoading,
    error: cgmError,
    period: cgmPeriod,
    setPeriod: setCgmPeriod,
  } = useGlucoseStats("24h");

  // Prevent flash of diabetic dashboard while caregiver redirect is pending
  if (isUserLoading || user?.role === "caregiver") {
    return null;
  }

  // Determine data to display
  // Issue 2 & 3 fix: The hook now returns the mapped frontend trend directly
  const glucoseValue = glucose?.value ?? null;
  const glucoseTrend = glucose?.trend ?? "Unknown";
  const iob = glucose?.iob?.current ?? null;
  const minutesAgo = glucose?.minutes_ago ?? null;
  const isStale = glucose?.is_stale ?? false;

  // Format "last updated" text
  const getLastUpdatedText = (): string => {
    if (minutesAgo === null) return "No data";
    if (minutesAgo < 1) return "Just now";
    if (minutesAgo === 1) return "1m ago";
    return `${minutesAgo}m ago`;
  };

  const getFreshnessText = (): string => {
    if (!isLive) return "Connecting...";
    if (isStale) return "Data is stale";
    return "Data is fresh";
  };

  // Derive in-range pct from detail stats for the metrics card
  const inRangePct = tirStats?.buckets?.find(
    (b) => b.label === "in_range"
  )?.pct;

  return (
    <main id="main-content" className="space-y-6">
      {/* Connection status banner - Story 4.5 */}
      <ConnectionStatusBanner
        isReconnecting={isReconnecting}
        hasError={!!error}
        errorMessage={error?.message}
        onReconnect={reconnect}
      />

      {/* Page header - using div instead of header to avoid banner role confusion inside main */}
      <div>
        <h1 className="text-2xl font-bold">Dashboard</h1>
        <p className="text-slate-400">Your glucose overview at a glance</p>
      </div>

      {/* Glucose hero - Story 4.2, 4.6 */}
      <GlucoseHero
        value={glucoseValue}
        trend={glucoseTrend}
        iob={iob}
        basalRate={pumpStatus.basal?.rate ?? null}
        batteryPct={pumpStatus.battery?.percentage ?? null}
        reservoirUnits={pumpStatus.reservoir?.units_remaining ?? null}
        isLoading={!isLive && !glucose}
        thresholds={glucoseThresholds}
      />

      {/* Glucose trend chart */}
      <GlucoseTrendChart refreshKey={chartRefreshKey} thresholds={glucoseThresholds} />

      {/* CGM Summary Stats Panel - Story 30.3 */}
      <CgmSummaryStats
        stats={cgmStats}
        isLoading={cgmLoading}
        error={cgmError}
        period={cgmPeriod}
        onPeriodChange={setCgmPeriod}
      />

      {/* AGP Percentile Band Chart - Story 30.5 */}
      <AgpChart thresholds={glucoseThresholds} />

      {/* Metrics grid with proper heading hierarchy */}
      <section aria-labelledby="metrics-heading">
        <h2 id="metrics-heading" className="sr-only">Dashboard Metrics</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* Time in Range Card */}
          <article className="bg-slate-900 rounded-xl p-6 border border-slate-800">
            <div className="flex items-center gap-3 mb-2">
              <div className="p-2 bg-green-500/10 rounded-lg">
                <Activity className="h-5 w-5 text-green-400" aria-hidden="true" />
              </div>
              <h3 className="text-slate-400 text-sm">Time in Range ({PERIOD_LABELS[tirPeriod]})</h3>
            </div>
            <p className="text-3xl font-bold text-green-400" aria-label={`Time in range: ${inRangePct != null && tirStats && tirStats.readings_count > 0 ? Math.round(inRangePct) : "--"} percent`}>
              {inRangePct != null && tirStats && tirStats.readings_count > 0 ? `${Math.round(inRangePct)}%` : "--"}
            </p>
            <p className="text-slate-500 text-xs mt-1">Target: {targetRange}</p>
          </article>

          {/* Last Updated Card */}
          <article className="bg-slate-900 rounded-xl p-6 border border-slate-800">
            <div className="flex items-center gap-3 mb-2">
              <div className="p-2 bg-emerald-500/10 rounded-lg">
                <Clock className="h-5 w-5 text-emerald-400" aria-hidden="true" />
              </div>
              <h3 className="text-slate-400 text-sm">Last Updated</h3>
            </div>
            <p className="text-3xl font-bold text-emerald-400" aria-label={`Last updated: ${getLastUpdatedText()}`}>
              {getLastUpdatedText()}
            </p>
            <p className="text-slate-500 text-xs mt-1">{getFreshnessText()}</p>
          </article>
        </div>
      </section>

      {/* Time in Range bar - consolidated 5-bucket display */}
      <TimeInRangeBar
        buckets={tirStats?.buckets ?? null}
        readingsCount={tirStats?.readings_count ?? 0}
        previousBuckets={tirStats?.previous_buckets ?? null}
        previousReadingsCount={tirStats?.previous_readings_count ?? null}
        error={tirError}
        period={tirPeriod}
        onPeriodChange={setTirPeriod}
        targetRange={targetRange}
        isLoading={tirLoading}
      />
    </main>
  );
}
