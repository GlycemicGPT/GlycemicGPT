"use client";

/**
 * Story 6.7: Escalation Timeline Component.
 *
 * Displays the escalation history for an alert, showing progression
 * through tiers (reminder, primary contact, all contacts).
 */

import { useEffect, useState } from "react";
import { AlertCircle, Clock, Loader2, User, Users } from "lucide-react";
import clsx from "clsx";
import { getAlertEscalationTimeline } from "@/lib/api";
import type { EscalationEvent } from "@/lib/api";

const TIER_CONFIG: Record<
  string,
  {
    label: string;
    icon: typeof Clock;
    color: string;
    bg: string;
    border: string;
  }
> = {
  reminder: {
    label: "Reminder Sent",
    icon: Clock,
    color: "text-amber-600 dark:text-amber-400",
    bg: "bg-amber-100/50 dark:bg-amber-900/20",
    border: "border-amber-300/50 dark:border-amber-700/30",
  },
  primary_contact: {
    label: "Primary Contact Notified",
    icon: User,
    color: "text-orange-600 dark:text-orange-400",
    bg: "bg-orange-100/50 dark:bg-orange-900/20",
    border: "border-orange-300/50 dark:border-orange-700/30",
  },
  all_contacts: {
    label: "All Contacts Notified",
    icon: Users,
    color: "text-red-600 dark:text-red-400",
    bg: "bg-red-100/50 dark:bg-red-900/20",
    border: "border-red-300/50 dark:border-red-700/30",
  },
};

const UNKNOWN_TIER = {
  label: "Unknown Escalation",
  icon: AlertCircle,
  color: "text-slate-500 dark:text-slate-400",
  bg: "bg-slate-50/20 dark:bg-slate-900/20",
  border: "border-slate-300/30 dark:border-slate-700/30",
};

function formatTimestamp(iso: string): string {
  const date = new Date(iso);
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    sent: "bg-green-100/50 dark:bg-green-900/30 text-green-700 dark:text-green-400 border-green-300/50 dark:border-green-700/30",
    pending: "bg-yellow-100/50 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-400 border-yellow-300/50 dark:border-yellow-700/30",
    failed: "bg-red-100/50 dark:bg-red-900/30 text-red-700 dark:text-red-400 border-red-300/50 dark:border-red-700/30",
  };

  return (
    <span
      className={clsx(
        "text-[10px] font-medium uppercase tracking-wider px-1.5 py-0.5 rounded border",
        styles[status] || styles.pending
      )}
    >
      {status}
    </span>
  );
}

interface EscalationTimelineProps {
  alertId: string;
}

export function EscalationTimeline({ alertId }: EscalationTimelineProps) {
  const [events, setEvents] = useState<EscalationEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [fetchedAlertId, setFetchedAlertId] = useState<string | null>(null);

  useEffect(() => {
    // Skip re-fetch if data is already loaded for this alert
    if (fetchedAlertId === alertId) return;

    let cancelled = false;

    async function fetchTimeline() {
      try {
        setLoading(true);
        const data = await getAlertEscalationTimeline(alertId);
        if (!cancelled) {
          setEvents(data.events);
          setError(null);
          setFetchedAlertId(alertId);
        }
      } catch (err) {
        if (!cancelled) {
          setError(
            err instanceof Error ? err.message : "Failed to load timeline"
          );
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    fetchTimeline();
    return () => {
      cancelled = true;
    };
  }, [alertId, fetchedAlertId]);

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400 mt-3">
        <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />
        <span>Loading escalation timeline...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="text-xs text-red-400 mt-3" role="alert">
        Escalation timeline unavailable
      </div>
    );
  }

  if (events.length === 0) {
    return null;
  }

  return (
    <div className="mt-3 space-y-2" aria-label="Escalation timeline">
      <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
        Escalation History
      </p>
      {events.map((event) => {
        const tier = TIER_CONFIG[event.tier] || UNKNOWN_TIER;
        const TierIcon = tier.icon;

        return (
          <div
            key={event.id}
            className={clsx(
              "flex items-center gap-2 rounded-lg border px-3 py-2",
              tier.bg,
              tier.border
            )}
          >
            <TierIcon
              className={clsx("h-3.5 w-3.5 shrink-0", tier.color)}
              aria-hidden="true"
            />
            <span className={clsx("text-xs font-medium", tier.color)}>
              {tier.label}
            </span>
            <span className="ml-auto flex items-center gap-2">
              <StatusBadge status={event.notification_status} />
              <span className="text-[10px] text-slate-500 dark:text-slate-400">
                {formatTimestamp(event.triggered_at)}
              </span>
            </span>
          </div>
        );
      })}
    </div>
  );
}
