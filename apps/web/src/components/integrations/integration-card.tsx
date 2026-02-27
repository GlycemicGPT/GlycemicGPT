"use client";

import { useState } from "react";
import {
  Loader2,
  Link2,
  Unlink,
  Wifi,
  WifiOff,
  Eye,
  EyeOff,
} from "lucide-react";
import clsx from "clsx";
import type { IntegrationResponse } from "@/lib/api";

export type IntegrationStatus = IntegrationResponse["status"];

export const STATUS_LABELS: Record<IntegrationStatus, string> = {
  pending: "Pending",
  connected: "Connected",
  error: "Error",
  disconnected: "Not Connected",
};

export const STATUS_COLORS: Record<IntegrationStatus, string> = {
  pending: "text-amber-400",
  connected: "text-green-400",
  error: "text-red-400",
  disconnected: "text-slate-500",
};

export function StatusBadge({ status }: { status: IntegrationStatus | null }) {
  const effectiveStatus = status ?? "disconnected";
  return (
    <span
      className={clsx(
        "ml-2 text-xs font-medium px-2 py-0.5 rounded-full",
        STATUS_COLORS[effectiveStatus],
        effectiveStatus === "connected" && "bg-green-500/10",
        effectiveStatus === "pending" && "bg-amber-500/10",
        effectiveStatus === "error" && "bg-red-500/10",
        effectiveStatus === "disconnected" && "bg-slate-500/10"
      )}
    >
      {STATUS_LABELS[effectiveStatus]}
    </span>
  );
}

export function PasswordInput({
  id,
  value,
  onChange,
  disabled,
  label,
  hint,
}: {
  id: string;
  value: string;
  onChange: (value: string) => void;
  disabled: boolean;
  label: string;
  hint?: string;
}) {
  const [visible, setVisible] = useState(false);

  return (
    <div>
      <label
        htmlFor={id}
        className="block text-sm font-medium text-slate-300 mb-1"
      >
        {label}
      </label>
      <div className="relative">
        <input
          id={id}
          type={visible ? "text" : "password"}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          disabled={disabled}
          autoComplete="current-password"
          className={clsx(
            "w-full rounded-lg border px-3 py-2 pr-10 text-sm",
            "bg-slate-800 border-slate-700 text-slate-200",
            "focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent",
            "disabled:opacity-50 disabled:cursor-not-allowed"
          )}
        />
        <button
          type="button"
          onClick={() => setVisible(!visible)}
          className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-slate-400 hover:text-slate-300"
          aria-label={visible ? "Hide password" : "Show password"}
        >
          {visible ? (
            <EyeOff className="h-4 w-4" />
          ) : (
            <Eye className="h-4 w-4" />
          )}
        </button>
      </div>
      {hint && <p className="text-xs text-slate-500 mt-1">{hint}</p>}
    </div>
  );
}

export function IntegrationCard({
  title,
  description,
  status,
  lastSyncAt,
  lastError,
  onConnect,
  onDisconnect,
  isConnecting,
  isOffline,
  fields,
}: {
  title: string;
  description: string;
  status: IntegrationStatus | null;
  lastSyncAt: string | null;
  lastError: string | null;
  onConnect: () => Promise<void>;
  onDisconnect: () => Promise<void>;
  isConnecting: boolean;
  isOffline?: boolean;
  fields: React.ReactNode;
}) {
  const [isDisconnecting, setIsDisconnecting] = useState(false);
  const [confirmDisconnect, setConfirmDisconnect] = useState(false);
  const isConnected = status === "connected";
  const hasIntegration = status !== null && status !== "disconnected";

  const handleDisconnect = async () => {
    setIsDisconnecting(true);
    try {
      await onDisconnect();
    } finally {
      setIsDisconnecting(false);
      setConfirmDisconnect(false);
    }
  };

  const handleFormSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await onConnect();
    } catch {
      // Connection errors are surfaced via the integration status/lastError
      // fields from the backend -- no additional handling needed here.
    }
  };

  return (
    <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <div
            className={clsx(
              "p-2 rounded-lg",
              isConnected ? "bg-green-500/10" : "bg-slate-700/50"
            )}
          >
            {isConnected ? (
              <Wifi className="h-5 w-5 text-green-400" />
            ) : (
              <WifiOff className="h-5 w-5 text-slate-500" />
            )}
          </div>
          <div>
            <h2 className="text-lg font-semibold">{title}</h2>
            <p className="text-xs text-slate-500">{description}</p>
          </div>
        </div>
        {status && (
          <span
            className={clsx("text-sm font-medium", STATUS_COLORS[status])}
          >
            {STATUS_LABELS[status]}
          </span>
        )}
      </div>

      {/* Connection details for connected integrations */}
      {hasIntegration && (
        <div className="mb-6 space-y-2">
          {lastSyncAt && (
            <div className="bg-slate-800/50 rounded-lg px-3 py-2 border border-slate-700/50">
              <p className="text-xs text-slate-500">Last synced</p>
              <p className="text-sm text-slate-300">
                {new Date(lastSyncAt).toLocaleString()}
              </p>
            </div>
          )}
          {lastError && status === "error" && (
            <div
              className="bg-red-500/10 rounded-lg px-3 py-2 border border-red-500/20"
              role="alert"
            >
              <p className="text-xs text-red-400 line-clamp-3">{lastError}</p>
            </div>
          )}
        </div>
      )}

      {/* Credential form */}
      <form onSubmit={handleFormSubmit}>
        {fields}

        {/* Action buttons */}
        <div className="flex items-center gap-3 mt-4">
          <button
            type="submit"
            disabled={isConnecting || isDisconnecting || isOffline}
            title={isOffline ? "Cannot connect while disconnected" : undefined}
            className={clsx(
              "flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium",
              "bg-blue-600 text-white hover:bg-blue-500",
              "transition-colors",
              "focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500",
              "disabled:opacity-50 disabled:cursor-not-allowed"
            )}
          >
            {isConnecting ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            ) : (
              <Link2 className="h-4 w-4" aria-hidden="true" />
            )}
            {isConnecting
              ? "Testing..."
              : hasIntegration
                ? "Update Credentials"
                : "Test Connection"}
          </button>

          {hasIntegration && !confirmDisconnect && (
            <button
              type="button"
              onClick={() => setConfirmDisconnect(true)}
              disabled={isConnecting || isDisconnecting || isOffline}
              className={clsx(
                "flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium",
                "bg-red-600/20 text-red-400 hover:bg-red-600/30",
                "transition-colors",
                "focus:outline-none focus-visible:ring-2 focus-visible:ring-red-500",
                "disabled:opacity-50 disabled:cursor-not-allowed"
              )}
            >
              <Unlink className="h-4 w-4" aria-hidden="true" />
              Disconnect
            </button>
          )}

          {hasIntegration && confirmDisconnect && (
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={handleDisconnect}
                disabled={isDisconnecting || isOffline || isConnecting}
                className={clsx(
                  "flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium",
                  "bg-red-600 text-white hover:bg-red-500",
                  "transition-colors",
                  "focus:outline-none focus-visible:ring-2 focus-visible:ring-red-500",
                  "disabled:opacity-50 disabled:cursor-not-allowed"
                )}
              >
                {isDisconnecting ? (
                  <Loader2
                    className="h-4 w-4 animate-spin"
                    aria-hidden="true"
                  />
                ) : (
                  <Unlink className="h-4 w-4" aria-hidden="true" />
                )}
                {isDisconnecting ? "Disconnecting..." : "Yes, Disconnect"}
              </button>
              <button
                type="button"
                onClick={() => setConfirmDisconnect(false)}
                disabled={isDisconnecting || isOffline || isConnecting}
                className={clsx(
                  "px-4 py-2 rounded-lg text-sm font-medium",
                  "bg-slate-800 text-slate-300 hover:bg-slate-700",
                  "transition-colors",
                  "focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-500",
                  "disabled:opacity-50 disabled:cursor-not-allowed"
                )}
              >
                Cancel
              </button>
            </div>
          )}
        </div>
      </form>
    </div>
  );
}
