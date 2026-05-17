"use client";

/**
 * GlucoseHero Component
 *
 * Story 4.2: GlucoseHero Component
 * Story 4.6: Dashboard Accessibility
 * Prominently displays current glucose with trend arrow so users
 * can understand their status in under 2 seconds.
 *
 * Accessibility features:
 * - Screen reader announcements with value, trend, and range status
 * - Dynamic aria-live (assertive for urgent, polite for normal)
 * - Keyboard focusable with visible focus ring
 * - Accessible labels for pump status metrics
 */

import { useReducedMotion } from "@/hooks/use-reduced-motion";
import clsx from "clsx";
import {
  type TrendDirection,
  TREND_ARROWS,
  TREND_DESCRIPTIONS,
} from "./trend-arrow";

// Glucose range classification
export type GlucoseRange =
  | "urgentLow"
  | "low"
  | "inRange"
  | "high"
  | "urgentHigh";

/** Default glucose range thresholds in mg/dL */
export const GLUCOSE_THRESHOLDS = {
  URGENT_LOW: 55,
  LOW: 70,
  HIGH: 180,
  URGENT_HIGH: 250,
} as const;

/**
 * Story 43.12 PR 6 -- closed-loop runtime state surfaces.
 *
 * These come from the backend's `/api/integrations/pump/status` and are
 * sourced from the latest Nightscout devicestatus snapshot. All three
 * are independently nullable -- absence means the underlying data
 * isn't present (no NS integration, no active override, no carbs
 * absorbing, snapshot stale, etc.) and we render nothing.
 */
export type LoopState = "looping" | "not_looping" | "failed";

/**
 * Narrow a free-form string from the backend into a LoopState. Returns
 * null for unrecognized values so the caller can render nothing
 * rather than crashing on `LOOP_STATE_STYLE[undefined]`.
 *
 * If a future translator surfaces a new state ("warming_up",
 * "unknown", etc.), this guard fails closed -- the badge stays hidden
 * until the frontend adds an explicit style for the new state.
 */
export function parseLoopState(value: string): LoopState | null {
  return value === "looping" || value === "not_looping" || value === "failed"
    ? value
    : null;
}

export interface LoopStatusInfo {
  state: LoopState;
  /** 'loop' | 'aaps' | 'trio' | 'oref0' | 'iaps' */
  source: string;
  /** ISO 8601 string from the backend. */
  issuedAt: string;
  /** Populated only when state === 'failed'. */
  failureReason?: string | null;
}

export interface OverrideInfo {
  name: string;
  /** ISO 8601 string. */
  startedAt: string;
  /** Null for indefinite overrides. */
  endsAt?: string | null;
  multiplier?: number | null;
  targetLowMgdl?: number | null;
  targetHighMgdl?: number | null;
}

export interface GlucoseHeroProps {
  /** Current glucose value in mg/dL */
  value: number | null;
  /** Trend direction */
  trend: TrendDirection;
  /** Insulin on Board in units */
  iob: number | null;
  /** Current basal rate in u/hr */
  basalRate: number | null;
  /** Battery percentage (0-100) */
  batteryPct: number | null;
  /** Reservoir insulin remaining in units */
  reservoirUnits: number | null;
  /** Carbs on Board in grams. PR 6 addition. */
  cobGrams?: number | null;
  /**
   * Closed-loop runtime state badge. PR 6 addition.
   * Null = no NS-sourced closed-loop data, or snapshot is stale.
   */
  loopStatus?: LoopStatusInfo | null;
  /**
   * Active override (workout / pre-meal / sleep mode). PR 6 addition,
   * Loop-only. AAPS/Trio overrides ride on Temp Target treatments and
   * are deferred to a follow-up. Null = no active override.
   */
  override?: OverrideInfo | null;
  /** Unit label (default: mg/dL) */
  unit?: string;
  /** Minutes since last reading */
  minutesAgo?: number;
  /** Whether data is considered stale (>10 minutes) */
  isStale?: boolean;
  /** Whether data is currently loading */
  isLoading?: boolean;
  /** Dynamic glucose thresholds from user settings */
  thresholds?: {
    urgentLow: number;
    low: number;
    high: number;
    urgentHigh: number;
  };
}


/**
 * Classify glucose value into range category.
 * Accepts optional dynamic thresholds; falls back to GLUCOSE_THRESHOLDS.
 */
export function classifyGlucose(
  value: number | null,
  thresholds?: { urgentLow: number; low: number; high: number; urgentHigh: number }
): GlucoseRange {
  if (value === null) return "inRange";
  const t = thresholds ?? {
    urgentLow: GLUCOSE_THRESHOLDS.URGENT_LOW,
    low: GLUCOSE_THRESHOLDS.LOW,
    high: GLUCOSE_THRESHOLDS.HIGH,
    urgentHigh: GLUCOSE_THRESHOLDS.URGENT_HIGH,
  };
  if (value < t.urgentLow) return "urgentLow";
  if (value < t.low) return "low";
  if (value <= t.high) return "inRange";
  if (value <= t.urgentHigh) return "high";
  return "urgentHigh";
}

// Accessible range status descriptions
type RangeStatus = "in-range" | "low" | "high" | "urgent-low" | "urgent-high";

const RANGE_STATUS_TEXT: Record<RangeStatus, string> = {
  "in-range": "in target range",
  "low": "below target",
  "high": "above target",
  "urgent-low": "dangerously low",
  "urgent-high": "dangerously high",
};

/**
 * Get accessible range status text for screen readers.
 */
export function getRangeStatus(range: GlucoseRange): RangeStatus {
  const mapping: Record<GlucoseRange, RangeStatus> = {
    inRange: "in-range",
    low: "low",
    high: "high",
    urgentLow: "urgent-low",
    urgentHigh: "urgent-high",
  };
  return mapping[range];
}

/**
 * Build accessible announcement for screen readers.
 * Format: "Glucose 142 milligrams per deciliter, falling slowly, in target range"
 */
export function buildGlucoseAnnouncement(
  value: number | null,
  trendDescription: string,
  rangeStatus: RangeStatus
): string {
  if (value === null) {
    return "Glucose reading unavailable";
  }

  const rangeText = RANGE_STATUS_TEXT[rangeStatus];
  return `Glucose ${Math.round(value)} milligrams per deciliter, ${trendDescription}, ${rangeText}`;
}

/**
 * Determine if glucose state is urgent (requires assertive announcement).
 */
export function isUrgentState(range: GlucoseRange): boolean {
  return range === "urgentLow" || range === "urgentHigh";
}

// Color configuration per glucose range
const rangeColors: Record<GlucoseRange, { text: string; bg: string }> = {
  urgentLow: { text: "text-red-500", bg: "bg-red-500/10" },
  low: { text: "text-amber-400", bg: "bg-amber-500/10" },
  inRange: { text: "text-green-400", bg: "bg-green-500/10" },
  high: { text: "text-amber-400", bg: "bg-amber-500/10" },
  urgentHigh: { text: "text-red-500", bg: "bg-red-500/10" },
};

/**
 * Determine if pulse animation should be shown.
 */
export function shouldPulse(range: GlucoseRange): "strong" | "subtle" | null {
  if (range === "urgentLow" || range === "urgentHigh") return "strong";
  if (range === "low" || range === "high") return "subtle";
  return null;
}

// CSS class names for pulse effects (keyframes defined in globals.css)
const PULSE_CLASS: Record<"subtle" | "strong", string> = {
  subtle: "animate-glucose-pulse-subtle",
  strong: "animate-glucose-pulse-strong",
};

/**
 * Validate and sanitize numeric value.
 * Returns null for invalid values (NaN, Infinity, negative).
 */
function sanitizeValue(value: number | null, allowNegative = false): number | null {
  if (value === null) return null;
  if (typeof value !== "number") return null;
  if (!Number.isFinite(value)) return null;
  if (!allowNegative && value < 0) return null;
  return value;
}

// ---------------------------------------------------------------------------
// Story 43.12 PR 6 helpers
// ---------------------------------------------------------------------------

const LOOP_STATE_STYLE: Record<
  LoopState,
  { label: string; pill: string; ariaLabel: (source: string) => string }
> = {
  looping: {
    label: "Looping",
    pill: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
    ariaLabel: (source) => `${prettySourceName(source)} is actively looping`,
  },
  not_looping: {
    label: "Not looping",
    pill: "bg-amber-500/15 text-amber-400 border-amber-500/30",
    ariaLabel: (source) =>
      `${prettySourceName(source)} is not currently looping`,
  },
  failed: {
    label: "Loop failed",
    pill: "bg-red-500/15 text-red-400 border-red-500/30",
    ariaLabel: (source) =>
      `${prettySourceName(source)} reported a loop cycle failure`,
  },
};

/**
 * Display name for the source engine in user-visible strings.
 *
 * Case-sensitive lookup -- the backend's Pydantic `Literal` always
 * emits lowercase canonical values, and this contract is mirrored on
 * the API type (`LoopApiSource` in `lib/api.ts`). Consistent with
 * `parseLoopState`'s case-sensitive gate: both rely on the same
 * backend contract and don't paper over upstream casing drift.
 *
 * Falls through to a generic "Closed loop" label for unknown values
 * rather than echoing whatever string the backend sent.
 */
export function prettySourceName(source: string): string {
  const map: Record<string, string> = {
    loop: "Loop",
    aaps: "AAPS",
    trio: "Trio",
    oref0: "oref0",
    iaps: "iAPS",
  };
  return map[source] ?? "Closed loop";
}

/**
 * Compute a human-friendly "ends in N min" string from an ISO ends_at
 * relative to now. Returns null when ends_at is null (indefinite
 * override) or already in the past (clock-skew safety net).
 */
export function formatOverrideRemaining(
  endsAt: string | null | undefined,
  now: Date = new Date()
): string | null {
  if (!endsAt) return null;
  const end = new Date(endsAt);
  if (Number.isNaN(end.getTime())) return null;
  const minutes = Math.round((end.getTime() - now.getTime()) / 60000);
  if (minutes <= 0) return null;
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const remainder = minutes % 60;
  if (remainder === 0) return `${hours}h`;
  return `${hours}h ${remainder}m`;
}

interface LoopStatusBadgeProps {
  status: LoopStatusInfo;
}

function LoopStatusBadge({ status }: LoopStatusBadgeProps) {
  const style = LOOP_STATE_STYLE[status.state];
  const sourceName = prettySourceName(status.source);
  // Tooltip carries the failure reason when present; absent for the
  // happy path. Source is always shown so users with multiple closed
  // loops (rare) can tell which one the badge belongs to.
  const tooltip =
    status.state === "failed" && status.failureReason
      ? `${sourceName}: ${status.failureReason}`
      : sourceName;
  return (
    <div
      className={clsx(
        "inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full",
        "text-xs font-medium border",
        style.pill
      )}
      role="status"
      aria-label={style.ariaLabel(status.source)}
      title={tooltip}
      data-testid="loop-status-badge"
      data-state={status.state}
    >
      <span
        className="inline-block w-1.5 h-1.5 rounded-full bg-current"
        aria-hidden="true"
      />
      <span>{style.label}</span>
      <span
        className="text-slate-400 font-normal border-l border-slate-700 pl-1.5 ml-0.5"
        aria-hidden="true"
      >
        {sourceName}
      </span>
    </div>
  );
}

interface OverrideRowProps {
  override: OverrideInfo;
}

function OverrideRow({ override }: OverrideRowProps) {
  const remaining = formatOverrideRemaining(override.endsAt);
  // Indefinite overrides show "ongoing" instead of computing a
  // phantom end time. Past-end overrides are filtered out by the
  // backend's `active: true` guard, but the formatter is the second
  // line of defense (returns null for past timestamps).
  const detail = remaining ? `ends in ${remaining}` : "ongoing";
  return (
    <div
      className="mt-3 flex items-center justify-center gap-2 text-xs text-slate-300"
      role="status"
      aria-label={`Override active: ${override.name}, ${detail}`}
      data-testid="override-row"
    >
      <span
        className="inline-block w-2 h-2 rounded-full bg-purple-400"
        aria-hidden="true"
      />
      <span className="font-medium">Override: {override.name}</span>
      <span className="text-slate-500" aria-hidden="true">
        &middot;
      </span>
      <span className="text-slate-400">{detail}</span>
    </div>
  );
}

export function GlucoseHero({
  value,
  trend,
  iob,
  basalRate,
  batteryPct,
  reservoirUnits,
  cobGrams,
  loopStatus,
  override,
  unit = "mg/dL",
  minutesAgo,
  isStale = false,
  isLoading = false,
  thresholds,
}: GlucoseHeroProps) {
  const prefersReducedMotion = useReducedMotion();

  // Loading skeleton state
  if (isLoading) {
    return (
      <div
        className="rounded-xl p-4 sm:p-6 md:p-8 border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 animate-pulse"
        role="region"
        aria-label="Loading glucose reading"
        aria-busy="true"
      >
        <div className="flex flex-col items-center">
          <div className="h-16 w-32 bg-slate-200 dark:bg-slate-700 rounded mb-4" />
          <div className="h-6 w-16 bg-slate-200 dark:bg-slate-700 rounded mb-4" />
          <div className="flex gap-6">
            <div className="h-10 w-12 bg-slate-200 dark:bg-slate-700 rounded" />
            <div className="h-10 w-12 bg-slate-200 dark:bg-slate-700 rounded" />
          </div>
        </div>
      </div>
    );
  }

  // Defensive: sanitize numeric values
  const safeValue = sanitizeValue(value);
  const safeIob = sanitizeValue(iob, true); // IoB can be negative (rare but possible)
  const safeBasal = sanitizeValue(basalRate);
  const safeBattery = sanitizeValue(batteryPct);
  const safeReservoir = sanitizeValue(reservoirUnits);
  // PR 6: COB is a one-way pass-through (already validated server-side
  // by the staleness + numeric checks). Negative is impossible
  // (carbs grams aren't negative); reuse the default sanitizer.
  const safeCob = sanitizeValue(cobGrams ?? null);

  const range = classifyGlucose(safeValue, thresholds);
  const colors = rangeColors[range];
  const pulseType = shouldPulse(range);
  const arrow = TREND_ARROWS[trend];
  const trendDescription = TREND_DESCRIPTIONS[trend];

  // Format display value
  const displayValue = safeValue !== null ? Math.round(safeValue).toString() : "--";

  // Accessibility: Build announcement and determine aria-live priority
  const rangeStatus = getRangeStatus(range);
  const announcement = buildGlucoseAnnouncement(safeValue, trendDescription, rangeStatus);
  const isUrgent = isUrgentState(range);
  const ariaLivePriority = isUrgent ? "assertive" : "polite";

  return (
    <div
      className={clsx(
        "rounded-xl p-4 sm:p-6 md:p-8 border border-slate-200 dark:border-slate-800 overflow-hidden",
        "focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 focus-visible:ring-offset-white dark:focus-visible:ring-offset-slate-900",
        colors.bg
      )}
      role="region"
      aria-label="Current glucose reading"
      tabIndex={0}
    >
      {/* PR 6: closed-loop badge in the top-right. Absent when the user
          has no NS-sourced closed loop or the snapshot is stale. */}
      {loopStatus && (
        <div className="flex justify-end -mt-2 mb-2">
          <LoopStatusBadge status={loopStatus} />
        </div>
      )}

      <div className="flex flex-col items-center justify-center text-center">
        {/* Main glucose display with dynamic aria-live priority */}
        <div
          className={clsx(
            "flex max-w-full items-center justify-center gap-2 sm:gap-4 mb-3 sm:mb-4",
            pulseType && !prefersReducedMotion && PULSE_CLASS[pulseType]
          )}
          aria-live={ariaLivePriority}
          aria-atomic="true"
        >
          <span
            className={clsx(
              "text-5xl min-[360px]:text-6xl sm:text-7xl font-bold tabular-nums leading-none",
              colors.text
            )}
            data-testid="glucose-value"
            aria-label={announcement}
          >
            {displayValue}
          </span>
          <span
            className={clsx(
              "text-4xl sm:text-5xl leading-none",
              // Trend arrow inherits glucose range color for visual consistency
              safeValue !== null ? colors.text : "text-slate-400"
            )}
            data-testid="trend-arrow"
            aria-hidden="true"
          >
            {arrow}
          </span>
        </div>

        {/* Unit label */}
        <p
          className="text-slate-400 text-base sm:text-lg"
          data-testid="glucose-unit"
        >
          {unit}
        </p>

        {/* Stale data warning */}
        {isStale && (
          <p
            className="text-amber-400 text-sm mt-2 flex items-center gap-1"
            data-testid="stale-warning"
            role="alert"
          >
            <span aria-hidden="true">⏱️</span>
            <span>Data is {minutesAgo ?? "10"}+ minutes old</span>
          </p>
        )}

        {/* PR 6: active override pill row. Absent when no override. */}
        {override && <OverrideRow override={override} />}

        {/* Secondary metrics: IoB, Basal, Battery, Reservoir, COB (PR 6) */}
        <div
          className="grid w-full grid-cols-2 gap-3 mt-4 text-xs sm:flex sm:w-auto sm:items-center sm:gap-4 sm:text-sm"
          role="group"
          aria-label="Pump status metrics"
          data-testid="secondary-metrics"
        >
          <div
            className="flex flex-col items-center"
            aria-label={safeIob !== null ? `Insulin on board: ${safeIob.toFixed(2)} units` : "Insulin on board: unavailable"}
          >
            <span className="text-slate-500 text-xs uppercase tracking-wide" aria-hidden="true">
              IoB
            </span>
            <span className="sr-only">Insulin on board</span>
            <span
              className="text-slate-300 font-medium"
              data-testid="iob-value"
              aria-hidden="true"
            >
              {safeIob !== null ? `${safeIob.toFixed(2)}u` : "--"}
            </span>
          </div>
          <div className="hidden sm:block w-px h-6 bg-slate-700" aria-hidden="true" />
          <div
            className="flex flex-col items-center"
            aria-label={safeBasal !== null ? `Basal rate: ${safeBasal.toFixed(2)} units per hour` : "Basal rate: unavailable"}
          >
            <span className="text-slate-500 text-xs uppercase tracking-wide" aria-hidden="true">
              Basal
            </span>
            <span className="sr-only">Basal rate</span>
            <span
              className="text-slate-300 font-medium"
              data-testid="basal-value"
              aria-hidden="true"
            >
              {safeBasal !== null ? `${safeBasal.toFixed(2)} u/hr` : "--"}
            </span>
          </div>
          <div className="hidden sm:block w-px h-6 bg-slate-700" aria-hidden="true" />
          <div
            className="flex flex-col items-center"
            aria-label={safeBattery !== null ? `Battery: ${Math.round(safeBattery)} percent` : "Battery: unavailable"}
          >
            <span className="text-slate-500 text-xs uppercase tracking-wide" aria-hidden="true">
              Battery
            </span>
            <span className="sr-only">Battery level</span>
            <span
              className="text-slate-300 font-medium"
              data-testid="battery-value"
              aria-hidden="true"
            >
              {safeBattery !== null ? `${Math.round(safeBattery)}%` : "--"}
            </span>
          </div>
          <div className="hidden sm:block w-px h-6 bg-slate-700" aria-hidden="true" />
          <div
            className="flex flex-col items-center"
            aria-label={safeReservoir !== null ? `Reservoir: ${safeReservoir.toFixed(0)} units remaining` : "Reservoir: unavailable"}
          >
            <span className="text-slate-500 text-xs uppercase tracking-wide" aria-hidden="true">
              Reservoir
            </span>
            <span className="sr-only">Reservoir level</span>
            <span
              className="text-slate-300 font-medium"
              data-testid="reservoir-value"
              aria-hidden="true"
            >
              {safeReservoir !== null ? `${Math.round(safeReservoir)}u` : "--"}
            </span>
          </div>
          {/* PR 6: COB column. Only renders when present so the row
              stays the same width for users without active carbs. */}
          {safeCob !== null && (
            <>
              <div className="w-px h-6 bg-slate-700" aria-hidden="true" />
              <div
                className="flex flex-col items-center"
                aria-label={`Carbs on board: ${Math.round(safeCob)} grams`}
              >
                <span
                  className="text-slate-500 text-xs uppercase tracking-wide"
                  aria-hidden="true"
                >
                  COB
                </span>
                <span className="sr-only">Carbs on board</span>
                <span
                  className="text-slate-300 font-medium"
                  data-testid="cob-value"
                  aria-hidden="true"
                >
                  {Math.round(safeCob)}g
                </span>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

// Re-export TrendDirection for backwards compatibility
// Primary source is now trend-arrow.tsx
export { type TrendDirection } from "./trend-arrow";

export default GlucoseHero;
