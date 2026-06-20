"use client";

/**
 * Story 6.3: Toast notification component for real-time alerts.
 *
 * Displays severity-appropriate toast notifications with auto-dismiss
 * timers that vary by urgency. EMERGENCY alerts never auto-dismiss.
 *
 * Accessibility: role="alert" on each toast. The parent container
 * provides the persistent aria-live region.
 */

import { useEffect, useRef, useState, useCallback } from "react";
import { X } from "lucide-react";
import clsx from "clsx";
import type { AlertEventData } from "@/hooks/use-glucose-stream";
import { getAlertIcon } from "@/lib/alert-utils";

const TOAST_CONFIG: Record<
  string,
  {
    bg: string;
    border: string;
    text: string;
    duration: number;
    animation: string;
  }
> = {
  emergency: {
    bg: "bg-red-500/20",
    border: "border-red-500",
    text: "text-red-400",
    duration: 0, // Never auto-dismiss
    animation: "animate-pulse-fast",
  },
  urgent: {
    bg: "bg-orange-500/20",
    border: "border-orange-500",
    text: "text-orange-400",
    duration: 30000,
    animation: "animate-pulse-slow",
  },
  warning: {
    bg: "bg-amber-500/20",
    border: "border-amber-500",
    text: "text-amber-400",
    duration: 15000,
    animation: "",
  },
  info: {
    bg: "bg-blue-500/20",
    border: "border-blue-500",
    text: "text-blue-400",
    duration: 10000,
    animation: "",
  },
};

export interface AlertToastProps {
  alert: AlertEventData;
  onDismiss: (id: string) => void;
}

export function AlertToast({ alert, onDismiss }: AlertToastProps) {
  const config = TOAST_CONFIG[alert.severity] ?? TOAST_CONFIG.info;
  const [isVisible, setIsVisible] = useState(true);
  const Icon = getAlertIcon(alert.alert_type);

  const dismissTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleDismiss = useCallback(() => {
    setIsVisible(false);
    dismissTimerRef.current = setTimeout(() => onDismiss(alert.id), 300);
  }, [onDismiss, alert.id]);

  // Clean up dismiss animation timer on unmount (Fix #6)
  useEffect(() => {
    return () => {
      if (dismissTimerRef.current) {
        clearTimeout(dismissTimerRef.current);
      }
    };
  }, []);

  useEffect(() => {
    if (config.duration > 0) {
      const timer = setTimeout(handleDismiss, config.duration);
      return () => clearTimeout(timer);
    }
  }, [config.duration, handleDismiss]);

  return (
    <div
      className={clsx(
        "rounded-lg border p-4 shadow-lg backdrop-blur-xs transition-all duration-300 w-80",
        config.bg,
        config.border,
        config.animation,
        isVisible ? "opacity-100 translate-x-0" : "opacity-0 translate-x-4"
      )}
      role="alert"
    >
      <div className="flex items-start gap-3">
        <Icon
          className={clsx("h-5 w-5 mt-0.5 shrink-0", config.text)}
          aria-hidden="true"
        />
        <div className="flex-1 min-w-0">
          <div
            className={clsx(
              "text-xs font-medium uppercase tracking-wider mb-1",
              config.text
            )}
          >
            {alert.severity}
          </div>
          <p className={clsx("text-sm", config.text)}>{alert.message}</p>
        </div>
        <button
          onClick={handleDismiss}
          className={clsx(
            "p-1 rounded-md hover:bg-slate-700/50 transition-colors shrink-0",
            config.text
          )}
          aria-label="Dismiss alert notification"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}
