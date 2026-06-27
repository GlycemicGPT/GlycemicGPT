"use client";

/**
 * Data Freshness Indicator Component.
 *
 * Story 3.6: Data Freshness Display
 * Shows users when their data was last updated so they know if
 * they're looking at current or stale information.
 */

import { useState, useEffect, useCallback } from "react";
import { motion } from "framer-motion";
import { RefreshCw, Clock, AlertTriangle, CheckCircle } from "lucide-react";

export type FreshnessLevel = "fresh" | "stale" | "critical";

export interface DataFreshnessIndicatorProps {
  /** ISO timestamp of when data was last updated */
  lastUpdated: string | null;
  /** Label for the data source (e.g., "CGM", "Pump") */
  label?: string;
  /** Callback when refresh button is clicked */
  onRefresh?: () => void;
  /** Whether a refresh is in progress */
  isRefreshing?: boolean;
  /** Threshold in minutes for "stale" status (default: 5) */
  staleThresholdMinutes?: number;
  /** Threshold in minutes for "critical" status (default: 10) */
  criticalThresholdMinutes?: number;
  /** Update interval in ms for relative time display (default: 30000) */
  updateInterval?: number;
}

/**
 * Calculate the freshness level based on data age.
 */
export function getFreshnessLevel(
  lastUpdated: string | null,
  staleThreshold: number,
  criticalThreshold: number
): FreshnessLevel {
  if (!lastUpdated) {
    return "critical";
  }

  const now = new Date();
  const lastUpdate = new Date(lastUpdated);
  const diffMinutes = (now.getTime() - lastUpdate.getTime()) / (1000 * 60);

  if (diffMinutes < staleThreshold) {
    return "fresh";
  } else if (diffMinutes < criticalThreshold) {
    return "stale";
  } else {
    return "critical";
  }
}

/**
 * Format the time difference as a human-readable string.
 */
export function formatTimeDiff(lastUpdated: string | null): string {
  if (!lastUpdated) {
    return "No data";
  }

  const now = new Date();
  const lastUpdate = new Date(lastUpdated);
  const diffMs = now.getTime() - lastUpdate.getTime();
  const diffMinutes = Math.floor(diffMs / (1000 * 60));

  if (diffMinutes < 1) {
    return "Just now";
  } else if (diffMinutes === 1) {
    return "1 min ago";
  } else if (diffMinutes < 60) {
    return `${diffMinutes} min ago`;
  } else {
    const diffHours = Math.floor(diffMinutes / 60);
    if (diffHours === 1) {
      return "1 hour ago";
    } else if (diffHours < 24) {
      return `${diffHours} hours ago`;
    } else {
      // For very old data, show the actual time
      return lastUpdate.toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
      });
    }
  }
}

/**
 * Format timestamp for display in stale/critical state.
 */
export function formatTimestamp(lastUpdated: string | null): string {
  if (!lastUpdated) {
    return "Unknown";
  }

  const date = new Date(lastUpdated);
  return date.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
}

const freshnessConfig = {
  fresh: {
    bgColor: "bg-green-500/20",
    borderColor: "border-green-500/50",
    textColor: "text-green-400",
    iconColor: "text-green-500",
    Icon: CheckCircle,
  },
  stale: {
    bgColor: "bg-yellow-500/20",
    borderColor: "border-yellow-500/50",
    textColor: "text-yellow-400",
    iconColor: "text-yellow-500",
    Icon: Clock,
  },
  critical: {
    bgColor: "bg-red-500/20",
    borderColor: "border-red-500/50",
    textColor: "text-red-400",
    iconColor: "text-red-500",
    Icon: AlertTriangle,
  },
};

export function DataFreshnessIndicator({
  lastUpdated,
  label,
  onRefresh,
  isRefreshing = false,
  staleThresholdMinutes = 5,
  criticalThresholdMinutes = 10,
  updateInterval = 30000,
}: DataFreshnessIndicatorProps) {
  const [timeDiff, setTimeDiff] = useState(() => formatTimeDiff(lastUpdated));
  const [freshnessLevel, setFreshnessLevel] = useState<FreshnessLevel>(() =>
    getFreshnessLevel(lastUpdated, staleThresholdMinutes, criticalThresholdMinutes)
  );

  // Update the time display periodically
  useEffect(() => {
    const updateDisplay = () => {
      setTimeDiff(formatTimeDiff(lastUpdated));
      setFreshnessLevel(
        getFreshnessLevel(lastUpdated, staleThresholdMinutes, criticalThresholdMinutes)
      );
    };

    // Update immediately when lastUpdated changes
    updateDisplay();

    // Set up interval for periodic updates
    const interval = setInterval(updateDisplay, updateInterval);

    return () => clearInterval(interval);
  }, [lastUpdated, staleThresholdMinutes, criticalThresholdMinutes, updateInterval]);

  const handleRefresh = useCallback(() => {
    if (!isRefreshing && onRefresh) {
      onRefresh();
    }
  }, [isRefreshing, onRefresh]);

  const config = freshnessConfig[freshnessLevel];
  const { Icon } = config;

  return (
    <motion.div
      initial={{ opacity: 0, y: -10 }}
      animate={{ opacity: 1, y: 0 }}
      className={`
        inline-flex items-center gap-2 px-3 py-1.5 rounded-lg
        border ${config.bgColor} ${config.borderColor}
      `}
      role="status"
      aria-label={`Data freshness: ${freshnessLevel}`}
    >
      <Icon className={`w-4 h-4 ${config.iconColor}`} aria-hidden="true" />

      <div className="flex items-center gap-1.5">
        {label && (
          <span className="text-xs text-gray-400 font-medium">{label}:</span>
        )}
        <span className={`text-sm font-medium ${config.textColor}`}>
          {freshnessLevel === "fresh" ? timeDiff : formatTimestamp(lastUpdated)}
        </span>
      </div>

      {freshnessLevel === "critical" && (
        <span className="text-xs text-red-400 ml-1">Data may be stale</span>
      )}

      {freshnessLevel !== "fresh" && onRefresh && (
        <button
          onClick={handleRefresh}
          disabled={isRefreshing}
          className={`
            ml-1 p-1 rounded-sm transition-colors
            ${
              isRefreshing
                ? "text-gray-500 cursor-not-allowed"
                : "text-gray-400 hover:text-white hover:bg-slate-700"
            }
          `}
          aria-label="Refresh data"
        >
          <RefreshCw
            className={`w-3.5 h-3.5 ${isRefreshing ? "animate-spin" : ""}`}
            aria-hidden="true"
          />
        </button>
      )}
    </motion.div>
  );
}

/**
 * Compact variant for use in tight spaces (e.g., header).
 */
export function DataFreshnessIndicatorCompact({
  lastUpdated,
  onRefresh,
  isRefreshing = false,
  staleThresholdMinutes = 5,
  criticalThresholdMinutes = 10,
}: Omit<DataFreshnessIndicatorProps, "label" | "updateInterval">) {
  const [freshnessLevel, setFreshnessLevel] = useState<FreshnessLevel>(() =>
    getFreshnessLevel(lastUpdated, staleThresholdMinutes, criticalThresholdMinutes)
  );

  useEffect(() => {
    setFreshnessLevel(
      getFreshnessLevel(lastUpdated, staleThresholdMinutes, criticalThresholdMinutes)
    );

    const interval = setInterval(() => {
      setFreshnessLevel(
        getFreshnessLevel(lastUpdated, staleThresholdMinutes, criticalThresholdMinutes)
      );
    }, 30000);

    return () => clearInterval(interval);
  }, [lastUpdated, staleThresholdMinutes, criticalThresholdMinutes]);

  const handleRefresh = useCallback(() => {
    if (!isRefreshing && onRefresh) {
      onRefresh();
    }
  }, [isRefreshing, onRefresh]);

  const config = freshnessConfig[freshnessLevel];
  const { Icon } = config;

  return (
    <div
      className="inline-flex items-center gap-1"
      role="status"
      aria-label={`Data freshness: ${freshnessLevel}`}
    >
      <Icon className={`w-3.5 h-3.5 ${config.iconColor}`} aria-hidden="true" />

      {freshnessLevel !== "fresh" && onRefresh && (
        <button
          onClick={handleRefresh}
          disabled={isRefreshing}
          className={`
            p-0.5 rounded-sm transition-colors
            ${
              isRefreshing
                ? "text-gray-500 cursor-not-allowed"
                : "text-gray-400 hover:text-white"
            }
          `}
          aria-label="Refresh data"
        >
          <RefreshCw
            className={`w-3 h-3 ${isRefreshing ? "animate-spin" : ""}`}
            aria-hidden="true"
          />
        </button>
      )}
    </div>
  );
}
