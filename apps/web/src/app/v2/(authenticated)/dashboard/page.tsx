"use client";
import { useEffect, useState, useRef } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  getCgmSources,
  getGlookoStatus,
  getMedtronicConnectStatus,
  listIntegrations,
  listNightscoutConnections,
  type CgmSourcesResponse,
  type GlookoStatus,
  type IntegrationResponse,
  type MedtronicConnectStatus,
  type NightscoutConnectionResponse,
} from "@/lib/api";
import { AnimatedCard } from "@/components/AnimatedCard";
import { PageTransition } from "@/components/PageTransition";
import { Panel } from "@/components/Panel";
import {
  GlucoseHero,
  parseLoopState,
  type LoopStatusInfo,
} from "@/components/GlucoseHero";
import { ConnectionStatusBanner } from "@/components/ConnectionStatusBanner";
import { GlucoseTrendChart } from "@/components/GlucoseTrendChart";
import { MergedGlucoseTrendChart } from "@/components/MergedGlucoseTrendChart";
import { CgmSummaryStats } from "@/components/CgmSummaryStats";
import { AgpChart } from "@/components/AgpChart";
import { InsulinSummaryStats } from "@/components/InsulinSummaryStats";
import { DataSourcesFreshnessCard } from "@/components/DataSourcesFreshnessCard";
import { LivePumpStats } from "@/components/LivePumpStats";
import { GlucoseUnitSeedNotice } from "@/components/GlucoseUnitSeedNotice";
import {
  DashboardTimeRangePicker,
  DashboardTimeRangeQuickSelect,
} from "@/components/DashboardTimeRangePicker";
import { useDashboardTimeRange } from "@/components/DashboardTimeRangeProvider";

import { useGlucoseStreamContext } from "@/providers/glucose-stream-provider";
import { useDashboardLiveRefresh } from "@/hooks/use-dashboard-live-refresh";
import { useUserContext } from "@/providers/user-provider";
import { useGlucoseUnit } from "@/hooks/use-glucose-unit";
import { useTimeInRangeDetailStats } from "@/hooks/use-time-in-range-stats";
import { useGlucoseStats } from "@/hooks/use-glucose-stats";
import { useGlucoseRange } from "@/hooks/use-glucose-range";
import { usePumpStatus } from "@/hooks/use-pump-status";
import { useForecast } from "@/hooks/use-forecast";
import { hasNightscoutPumpHint } from "@/lib/pump/pump-history-context";
import type { LoopStatusResponse } from "@/lib/api";
/**
 * Map the backend's loop_status payload to the component's
 * LoopStatusInfo shape. `parseLoopState` fails closed on unknown
 * states so a future backend addition (e.g."warming_up") doesn't
 * crash the badge renderer.
 */
function mapLoopStatus(
  raw: LoopStatusResponse | null | undefined,
): LoopStatusInfo | null {
  if (!raw) return null;
  const state = parseLoopState(raw.state);
  if (state === null) return null;
  return {
    state,
    source: raw.source,
    issuedAt: raw.issued_at,
    failureReason: raw.failure_reason,
  };
}

function DashboardPageContent() {
  const router = useRouter();
  const dashboardTimeRange = useDashboardTimeRange();
  const { user, isLoading: isUserLoading } = useUserContext();
  const unit = useGlucoseUnit();
  // All hooks must be called before any early return
  const { glucose, isLive, isReconnecting, error, reconnect } =
    useGlucoseStreamContext();
  const chartRefreshKey = useDashboardLiveRefresh(glucose?.reading_timestamp);
  // Fetch user's configured glucose range thresholds (always mg/dL; display
  // converts to the active unit).
  const glucoseThresholds = useGlucoseRange();
  // Fetch latest pump status (basal, battery, reservoir) for hero card
  const pumpStatus = usePumpStatus(chartRefreshKey);
  // The forecast shares the chart's SSE-driven `chartRefreshKey` so the dotted line
  // refreshes on the same cadence as the underlying readings.
  const { forecast } = useForecast(chartRefreshKey);
  // Per-source freshness for the "Data Sources" card, fetched once on mount
  // and every 30 seconds after that.
  const [nightscoutConnections, setNightscoutConnections] = useState<
    NightscoutConnectionResponse[]
  >([]);
  const [dexcomIntegration, setDexcomIntegration] =
    useState<IntegrationResponse | null>(null);
  const [tandemIntegration, setTandemIntegration] =
    useState<IntegrationResponse | null>(null);
  const [cgmSources, setCgmSources] = useState<CgmSourcesResponse | null>(null);
  const [glookoStatus, setGlookoStatus] = useState<GlookoStatus | null>(null);
  const [medtronicStatus, setMedtronicStatus] =
    useState<MedtronicConnectStatus | null>(null);
  const [sourcesLoadFailed, setSourcesLoadFailed] = useState(false);
  const hasLoadedSourcesRef = useRef(false);
  useEffect(() => {
    let cancelled = false;
    const refetch = async () => {
      try {
        const [
          integrationsResult,
          nsResult,
          cgmSourcesResult,
          glookoResult,
          medtronicResult,
        ] = await Promise.allSettled([
          listIntegrations(),
          listNightscoutConnections(),
          getCgmSources(),
          getGlookoStatus(),
          getMedtronicConnectStatus(),
        ]);
        if (cancelled) return;
        const anyFulfilled = [
          integrationsResult,
          nsResult,
          cgmSourcesResult,
          glookoResult,
          medtronicResult,
        ].some((result) => result.status === "fulfilled");
        if (!hasLoadedSourcesRef.current || anyFulfilled) {
          setSourcesLoadFailed(!anyFulfilled);
          hasLoadedSourcesRef.current = true;
        }
        if (integrationsResult.status === "fulfilled") {
          const data = integrationsResult.value;
          setDexcomIntegration(
            data.integrations.find((i) => i.integration_type === "dexcom") ||
              null,
          );
          setTandemIntegration(
            data.integrations.find((i) => i.integration_type === "tandem") ||
              null,
          );
        }
        if (nsResult.status === "fulfilled") {
          setNightscoutConnections(nsResult.value.connections);
        }
        if (cgmSourcesResult.status === "fulfilled") {
          setCgmSources(cgmSourcesResult.value);
        }
        if (glookoResult.status === "fulfilled") {
          setGlookoStatus(glookoResult.value);
        }
        if (medtronicResult.status === "fulfilled") {
          setMedtronicStatus(medtronicResult.value);
        }
      } catch {
        // Best-effort: leaving stale state during a transient API blip
        // is preferable to clobbering the rendered freshness rows.
      }
    };
    void refetch();
    const refetchInterval = setInterval(() => void refetch(), 30_000);
    return () => {
      cancelled = true;
      clearInterval(refetchInterval);
    };
  }, []);
  // Redirect caregivers to the caregiver-specific dashboard.
  useEffect(() => {
    if (user?.role === "caregiver") {
      router.replace("/dashboard/caregiver");
    }
  }, [user, router]);
  const {
    stats: tirStats,
    isLoading: tirLoading,
    error: tirError,
  } = useTimeInRangeDetailStats("24h", dashboardTimeRange.currentWindow);
  const {
    stats: cgmStats,
    isLoading: cgmLoading,
    error: cgmError,
    period: cgmPeriod,
  } = useGlucoseStats("24h", dashboardTimeRange.currentWindow);
  // Prevent flash of diabetic dashboard while caregiver redirect is pending
  if (isUserLoading || user?.role === "caregiver") {
    return null;
  }
  // Determine data to display
  // Issue 2 & 3 fix: The hook now returns the mapped frontend trend directly
  const glucoseValue = glucose?.value ?? null;
  const glucoseTrend = glucose?.trend ?? "Unknown";
  const iob = glucose?.iob?.current ?? null;
  const hasConnectionSources =
    nightscoutConnections.some((connection) => connection.is_active) ||
    Boolean(dexcomIntegration && dexcomIntegration.status !== "disconnected") ||
    Boolean(tandemIntegration && tandemIntegration.status !== "disconnected") ||
    Boolean(
      glookoStatus &&
      glookoStatus.status !== "not_configured" &&
      glookoStatus.status !== "disconnected",
    ) ||
    Boolean(
      medtronicStatus &&
      medtronicStatus.status !== "not_configured" &&
      medtronicStatus.status !== "disconnected",
    ) ||
    Boolean(
      cgmSources?.sources.some((source) => {
        const identity = `${source.source} ${source.label}`.toLowerCase();
        return (
          source.role !== "off" &&
          !["dexcom", "nightscout", "glooko"].some((knownSource) =>
            identity.includes(knownSource),
          )
        );
      }),
    );
  const hasConfiguredPump =
    Boolean(tandemIntegration && tandemIntegration.status !== "disconnected") ||
    nightscoutConnections.some(hasNightscoutPumpHint) ||
    Boolean(pumpStatus.basal || pumpStatus.battery || pumpStatus.reservoir);
  return (
    <PageTransition>
      <div className="max-w-full min-w-0 space-y-dashboard-panel-gap">
        <ConnectionStatusBanner
          isReconnecting={isReconnecting}
          hasError={!!error}
          errorMessage={error?.message}
          onReconnect={reconnect}
        />
        {/* One-time smart-default glucose-unit notice */}
        <GlucoseUnitSeedNotice />
        {/* Top status panels for live data and configured connections */}
        <AnimatedCard
          className="grid grid-cols-1 gap-dashboard-panel-gap lg:grid-cols-[minmax(0,1fr)_minmax(18rem,0.6fr)_minmax(0,1fr)]"
          delay={0.05}
        >
          <Panel
            disableHeaderMobile
            heading="Live CGM"
            bodyClassName="p-0 sm:p-0"
            className="min-w-0"
          >
            <GlucoseHero
              value={glucoseValue}
              trend={glucoseTrend}
              iob={iob}
              basalRate={pumpStatus.basal?.rate ?? null}
              batteryPct={pumpStatus.battery?.percentage ?? null}
              reservoirUnits={pumpStatus.reservoir?.units_remaining ?? null}
              timestamp={glucose?.reading_timestamp ?? null}
              isStale={glucose?.is_stale}
              cobGrams={pumpStatus.cobGrams}
              isLoading={!isLive && !glucose}
              embedded
              showPumpStats={false}
              thresholds={glucoseThresholds}
              unit={unit}
            />
          </Panel>
          <Panel disableHeaderMobile heading="Live Pump" className="min-w-0">
            <LivePumpStats
              iob={iob}
              basalRate={pumpStatus.basal?.rate ?? null}
              batteryPct={pumpStatus.battery?.percentage ?? null}
              reservoirUnits={pumpStatus.reservoir?.units_remaining ?? null}
              cobGrams={pumpStatus.cobGrams}
              // Closed-loop runtime state belongs with insulin delivery,
              // not with the CGM reading that helps drive the algorithm.
              loopStatus={mapLoopStatus(pumpStatus.loopStatus)}
              override={
                pumpStatus.override
                  ? {
                      name: pumpStatus.override.name,
                      startedAt: pumpStatus.override.started_at,
                      endsAt: pumpStatus.override.ends_at,
                      multiplier: pumpStatus.override.multiplier,
                      targetLowMgdl: pumpStatus.override.target_low_mgdl,
                      targetHighMgdl: pumpStatus.override.target_high_mgdl,
                    }
                  : null
              }
            />
          </Panel>
          <Panel
            disableHeaderMobile
            heading="Live Connections"
            className="hidden min-w-0 lg:block"
          >
            {sourcesLoadFailed ? (
              <div className="space-y-3">
                <p className="font_body_3 text-foreground-primary">
                  Connection status is unavailable.
                </p>
                <Link
                  href="/settings/connections"
                  className="font_metric_label text-foreground-primary underline underline-offset-4 hover:decoration-2"
                >
                  Settings / Integrations
                </Link>
              </div>
            ) : hasConnectionSources ? (
              <DataSourcesFreshnessCard
                cgmSources={cgmSources}
                cgmUpdatedAt={glucose?.reading_timestamp ?? null}
                nightscoutConnections={nightscoutConnections}
                dexcom={dexcomIntegration}
                embedded
                glooko={glookoStatus}
                medtronic={medtronicStatus}
                tandem={tandemIntegration}
              />
            ) : (
              <div className="space-y-3">
                <p className="font_body_3 text-foreground-primary">
                  No connected data sources yet.
                </p>
                <Link
                  href="/settings/connections"
                  className="font_metric_label text-foreground-primary underline underline-offset-4 hover:decoration-2"
                >
                  Settings / Integrations
                </Link>
              </div>
            )}
          </Panel>
        </AnimatedCard>
        <div
          className="sticky -top-dashboard-panel-gap z-30 -mx-dashboard-panel-gap flex h-dashboard-header-height items-center border-y border-border-default bg-surface-elevated px-dashboard-panel-gap shadow-sm"
          aria-label="Dashboard time range"
          role="group"
        >
          <div className="w-full">
            <div className="w-full lg:hidden">
              <DashboardTimeRangeQuickSelect
                ranges={["3h", "24h", "3d", "7d"]}
                selection={dashboardTimeRange.selection}
                timeZone={dashboardTimeRange.timeZone}
                onChange={dashboardTimeRange.setSelection}
              />
            </div>
            <div className="hidden lg:block">
              <DashboardTimeRangePicker
                selection={dashboardTimeRange.selection}
                currentWindow={dashboardTimeRange.currentWindow}
                timeZone={dashboardTimeRange.timeZone}
                maxRangeDays={31}
                onChange={dashboardTimeRange.setSelection}
              />
            </div>
          </div>
        </div>
        {/* Mobile glucose trend chart */}
        <AnimatedCard className="lg:hidden" delay={0.1}>
          <Panel
            disableHeaderMobile
            fullWidthMobile
            heading="Merged Glucose Trend"
            bodyClassName="p-0 sm:p-0"
            className="min-w-0"
          >
            <MergedGlucoseTrendChart
              forecast={forecast}
              refreshKey={chartRefreshKey}
              hasConfiguredPump={hasConfiguredPump}
              thresholds={glucoseThresholds}
              unit={unit}
            />
          </Panel>
        </AnimatedCard>
        {/* Desktop glucose trend chart */}
        <AnimatedCard className="hidden lg:block" delay={0.12}>
          <Panel
            heading="Glucose Trend"
            bodyClassName="p-0 sm:p-0"
            className="min-w-0"
          >
            <GlucoseTrendChart
              refreshKey={chartRefreshKey}
              hasConfiguredPump={hasConfiguredPump}
              thresholds={glucoseThresholds}
              forecast={forecast}
              unit={unit}
              embedded
            />
          </Panel>
        </AnimatedCard>
        {/* CGM and insulin summaries */}
        <AnimatedCard
          className="grid grid-cols-1 gap-dashboard-panel-gap lg:grid-cols-2"
          delay={0.15}
        >
          <CgmSummaryStats
            stats={cgmStats}
            isLoading={cgmLoading}
            error={cgmError}
            period={cgmPeriod}
            className="h-full"
            unit={unit}
            timeInRange={{
              buckets: tirStats?.buckets ?? null,
              readingsCount: tirStats?.readings_count ?? 0,
              previousBuckets: tirStats?.previous_buckets ?? null,
              previousReadingsCount: tirStats?.previous_readings_count ?? null,
              error: tirError,
              isLoading: tirLoading,
            }}
          />
          <InsulinSummaryStats className="h-full" />
        </AnimatedCard>
        <AnimatedCard delay={0.2}>
          <AgpChart thresholds={glucoseThresholds} unit={unit} />
        </AnimatedCard>
      </div>
    </PageTransition>
  );
}

export default function DashboardPage() {
  return <DashboardPageContent />;
}
