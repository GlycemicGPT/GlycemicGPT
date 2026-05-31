"use client";

import { useCallback, useEffect, useState } from "react";
import clsx from "clsx";
import {
  connectGlooko,
  disconnectGlooko,
  getGlookoStatus,
  getGlookoSyncAvailability,
  importGlookoHistory,
  syncGlookoNow,
  updateGlookoSyncSettings,
  type GlookoAvailability,
  type GlookoStatus,
  type GlookoSyncResult,
} from "@/lib/api";
import { PasswordInput } from "./integration-card";

/**
 * Omnipod via Glooko -- autonomous cloud sync.
 *
 * Omnipod 5 uploads to Glooko only, so Glooko is the onramp. Unlike Medtronic
 * Connect (whose mobile-app login needs a desktop helper), Glooko authenticates
 * with a plain web session, so the user connects directly with their Glooko
 * email + password and a required consent acknowledgment. The backend validates
 * the credentials live, stores them encrypted, and syncs on a schedule. The
 * credentials never come back to the browser.
 */

const MIN_INTERVAL = 15;
const MAX_INTERVAL = 1440;

// US is the supported default. EU is wired but unvalidated against a live
// account (the eu.api.glooko.com host is fragile upstream) -- it is offered but
// labeled so users know what they're choosing.
const REGIONS = [
  { code: "US", label: "United States" },
  { code: "EU", label: "Europe / International (experimental)" },
] as const;

function regionLabel(code: string | null | undefined): string {
  return REGIONS.find((r) => r.code === code)?.label ?? code ?? "";
}

export function GlookoSyncCard({ isOffline }: { isOffline: boolean }) {
  const [status, setStatus] = useState<GlookoStatus | null>(null);
  const [loaded, setLoaded] = useState(false);
  // True when the initial status fetch failed on a transport/auth error (the
  // endpoint returns 200 "not_configured" when there's simply no connection, so
  // an actual failure here is transient -- we show a retry, not the connect form).
  const [loadFailed, setLoadFailed] = useState(false);

  // Connect-form state.
  const [regionCode, setRegionCode] = useState<string>("US");
  const [email, setEmail] = useState<string>("");
  const [password, setPassword] = useState<string>("");
  const [acceptRisk, setAcceptRisk] = useState<boolean>(false);
  const [isConnecting, setIsConnecting] = useState(false);

  // Settings + actions state.
  const [interval, setIntervalMinutes] = useState<number>(30);
  const [enabled, setEnabled] = useState<boolean>(true);
  const [isSavingSettings, setIsSavingSettings] = useState(false);
  const [isSyncing, setIsSyncing] = useState(false);
  const [isImporting, setIsImporting] = useState(false);
  const [isDisconnecting, setIsDisconnecting] = useState(false);

  // CGM availability is fetched on demand (it does a live Glooko login), not on
  // mount -- auto-probing on every page visit would add credential-replay
  // traffic to Glooko on every render, which we'd rather keep minimal.
  const [availability, setAvailability] = useState<GlookoAvailability | null>(
    null
  );
  const [isCheckingAvailability, setIsCheckingAvailability] = useState(false);

  const [error, setError] = useState<string | null>(null);
  const [syncResult, setSyncResult] = useState<GlookoSyncResult | null>(null);

  const applyStatus = useCallback((s: GlookoStatus) => {
    setStatus(s);
    setEnabled(s.enabled);
    if (s.sync_interval_minutes) setIntervalMinutes(s.sync_interval_minutes);
  }, []);

  const loadStatus = useCallback(async () => {
    setLoadFailed(false);
    try {
      applyStatus(await getGlookoStatus());
    } catch {
      // 200 "not_configured" covers the no-connection case, so reaching here is
      // a transient transport/auth failure -- flag it instead of silently
      // rendering the connect form for a possibly-connected account.
      setLoadFailed(true);
    } finally {
      setLoaded(true);
    }
  }, [applyStatus]);

  useEffect(() => {
    void loadStatus();
  }, [loadStatus]);

  // "configured" = a row exists (any state). "needsReconnect" = the stored login
  // is no longer valid, so the user must re-enter credentials. A transient
  // "error" status keeps the connected controls (it's a retryable sync failure),
  // whereas "disconnected" sends the user back to the connect form.
  const configured = !!status && status.status !== "not_configured";
  const needsReconnect = status?.status === "disconnected";
  // When the initial load failed we can't tell connected from not-connected, so
  // show a retry rather than the connect form (which would imply not-connected).
  const showLoadError = loaded && loadFailed && !configured;
  const showConnectForm = loaded && !showLoadError && (!configured || needsReconnect);
  const showControls = loaded && configured && !needsReconnect && !!status;
  const isConnected = status?.status === "connected";

  const handleConnect = useCallback(async () => {
    setError(null);
    setSyncResult(null);
    const trimmedEmail = email.trim();
    if (!trimmedEmail || !password) {
      setError("Enter your Glooko email and password first.");
      return;
    }
    if (!acceptRisk) {
      setError("Please check the acknowledgment box before connecting.");
      return;
    }
    setIsConnecting(true);
    try {
      const s = await connectGlooko({
        email: trimmedEmail,
        password,
        region: regionCode,
        acceptRisk,
      });
      applyStatus(s);
      setAvailability(null);
      // Don't keep the password in component state after a successful connect.
      setPassword("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to connect Glooko");
    } finally {
      setIsConnecting(false);
    }
  }, [email, password, acceptRisk, regionCode, applyStatus]);

  const saveSettings = useCallback(async () => {
    setError(null);
    setIsSavingSettings(true);
    try {
      applyStatus(await updateGlookoSyncSettings(enabled, interval));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save settings");
    } finally {
      setIsSavingSettings(false);
    }
  }, [enabled, interval, applyStatus]);

  const syncNow = useCallback(async () => {
    setError(null);
    setSyncResult(null);
    setIsSyncing(true);
    try {
      setSyncResult(await syncGlookoNow());
      // The sync itself succeeded; a failed status refresh must not turn that
      // into "Sync failed". Refresh best-effort -- the status reloads anyway.
      try {
        applyStatus(await getGlookoStatus());
      } catch {
        /* keep the successful sync result */
      }
    } catch (e) {
      // A failed sync may have flipped the connection to disconnected; refresh so
      // the card reflects it instead of showing a stale "Connected" banner. When
      // it did disconnect, the reconnect prompt already explains it -- skip the
      // redundant error banner; otherwise surface the failure.
      try {
        const s = await getGlookoStatus();
        applyStatus(s);
        if (s.status !== "disconnected") {
          setError(e instanceof Error ? e.message : "Sync failed");
        }
      } catch {
        setError(e instanceof Error ? e.message : "Sync failed");
      }
    } finally {
      setIsSyncing(false);
    }
  }, [applyStatus]);

  const importHistory = useCallback(async () => {
    setError(null);
    setSyncResult(null);
    setIsImporting(true);
    try {
      setSyncResult(await importGlookoHistory());
      try {
        applyStatus(await getGlookoStatus());
      } catch {
        /* keep the successful import result */
      }
    } catch (e) {
      // Same as syncNow: refresh so a disconnect is reflected; when disconnected
      // the reconnect prompt covers it, so skip the redundant error banner.
      try {
        const s = await getGlookoStatus();
        applyStatus(s);
        if (s.status !== "disconnected") {
          setError(e instanceof Error ? e.message : "Import failed");
        }
      } catch {
        setError(e instanceof Error ? e.message : "Import failed");
      }
    } finally {
      setIsImporting(false);
    }
  }, [applyStatus]);

  // Read-only probe: authenticates and walks the CGM window but never mutates
  // the sync state. User-initiated so the live login only happens when asked.
  const checkAvailability = useCallback(async () => {
    setError(null);
    setIsCheckingAvailability(true);
    try {
      setAvailability(await getGlookoSyncAvailability());
    } catch (e) {
      setAvailability(null);
      setError(
        e instanceof Error ? e.message : "Failed to check available data"
      );
    } finally {
      setIsCheckingAvailability(false);
    }
  }, []);

  const disconnect = useCallback(async () => {
    setError(null);
    setIsDisconnecting(true);
    try {
      await disconnectGlooko();
      setStatus(null);
      setAvailability(null);
      setSyncResult(null);
      setAcceptRisk(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to disconnect");
    } finally {
      setIsDisconnecting(false);
    }
  }, []);

  const intervalValid =
    interval >= MIN_INTERVAL && interval <= MAX_INTERVAL && Number.isInteger(interval);

  const inputClass = clsx(
    "w-full rounded-lg border px-3 py-2 text-sm",
    "bg-slate-800 border-slate-700 text-slate-200 placeholder:text-slate-500",
    "focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent",
    "disabled:opacity-50 disabled:cursor-not-allowed"
  );
  const btnClass = clsx(
    "rounded-lg px-4 py-2 text-sm font-medium transition-colors",
    "bg-blue-600 hover:bg-blue-500 text-white",
    "disabled:opacity-50 disabled:cursor-not-allowed"
  );

  return (
    <div className="space-y-5 rounded-lg border border-slate-700 bg-slate-900/40 p-4">
      <div className="flex items-center gap-2">
        <p className="text-sm font-medium text-slate-200">
          Automatic sync (Omnipod via Glooko)
        </p>
      </div>
      <div className="space-y-2 text-sm text-slate-400">
        <p>
          Keep GlycemicGPT updated automatically from your Glooko account — the
          only place an Omnipod 5 uploads its data. Pulls basal, bolus, and pod
          changes; sensor glucose syncs too when your Omnipod streams it to
          Glooko.
        </p>
      </div>

      {/* ---- Initial status load failed (transient): offer a retry ---- */}
      {showLoadError && (
        <div className="space-y-2">
          <p className="text-sm text-slate-400">
            Couldn&apos;t load your Glooko connection status.
          </p>
          <button
            type="button"
            onClick={() => void loadStatus()}
            disabled={isOffline}
            className="rounded-lg border border-slate-600 px-4 py-2 text-sm font-medium text-slate-300 hover:bg-slate-800 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Retry
          </button>
        </div>
      )}

      {/* ---- Not connected (or login expired): direct email/password connect ---- */}
      {showConnectForm && (
        <form
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            void handleConnect();
          }}
        >
          {needsReconnect && (
            <div
              role="alert"
              className="rounded-md border border-amber-600/40 bg-amber-600/10 p-3 text-sm text-amber-300"
            >
              Your Glooko login is no longer valid. Re-enter your current Glooko
              password below to resume syncing.
              {status?.last_error ? ` (${status.last_error})` : ""}
            </div>
          )}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 max-w-md">
            <div>
              <label
                htmlFor="glooko-email"
                className="block text-sm font-medium text-slate-300 mb-1"
              >
                Glooko email
              </label>
              <input
                id="glooko-email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                disabled={isOffline || isConnecting}
                placeholder="you@example.com"
                autoComplete="email"
                className={inputClass}
              />
            </div>
            <div>
              <label
                htmlFor="glooko-region"
                className="block text-sm font-medium text-slate-300 mb-1"
              >
                Region
              </label>
              <select
                id="glooko-region"
                value={regionCode}
                onChange={(e) => setRegionCode(e.target.value)}
                disabled={isOffline || isConnecting}
                className={inputClass}
              >
                {REGIONS.map((r) => (
                  <option key={r.code} value={r.code}>
                    {r.label}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div className="max-w-md">
            <PasswordInput
              id="glooko-password"
              value={password}
              onChange={setPassword}
              disabled={isOffline || isConnecting}
              label="Glooko password"
            />
          </div>

          {/* Required acknowledgment: Glooko has no official app integration, so
              we sign in with the user's credentials. We ask them to confirm they
              understand this isn't officially supported before we store
              credentials and sync on their behalf. */}
          <div className="rounded-md border border-slate-700 bg-slate-800/40 p-3">
            <label className="flex items-start gap-2 text-sm text-slate-300">
              <input
                type="checkbox"
                checked={acceptRisk}
                onChange={(e) => setAcceptRisk(e.target.checked)}
                disabled={isOffline || isConnecting}
                className="mt-0.5 h-4 w-4 shrink-0"
              />
              <span>
                I understand that Glooko doesn&apos;t offer an official way for
                other apps to connect, so GlycemicGPT signs in with my Glooko
                credentials on my behalf. This isn&apos;t officially supported by
                Glooko, and I&apos;m connecting my own account by choice.
              </span>
            </label>
          </div>

          <button
            type="submit"
            disabled={
              isOffline ||
              isConnecting ||
              !email.trim() ||
              !password ||
              !acceptRisk
            }
            className={btnClass}
          >
            {isConnecting
              ? "Connecting…"
              : needsReconnect
                ? "Reconnect Glooko"
                : "Connect Glooko"}
          </button>
          <p className="text-xs text-slate-500">
            Your Glooko password is encrypted and stored only to keep the sync
            authorized — it is never shown back to you. Data flows one way: from
            Glooko into GlycemicGPT.
          </p>
        </form>
      )}

      {/* ---- Configured (connected, or a retryable error): status + controls ---- */}
      {showControls && status && (
        <div className="space-y-4">
          {isConnected ? (
            <div className="rounded-md border border-green-600/40 bg-green-600/10 p-3 text-sm text-green-300">
              ✓ Connected{status.region ? ` (${regionLabel(status.region)})` : ""}.
              Last sync:{" "}
              {status.last_sync_at
                ? new Date(status.last_sync_at).toLocaleString()
                : "not yet"}
              . Readings synced so far: {status.readings_synced_total ?? 0}.
            </div>
          ) : (
            <div
              role="alert"
              className="rounded-md border border-amber-600/40 bg-amber-600/10 p-3 text-sm text-amber-300"
            >
              The last sync didn&apos;t complete; GlycemicGPT will retry on the
              schedule. Last successful sync:{" "}
              {status.last_sync_at
                ? new Date(status.last_sync_at).toLocaleString()
                : "not yet"}
              .{status.last_error ? ` (${status.last_error})` : ""}
            </div>
          )}

          {/* Honest CGM availability: pump data syncs regardless, but sensor
              glucose depends on the account streaming it to Glooko. Fetched on
              demand to avoid an automatic live login on every page visit. */}
          <div className="space-y-2">
            <button
              type="button"
              onClick={checkAvailability}
              disabled={isOffline || isCheckingAvailability}
              className="rounded-lg border border-slate-600 px-3 py-1.5 text-xs font-medium text-slate-300 hover:bg-slate-800 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isCheckingAvailability ? "Checking…" : "Check CGM availability"}
            </button>
            {availability && (
              <div className="rounded-md border border-slate-700 bg-slate-800/40 p-3 text-xs text-slate-400">
                {availability.cgm_available ? (
                  <p>
                    Sensor glucose is available
                    {availability.earliest && availability.latest
                      ? ` (${new Date(
                          availability.earliest
                        ).toLocaleDateString()} – ${new Date(
                          availability.latest
                        ).toLocaleDateString()})`
                      : ""}
                    . Pump data (basal, bolus, pod changes) syncs as well.
                  </p>
                ) : (
                  <p>
                    Pump data (basal, bolus, pod changes) is connected. No sensor
                    glucose was found in your Glooko account yet — CGM data
                    appears here only if your Omnipod streams integrated CGM to
                    Glooko.
                  </p>
                )}
              </div>
            )}
          </div>

          <div className="flex flex-wrap items-end gap-4">
            <label className="flex items-center gap-2 text-sm text-slate-300">
              <input
                type="checkbox"
                checked={enabled}
                onChange={(e) => setEnabled(e.target.checked)}
                disabled={isOffline || isSavingSettings}
                className="h-4 w-4"
              />
              Automatic sync enabled
            </label>
            <div>
              <label
                htmlFor="glooko-interval"
                className="block text-xs text-slate-400 mb-1"
              >
                Sync every (minutes)
              </label>
              <input
                id="glooko-interval"
                type="number"
                min={MIN_INTERVAL}
                max={MAX_INTERVAL}
                step={1}
                value={interval}
                onChange={(e) => setIntervalMinutes(Number(e.target.value))}
                disabled={isOffline || isSavingSettings}
                className={clsx(inputClass, "w-28")}
              />
            </div>
            <button
              type="button"
              onClick={saveSettings}
              disabled={isOffline || isSavingSettings || !intervalValid}
              className={btnClass}
            >
              {isSavingSettings ? "Saving…" : "Save"}
            </button>
          </div>
          {!intervalValid && (
            <p className="text-xs text-amber-400">
              Choose an interval between {MIN_INTERVAL} and {MAX_INTERVAL} minutes.
            </p>
          )}

          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={syncNow}
              disabled={isOffline || isSyncing || isImporting}
              className={btnClass}
            >
              {isSyncing ? "Syncing…" : "Sync now"}
            </button>
            <button
              type="button"
              onClick={importHistory}
              disabled={isOffline || isImporting || isSyncing}
              className="rounded-lg border border-slate-600 px-4 py-2 text-sm font-medium text-slate-300 hover:bg-slate-800 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isImporting ? "Importing…" : "Import history (one-time)"}
            </button>
            <button
              type="button"
              onClick={disconnect}
              disabled={isOffline || isDisconnecting}
              className="rounded-lg border border-red-600/50 px-4 py-2 text-sm font-medium text-red-300 hover:bg-red-600/10 disabled:opacity-50"
            >
              {isDisconnecting ? "Disconnecting…" : "Disconnect"}
            </button>
          </div>
          <p className="text-xs text-slate-500">
            One-time import backfills history from before you connected; it can
            take a minute and is safe to run again (duplicates are skipped).
          </p>
        </div>
      )}

      {syncResult && (
        <div className="rounded-md border border-green-600/40 bg-green-600/10 p-3 text-sm text-green-300">
          ✓ Synced {syncResult.glucose_stored} new glucose readings and{" "}
          {syncResult.events_stored} pump events.
        </div>
      )}
      {error && (
        <div
          role="alert"
          className="rounded-md border border-red-600/40 bg-red-600/10 p-3 text-sm text-red-300"
        >
          {error}
        </div>
      )}
    </div>
  );
}
