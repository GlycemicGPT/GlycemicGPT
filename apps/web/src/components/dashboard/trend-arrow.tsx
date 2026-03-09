"use client";

/**
 * TrendArrow Component
 *
 * Story 4.3: Trend Arrow Component
 * Reusable component that displays glucose trend direction as an arrow.
 * Can be used standalone or embedded in other components.
 */

import clsx from "clsx";
import { useReducedMotion } from "@/hooks/use-reduced-motion";

/**
 * Trend direction enum matching CGM API values.
 * - RisingFast: Glucose increasing > 3 mg/dL/min
 * - Rising: Glucose increasing 1-3 mg/dL/min
 * - Stable: Glucose change -1 to +1 mg/dL/min
 * - Falling: Glucose decreasing 1-3 mg/dL/min
 * - FallingFast: Glucose decreasing > 3 mg/dL/min
 * - Unknown: Trend data unavailable
 */
export type TrendDirection =
  | "RisingFast"
  | "Rising"
  | "Stable"
  | "Falling"
  | "FallingFast"
  | "Unknown";

/** Size variants for the trend arrow */
export type TrendArrowSize = "sm" | "md" | "lg" | "xl";

export interface TrendArrowProps {
  /** The trend direction to display */
  direction: TrendDirection;
  /** Size variant (default: md) */
  size?: TrendArrowSize;
  /** Custom color class (overrides trend-based color) */
  colorClass?: string;
  /** Whether to use trend-based coloring (default: false) */
  useTrendColor?: boolean;
  /** Whether arrow is decorative (hidden from screen readers) (default: true) */
  decorative?: boolean;
  /** Whether to animate the arrow (default: false) */
  animated?: boolean;
  /** Additional CSS classes */
  className?: string;
}

/** Arrow symbols for each trend direction */
export const TREND_ARROWS: Record<TrendDirection, string> = {
  RisingFast: "↑↑",
  Rising: "↗",
  Stable: "→",
  Falling: "↘",
  FallingFast: "↓↓",
  Unknown: "?",
};

/** Human-readable descriptions for screen readers */
export const TREND_DESCRIPTIONS: Record<TrendDirection, string> = {
  RisingFast: "rising fast",
  Rising: "rising",
  Stable: "stable",
  Falling: "falling",
  FallingFast: "falling fast",
  Unknown: "unknown trend",
};

/** Trend-based color classes (for when useTrendColor is true) */
const TREND_COLORS: Record<TrendDirection, string> = {
  RisingFast: "text-red-400",
  Rising: "text-amber-400",
  Stable: "text-green-400",
  Falling: "text-amber-400",
  FallingFast: "text-red-400",
  Unknown: "text-slate-400",
};

/** Size classes for different arrow sizes */
const SIZE_CLASSES: Record<TrendArrowSize, string> = {
  sm: "text-lg",
  md: "text-2xl",
  lg: "text-4xl",
  xl: "text-5xl",
};

/** CSS animation classes for trend arrow bounce (keyframes in globals.css) */
const ARROW_ANIM_CLASS: Partial<Record<TrendDirection, string>> = {
  RisingFast: "animate-trend-bounce-up-fast",
  Rising: "animate-trend-bounce-up",
  Falling: "animate-trend-bounce-down",
  FallingFast: "animate-trend-bounce-down-fast",
};

/**
 * Get the arrow symbol for a given trend direction.
 */
export function getTrendArrow(direction: TrendDirection): string {
  return TREND_ARROWS[direction];
}

/**
 * Get the human-readable description for a trend direction.
 */
export function getTrendDescription(direction: TrendDirection): string {
  return TREND_DESCRIPTIONS[direction];
}

/**
 * Check if a trend direction indicates rising glucose.
 */
export function isRising(direction: TrendDirection): boolean {
  return direction === "RisingFast" || direction === "Rising";
}

/**
 * Check if a trend direction indicates falling glucose.
 */
export function isFalling(direction: TrendDirection): boolean {
  return direction === "FallingFast" || direction === "Falling";
}

/**
 * Check if a trend direction indicates rapid change (either direction).
 */
export function isRapidChange(direction: TrendDirection): boolean {
  return direction === "RisingFast" || direction === "FallingFast";
}

/**
 * Check if a trend direction indicates stable glucose.
 */
export function isStable(direction: TrendDirection): boolean {
  return direction === "Stable";
}

/**
 * Check if a trend direction is unknown.
 */
export function isUnknown(direction: TrendDirection): boolean {
  return direction === "Unknown";
}

export function TrendArrow({
  direction,
  size = "md",
  colorClass,
  useTrendColor = false,
  decorative = true,
  animated = false,
  className,
}: TrendArrowProps) {
  const prefersReducedMotion = useReducedMotion();

  const arrow = TREND_ARROWS[direction];
  const description = TREND_DESCRIPTIONS[direction];

  // Determine color class
  const color = colorClass ?? (useTrendColor ? TREND_COLORS[direction] : "");

  // Should we animate?
  const animClass = animated && !prefersReducedMotion ? ARROW_ANIM_CLASS[direction] : undefined;

  // Build common props
  const ariaProps = decorative
    ? { "aria-hidden": "true" as const }
    : { role: "img" as const, "aria-label": `Glucose trend: ${description}` };

  const commonProps = {
    "data-testid": "trend-arrow",
    "data-direction": direction,
    ...ariaProps,
  };

  return (
    <span
      className={clsx(SIZE_CLASSES[size], color, className, animClass && "inline-block", animClass)}
      {...commonProps}
    >
      {arrow}
    </span>
  );
}

export default TrendArrow;
