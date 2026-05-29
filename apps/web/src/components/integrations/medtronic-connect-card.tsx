"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import clsx from "clsx";
import {
  disconnectMedtronicConnect,
  getMedtronicConnectStatus,
  installMedtronicConnect,
  syncMedtronicConnectNow,
  updateMedtronicConnectSettings,
  type MedtronicConnectInstall,
  type MedtronicConnectStatus,
  type MedtronicConnectSyncResult,
} from "@/lib/api";

/**
 * Medtronic CareLink CarePartner (Connect) -- autonomous sync.
 *
 * The one-time CarePartner login can't run in the web app: it redirects to a
 * mobile-app URL scheme (com.medtronic.carepartner:) that a browser/server
 * can't receive. So a small LOCAL desktop helper drives the login + captures
 * the auth code, authenticating to the backend with a short-lived pairing token
 * minted here. The backend exchanges the code for the refresh token and stores
 * it server-side; thereafter sync is fully automatic. The refresh token never
 * reaches the browser.
 */

const MIN_INTERVAL = 15;
const MAX_INTERVAL = 1440;
const POLL_MS = 4000;

// "EU" is Medtronic's catch-all for non-US CarePartner countries -- UK, EU
// member states, Australia, South Africa, etc. all share a single OUS Auth0
// tenant + cloud host. Picking the right region just selects which Auth0
// tenant the helper points your sign-in at.
const REGIONS = [
  { code: "US", label: "United States" },
  { code: "EU", label: "Europe / International (UK, EU, AU, …)" },
] as const;

type HelperOS = "linux-mac" | "windows";

function detectOS(): HelperOS {
  if (typeof navigator === "undefined") return "linux-mac";
  const ua = navigator.userAgent.toLowerCase();
  return ua.includes("win") ? "windows" : "linux-mac";
}

export function MedtronicConnectCard({ isOffline }: { isOffline: boolean }) {
  const [status, setStatus] = useState<MedtronicConnectStatus | null>(null);
  const [loaded, setLoaded] = useState(false);

  // Pairing flow state.
  const [regionCode, setRegionCode] = useState<string>("US");
  const [username, setUsername] = useState<string>("");
  const [pairing, setPairing] = useState<MedtronicConnectInstall | null>(null);
  const [isPairing, setIsPairing] = useState(false);
  const [copied, setCopied] = useState(false);

  // Settings + actions state.
  const [interval, setIntervalMinutes] = useState<number>(30);
  const [enabled, setEnabled] = useState<boolean>(true);
  const [isSavingSettings, setIsSavingSettings] = useState(false);
  const [isSyncing, setIsSyncing] = useState(false);
  const [isDisconnecting, setIsDisconnecting] = useState(false);

  const [error, setError] = useState<string | null>(null);
  const [syncResult, setSyncResult] = useState<MedtronicConnectSyncResult | null>(
    null
  );

  const applyStatus = useCallback((s: MedtronicConnectStatus) => {
    setStatus(s);
    setEnabled(s.enabled);
    if (s.sync_interval_minutes) setIntervalMinutes(s.sync_interval_minutes);
  }, []);

  const connected = !!status?.connected;

  // The URL the user typed to reach the dashboard -- the only URL we can be
  // sure is reachable from whatever machine they'll run the helper on (because
  // they just reached it that way). Editable for the rare split-origin
  // deployment where the API is at a different URL than the web app.
  const [instanceUrl, setInstanceUrl] = useState<string>(() =>
    typeof window !== "undefined" ? window.location.origin : ""
  );
  const [selectedOS, setSelectedOS] = useState<HelperOS>(() => detectOS());

  useEffect(() => {
    let cancelled = false;
    getMedtronicConnectStatus()
      .then((s) => {
        if (!cancelled) applyStatus(s);
      })
      .catch(() => {
        /* not configured / unauth -- treated as not connected */
      })
      .finally(() => {
        if (!cancelled) setLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, [applyStatus]);

  // While a pairing is pending, poll for the CLI to complete the connection.
  // Stop once the pairing token has expired (the token is useless after that),
  // so an abandoned pairing doesn't poll forever.
  useEffect(() => {
    if (!pairing || connected) return;
    const expiresAtMs = Date.parse(pairing.expires_at);
    const id = setInterval(async () => {
      if (Number.isFinite(expiresAtMs) && Date.now() > expiresAtMs) {
        setPairing(null);
        setError("Pairing token expired before connecting. Get a new one.");
        return;
      }
      try {
        const s = await getMedtronicConnectStatus();
        if (s.connected) {
          applyStatus(s);
          setPairing(null);
        }
      } catch {
        /* keep polling */
      }
    }, POLL_MS);
    return () => clearInterval(id);
  }, [pairing, connected, applyStatus]);

  const startPairing = useCallback(async () => {
    setError(null);
    setSyncResult(null);
    const trimmedUser = username.trim();
    const trimmedApi = instanceUrl.trim();
    if (!trimmedUser) {
      setError("Enter your CareLink username first.");
      return;
    }
    if (!trimmedApi) {
      setError("Enter the URL of your GlycemicGPT instance first.");
      return;
    }
    setIsPairing(true);
    try {
      setPairing(
        await installMedtronicConnect({
          apiUrl: trimmedApi,
          username: trimmedUser,
          region: regionCode,
        })
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to start pairing");
    } finally {
      setIsPairing(false);
    }
  }, [username, instanceUrl, regionCode]);

  // The primary command: a one-liner that downloads our native Go helper from
  // THIS instance and runs it. Uses the short-handle install endpoint, so the
  // copy-paste line is ~80 chars instead of the ~540 char form that inlined
  // the full Fernet pair token. The handle indexes a server-side bundle that
  // holds the same {pair, api, username, region}, with the same single-use
  // gate as the long URL form.
  const nativeCommand = useMemo(() => {
    const base = instanceUrl.trim();
    if (!pairing || !base) return "";
    const ext = selectedOS === "windows" ? "ps1" : "sh";
    let url: string;
    try {
      // Runs during render -- a malformed/whitespace-padded instance URL would
      // otherwise throw here and take down the whole settings page.
      url = new URL(
        `/api/integrations/medtronic/connect/install/${pairing.handle}.${ext}`,
        base
      ).toString();
    } catch {
      return "";
    }
    if (selectedOS === "windows") {
      // PowerShell single-quoted; the URL has no ' so no doubling needed.
      return `iwr '${url}' -UseBasicParsing | iex`;
    }
    return `curl -fsSL '${url}' | bash`;
  }, [pairing, instanceUrl, selectedOS]);

  // Non-empty but unparseable instance URL -> show an inline error instead of
  // silently rendering no command (and never throw during render).
  const instanceUrlInvalid = useMemo(() => {
    const t = instanceUrl.trim();
    if (!t) return false;
    try {
      new URL(t);
      return false;
    } catch {
      return true;
    }
  }, [instanceUrl]);

  // Advanced fallback for users who'd rather run the in-tree Python CLI than
  // download a binary -- same backend endpoints, same flow, just heavier deps.
  const pythonCommand = useMemo(() => {
    if (!pairing) return "";
    const q = (s: string) => `'${s.replace(/'/g, "'\\''")}'`;
    const api = q(instanceUrl || "https://your-glycemicgpt-instance");
    const user = q(username.trim());
    const pair = q(pairing.pairing_token);
    const region = q(regionCode);
    return [
      "uv run tools/medtronic-connect-login/medtronic_connect_login.py \\",
      `  --api ${api} \\`,
      `  --pair ${pair} \\`,
      `  --username ${user} \\`,
      `  --region ${region}`,
    ].join("\n");
  }, [pairing, instanceUrl, username, regionCode]);

  const copyCommand = useCallback(() => {
    if (!navigator.clipboard) return;
    navigator.clipboard.writeText(nativeCommand).then(
      () => {
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      },
      () => {}
    );
  }, [nativeCommand]);

  const saveSettings = useCallback(async () => {
    setError(null);
    setIsSavingSettings(true);
    try {
      applyStatus(await updateMedtronicConnectSettings(enabled, interval));
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
      setSyncResult(await syncMedtronicConnectNow());
      applyStatus(await getMedtronicConnectStatus());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Sync failed");
    } finally {
      setIsSyncing(false);
    }
  }, [applyStatus]);

  const disconnect = useCallback(async () => {
    setError(null);
    setIsDisconnecting(true);
    try {
      await disconnectMedtronicConnect();
      setStatus(null);
      setPairing(null);
      setSyncResult(null);
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
          Automatic sync (CareLink CarePartner)
        </p>
      </div>
      <div className="space-y-2 text-sm text-slate-400">
        <p>
          Keep GlycemicGPT updated automatically from Medtronic&apos;s CareLink
          CarePartner service — no cables, and no need to import by hand.
          CarePartner reports recent data (about the last 24 hours); GlycemicGPT
          keeps a rolling history as it syncs.
        </p>
      </div>

      {/* ---- Not connected: pair with the local desktop helper ---- */}
      {loaded && !connected && (
        <div className="space-y-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 max-w-md">
            <div>
              <label
                htmlFor="connect-region"
                className="block text-sm font-medium text-slate-300 mb-1"
              >
                Region
              </label>
              <select
                id="connect-region"
                value={regionCode}
                onChange={(e) => setRegionCode(e.target.value)}
                disabled={isOffline || !!pairing}
                className={inputClass}
              >
                {REGIONS.map((r) => (
                  <option key={r.code} value={r.code}>
                    {r.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label
                htmlFor="connect-username"
                className="block text-sm font-medium text-slate-300 mb-1"
              >
                CareLink username
              </label>
              <input
                id="connect-username"
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                // Frozen once a pairing token is minted: the bundle was created
                // with this username, so editing it now would desync the
                // displayed setup command from the server-side bundle.
                disabled={isOffline || !!pairing}
                placeholder="your CareLink username"
                autoComplete="username"
                className={inputClass}
              />
            </div>
          </div>
          <p className="text-xs text-slate-500">
            UK and other non-US accounts: pick &quot;Europe / International.&quot;
            One Medtronic OUS account covers the whole region.
          </p>

          {!pairing ? (
            <div className="space-y-2">
              <button
                type="button"
                onClick={startPairing}
                disabled={isOffline || isPairing || !username.trim()}
                className={btnClass}
              >
                {isPairing ? "Preparing…" : "Connect with CareLink"}
              </button>
              <p className="text-xs text-slate-500">
                Medtronic&apos;s sign-in only works in a browser on your
                computer, so connecting uses a one-time setup command you run
                on your own machine. GlycemicGPT never sees your CareLink or
                GlycemicGPT password.
              </p>
            </div>
          ) : (
            <div className="space-y-3">
              <p className="text-sm font-medium text-slate-300">
                Run the setup command
              </p>

              {/* Editable instance URL (default: window.location.origin). */}
              <div>
                <label
                  htmlFor="connect-instance-url"
                  className="block text-xs font-medium text-slate-400 mb-1"
                >
                  Your GlycemicGPT URL
                </label>
                <input
                  id="connect-instance-url"
                  type="text"
                  value={instanceUrl}
                  onChange={(e) => setInstanceUrl(e.target.value)}
                  className={clsx(inputClass, "max-w-md")}
                  spellCheck={false}
                  aria-invalid={instanceUrlInvalid}
                />
                {instanceUrlInvalid ? (
                  <p className="mt-1 text-xs text-red-400">
                    That doesn&apos;t look like a valid URL. Include the scheme,
                    e.g. https://glycemicgpt.example.com.
                  </p>
                ) : (
                  <p className="mt-1 text-xs text-slate-500">
                    Auto-detected from your address bar. Only edit this if your
                    API is at a different URL than this dashboard.
                  </p>
                )}
              </div>

              {/* OS picker. */}
              <div className="inline-flex rounded-md border border-slate-700 overflow-hidden">
                {(
                  [
                    { v: "linux-mac" as const, label: "macOS / Linux" },
                    { v: "windows" as const, label: "Windows" },
                  ] as const
                ).map((o) => (
                  <button
                    key={o.v}
                    type="button"
                    onClick={() => setSelectedOS(o.v)}
                    className={clsx(
                      "px-3 py-1.5 text-sm",
                      selectedOS === o.v
                        ? "bg-blue-600 text-white"
                        : "bg-slate-900 text-slate-300 hover:bg-slate-800"
                    )}
                  >
                    {o.label}
                  </button>
                ))}
              </div>

              <p className="text-xs text-slate-500">
                Paste this one line into a terminal on your computer. It runs
                a small one-time connector from your own GlycemicGPT, opens
                your browser to CareLink, and connects automatically. No
                installs; requires Chrome, Edge, Brave, or Chromium.
              </p>

              <pre className="overflow-x-auto rounded-md border border-slate-700 bg-slate-950 p-3 text-xs text-slate-200">
                {nativeCommand}
              </pre>

              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={copyCommand}
                  className="rounded-md border border-slate-600 px-3 py-1.5 text-sm text-slate-300 hover:bg-slate-800"
                >
                  {copied ? "Copied!" : "Copy command"}
                </button>
                <button
                  type="button"
                  onClick={startPairing}
                  disabled={isPairing}
                  className="rounded-md border border-slate-600 px-3 py-1.5 text-sm text-slate-300 hover:bg-slate-800"
                >
                  New token
                </button>
                <span className="inline-flex items-center gap-2 text-xs text-slate-500">
                  <span className="h-2 w-2 animate-pulse rounded-full bg-blue-400" />
                  Waiting for the helper to finish…
                </span>
              </div>

              <details className="text-xs text-slate-500">
                <summary className="cursor-pointer hover:text-slate-300">
                  Advanced — Python CLI (requires uv + Playwright on your machine)
                </summary>
                <pre className="mt-2 overflow-x-auto rounded-md border border-slate-700 bg-slate-950 p-3 text-slate-200">
                  {pythonCommand}
                </pre>
                <p className="mt-1">
                  Equivalent flow using the in-tree Python helper. Useful for
                  devs / Firefox-only users; otherwise prefer the one-liner above.
                </p>
              </details>

              <p className="text-xs text-slate-500">
                The pairing token is short-lived (~15 min). A browser opens —
                sign in to CareLink and solve the captcha. This page updates
                automatically when it connects. If the token expires, click
                &quot;New token&quot;.
              </p>
            </div>
          )}
        </div>
      )}

      {/* ---- Connected: status + controls ---- */}
      {loaded && connected && status && (
        <div className="space-y-4">
          <div className="rounded-md border border-green-600/40 bg-green-600/10 p-3 text-sm text-green-300">
            ✓ Connected ({status.region}). Last sync:{" "}
            {status.last_sync_at
              ? new Date(status.last_sync_at).toLocaleString()
              : "not yet"}
            . Readings synced so far: {status.readings_synced_total}.
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
                htmlFor="connect-interval"
                className="block text-xs text-slate-400 mb-1"
              >
                Sync every (minutes)
              </label>
              <input
                id="connect-interval"
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
              disabled={isOffline || isSyncing}
              className={btnClass}
            >
              {isSyncing ? "Syncing…" : "Sync now"}
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

          {status.last_error && (
            <p className="text-xs text-amber-400">
              Last sync issue: {status.last_error}
            </p>
          )}
        </div>
      )}

      {syncResult && (
        <div className="rounded-md border border-green-600/40 bg-green-600/10 p-3 text-sm text-green-300">
          ✓ Synced {syncResult.glucose_stored} new glucose readings and{" "}
          {syncResult.events_stored} pump events.
        </div>
      )}
      {error && (
        <div className="rounded-md border border-red-600/40 bg-red-600/10 p-3 text-sm text-red-300">
          {error}
        </div>
      )}
    </div>
  );
}
