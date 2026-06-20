"use client";

/**
 * "How this was estimated" audit / provenance panel for the meal detail view.
 *
 * Surfaces the deterministic audit trail the API records for a vision estimate
 * (the merged `GET /api/food-records/{id}/audit`, Story 50.H3): the raw per-sample
 * vision reads, the empirical dispersion summary, and the precedence decision.
 * The point is the same one a deterministic healthcare tool gives you -- let the
 * user judge how much to trust a number by showing how it was produced.
 *
 * Strictly descriptive provenance: it carries the server-cleared never-dose
 * qualifier and never presents a dose or recommendation. It deliberately does NOT
 * surface the model's self-reported confidence -- the server strips that before
 * responding (it stays internal, per Story 50.H1), and only the EMPIRICAL
 * dispersion-derived confidence is shown.
 *
 * Reuses `AIInsightCard`'s shape: a card with an amber safety note and a lazy
 * expand/collapse that fetches the detail only on first open.
 *
 * Hidden when meal intelligence is off: this only renders inside the loaded-record
 * detail view, and a flag-off server hides the record itself (the detail page
 * shows a blocked state and never reaches this panel).
 */

import { useCallback, useState } from "react";
import {
  AlertTriangle,
  BadgeCheck,
  ChevronDown,
  ChevronUp,
  ExternalLink,
  FileSearch,
  Loader2,
  ScanLine,
} from "lucide-react";
import {
  getFoodRecordAudit,
  MealApiError,
  type AuditDispersion,
  type AuditPrecedence,
  type AuditSample,
  type FoodRecord,
  type FoodRecordAudit,
} from "@/lib/api";
import {
  confidenceLabel,
  formatCarbRange,
  formatCoefficientOfVariation,
  isGrounded,
  isSafeHttpUrl,
} from "@/lib/meal-format";
import { MealSafetyQualifier } from "@/components/meals/meal-ui";

/** A labelled key/value provenance row. */
function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="text-xs text-slate-500 dark:text-slate-400">{label}</dt>
      <dd className="text-xs font-medium text-slate-700 dark:text-slate-200 text-right">
        {value}
      </dd>
    </div>
  );
}

/** Section heading inside the expanded audit trail. */
function SectionHeading({ children }: { children: React.ReactNode }) {
  return (
    <h4 className="text-xs font-medium uppercase tracking-wider text-slate-500 dark:text-slate-400">
      {children}
    </h4>
  );
}

/**
 * The grounding citation (AC2): renders the record's grounding attribution as a
 * "how this was grounded" line, distinct from the raw vision estimate. Gated on
 * `isGrounded` -- the same identity-confirmed gate the detail view uses (Story
 * 50.W2) -- so a stale/regressed source can never render an authoritative
 * citation before the user has confirmed what the food is. The outbound link is
 * defended by the shared safe-URL guard.
 */
function GroundingCitation({ record }: { record: FoodRecord }) {
  if (!isGrounded(record)) return null;
  return (
    <div className="space-y-2">
      <SectionHeading>How this was grounded</SectionHeading>
      <div
        role="note"
        data-testid="meal-audit-grounding"
        className="flex items-start gap-2 rounded-lg border border-blue-500/30 bg-blue-500/5 dark:bg-blue-500/10 px-3 py-2 text-xs text-slate-600 dark:text-slate-300"
      >
        <BadgeCheck className="h-4 w-4 flex-shrink-0 mt-0.5 text-blue-600 dark:text-blue-400" />
        <span>
          Checked against{" "}
          <span className="font-medium text-slate-900 dark:text-white">
            {record.grounding_source}
          </span>
          {record.grounding_trust_tier && (
            <> ({record.grounding_trust_tier.toLowerCase()} source)</>
          )}
          {isSafeHttpUrl(record.grounding_source_url) && (
            <>
              {" — "}
              <a
                href={record.grounding_source_url!}
                target="_blank"
                rel="noopener noreferrer"
                data-testid="meal-audit-grounding-link"
                aria-label={`View ${record.grounding_source} source (opens in a new window)`}
                className="inline-flex items-center gap-0.5 text-blue-600 dark:text-blue-400 hover:underline"
              >
                view source
                <ExternalLink className="h-3 w-3" />
              </a>
            </>
          )}
          .
        </span>
      </div>
    </div>
  );
}

/** The raw per-sample vision reads (AC1). One row per sample; no self-reported confidence. */
function SamplesSection({ samples }: { samples: AuditSample[] }) {
  if (samples.length === 0) return null;
  return (
    <div className="space-y-2">
      <SectionHeading>Photo reads ({samples.length})</SectionHeading>
      <ul className="space-y-1.5">
        {samples.map((sample, i) => {
          const carbs =
            sample.carbs_low != null && sample.carbs_high != null
              ? formatCarbRange(sample.carbs_low, sample.carbs_high)
              : "no carb read";
          return (
            <li
              key={i}
              data-testid="meal-audit-sample"
              className="flex items-baseline justify-between gap-3 text-xs"
            >
              <span className="text-slate-600 dark:text-slate-300 min-w-0 truncate">
                {sample.identity?.trim() || "Unlabelled read"}
              </span>
              <span className="flex-shrink-0 font-medium text-slate-700 dark:text-slate-200">
                {sample.parse_ok ? carbs : "unreadable"}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/**
 * The empirical dispersion summary (AC1 + AC3): how much the photo reads
 * disagreed. The confidence here is the EMPIRICAL dispersion band, never the
 * model's self-reported confidence.
 */
function DispersionSection({ dispersion }: { dispersion: AuditDispersion }) {
  const cv = formatCoefficientOfVariation(dispersion.coefficient_of_variation);
  const sampleCount =
    dispersion.samples_used != null && dispersion.samples_requested != null
      ? `${dispersion.samples_used} of ${dispersion.samples_requested}`
      : dispersion.samples_used != null
        ? String(dispersion.samples_used)
        : null;
  return (
    <div className="space-y-2">
      <SectionHeading>How much the reads agreed</SectionHeading>
      <dl
        data-testid="meal-audit-dispersion"
        className="space-y-1.5 rounded-lg border border-slate-200 dark:border-slate-800 px-3 py-2"
      >
        <DetailRow
          label="Confidence (from spread)"
          value={confidenceLabel(dispersion.confidence)}
        />
        {cv && <DetailRow label="Spread between reads" value={cv} />}
        {sampleCount && <DetailRow label="Usable reads" value={sampleCount} />}
        {dispersion.identity_agreement != null && (
          <DetailRow
            label="Reads agreed on the food"
            value={dispersion.identity_agreement ? "Yes" : "No"}
          />
        )}
        {dispersion.distinct_identities.length > 1 && (
          <DetailRow
            label="Identities seen"
            value={dispersion.distinct_identities.join(", ")}
          />
        )}
      </dl>
    </div>
  );
}

/** Humanize the precedence outcome into a short decision line. */
function precedenceDecision(precedence: AuditPrecedence): string {
  if (precedence.outcome === "grounded" && precedence.chosen_source) {
    return `Grounded against ${precedence.chosen_source}`;
  }
  return "Vision-only estimate";
}

/**
 * The precedence decision (AC1): which source won and the ladder AS IT STOOD when
 * the decision was made. The recorded ladder is shown rather than a live constant
 * so the trail reads the ordering that actually applied.
 */
function PrecedenceSection({ precedence }: { precedence: AuditPrecedence }) {
  return (
    <div className="space-y-2" data-testid="meal-audit-precedence">
      <SectionHeading>Which source was used</SectionHeading>
      <div className="space-y-1.5 rounded-lg border border-slate-200 dark:border-slate-800 px-3 py-2">
        <DetailRow label="Decision" value={precedenceDecision(precedence)} />
        {precedence.identity_used && (
          <DetailRow label="Keyed on" value={precedence.identity_used} />
        )}
        {precedence.reason && (
          <p className="text-xs text-slate-500 dark:text-slate-400">
            {precedence.reason}
          </p>
        )}
        {precedence.ladder.length > 0 && (
          <div className="pt-1">
            <p className="text-xs text-slate-500 dark:text-slate-400 mb-1">
              Sources considered, in order:
            </p>
            <ol className="list-decimal list-inside space-y-0.5">
              {precedence.ladder.map((rung) => {
                const used =
                  !!precedence.chosen_source &&
                  rung.toLowerCase() === precedence.chosen_source.toLowerCase();
                return (
                  <li
                    key={rung}
                    className={
                      used
                        ? "text-xs font-medium text-slate-900 dark:text-white"
                        : "text-xs text-slate-500 dark:text-slate-400"
                    }
                  >
                    {rung}
                    {used && " — used"}
                  </li>
                );
              })}
            </ol>
          </div>
        )}
      </div>
    </div>
  );
}

/** The expanded provenance body, once the audit has loaded. */
function AuditDetails({
  record,
  audit,
}: {
  record: FoodRecord;
  audit: FoodRecordAudit;
}) {
  return (
    <div
      data-testid="meal-audit-details"
      role="region"
      aria-label="How this estimate was produced"
      className="mt-3 pt-3 border-t border-slate-200 dark:border-slate-800 space-y-4"
    >
      <GroundingCitation record={record} />
      <SamplesSection samples={audit.samples} />
      {audit.dispersion && (
        <DispersionSection dispersion={audit.dispersion} />
      )}
      {audit.precedence && (
        <PrecedenceSection precedence={audit.precedence} />
      )}
    </div>
  );
}

/**
 * The audit / provenance panel. Closed, it is a compact "How this was estimated"
 * card with the never-dose qualifier; opening it lazily fetches and renders the
 * full audit trail.
 */
export function MealAuditPanel({ record }: { record: FoodRecord }) {
  const [expanded, setExpanded] = useState(false);
  const [audit, setAudit] = useState<FoodRecordAudit | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // A 404 means the record simply has no stored audit trail (benign) rather than
  // a failure to surface for retry.
  const [unavailable, setUnavailable] = useState(false);

  const toggle = useCallback(async () => {
    if (expanded) {
      setExpanded(false);
      return;
    }
    // Already resolved once (loaded, or known-unavailable): just re-open.
    if (audit || unavailable) {
      setExpanded(true);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const result = await getFoodRecordAudit(record.id);
      setAudit(result);
      setExpanded(true);
    } catch (err) {
      if (err instanceof MealApiError && err.status === 404) {
        setUnavailable(true);
        setExpanded(true);
      } else {
        // Transient: leave the panel collapsed so the button retries on re-click.
        setError("Couldn’t load how this was estimated. Try again.");
      }
    } finally {
      setLoading(false);
    }
  }, [expanded, audit, unavailable, record.id]);

  return (
    <article
      data-testid="meal-audit-panel"
      aria-label="How this was estimated"
      className="rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-6 space-y-3 focus-within:ring-2 focus-within:ring-blue-500 focus-within:ring-offset-2 focus-within:ring-offset-white dark:focus-within:ring-offset-slate-950"
    >
      <div className="flex items-start gap-3">
        <div className="p-2 rounded-lg shrink-0 bg-slate-100 dark:bg-slate-800" aria-hidden="true">
          <FileSearch className="h-5 w-5 text-slate-500 dark:text-slate-400" />
        </div>
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-slate-900 dark:text-white">
            How this was estimated
          </h2>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
            The photo reads, how much they agreed, and what grounded the number —
            so you can judge how much to trust it.
          </p>
        </div>
      </div>

      {/* The never-dose qualifier travels with this provenance surface (AC4),
          rendered verbatim from the server-cleared field. */}
      <MealSafetyQualifier
        qualifier={record.safety_qualifier}
        testId="meal-audit-safety-qualifier"
      />

      <button
        type="button"
        onClick={toggle}
        disabled={loading}
        data-testid="meal-audit-toggle"
        aria-expanded={expanded}
        className="inline-flex items-center gap-1.5 text-xs font-medium text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 rounded disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
      >
        {loading ? (
          <>
            <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
            Loading…
          </>
        ) : (
          <>
            <ScanLine className="h-3.5 w-3.5" aria-hidden="true" />
            {expanded ? "Hide details" : "View details"}
            {expanded ? (
              <ChevronUp className="h-3 w-3" />
            ) : (
              <ChevronDown className="h-3 w-3" />
            )}
          </>
        )}
      </button>

      {error && (
        <p
          role="alert"
          data-testid="meal-audit-error"
          className="text-xs text-red-600 dark:text-red-400"
        >
          {error}
        </p>
      )}

      {expanded && unavailable && (
        <div
          role="note"
          data-testid="meal-audit-unavailable"
          className="flex items-start gap-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/40 px-3 py-2 text-xs text-slate-500 dark:text-slate-400"
        >
          <AlertTriangle className="h-4 w-4 flex-shrink-0 mt-0.5" />
          <span>No estimation trail was recorded for this meal.</span>
        </div>
      )}

      {expanded && audit && <AuditDetails record={record} audit={audit} />}
    </article>
  );
}
