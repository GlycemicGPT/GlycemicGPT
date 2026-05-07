"use client";

/**
 * Multi-source freshness card for the dashboard.
 *
 * Replaces the old single-row "Last Updated" card. Renders one row
 * per active data source (Nightscout connection, Dexcom integration,
 * Tandem integration) with its `last_synced_at` relative time + a
 * status pill colored by recency-vs-cadence.
 *
 * Color thresholds:
 * - Slate (Pending): never synced yet (NS `last_sync_status === "never"`
 *   or no `last_sync_at` for direct integrations).
 * - Green (Connected): within 2x sync interval. One missed tick is
 *   tolerated -- the scheduler tick is 1-min granularity + jitter.
 * - Amber (Lagging): 2x to 5x interval, OR `rate_limited` / `network`.
 * - Red (Stale/Error): >5x interval, OR `auth_failed` / `unreachable` /
 *   `error`.
 *
 * Direct integrations (Dexcom, Tandem) don't have a per-source
 * `sync_interval_minutes` -- they use a flat 15m amber / 60m red.
 *
 * Returns null when the user has no data sources configured -- no
 * orphan empty card on the dashboard.
 */

import { Database } from "lucide-react";
import clsx from "clsx";
import type {
  IntegrationResponse,
  NightscoutConnectionResponse,
  NightscoutSyncStatus,
} from "@/lib/api";

type StaleBand = "pending" | "fresh" | "lagging" | "stale";

const BAND_COLORS: Record<StaleBand, string> = {
  pending: "text-slate-500 bg-slate-500/10",
  fresh: "text-green-400 bg-green-500/10",
  lagging: "text-amber-400 bg-amber-500/10",
  stale: "text-red-400 bg-red-500/10",
};

const BAND_LABELS: Record<StaleBand, string> = {
  pending: "Pending",
  fresh: "Connected",
  lagging: "Lagging",
  stale: "Stale",
};

// Direct-integration thresholds (no per-source interval available).
const DIRECT_INTEGRATION_AMBER_MIN = 15;
const DIRECT_INTEGRATION_RED_MIN = 60;

function formatRelative(iso: string | null, now: number): string {
  if (!iso) return "never";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "unknown";
  const minutes = Math.floor((now - then) / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

function nightscoutBand(
  status: NightscoutSyncStatus,
  lastSyncedIso: string | null,
  syncIntervalMinutes: number,
  now: number
): StaleBand {
  if (status === "never") return "pending";
  if (status === "auth_failed" || status === "unreachable" || status === "error") {
    return "stale";
  }
  if (!lastSyncedIso) return "pending";
  const elapsedMin = (now - new Date(lastSyncedIso).getTime()) / 60_000;
  if (Number.isNaN(elapsedMin)) return "pending";
  if (status === "rate_limited" || status === "network") {
    // Network glitches -- amber regardless of recency.
    return "lagging";
  }
  if (elapsedMin > 5 * syncIntervalMinutes) return "stale";
  if (elapsedMin > 2 * syncIntervalMinutes) return "lagging";
  return "fresh";
}

function directBand(
  integration: IntegrationResponse,
  now: number
): StaleBand {
  if (integration.status === "error") return "stale";
  if (integration.status === "pending" || !integration.last_sync_at) {
    return "pending";
  }
  const elapsedMin =
    (now - new Date(integration.last_sync_at).getTime()) / 60_000;
  if (Number.isNaN(elapsedMin)) return "pending";
  if (elapsedMin > DIRECT_INTEGRATION_RED_MIN) return "stale";
  if (elapsedMin > DIRECT_INTEGRATION_AMBER_MIN) return "lagging";
  return "fresh";
}

function StatusPill({ band }: { band: StaleBand }) {
  return (
    <span
      className={clsx(
        "text-xs font-medium px-2 py-0.5 rounded-full",
        BAND_COLORS[band]
      )}
    >
      {BAND_LABELS[band]}
    </span>
  );
}

interface DataSourcesFreshnessCardProps {
  nightscoutConnections: NightscoutConnectionResponse[];
  dexcom: IntegrationResponse | null;
  tandem: IntegrationResponse | null;
  /**
   * Wall-clock "now" passed in from the parent. Hoisting this up
   * lets the parent advance it on a setInterval so the component
   * re-renders without needing to re-fetch from the server.
   */
  now: number;
}

export function DataSourcesFreshnessCard({
  nightscoutConnections,
  dexcom,
  tandem,
  now,
}: DataSourcesFreshnessCardProps) {
  // Only render NS connections that are active (the list endpoint
  // also returns deactivated rows for history -- those shouldn't
  // count as freshness sources).
  const activeNs = nightscoutConnections.filter((c) => c.is_active);

  const directRows: { key: string; label: string; band: StaleBand; relative: string; iso: string | null }[] = [];
  if (dexcom && dexcom.status !== "disconnected") {
    directRows.push({
      key: "dexcom",
      label: "Dexcom",
      band: directBand(dexcom, now),
      relative: formatRelative(dexcom.last_sync_at, now),
      iso: dexcom.last_sync_at,
    });
  }
  if (tandem && tandem.status !== "disconnected") {
    directRows.push({
      key: "tandem",
      label: "Tandem",
      band: directBand(tandem, now),
      relative: formatRelative(tandem.last_sync_at, now),
      iso: tandem.last_sync_at,
    });
  }

  const totalSources = directRows.length + activeNs.length;
  if (totalSources === 0) {
    // No configured sources -- don't render an orphan empty card.
    return null;
  }

  return (
    <article
      className="bg-white dark:bg-slate-900 rounded-xl p-6 border border-slate-200 dark:border-slate-800"
      aria-label="Data sources"
    >
      <div className="flex items-center gap-3 mb-3">
        <div className="p-2 bg-emerald-500/10 rounded-lg">
          <Database className="h-5 w-5 text-emerald-400" aria-hidden="true" />
        </div>
        <h3 className="text-slate-500 dark:text-slate-400 text-sm">
          Data Sources
        </h3>
      </div>
      <ul role="list" className="space-y-2">
        {directRows.map((row) => (
          <li
            key={row.key}
            data-testid={`freshness-row-${row.key}`}
            className="flex items-center justify-between gap-3 text-sm"
          >
            <span className="font-medium text-slate-700 dark:text-slate-200 truncate">
              {row.label}
            </span>
            <div className="flex items-center gap-2 shrink-0">
              <StatusPill band={row.band} />
              <span
                className="text-xs text-slate-500 dark:text-slate-400"
                title={row.iso ? new Date(row.iso).toLocaleString() : undefined}
              >
                {row.relative}
              </span>
            </div>
          </li>
        ))}
        {activeNs.map((conn) => {
          const band = nightscoutBand(
            conn.last_sync_status,
            conn.last_synced_at,
            conn.sync_interval_minutes,
            now
          );
          return (
            <li
              key={conn.id}
              data-testid={`freshness-row-nightscout-${conn.id}`}
              className="flex items-center justify-between gap-3 text-sm"
            >
              <span className="font-medium text-slate-700 dark:text-slate-200 truncate">
                {conn.name}
                <span className="ml-1 text-xs text-slate-500 dark:text-slate-400 font-normal">
                  (Nightscout)
                </span>
              </span>
              <div className="flex items-center gap-2 shrink-0">
                <StatusPill band={band} />
                <span
                  className="text-xs text-slate-500 dark:text-slate-400"
                  title={
                    conn.last_synced_at
                      ? new Date(conn.last_synced_at).toLocaleString()
                      : undefined
                  }
                >
                  {formatRelative(conn.last_synced_at, now)}
                </span>
              </div>
            </li>
          );
        })}
      </ul>
    </article>
  );
}
