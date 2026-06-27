"use client";

/**
 * GlucoseUnitSeedNotice Component
 *
 * A one-time, dismissible notice shown when the account's glucose unit was set
 * by a smart default (registration locale or a confidently-mmol
 * Nightscout) and is still seed-owned and non-mgdl. It is the visible safety
 * valve for an overridable best guess -- it never blocks the UI and never
 * appears for mg/dL-defaulted users.
 *
 * Dismissing it acknowledges the preference server-side (`source=user`) so it
 * never recurs; changing the unit in Settings flips the source the same way.
 */

import { Info, X } from "lucide-react";
import clsx from "clsx";
import { useState } from "react";
import Link from "next/link";
import { useUserContext } from "@/providers";
import { acknowledgeGlucoseUnitSeed } from "@/lib/api";
import { unitLabel } from "@/lib/glucose-units";

export function GlucoseUnitSeedNotice() {
  const { user, refreshUser } = useUserContext();
  // Optimistic local hide so the notice disappears immediately on dismiss,
  // independent of the best-effort server acknowledgment below.
  const [isDismissed, setIsDismissed] = useState(false);

  const unit = user?.glucose_unit ?? "mgdl";
  const isSeeded = user?.glucose_unit_source === "seed" && unit !== "mgdl";

  if (!isSeeded || isDismissed) {
    return null;
  }

  const handleDismiss = async () => {
    setIsDismissed(true);
    try {
      // Persist the acknowledgment so the notice doesn't return on next load,
      // then refresh the shared user context so `source` flips to "user".
      await acknowledgeGlucoseUnitSeed();
      await refreshUser();
    } catch {
      // Non-fatal: it stays hidden for this session and the server can be
      // acknowledged again on a later dismiss if this call failed.
    }
  };

  return (
    <div
      className={clsx(
        "rounded-lg border px-4 py-3 flex items-center justify-between gap-3",
        "bg-sky-500/20 border-sky-500"
      )}
      role="status"
      aria-live="polite"
      data-testid="glucose-unit-seed-notice"
    >
      <div className="flex items-center gap-3">
        <Info className="h-5 w-5 text-sky-400 shrink-0" aria-hidden="true" />
        <span className="text-sm font-medium text-sky-300">
          We set your glucose unit to {unitLabel(unit)} based on your region or
          your Nightscout.{" "}
          <Link
            href="/dashboard/settings/profile"
            className="underline hover:text-sky-200"
          >
            Change anytime in Settings
          </Link>
          .
        </span>
      </div>

      <button
        onClick={handleDismiss}
        className="p-1 rounded-md transition-colors hover:bg-slate-700/50 text-sky-300 shrink-0"
        type="button"
        aria-label="Dismiss glucose unit notice"
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  );
}

export default GlucoseUnitSeedNotice;
