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
import { Activity } from "lucide-react";
import {
  listIntegrations,
  listNightscoutConnections,
  type IntegrationResponse,
  type NightscoutConnectionResponse,
} from "@/lib/api";
import { AnimatedCard } from "@/components/ui/animated-card";
import { PageTransition } from "@/components/ui/page-transition";

import {
  GlucoseHero,
  TimeInRangeBar,
  ConnectionStatusBanner,
  GlucoseTrendChart,
  CgmSummaryStats,
  AgpChart,
  InsulinSummaryStats,
  BolusReviewTable,
  DataSourcesFreshnessCard,
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

  // Per-source freshness for the "Data Sources" card. Fetched once on
  // mount + every 30s after that, with `freshnessNow` advancing every
  // 30s so relative-time labels walk forward without a refetch. 30s
  // (not 60s) so the worst-case "lagging" flash before the 1-min
  // scheduler tick is bounded.
  const [nightscoutConnections, setNightscoutConnections] = useState<
    NightscoutConnectionResponse[]
  >([]);
  const [dexcomIntegration, setDexcomIntegration] =
    useState<IntegrationResponse | null>(null);
  const [tandemIntegration, setTandemIntegration] =
    useState<IntegrationResponse | null>(null);
  const [freshnessNow, setFreshnessNow] = useState<number>(() => Date.now());

  useEffect(() => {
    let cancelled = false;
    const refetch = async () => {
      try {
        const [integrationsResult, nsResult] = await Promise.allSettled([
          listIntegrations(),
          listNightscoutConnections(),
        ]);
        if (cancelled) return;
        if (integrationsResult.status === "fulfilled") {
          const data = integrationsResult.value;
          setDexcomIntegration(
            data.integrations.find((i) => i.integration_type === "dexcom") ||
              null
          );
          setTandemIntegration(
            data.integrations.find((i) => i.integration_type === "tandem") ||
              null
          );
        }
        if (nsResult.status === "fulfilled") {
          setNightscoutConnections(nsResult.value.connections);
        }
      } catch {
        // Best-effort: leaving stale state during a transient API blip
        // is preferable to clobbering the rendered freshness rows.
      }
    };
    void refetch();
    const refetchInterval = setInterval(() => void refetch(), 30_000);
    const tickInterval = setInterval(() => setFreshnessNow(Date.now()), 30_000);
    return () => {
      cancelled = true;
      clearInterval(refetchInterval);
      clearInterval(tickInterval);
    };
  }, []);

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

  // Derive in-range pct from detail stats for the metrics card
  const inRangePct = tirStats?.buckets?.find(
    (b) => b.label === "in_range"
  )?.pct;

  return (
    <PageTransition>
    <div className="space-y-6">
      {/* Connection status banner - Story 4.5 */}
      <ConnectionStatusBanner
        isReconnecting={isReconnecting}
        hasError={!!error}
        errorMessage={error?.message}
        onReconnect={reconnect}
      />

      {/* Page header - using div instead of header to avoid banner role confusion inside main */}
      <AnimatedCard>
        <div>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white">Dashboard</h1>
          <p className="text-slate-500 dark:text-slate-400">Your glucose overview at a glance</p>
        </div>
      </AnimatedCard>

      {/* Glucose hero - Story 4.2, 4.6 */}
      <AnimatedCard delay={0.05}>
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
      </AnimatedCard>

      {/* Glucose trend chart */}
      <AnimatedCard delay={0.1}>
        <GlucoseTrendChart refreshKey={chartRefreshKey} thresholds={glucoseThresholds} />
      </AnimatedCard>

      {/* CGM Summary Stats Panel - Story 30.3 */}
      <AnimatedCard delay={0.15}>
        <CgmSummaryStats
          stats={cgmStats}
          isLoading={cgmLoading}
          error={cgmError}
          period={cgmPeriod}
          onPeriodChange={setCgmPeriod}
        />
      </AnimatedCard>

      {/* AGP Percentile Band Chart - Story 30.5 */}
      <AnimatedCard delay={0.2}>
        <AgpChart thresholds={glucoseThresholds} />
      </AnimatedCard>

      {/* Insulin Summary & Bolus Review - Story 30.7 */}
      <AnimatedCard delay={0.25}>
        <InsulinSummaryStats />
      </AnimatedCard>
      <AnimatedCard delay={0.3}>
        <BolusReviewTable />
      </AnimatedCard>

      {/* Metrics grid with proper heading hierarchy */}
      <AnimatedCard delay={0.35}>
        <section aria-labelledby="metrics-heading">
          <h2 id="metrics-heading" className="sr-only">Dashboard Metrics</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Time in Range Card */}
            <article className="bg-white dark:bg-slate-900 rounded-xl p-6 border border-slate-200 dark:border-slate-800">
              <div className="flex items-center gap-3 mb-2">
                <div className="p-2 bg-green-500/10 rounded-lg">
                  <Activity className="h-5 w-5 text-green-400" aria-hidden="true" />
                </div>
                <h3 className="text-slate-500 dark:text-slate-400 text-sm">Time in Range ({PERIOD_LABELS[tirPeriod]})</h3>
              </div>
              <p className="text-3xl font-bold text-green-400" aria-label={`Time in range: ${inRangePct != null && tirStats && tirStats.readings_count > 0 ? Math.round(inRangePct) : "--"} percent`}>
                {inRangePct != null && tirStats && tirStats.readings_count > 0 ? `${Math.round(inRangePct)}%` : "--"}
              </p>
              <p className="text-slate-500 text-xs mt-1">Target: {targetRange}</p>
            </article>

            {/* Data Sources card -- per-source freshness with status
                pills. Replaces the old single-row "Last Updated" card.
                Returns null when the user has zero configured sources,
                in which case the parent grid silently shrinks. */}
            <DataSourcesFreshnessCard
              nightscoutConnections={nightscoutConnections}
              dexcom={dexcomIntegration}
              tandem={tandemIntegration}
              now={freshnessNow}
            />
            {/* When no sources are configured, fall back to the
                glucose-stream freshness signal so the grid slot
                isn't empty during initial onboarding. */}
            {nightscoutConnections.length === 0 &&
              !dexcomIntegration &&
              !tandemIntegration && (
                <article className="bg-white dark:bg-slate-900 rounded-xl p-6 border border-slate-200 dark:border-slate-800">
                  <h3 className="text-slate-500 dark:text-slate-400 text-sm mb-2">
                    Data Sources
                  </h3>
                  <p className="text-sm text-slate-500">
                    No data sources configured yet. Connect a CGM, pump, or
                    Nightscout instance from{" "}
                    <a
                      href="/dashboard/settings/integrations"
                      className="text-blue-400 hover:underline"
                    >
                      Settings → Integrations
                    </a>
                    .
                  </p>
                </article>
              )}
          </div>
        </section>
      </AnimatedCard>

      {/* Time in Range bar - consolidated 5-bucket display */}
      <AnimatedCard delay={0.4}>
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
      </AnimatedCard>
    </div>
    </PageTransition>
  );
}
