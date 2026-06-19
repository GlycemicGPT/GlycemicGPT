/**
 * Shared presentational pieces for the meal-management surfaces (list + detail).
 *
 * Descriptive only: the safety qualifier is rendered verbatim from the server
 * `safety_qualifier` field, and nothing here renders a dose or insulin value.
 */

import Link from "next/link";
import {
  AlertTriangle,
  CheckCircle2,
  ImageOff,
  Settings as SettingsIcon,
  X,
} from "lucide-react";
import { sourceMeta } from "@/lib/meal-format";
import type { FoodRecordSource } from "@/lib/api";
import type { MealErrorInfo } from "@/lib/meal-errors";

/** Provenance badge (AI estimate / corrected / grounded). */
export function SourceBadge({ source }: { source: FoodRecordSource | string }) {
  const meta = sourceMeta(source);
  return (
    <span
      data-testid="meal-source-badge"
      className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${meta.bg} ${meta.text}`}
    >
      {meta.label}
    </span>
  );
}

/** "Identity confirmed" marker -- only shown once the user has confirmed the food. */
export function IdentityConfirmedBadge() {
  return (
    <span
      data-testid="meal-identity-confirmed"
      className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-emerald-500/15 text-emerald-700 dark:text-emerald-400"
    >
      <CheckCircle2 className="h-3 w-3" />
      Identity confirmed
    </span>
  );
}

/**
 * The always-present, server-cleared safety qualifier. Rendered verbatim from
 * the record's `safety_qualifier` so the never-dose framing can never drift or
 * be omitted on a carb surface.
 */
export function MealSafetyQualifier({
  qualifier,
  className = "",
}: {
  qualifier: string;
  className?: string;
}) {
  return (
    <div
      role="note"
      data-testid="meal-safety-qualifier"
      className={`flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-800 dark:text-amber-300 ${className}`}
    >
      <AlertTriangle className="h-4 w-4 flex-shrink-0 mt-0.5" />
      <span>{qualifier}</span>
    </div>
  );
}

/**
 * Placeholder for the meal photo. The current API stores the photo for analysis
 * but never serves it back to clients (no photo URL / endpoint), so there is
 * nothing to render; this shows a neutral placeholder rather than a broken image.
 */
export function MealPhotoPlaceholder({
  size = "sm",
}: {
  size?: "sm" | "lg";
}) {
  const dimensions = size === "lg" ? "h-48 w-full" : "h-14 w-14";
  const iconSize = size === "lg" ? "h-8 w-8" : "h-5 w-5";
  return (
    <div
      data-testid="meal-photo-placeholder"
      aria-hidden="true"
      className={`${dimensions} flex-shrink-0 flex items-center justify-center rounded-lg bg-slate-100 dark:bg-slate-800 text-slate-400 dark:text-slate-500`}
    >
      <ImageOff className={iconSize} />
    </div>
  );
}

/**
 * Renders a classified meal error. Non-retryable failures (feature off, no
 * provider, vision unavailable) become a blocking card that points the user at
 * Settings; retryable ones become a dismissible inline banner.
 */
export function MealErrorPanel({
  info,
  onDismiss,
}: {
  info: MealErrorInfo;
  onDismiss?: () => void;
}) {
  if (info.retryable) {
    return (
      <div
        role="alert"
        data-testid="meal-error"
        className="flex items-start justify-between gap-3 rounded-lg border border-red-500/20 bg-red-500/10 px-4 py-3 text-sm text-red-700 dark:text-red-400"
      >
        <span>
          <span className="font-medium">{info.title}.</span> {info.message}
        </span>
        {onDismiss && (
          <button
            type="button"
            onClick={onDismiss}
            className="text-red-700 dark:text-red-400 hover:opacity-70"
            aria-label="Dismiss"
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>
    );
  }

  return (
    <div
      role="alert"
      data-testid={`meal-${info.kind.replace(/_/g, "-")}`}
      className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-4 text-sm"
    >
      <div className="flex items-start gap-2">
        <AlertTriangle className="h-5 w-5 flex-shrink-0 text-amber-600 dark:text-amber-400" />
        <div className="space-y-2">
          <p className="font-medium text-slate-900 dark:text-white">{info.title}</p>
          <p className="text-slate-600 dark:text-slate-300">{info.message}</p>
          {info.settingsHref && (
            <Link
              href={info.settingsHref}
              className="inline-flex items-center gap-1.5 text-blue-600 dark:text-blue-400 hover:underline"
            >
              <SettingsIcon className="h-4 w-4" />
              Open Settings
            </Link>
          )}
        </div>
      </div>
    </div>
  );
}
