"use client";

/**
 * Story 6.4: AlertCard Component with Acknowledgment.
 *
 * Displays a predictive alert with severity styling, glucose values,
 * prediction details, countdown timer, and a large acknowledge button
 * (56px min-height for hypoglycemia fine motor control).
 *
 * Accessibility: role="alert", aria-labels, focus-visible rings, 56px touch target.
 */

import { useEffect, useRef, useState } from "react";
import { CheckCircle, Clock, Loader2 } from "lucide-react";
import clsx from "clsx";
import type { PredictiveAlert } from "@/lib/api";
import {
  SEVERITY_CONFIG,
  getAlertIcon,
  formatAlertTitle,
  formatTimeAgo,
  formatCountdown,
} from "@/lib/alert-utils";
import { EscalationTimeline } from "./escalation-timeline";

export interface AlertCardProps {
  alert: PredictiveAlert;
  onAcknowledge: (alertId: string) => Promise<void>;
  isAcknowledging?: boolean;
}

export function AlertCard({
  alert,
  onAcknowledge,
  isAcknowledging = false,
}: AlertCardProps) {
  const config = SEVERITY_CONFIG[alert.severity] ?? SEVERITY_CONFIG.info;
  const Icon = getAlertIcon(alert.alert_type);
  const title = formatAlertTitle(alert.alert_type);

  // Countdown timer
  const [countdown, setCountdown] = useState<string | null>(() =>
    formatCountdown(alert.expires_at)
  );
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    intervalRef.current = setInterval(() => {
      const remaining = formatCountdown(alert.expires_at);
      setCountdown(remaining);
      if (remaining === null && intervalRef.current) {
        clearInterval(intervalRef.current);
      }
    }, 1000);
    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
      }
    };
  }, [alert.expires_at]);

  const isExpired = countdown === null;

  return (
    <div
      className={clsx(
        "rounded-xl border p-5 transition-all",
        config.bg,
        config.border,
        config.animation
      )}
      role="alert"
      aria-label={`${alert.severity} alert: ${title}`}
    >
      {/* Header */}
      <div className="flex items-center gap-3 mb-3">
        <Icon
          className={clsx("h-5 w-5 shrink-0", config.icon)}
          aria-hidden="true"
        />
        <span
          className={clsx(
            "text-xs font-semibold uppercase tracking-wider",
            config.text
          )}
        >
          {alert.severity}
        </span>
        <span className="text-sm font-medium text-slate-200">{title}</span>
        {alert.source === "predictive" && (
          <span className="ml-auto text-xs text-slate-500">Predicted</span>
        )}
      </div>

      {/* Glucose values */}
      <div className="flex items-baseline gap-4 mb-3">
        <div>
          <span className={clsx("text-2xl font-bold", config.text)}>
            {alert.current_value}
          </span>
          <span className="text-sm text-slate-400 ml-1">mg/dL</span>
        </div>
        {alert.predicted_value != null && alert.prediction_minutes != null && (
          <div className="text-sm text-slate-400">
            <span className="mr-1">&rarr;</span>
            <span className={clsx("font-medium", config.text)}>
              {alert.predicted_value}
            </span>
            <span className="ml-1">
              mg/dL in {alert.prediction_minutes}min
            </span>
          </div>
        )}
      </div>

      {/* Message / Recommended action */}
      <p className={clsx("text-sm mb-3", config.text)}>{alert.message}</p>

      {/* Metadata */}
      <div className="flex items-center gap-4 mb-4 text-xs text-slate-500">
        <span className="flex items-center gap-1">
          <Clock className="h-3 w-3" aria-hidden="true" />
          {formatTimeAgo(alert.created_at)}
        </span>
        {alert.iob_value != null && (
          <span>IoB: {alert.iob_value.toFixed(2)}u</span>
        )}
        {alert.trend_rate != null && (
          <span>
            {alert.trend_rate > 0 ? "+" : ""}
            {alert.trend_rate.toFixed(1)} mg/dL/min
          </span>
        )}
      </div>

      {/* Countdown timer */}
      {!isExpired && (
        <div
          className="flex items-center gap-2 mb-4 text-xs text-slate-400"
          aria-hidden="true"
        >
          <Clock className="h-3 w-3" aria-hidden="true" />
          <span>Expires in {countdown}</span>
        </div>
      )}
      {isExpired && (
        <div className="flex items-center gap-2 mb-4 text-xs text-slate-500">
          <Clock className="h-3 w-3" aria-hidden="true" />
          <span>Expired</span>
        </div>
      )}

      {/* Acknowledge button - 56px min height for hypoglycemia fine motor control */}
      <button
        type="button"
        onClick={() => onAcknowledge(alert.id)}
        disabled={isAcknowledging || isExpired}
        className={clsx(
          "flex items-center justify-center gap-2 w-full rounded-lg",
          "min-h-[56px] px-4 py-3 text-base font-semibold",
          "transition-colors",
          "focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500",
          "disabled:opacity-50 disabled:cursor-not-allowed",
          isExpired
            ? "bg-slate-100/30 dark:bg-slate-800/30 text-slate-500"
            : "bg-slate-100/50 dark:bg-slate-800/50 text-slate-700 dark:text-slate-200 hover:bg-slate-200 dark:hover:bg-slate-700"
        )}
        aria-label={`Acknowledge ${alert.alert_type.replace(/_/g, " ")} alert`}
      >
        {isAcknowledging ? (
          <Loader2 className="h-5 w-5 animate-spin" aria-hidden="true" />
        ) : (
          <CheckCircle className="h-5 w-5" aria-hidden="true" />
        )}
        {isAcknowledging ? "Acknowledging..." : "Acknowledge"}
      </button>

      {/* Escalation timeline for critical alerts (Story 6.7) */}
      {(alert.severity === "urgent" || alert.severity === "emergency") &&
        !alert.acknowledged && <EscalationTimeline alertId={alert.id} />}
    </div>
  );
}

