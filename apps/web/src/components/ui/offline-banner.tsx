"use client";

/**
 * Story 12.4: Reusable offline/disconnected state banner.
 *
 * Shows a clear warning when the API is unavailable, with a retry button.
 */

import { RefreshCw, WifiOff } from "lucide-react";
import clsx from "clsx";

export function OfflineBanner({
  onRetry,
  isRetrying,
  message,
}: {
  onRetry: () => void;
  isRetrying?: boolean;
  message?: string;
}) {
  return (
    <div
      className="bg-amber-500/10 rounded-xl p-4 border border-amber-500/20"
      role="alert"
    >
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <WifiOff className="h-4 w-4 text-amber-400 shrink-0" />
          <p className="text-sm text-amber-400">
            {message ||
              "Unable to connect to server. Showing default values."}
          </p>
        </div>
        <button
          type="button"
          onClick={onRetry}
          disabled={isRetrying}
          className={clsx(
            "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap",
            "bg-amber-500/20 text-amber-400 hover:bg-amber-500/30",
            "transition-colors",
            "focus:outline-hidden focus-visible:ring-2 focus-visible:ring-amber-500",
            "disabled:opacity-50 disabled:cursor-not-allowed"
          )}
        >
          <RefreshCw
            className={clsx(
              "h-3.5 w-3.5",
              isRetrying && "animate-spin"
            )}
            aria-hidden="true"
          />
          {isRetrying ? "Retrying..." : "Retry Connection"}
        </button>
      </div>
    </div>
  );
}
