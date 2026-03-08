"use client";

/**
 * AIInsightCard Component
 *
 * Stories 5.7-5.8: AI Insight Card
 * Displays an AI-generated insight (daily brief, meal analysis,
 * or correction analysis) with acknowledge/dismiss actions,
 * "Not medical advice" disclaimer, and expandable reasoning/audit panel.
 *
 * Accessibility features:
 * - Semantic article element with aria-label
 * - Keyboard-navigable action buttons
 * - Screen reader status announcements via aria-live
 * - Visible focus rings
 * - Respects reduced motion preferences
 */

import { useMemo, useState } from "react";
import { motion, useReducedMotion } from "framer-motion";
import clsx from "clsx";
import {
  FileText,
  Utensils,
  Syringe,
  Check,
  X,
  ChevronDown,
  ChevronUp,
  Info,
  Shield,
  ShieldAlert,
  Bot,
  AlertTriangle,
  Loader2,
} from "lucide-react";
import type { InsightDetail } from "@/lib/api";
import { MarkdownContent } from "@/components/ui/markdown-content";

// Analysis type configuration
const ANALYSIS_CONFIG = {
  daily_brief: {
    icon: FileText,
    color: "text-blue-400",
    bg: "bg-blue-500/10",
    border: "border-blue-500/20",
    label: "Daily Brief",
  },
  meal_analysis: {
    icon: Utensils,
    color: "text-amber-400",
    bg: "bg-amber-500/10",
    border: "border-amber-500/20",
    label: "Meal Analysis",
  },
  correction_analysis: {
    icon: Syringe,
    color: "text-purple-400",
    bg: "bg-purple-500/10",
    border: "border-purple-500/20",
    label: "Correction Analysis",
  },
} as const;

type AnalysisType = keyof typeof ANALYSIS_CONFIG;

export interface InsightData {
  id: string;
  analysis_type: AnalysisType;
  title: string;
  content: string;
  created_at: string;
  status: "pending" | "acknowledged" | "dismissed";
}

export interface AIInsightCardProps {
  insight: InsightData;
  onRespond?: (
    analysisType: AnalysisType,
    analysisId: string,
    response: "acknowledged" | "dismissed",
    reason?: string
  ) => Promise<void>;
  onFetchDetail?: (
    analysisType: AnalysisType,
    analysisId: string
  ) => Promise<InsightDetail>;
}

/**
 * Format a date string for display.
 */
function formatDate(dateStr: string): string {
  const date = new Date(dateStr);
  if (isNaN(date.getTime())) return "Unknown date";
  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

/**
 * Format a date range for the analysis period.
 */
function formatPeriod(start: string, end: string): string {
  const s = new Date(start);
  const e = new Date(end);
  if (isNaN(s.getTime()) || isNaN(e.getTime())) return "Unknown period";
  const fmt = (d: Date) =>
    d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  return `${fmt(s)} – ${fmt(e)}`;
}

/**
 * Format data context values for display.
 */
function DataContextDisplay({ data }: { data: Record<string, unknown> }) {
  const entries = Object.entries(data).filter(
    ([, v]) => v !== null && v !== undefined
  );

  if (entries.length === 0) return null;

  const formatKey = (key: string) =>
    key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

  const formatValue = (v: unknown): string => {
    if (Array.isArray(v)) {
      return `${v.length} ${v.length === 1 ? "period" : "periods"} analyzed`;
    }
    if (typeof v === "number") {
      return Number.isInteger(v) ? String(v) : v.toFixed(1);
    }
    return String(v);
  };

  return (
    <div className="grid grid-cols-2 gap-x-4 gap-y-1">
      {entries.map(([key, value]) => (
        <div key={key} className="flex justify-between text-xs">
          <span className="text-slate-500 dark:text-slate-400">{formatKey(key)}</span>
          <span className="text-slate-600 dark:text-slate-300 font-mono">{formatValue(value)}</span>
        </div>
      ))}
    </div>
  );
}

/**
 * Status badge component.
 */
function StatusBadge({ status }: { status: InsightData["status"] }) {
  const config = {
    pending: {
      text: "New",
      className: "bg-blue-100 text-blue-700 dark:bg-blue-500/20 dark:text-blue-300",
    },
    acknowledged: {
      text: "Acknowledged",
      className: "bg-green-100 text-green-700 dark:bg-green-500/20 dark:text-green-300",
    },
    dismissed: {
      text: "Dismissed",
      className: "bg-slate-100 text-slate-700 dark:bg-slate-500/20 dark:text-slate-400",
    },
  };

  const { text, className } = config[status];

  return (
    <span
      className={clsx(
        "inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium",
        className
      )}
    >
      {text}
    </span>
  );
}

export function AIInsightCard({ insight, onRespond, onFetchDetail }: AIInsightCardProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [isResponding, setIsResponding] = useState(false);
  const [localStatus, setLocalStatus] = useState(insight.status);
  const [error, setError] = useState<string | null>(null);
  const [announcement, setAnnouncement] = useState<string | null>(null);
  const [showDetail, setShowDetail] = useState(false);
  const [detail, setDetail] = useState<InsightDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const prefersReducedMotion = useReducedMotion();

  const config = ANALYSIS_CONFIG[insight.analysis_type];
  const Icon = config.icon;

  // Strip markdown syntax for clean plain-text preview in collapsed view
  const plainText = useMemo(
    () =>
      insight.content
        .replace(/#{1,6}\s+/g, "")        // headings
        .replace(/\*\*(.+?)\*\*/g, "$1")  // bold
        .replace(/\*(.+?)\*/g, "$1")      // italic
        .replace(/`{1,3}[^`]*`{1,3}/g, (m) => m.replace(/`/g, "")) // code
        .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1") // links
        .replace(/^[-*+]\s+/gm, "")       // unordered list markers
        .replace(/^\d+\.\s+/gm, "")       // ordered list markers
        .replace(/^>\s+/gm, "")           // blockquotes
        .replace(/\n{2,}/g, " ")          // collapse multiple newlines
        .trim(),
    [insight.content],
  );
  const maxPreviewLength = 200;
  const needsTruncation = plainText.length > maxPreviewLength;
  const previewContent = needsTruncation
    ? plainText.slice(0, maxPreviewLength) + "..."
    : plainText;

  const handleRespond = async (response: "acknowledged" | "dismissed") => {
    if (!onRespond || isResponding) return;

    setIsResponding(true);
    setError(null);
    try {
      await onRespond(
        insight.analysis_type,
        insight.id,
        response
      );
      setLocalStatus(response);
      setDetail(null); // Invalidate cached detail so re-fetch picks up response
      setAnnouncement(
        `Insight ${response === "acknowledged" ? "acknowledged" : "dismissed"}`
      );
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to record response"
      );
    } finally {
      setIsResponding(false);
    }
  };

  const handleToggleDetail = async () => {
    if (showDetail) {
      setShowDetail(false);
      return;
    }

    // Fetch detail if not already loaded
    if (!detail && onFetchDetail) {
      setDetailLoading(true);
      setDetailError(null);
      try {
        const result = await onFetchDetail(insight.analysis_type, insight.id);
        setDetail(result);
      } catch (err) {
        setDetailError(
          err instanceof Error ? err.message : "Failed to load details"
        );
        setDetailLoading(false);
        return;
      } finally {
        setDetailLoading(false);
      }
    }

    setShowDetail(true);
  };

  return (
    <motion.article
      className={clsx(
        "rounded-xl border p-5 transition-colors",
        "bg-white dark:bg-slate-900",
        config.border,
        "focus-within:ring-2 focus-within:ring-blue-500 focus-within:ring-offset-2 focus-within:ring-offset-white dark:focus-within:ring-offset-slate-950"
      )}
      initial={prefersReducedMotion ? false : { opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      aria-label={`${config.label}: ${insight.title}`}
    >
      {/* Screen reader announcement for status changes */}
      <div className="sr-only" aria-live="polite" aria-atomic="true">
        {announcement}
      </div>

      {/* Header row */}
      <div className="flex items-start gap-3 mb-3">
        <div
          className={clsx(
            "p-2 rounded-lg shrink-0",
            config.bg
          )}
          aria-hidden="true"
        >
          <Icon className={clsx("h-5 w-5", config.color)} />
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span
              className={clsx("text-xs font-medium uppercase tracking-wider", config.color)}
            >
              {config.label}
            </span>
            <StatusBadge status={localStatus} />
          </div>
          <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-200 leading-tight">
            {insight.title}
          </h3>
          <time
            className="text-xs text-slate-500 dark:text-slate-400 mt-0.5 block"
            dateTime={insight.created_at}
          >
            {formatDate(insight.created_at)}
          </time>
        </div>
      </div>

      {/* Not medical advice disclaimer */}
      <div
        className="flex items-center gap-2 mb-3 px-3 py-2 rounded-lg bg-amber-500/5 border border-amber-500/10"
        role="note"
        aria-label="Not medical advice disclaimer"
      >
        <AlertTriangle className="h-3.5 w-3.5 text-amber-500 shrink-0" aria-hidden="true" />
        <p className="text-xs text-amber-400/80">
          Not medical advice. Always consult your healthcare provider.
        </p>
      </div>

      {/* Content */}
      {isExpanded || !needsTruncation ? (
        <MarkdownContent content={insight.content} className="text-slate-600 dark:text-slate-300" />
      ) : (
        <div className="text-sm text-slate-600 dark:text-slate-300 leading-relaxed whitespace-pre-line">
          {previewContent}
        </div>
      )}

      {/* Expand/collapse toggle */}
      {needsTruncation && (
        <button
          onClick={() => setIsExpanded(!isExpanded)}
          className={clsx(
            "mt-2 text-xs font-medium flex items-center gap-1",
            "text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200 transition-colors",
            "focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 rounded"
          )}
          aria-expanded={isExpanded}
          aria-label={isExpanded ? "Show less" : "Show more"}
        >
          {isExpanded ? (
            <>
              Show less <ChevronUp className="h-3 w-3" />
            </>
          ) : (
            <>
              Show more <ChevronDown className="h-3 w-3" />
            </>
          )}
        </button>
      )}

      {/* View Details button */}
      {onFetchDetail && (
        <button
          onClick={handleToggleDetail}
          disabled={detailLoading}
          className={clsx(
            "mt-3 text-xs font-medium flex items-center gap-1.5",
            "text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200 transition-colors",
            "focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 rounded",
            "disabled:opacity-50 disabled:cursor-not-allowed"
          )}
          aria-expanded={showDetail}
          aria-label={showDetail ? "Hide reasoning and audit details" : "View reasoning and audit details"}
        >
          {detailLoading ? (
            <>
              <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
              Loading...
            </>
          ) : (
            <>
              <Info className="h-3.5 w-3.5" aria-hidden="true" />
              {showDetail ? "Hide Details" : "View Details"}
              {showDetail ? (
                <ChevronUp className="h-3 w-3" />
              ) : (
                <ChevronDown className="h-3 w-3" />
              )}
            </>
          )}
        </button>
      )}

      {/* Detail error */}
      {detailError && (
        <p className="mt-2 text-xs text-red-400" role="alert">
          {detailError}
        </p>
      )}

      {/* Reasoning & Audit Detail Panel */}
      {showDetail && detail && (
        <div
          className="mt-3 pt-3 border-t border-slate-200 dark:border-slate-800 space-y-4"
          role="region"
          aria-label="Insight reasoning and audit details"
        >
          {/* Analysis Period */}
          <div>
            <h4 className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-1">
              Analysis Period
            </h4>
            <p className="text-sm text-slate-600 dark:text-slate-300">
              {formatPeriod(detail.period_start, detail.period_end)}
            </p>
          </div>

          {/* Data Context */}
          <div>
            <h4 className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-2">
              Data Used for Analysis
            </h4>
            <DataContextDisplay data={detail.data_context} />
          </div>

          {/* AI Model Info */}
          <div>
            <h4 className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-2">
              AI Model
            </h4>
            <div className="flex items-center gap-2">
              <Bot className="h-3.5 w-3.5 text-slate-500 dark:text-slate-400" aria-hidden="true" />
              <span className="text-xs text-slate-600 dark:text-slate-300">
                {detail.model_info.provider} / {detail.model_info.model}
              </span>
            </div>
            <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
              Tokens: {detail.model_info.input_tokens.toLocaleString()} in / {detail.model_info.output_tokens.toLocaleString()} out
            </div>
          </div>

          {/* Safety Validation */}
          <div>
            <h4 className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-2">
              Safety Validation
            </h4>
            {detail.safety ? (
              <div className="flex items-center gap-2">
                {detail.safety.has_dangerous_content ? (
                  <ShieldAlert className="h-3.5 w-3.5 text-red-400" aria-hidden="true" />
                ) : (
                  <Shield className="h-3.5 w-3.5 text-green-400" aria-hidden="true" />
                )}
                <span
                  className={clsx(
                    "text-xs",
                    detail.safety.has_dangerous_content
                      ? "text-red-400"
                      : "text-green-400"
                  )}
                >
                  {detail.safety.status}
                  {detail.safety.has_dangerous_content && " — flagged content detected"}
                </span>
              </div>
            ) : (
              <p className="text-xs text-slate-500 dark:text-slate-400">No safety log available</p>
            )}
          </div>
        </div>
      )}

      {/* Error message */}
      {error && (
        <p className="mt-2 text-xs text-red-400" role="alert">
          {error}
        </p>
      )}

      {/* Action buttons (only show for pending insights) */}
      {localStatus === "pending" && onRespond && (
        <div
          className="flex items-center gap-2 mt-4 pt-3 border-t border-slate-200 dark:border-slate-800"
          role="group"
          aria-label="Insight actions"
        >
          <button
            onClick={() => handleRespond("acknowledged")}
            disabled={isResponding}
            className={clsx(
              "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium",
              "bg-green-500/10 text-green-400 hover:bg-green-500/20",
              "transition-colors",
              "focus:outline-none focus-visible:ring-2 focus-visible:ring-green-500",
              "disabled:opacity-50 disabled:cursor-not-allowed"
            )}
            aria-label="Acknowledge this insight"
          >
            <Check className="h-3.5 w-3.5" aria-hidden="true" />
            Acknowledge
          </button>
          <button
            onClick={() => handleRespond("dismissed")}
            disabled={isResponding}
            className={clsx(
              "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium",
              "bg-slate-100 text-slate-700 hover:bg-slate-200 dark:bg-slate-700/50 dark:text-slate-300 dark:hover:bg-slate-700",
              "transition-colors",
              "focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-500",
              "disabled:opacity-50 disabled:cursor-not-allowed"
            )}
            aria-label="Dismiss this insight"
          >
            <X className="h-3.5 w-3.5" aria-hidden="true" />
            Dismiss
          </button>
        </div>
      )}
    </motion.article>
  );
}
