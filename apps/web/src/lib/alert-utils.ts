/**
 * Story 6.4: Shared alert utilities.
 *
 * Consolidates severity config, icon mapping, and time formatting
 * used by AlertCard, AlertToast, and the alerts page.
 */

import {
  TrendingDown,
  TrendingUp,
  Syringe,
  AlertTriangle,
  type LucideIcon,
} from "lucide-react";
import { formatGlucose, unitLabel, type GlucoseUnit } from "./glucose-units";

/** Visual config per alert severity level */
export const SEVERITY_CONFIG: Record<
  string,
  { bg: string; border: string; text: string; icon: string; animation: string }
> = {
  emergency: {
    bg: "bg-red-500/15",
    border: "border-red-500/30",
    text: "text-red-400",
    icon: "text-red-400",
    animation: "animate-pulse-fast",
  },
  urgent: {
    bg: "bg-orange-500/10",
    border: "border-orange-500/20",
    text: "text-orange-400",
    icon: "text-orange-400",
    animation: "animate-pulse-slow",
  },
  warning: {
    bg: "bg-amber-500/10",
    border: "border-amber-500/20",
    text: "text-amber-400",
    icon: "text-amber-400",
    animation: "",
  },
  info: {
    bg: "bg-blue-500/10",
    border: "border-blue-500/20",
    text: "text-blue-400",
    icon: "text-blue-400",
    animation: "",
  },
};

/** Map alert_type string to a lucide-react icon component */
export function getAlertIcon(alertType: string): LucideIcon {
  if (alertType.includes("low")) return TrendingDown;
  if (alertType.includes("high")) return TrendingUp;
  if (alertType === "iob_warning") return Syringe;
  return AlertTriangle;
}

/** Format a date string as relative time (e.g., "5m ago") */
export function formatTimeAgo(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  if (diff < 0) return "just now";
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ago`;
}

/** Format expires_at as countdown string "M:SS", or null if expired */
export function formatCountdown(expiresAt: string): string | null {
  const remaining = new Date(expiresAt).getTime() - Date.now();
  if (remaining <= 0) return null;
  const totalSeconds = Math.floor(remaining / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

const ALERT_TYPE_LABELS: Record<string, string> = {
  low_urgent: "Urgent Low Glucose",
  low_warning: "Low Glucose Warning",
  high_warning: "High Glucose Warning",
  high_urgent: "Urgent High Glucose",
  iob_warning: "Insulin on Board Warning",
};

/** Convert alert_type to human-readable title */
export function formatAlertTitle(alertType: string): string {
  return (
    ALERT_TYPE_LABELS[alertType] ??
    alertType.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())
  );
}

/** Minimal alert shape needed to render a glucose summary line. */
interface AlertGlucoseFields {
  alert_type: string;
  current_value: number;
  predicted_value: number | null;
  prediction_minutes: number | null;
  message: string;
}

/**
 * Build a one-line alert summary in the active unit from the alert's STRUCTURED
 * numeric fields (mg/dL), so the displayed glucose number is never the frozen
 * mg/dL `message` string — which is rendered once at persist and would read in a
 * stale unit after the user changes their display preference.
 *
 * The persisted message also carried a "(threshold: X)" parenthetical; it is
 * intentionally dropped here because the threshold is not a structured field on
 * the alert payload and so cannot be re-rendered in the active unit. This helper
 * feeds the toast and browser notification — transient surfaces with no separate
 * glucose block — where a non-stale value + unit beats a stale-prone threshold
 * annotation (the alert title already conveys which threshold was crossed).
 *
 * IoB warnings describe insulin units (never converted), so their persisted
 * message is already unit-stable and is shown verbatim.
 */
export function formatAlertSummary(
  alert: AlertGlucoseFields,
  unit: GlucoseUnit
): string {
  if (alert.alert_type === "iob_warning") {
    return alert.message;
  }
  const title = formatAlertTitle(alert.alert_type);
  const current = `${formatGlucose(alert.current_value, unit)} ${unitLabel(unit)}`;
  if (alert.predicted_value != null && alert.prediction_minutes != null) {
    const predicted = `${formatGlucose(alert.predicted_value, unit)} ${unitLabel(unit)}`;
    return `${title}: ${current} → ${predicted} in ${alert.prediction_minutes}min`;
  }
  return `${title}: ${current}`;
}
