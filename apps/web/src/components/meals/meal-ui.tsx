/**
 * Shared presentational pieces for the meal-management surfaces (list + detail).
 *
 * Descriptive only: the safety qualifier is rendered verbatim from the server
 * `safety_qualifier` field, and nothing here renders a dose or insulin value.
 */

import Link from "next/link";
import {
  AlertTriangle,
  BadgeCheck,
  CheckCircle2,
  ExternalLink,
  ImageOff,
  ScanLine,
  Settings as SettingsIcon,
  X,
} from "lucide-react";
import {
  formatMacroValue,
  formatNetCarbs,
  isGrounded,
  sourceMeta,
} from "@/lib/meal-format";
import type { FoodRecord, FoodRecordSource, NutritionFacts } from "@/lib/api";
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
 * The assumed portion (Story 50.N1), surfaced prominently as the estimate's
 * primary sanity-check -- portion size is the dominant error source, so it gets
 * its own card and an explicit "does this match?" prompt. Descriptive only.
 */
export function MealAssumedPortion({ portion }: { portion: string }) {
  return (
    <div
      data-testid="meal-portion"
      className="rounded-xl border border-blue-500/30 bg-blue-500/5 dark:bg-blue-500/10 p-5 space-y-1"
    >
      <p className="text-xs font-semibold uppercase tracking-wide text-blue-700 dark:text-blue-300">
        Assumed portion
      </p>
      <p className="text-base text-slate-900 dark:text-white">{portion}</p>
      <p className="text-xs text-slate-500 dark:text-slate-400">
        Portion size is the biggest source of error in a photo estimate — does
        this match what you ate?
      </p>
    </div>
  );
}

/**
 * Glucose-framed nutrition (Story 50.N1): the macros with their descriptive
 * "how this affects glucose" notes, the caveated net-carbs figure (clearly
 * secondary, behind the never-dose caveat), and the section disclaimer. All copy
 * is rendered verbatim from the server `nutrition_facts` block so it can never
 * drift into dosing language. Read-only -- nothing here is a dose.
 */
export function MealNutritionFacts({ facts }: { facts: NutritionFacts }) {
  return (
    <div className="rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-6 space-y-4">
      <h2 className="text-sm font-semibold text-slate-900 dark:text-white">
        Estimated nutrition
      </h2>

      {facts.macros.length > 0 && (
        <dl className="space-y-3">
          {facts.macros.map((macro) => (
            <div
              key={macro.key}
              data-testid="meal-macro"
              className="space-y-0.5"
            >
              <div className="flex items-baseline justify-between gap-3">
                <dt className="text-sm text-slate-600 dark:text-slate-300">
                  {macro.label}
                </dt>
                <dd
                  data-testid="meal-macro-value"
                  className="text-sm font-medium text-slate-900 dark:text-white"
                >
                  {formatMacroValue(macro.value, macro.unit)}
                </dd>
              </div>
              {macro.glucose_note && (
                <p
                  data-testid="meal-macro-note"
                  className="text-xs text-slate-500 dark:text-slate-400"
                >
                  {macro.glucose_note}
                </p>
              )}
            </div>
          ))}
        </dl>
      )}

      {facts.net_carbs && (
        <div
          data-testid="meal-net-carbs"
          className="space-y-2 border-t border-slate-200 dark:border-slate-800 pt-3"
        >
          <div className="flex items-baseline justify-between gap-3">
            <span className="text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">
              Net carbs
            </span>
            <span className="text-sm font-medium text-slate-700 dark:text-slate-200">
              {formatNetCarbs(facts.net_carbs.low, facts.net_carbs.high)}
            </span>
          </div>
          <div
            role="note"
            data-testid="meal-net-carbs-caveat"
            className="flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-800 dark:text-amber-300"
          >
            <AlertTriangle className="h-4 w-4 flex-shrink-0 mt-0.5" />
            <span>{facts.net_carbs.caveat}</span>
          </div>
        </div>
      )}
      {/* The section disclaimer renders at the page level (so it also shows for
          a portion-only payload), not inside this macros/net-carbs card. */}
    </div>
  );
}

/**
 * The section-level never-dose disclaimer for the nutrition block (Story 50.N1).
 * Rendered whenever any nutrition surfaces -- including a portion-only payload --
 * so the framing is never dropped. Verbatim from the server.
 */
export function MealNutritionDisclaimer({ disclaimer }: { disclaimer: string }) {
  return (
    <p
      data-testid="meal-nutrition-disclaimer"
      className="text-xs text-center text-slate-400 dark:text-slate-500"
    >
      {disclaimer}
    </p>
  );
}

/**
 * Grounding status for the carb estimate (Story 50.H2/E1). Confirming the food's
 * identity opens the grounding gate, so an unconfirmed record is "vision-only --
 * not checked against an external source"; once a source grounds it, the
 * attribution (and an optional outbound link) is shown. Descriptive provenance
 * only -- nothing here is a dose.
 */
export function MealGroundingStatus({ record }: { record: FoodRecord }) {
  if (isGrounded(record)) {
    return (
      <div
        role="note"
        data-testid="meal-grounding-grounded"
        className="flex items-start gap-2 rounded-lg border border-blue-500/30 bg-blue-500/5 dark:bg-blue-500/10 px-3 py-2 text-xs text-slate-600 dark:text-slate-300"
      >
        <BadgeCheck className="h-4 w-4 flex-shrink-0 mt-0.5 text-blue-600 dark:text-blue-400" />
        <span>
          Grounded against{" "}
          <span className="font-medium text-slate-900 dark:text-white">
            {record.grounding_source}
          </span>
          {record.grounding_source_url && (
            <>
              {" "}
              <a
                href={record.grounding_source_url}
                target="_blank"
                rel="noopener noreferrer"
                data-testid="meal-grounding-link"
                className="inline-flex items-center gap-0.5 text-blue-600 dark:text-blue-400 hover:underline"
              >
                source
                <ExternalLink className="h-3 w-3" />
              </a>
            </>
          )}
          .
        </span>
      </div>
    );
  }

  // Not grounded: be precise about *why*, since provenance accuracy is the whole
  // point of the grounding gate. A corrected band is the user's own number; a
  // confirmed-but-unmatched record was checked and nothing authoritative matched;
  // otherwise it is a pure vision estimate that hasn't been checked at all.
  let copy: string;
  if (record.source === "user_corrected") {
    copy =
      "Your corrected estimate — not checked against an external nutrition source.";
  } else if (record.identity_confirmed) {
    copy =
      "Confirmed, but no authoritative nutrition source matched this food.";
  } else {
    copy =
      "Vision-only — this estimate hasn’t been checked against an external nutrition source.";
  }
  return (
    <div
      role="note"
      data-testid="meal-grounding-vision-only"
      className="flex items-start gap-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/40 px-3 py-2 text-xs text-slate-500 dark:text-slate-400"
    >
      <ScanLine className="h-4 w-4 flex-shrink-0 mt-0.5" />
      <span>{copy}</span>
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
