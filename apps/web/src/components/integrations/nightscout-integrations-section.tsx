"use client";

import { useState, type FormEvent } from "react";
import {
  Cloud,
  Link2,
  Unlink,
  Loader2,
  Wifi,
  AlertTriangle,
  Check,
  Eye,
  EyeOff,
  RefreshCw,
} from "lucide-react";
import clsx from "clsx";
import { CollapsibleSection } from "@/components/ui/collapsible-section";
import type {
  NightscoutApiVersion,
  NightscoutAuthType,
  NightscoutConnectionCreate,
  NightscoutConnectionResponse,
  NightscoutConnectionTestResult,
  NightscoutManualSyncResponse,
  NightscoutSyncStatus,
} from "@/lib/api";

const SYNC_STATUS_LABEL: Record<NightscoutSyncStatus, string> = {
  ok: "Connected",
  error: "Error",
  auth_failed: "Auth Failed",
  rate_limited: "Rate Limited",
  network: "Network Error",
  unknown: "Pending",
};

const SYNC_STATUS_COLOR: Record<NightscoutSyncStatus, string> = {
  ok: "text-green-400 bg-green-500/10",
  error: "text-red-400 bg-red-500/10",
  auth_failed: "text-red-400 bg-red-500/10",
  rate_limited: "text-amber-400 bg-amber-500/10",
  network: "text-amber-400 bg-amber-500/10",
  unknown: "text-slate-500 bg-slate-500/10",
};

function SyncStatusBadge({ status }: { status: NightscoutSyncStatus }) {
  return (
    <span
      className={clsx(
        "ml-2 text-xs font-medium px-2 py-0.5 rounded-full",
        SYNC_STATUS_COLOR[status]
      )}
    >
      {SYNC_STATUS_LABEL[status]}
    </span>
  );
}

function formatRelative(iso: string | null): string {
  if (!iso) return "never";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "unknown";
  // floor not round so 59 minutes stays "59m ago" instead of jumping to "1h"
  const minutes = Math.floor((Date.now() - then) / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

interface NightscoutIntegrationsSectionProps {
  connections: NightscoutConnectionResponse[];
  isOffline: boolean;
  onCreate: (body: NightscoutConnectionCreate) => Promise<void>;
  onDelete: (connectionId: string) => Promise<void>;
  onTest: (connectionId: string) => Promise<NightscoutConnectionTestResult>;
  onSync: (connectionId: string) => Promise<NightscoutManualSyncResponse>;
}

export function NightscoutIntegrationsSection({
  connections,
  isOffline,
  onCreate,
  onDelete,
  onTest,
  onSync,
}: NightscoutIntegrationsSectionProps) {
  const [name, setName] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [credential, setCredential] = useState("");
  const [credentialVisible, setCredentialVisible] = useState(false);
  const [authType, setAuthType] = useState<NightscoutAuthType>("auto");
  const [apiVersion, setApiVersion] = useState<NightscoutApiVersion>("auto");
  const [isCreating, setIsCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [syncingId, setSyncingId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [perConnectionResult, setPerConnectionResult] = useState<
    Record<string, { ok: boolean; message: string }>
  >({});

  const handleCreate = async (e: FormEvent) => {
    e.preventDefault();
    if (isCreating) return;
    setCreateError(null);
    if (!name.trim() || !baseUrl.trim() || !credential.trim()) {
      setCreateError("Name, base URL, and credential are all required");
      return;
    }
    setIsCreating(true);
    try {
      await onCreate({
        name: name.trim(),
        base_url: baseUrl.trim(),
        credential,
        auth_type: authType,
        api_version: apiVersion,
      });
      setName("");
      setBaseUrl("");
      setCredential("");
      setAuthType("auto");
      setApiVersion("auto");
    } catch (err) {
      setCreateError(
        err instanceof Error ? err.message : "Failed to create connection"
      );
    } finally {
      setIsCreating(false);
    }
  };

  const handleTest = async (connectionId: string) => {
    setTestingId(connectionId);
    setPerConnectionResult((prev) => {
      const { [connectionId]: _drop, ...rest } = prev;
      return rest;
    });
    try {
      const result = await onTest(connectionId);
      setPerConnectionResult((prev) => ({
        ...prev,
        [connectionId]: {
          ok: result.ok,
          message: result.ok
            ? `Connected${result.server_version ? ` (Nightscout ${result.server_version})` : ""}`
            : result.error || "Connection test failed",
        },
      }));
    } catch (err) {
      setPerConnectionResult((prev) => ({
        ...prev,
        [connectionId]: {
          ok: false,
          message: err instanceof Error ? err.message : "Test failed",
        },
      }));
    } finally {
      setTestingId(null);
    }
  };

  const handleSync = async (connectionId: string) => {
    setSyncingId(connectionId);
    setPerConnectionResult((prev) => {
      const { [connectionId]: _drop, ...rest } = prev;
      return rest;
    });
    try {
      const result = await onSync(connectionId);
      const inserted =
        result.entries_inserted +
        result.treatments_inserted_pump +
        result.treatments_inserted_glucose +
        result.devicestatuses_inserted;
      const failed =
        result.entries_failed +
        result.treatments_failed +
        result.devicestatuses_failed;
      const buildSuccess = () => {
        const parts = [
          inserted > 0
            ? `${inserted} new row${inserted === 1 ? "" : "s"}`
            : "already up to date",
        ];
        if (failed > 0) {
          parts.push(`${failed} record${failed === 1 ? "" : "s"} rejected`);
        }
        return `Synced — ${parts.join("; ")} (${result.duration_ms}ms)`;
      };
      setPerConnectionResult((prev) => ({
        ...prev,
        [connectionId]: {
          ok: result.status === "ok" && failed === 0,
          message:
            result.status === "ok"
              ? buildSuccess()
              : result.error || `Sync failed (${result.status})`,
        },
      }));
    } catch (err) {
      setPerConnectionResult((prev) => ({
        ...prev,
        [connectionId]: {
          ok: false,
          message: err instanceof Error ? err.message : "Sync failed",
        },
      }));
    } finally {
      setSyncingId(null);
    }
  };

  const handleDelete = async (connectionId: string) => {
    setDeletingId(connectionId);
    try {
      await onDelete(connectionId);
      // Drop any in-memory test result for the deleted connection so the
      // entry doesn't leak in component state until unmount.
      setPerConnectionResult((prev) => {
        const { [connectionId]: _drop, ...rest } = prev;
        return rest;
      });
      setConfirmDeleteId(null);
    } catch (err) {
      // Surface the failure inline so the user knows the row did NOT
      // go away. The card stays visible (no refetch happened yet) and
      // the confirm dialog stays open so they can retry without
      // re-opening it.
      setPerConnectionResult((prev) => ({
        ...prev,
        [connectionId]: {
          ok: false,
          message:
            err instanceof Error
              ? err.message
              : "Failed to delete connection",
        },
      }));
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <CollapsibleSection title="Third-Party Integrations" icon={Cloud}>
      <div className="space-y-4">
        <CollapsibleSection
          title="Nightscout"
          variant="subsection"
          badge={
            <span className="ml-2 text-xs font-medium text-slate-500">
              {connections.length} connection
              {connections.length === 1 ? "" : "s"}
            </span>
          }
        >
          <div className="space-y-4">
            <p className="text-xs text-slate-500 dark:text-slate-400">
              Nightscout is an independent open-source project, not a
              GlycemicGPT product. If you already self-host (or use a hosted)
              Nightscout instance, you can point GlycemicGPT at it to pull
              glucose readings, insulin events, and pump data. Multiple
              connections are supported (e.g. one per family member or per
              uploader).
            </p>

            {connections.length > 0 && (
              <ul
                role="list"
                aria-label="Nightscout connections"
                className="space-y-3"
                data-testid="nightscout-connections-list"
              >
                {connections.map((conn) => {
                  const result = perConnectionResult[conn.id];
                  const showConfirm = confirmDeleteId === conn.id;
                  return (
                    <li
                      key={conn.id}
                      data-testid={`nightscout-connection-${conn.id}`}
                      className="bg-white dark:bg-slate-900 rounded-lg p-4 border border-slate-200 dark:border-slate-800"
                    >
                      <div className="flex items-start justify-between gap-4 flex-wrap">
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2 flex-wrap">
                            <Wifi className="h-4 w-4 text-slate-500 shrink-0" />
                            <span className="font-medium text-slate-700 dark:text-slate-200 truncate">
                              {conn.name}
                            </span>
                            <SyncStatusBadge status={conn.last_sync_status} />
                          </div>
                          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1 truncate">
                            {conn.base_url}
                          </p>
                          <div className="text-xs text-slate-500 dark:text-slate-400 mt-1 flex gap-3 flex-wrap">
                            <span>
                              Last sync:{" "}
                              {conn.last_synced_at ? (
                                <time
                                  dateTime={conn.last_synced_at}
                                  title={new Date(
                                    conn.last_synced_at
                                  ).toLocaleString()}
                                >
                                  {formatRelative(conn.last_synced_at)}
                                </time>
                              ) : (
                                "never"
                              )}
                            </span>
                            <span>Every {conn.sync_interval_minutes} min</span>
                            <span>
                              {conn.api_version === "auto"
                                ? "Auto API"
                                : `API ${conn.api_version}`}
                            </span>
                          </div>
                          {conn.last_sync_error && (
                            <p
                              className="text-xs text-red-400 mt-1"
                              role="status"
                            >
                              {conn.last_sync_error}
                            </p>
                          )}
                        </div>
                        <div className="flex gap-2 shrink-0">
                          <button
                            type="button"
                            onClick={() => handleSync(conn.id)}
                            disabled={isOffline || syncingId === conn.id}
                            data-testid={`nightscout-sync-${conn.id}`}
                            className={clsx(
                              "px-3 py-1.5 rounded-lg text-xs font-medium",
                              "border border-blue-500/30 text-blue-400",
                              "hover:bg-blue-500/10",
                              "disabled:opacity-50 disabled:cursor-not-allowed",
                              "transition-colors flex items-center gap-1"
                            )}
                          >
                            {syncingId === conn.id ? (
                              <Loader2 className="h-3 w-3 animate-spin" />
                            ) : (
                              <RefreshCw className="h-3 w-3" />
                            )}
                            Sync now
                          </button>
                          <button
                            type="button"
                            onClick={() => handleTest(conn.id)}
                            disabled={isOffline || testingId === conn.id}
                            data-testid={`nightscout-test-${conn.id}`}
                            className={clsx(
                              "px-3 py-1.5 rounded-lg text-xs font-medium",
                              "border border-slate-300 dark:border-slate-700",
                              "text-slate-700 dark:text-slate-300",
                              "hover:bg-slate-100 dark:hover:bg-slate-800",
                              "disabled:opacity-50 disabled:cursor-not-allowed",
                              "transition-colors flex items-center gap-1"
                            )}
                          >
                            {testingId === conn.id ? (
                              <Loader2 className="h-3 w-3 animate-spin" />
                            ) : (
                              <Link2 className="h-3 w-3" />
                            )}
                            Test
                          </button>
                          <button
                            type="button"
                            onClick={() => setConfirmDeleteId(conn.id)}
                            disabled={isOffline || deletingId === conn.id}
                            data-testid={`nightscout-delete-${conn.id}`}
                            className={clsx(
                              "px-3 py-1.5 rounded-lg text-xs font-medium",
                              "border border-red-500/30 text-red-400",
                              "hover:bg-red-500/10",
                              "disabled:opacity-50 disabled:cursor-not-allowed",
                              "transition-colors flex items-center gap-1"
                            )}
                          >
                            {deletingId === conn.id ? (
                              <Loader2 className="h-3 w-3 animate-spin" />
                            ) : (
                              <Unlink className="h-3 w-3" />
                            )}
                            Delete
                          </button>
                        </div>
                      </div>

                      {showConfirm && (
                        <div
                          role="alertdialog"
                          aria-label={`Confirm delete connection ${conn.name}`}
                          className="mt-3 px-3 py-3 rounded-lg bg-red-500/5 border border-red-500/30"
                        >
                          <p className="text-xs text-slate-700 dark:text-slate-200 mb-3">
                            Delete <strong>{conn.name}</strong>? Historical data
                            already imported is preserved; only future syncs
                            stop.
                          </p>
                          <div className="flex gap-2">
                            <button
                              type="button"
                              onClick={() => handleDelete(conn.id)}
                              disabled={deletingId === conn.id}
                              data-testid={`nightscout-confirm-delete-${conn.id}`}
                              className={clsx(
                                "px-3 py-1.5 rounded-lg text-xs font-medium",
                                "bg-red-500 text-white hover:bg-red-400",
                                "disabled:opacity-50 disabled:cursor-not-allowed",
                                "transition-colors flex items-center gap-1"
                              )}
                            >
                              {deletingId === conn.id ? (
                                <Loader2 className="h-3 w-3 animate-spin" />
                              ) : null}
                              Delete connection
                            </button>
                            <button
                              type="button"
                              onClick={() => setConfirmDeleteId(null)}
                              disabled={deletingId === conn.id}
                              className={clsx(
                                "px-3 py-1.5 rounded-lg text-xs font-medium",
                                "border border-slate-300 dark:border-slate-700",
                                "text-slate-700 dark:text-slate-300",
                                "hover:bg-slate-100 dark:hover:bg-slate-800",
                                "disabled:opacity-50 disabled:cursor-not-allowed",
                                "transition-colors"
                              )}
                            >
                              Cancel
                            </button>
                          </div>
                        </div>
                      )}

                      {/* Always-mounted live region so screen readers
                          register it before the first async insertion. */}
                      <div
                        role="status"
                        aria-live="polite"
                        aria-atomic="true"
                        className={clsx(
                          result &&
                            "mt-3 px-3 py-2 rounded-lg text-xs flex items-center gap-2",
                          result?.ok && "bg-green-500/10 text-green-400",
                          result && !result.ok && "bg-red-500/10 text-red-400"
                        )}
                      >
                        {result && (
                          <>
                            {result.ok ? (
                              <Check className="h-3 w-3 shrink-0" />
                            ) : (
                              <AlertTriangle className="h-3 w-3 shrink-0" />
                            )}
                            <span>{result.message}</span>
                          </>
                        )}
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}

            <form
              onSubmit={handleCreate}
              className="bg-slate-50 dark:bg-slate-900 rounded-lg p-4 border border-slate-200 dark:border-slate-800"
              aria-label="Add a Nightscout connection"
            >
              <h4 className="text-sm font-medium text-slate-700 dark:text-slate-200 mb-3">
                Add a Nightscout connection
              </h4>
              <div className="space-y-3">
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div>
                    <label
                      htmlFor="ns-name"
                      className="block text-sm font-medium text-slate-600 dark:text-slate-300 mb-1"
                    >
                      Name
                    </label>
                    <input
                      id="ns-name"
                      type="text"
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                      disabled={isCreating}
                      placeholder="e.g. Home Loop, Spouse, ..."
                      className={clsx(
                        "w-full rounded-lg border px-3 py-2 text-sm",
                        "bg-white dark:bg-slate-800",
                        "border-slate-300 dark:border-slate-700",
                        "text-slate-700 dark:text-slate-200",
                        "placeholder:text-slate-400 dark:placeholder:text-slate-500",
                        "focus:outline-none focus:ring-2 focus:ring-blue-500",
                        "disabled:opacity-50 disabled:cursor-not-allowed"
                      )}
                    />
                  </div>
                  <div>
                    <label
                      htmlFor="ns-url"
                      className="block text-sm font-medium text-slate-600 dark:text-slate-300 mb-1"
                    >
                      Nightscout URL
                    </label>
                    <input
                      id="ns-url"
                      type="url"
                      value={baseUrl}
                      onChange={(e) => setBaseUrl(e.target.value)}
                      disabled={isCreating}
                      placeholder="https://my-ns.example.com"
                      autoComplete="off"
                      className={clsx(
                        "w-full rounded-lg border px-3 py-2 text-sm",
                        "bg-white dark:bg-slate-800",
                        "border-slate-300 dark:border-slate-700",
                        "text-slate-700 dark:text-slate-200",
                        "placeholder:text-slate-400 dark:placeholder:text-slate-500",
                        "focus:outline-none focus:ring-2 focus:ring-blue-500",
                        "disabled:opacity-50 disabled:cursor-not-allowed"
                      )}
                    />
                  </div>
                </div>
                <div>
                  <label
                    htmlFor="ns-credential"
                    className="block text-sm font-medium text-slate-600 dark:text-slate-300 mb-1"
                  >
                    API_SECRET or bearer token
                  </label>
                  <div className="relative">
                    <input
                      id="ns-credential"
                      type={credentialVisible ? "text" : "password"}
                      value={credential}
                      onChange={(e) => setCredential(e.target.value)}
                      disabled={isCreating}
                      // Not a browser/OS login credential — opt out of
                      // password-manager autofill and OS keychain capture.
                      autoComplete="off"
                      spellCheck={false}
                      data-1p-ignore=""
                      data-lpignore="true"
                      className={clsx(
                        "w-full rounded-lg border px-3 py-2 pr-10 text-sm",
                        "bg-slate-100 dark:bg-slate-800",
                        "border-slate-300 dark:border-slate-700",
                        "text-slate-700 dark:text-slate-200",
                        "focus:outline-none focus:ring-2 focus:ring-blue-500",
                        "disabled:opacity-50 disabled:cursor-not-allowed"
                      )}
                    />
                    <button
                      type="button"
                      onClick={() => setCredentialVisible(!credentialVisible)}
                      className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-slate-500 dark:text-slate-400 hover:text-slate-600 dark:hover:text-slate-300"
                      aria-label={
                        credentialVisible
                          ? "Hide credential"
                          : "Show credential"
                      }
                    >
                      {credentialVisible ? (
                        <EyeOff className="h-4 w-4" />
                      ) : (
                        <Eye className="h-4 w-4" />
                      )}
                    </button>
                  </div>
                  <p className="text-xs text-slate-500 mt-1">
                    Use the Nightscout API_SECRET (the longer string from your
                    instance config) or a bearer token issued by your Nightscout
                    deployment.
                  </p>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div>
                    <label
                      htmlFor="ns-auth-type"
                      className="block text-sm font-medium text-slate-600 dark:text-slate-300 mb-1"
                    >
                      Credential type
                    </label>
                    <select
                      id="ns-auth-type"
                      value={authType}
                      onChange={(e) =>
                        setAuthType(e.target.value as NightscoutAuthType)
                      }
                      disabled={isCreating}
                      className={clsx(
                        "w-full rounded-lg border px-3 py-2 text-sm",
                        "bg-white dark:bg-slate-800",
                        "border-slate-300 dark:border-slate-700",
                        "text-slate-700 dark:text-slate-200",
                        "focus:outline-none focus:ring-2 focus:ring-blue-500",
                        "disabled:opacity-50 disabled:cursor-not-allowed"
                      )}
                    >
                      <option value="auto">Auto-detect</option>
                      <option value="secret">API_SECRET</option>
                      <option value="token">Bearer token</option>
                    </select>
                  </div>
                  <div>
                    <label
                      htmlFor="ns-api-version"
                      className="block text-sm font-medium text-slate-600 dark:text-slate-300 mb-1"
                    >
                      Nightscout API version
                    </label>
                    <select
                      id="ns-api-version"
                      value={apiVersion}
                      onChange={(e) =>
                        setApiVersion(e.target.value as NightscoutApiVersion)
                      }
                      disabled={isCreating}
                      className={clsx(
                        "w-full rounded-lg border px-3 py-2 text-sm",
                        "bg-white dark:bg-slate-800",
                        "border-slate-300 dark:border-slate-700",
                        "text-slate-700 dark:text-slate-200",
                        "focus:outline-none focus:ring-2 focus:ring-blue-500",
                        "disabled:opacity-50 disabled:cursor-not-allowed"
                      )}
                    >
                      <option value="auto">Auto-detect</option>
                      <option value="v1">v1</option>
                      <option value="v3">v3</option>
                    </select>
                  </div>
                </div>
                {createError && (
                  <div
                    className="bg-red-500/10 rounded-lg p-2 px-3 text-xs text-red-400 flex items-center gap-2"
                    role="alert"
                  >
                    <AlertTriangle className="h-3 w-3 shrink-0" />
                    {createError}
                  </div>
                )}
                <button
                  type="submit"
                  disabled={isOffline || isCreating}
                  className={clsx(
                    "w-full sm:w-auto px-4 py-2 rounded-lg text-sm font-medium",
                    "bg-blue-600 text-white hover:bg-blue-500",
                    "disabled:opacity-50 disabled:cursor-not-allowed",
                    "transition-colors flex items-center justify-center gap-2"
                  )}
                >
                  {isCreating ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Link2 className="h-4 w-4" />
                  )}
                  Connect Nightscout
                </button>
              </div>
            </form>
          </div>
        </CollapsibleSection>
      </div>
    </CollapsibleSection>
  );
}
