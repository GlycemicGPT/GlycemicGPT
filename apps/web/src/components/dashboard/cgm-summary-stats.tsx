"use client";

/**
 * CGM Summary Stats Panel
 *
 * Story 30.3: Displays aggregate CGM statistics including average glucose,
 * standard deviation, CV%, GMI (estimated A1C), CGM active time, and
 * readings count. Period-selectable.
 */

import { useRef } from "react";
import { AlertCircle, BarChart3, TrendingUp, Percent, Heart, Radio, Hash } from "lucide-react";
import type { GlucoseStats } from "@/lib/api";
import type { StatsPeriod } from "@/hooks/use-glucose-stats";
import { PERIOD_LABELS } from "@/components/dashboard/time-in-range-bar";

export interface CgmSummaryStatsProps {
  stats: GlucoseStats | null;
  isLoading: boolean;
  error?: string | null;
  period: StatsPeriod;
  onPeriodChange: (p: StatsPeriod) => void;
}

const PERIOD_OPTIONS: { value: StatsPeriod; label: string }[] = [
  { value: "24h", label: "24H" },
  { value: "3d", label: "3D" },
  { value: "7d", label: "7D" },
  { value: "14d", label: "14D" },
  { value: "30d", label: "30D" },
];

function getCvAssessment(cv: number): { label: string; color: string } {
  if (cv <= 36) return { label: "Stable", color: "text-green-400" };
  if (cv <= 50) return { label: "Moderate", color: "text-amber-400" };
  return { label: "High variability", color: "text-red-400" };
}

function getCgmActiveAssessment(pct: number): { label: string; color: string } {
  if (pct >= 70) return { label: "Good coverage", color: "text-green-400" };
  if (pct >= 50) return { label: "Partial coverage", color: "text-amber-400" };
  return { label: "Low coverage", color: "text-red-400" };
}

/** Check if a glucose value is within reasonable physiological range. */
function isReasonableGlucose(value: number): boolean {
  return Number.isFinite(value) && value >= 20 && value <= 500;
}

/** Safely format a number, returning "--" for NaN/Infinity. */
function safeRound(value: number): string {
  if (!Number.isFinite(value)) return "--";
  return String(Math.round(value));
}

/** Safely format to 1 decimal place, returning "--" for NaN/Infinity. */
function safeFixed1(value: number): string {
  if (!Number.isFinite(value)) return "--";
  return value.toFixed(1);
}

/** Safely format a percentage with 1 decimal, returning "--" for NaN/Infinity. */
function safePercent1(value: number): string {
  if (!Number.isFinite(value)) return "--";
  return `${value.toFixed(1)}%`;
}

/** Safely format a percentage (rounded), returning "--" for NaN/Infinity. */
function safePercent0(value: number): string {
  if (!Number.isFinite(value)) return "--";
  return `${Math.round(value)}%`;
}

/** Safely format a count, returning "--" for NaN/Infinity/negative. */
function safeCount(value: number): string {
  if (!Number.isFinite(value) || value < 0) return "--";
  return Math.round(value).toLocaleString();
}

function StatSkeleton() {
  return (
    <div className="animate-pulse space-y-2">
      <div className="h-4 w-20 bg-slate-700 rounded" />
      <div className="h-8 w-16 bg-slate-700 rounded" />
      <div className="h-3 w-24 bg-slate-800 rounded" />
    </div>
  );
}

interface StatCardProps {
  icon: React.ReactNode;
  label: string;
  value: string;
  subtitle: string;
  subtitleColor?: string;
  ariaLabel: string;
}

function StatCard({ icon, label, value, subtitle, subtitleColor = "text-slate-500", ariaLabel }: StatCardProps) {
  return (
    <div className="space-y-1" role="group" aria-label={ariaLabel}>
      <div className="flex items-center gap-2">
        {icon}
        <span className="text-slate-400 text-xs font-medium">{label}</span>
      </div>
      <p className="text-2xl font-bold text-white">{value}</p>
      <p className={`text-xs ${subtitleColor}`}>{subtitle}</p>
    </div>
  );
}

export function CgmSummaryStats({
  stats,
  isLoading,
  error,
  period,
  onPeriodChange,
}: CgmSummaryStatsProps) {
  const noData = !stats || !Number.isFinite(stats.readings_count) || stats.readings_count <= 0;
  const cvAssessment = stats && Number.isFinite(stats.cv_pct) ? getCvAssessment(stats.cv_pct) : null;
  const cgmAssessment = stats && Number.isFinite(stats.cgm_active_pct) ? getCgmActiveAssessment(stats.cgm_active_pct) : null;
  const periodLabel = PERIOD_LABELS[period] ?? period;
  const buttonsRef = useRef<(HTMLButtonElement | null)[]>([]);

  const handlePeriodKeyDown = (e: React.KeyboardEvent, index: number) => {
    let newIndex = index;
    if (e.key === "ArrowRight" || e.key === "ArrowDown") {
      e.preventDefault();
      newIndex = (index + 1) % PERIOD_OPTIONS.length;
    } else if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
      e.preventDefault();
      newIndex = (index - 1 + PERIOD_OPTIONS.length) % PERIOD_OPTIONS.length;
    } else if (e.key === "Home") {
      e.preventDefault();
      newIndex = 0;
    } else if (e.key === "End") {
      e.preventDefault();
      newIndex = PERIOD_OPTIONS.length - 1;
    } else {
      return;
    }
    onPeriodChange(PERIOD_OPTIONS[newIndex].value);
    buttonsRef.current[newIndex]?.focus();
  };

  return (
    <section
      aria-labelledby="cgm-stats-heading"
      aria-busy={isLoading}
      className="bg-slate-900 rounded-xl p-6 border border-slate-800"
    >
      {/* Header with period selector */}
      <div className="flex items-center justify-between mb-5">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-blue-500/10 rounded-lg">
            <BarChart3 className="h-5 w-5 text-blue-400" aria-hidden="true" />
          </div>
          <h2 id="cgm-stats-heading" className="text-white font-semibold">
            CGM Summary
            <span className="text-slate-400 text-sm font-normal ml-2">
              {periodLabel}
            </span>
          </h2>
        </div>

        <div className="flex gap-1" role="radiogroup" aria-label="Statistics time period">
          {PERIOD_OPTIONS.map((opt, i) => (
            <button
              key={opt.value}
              ref={(el) => { buttonsRef.current[i] = el; }}
              role="radio"
              aria-checked={period === opt.value}
              tabIndex={period === opt.value ? 0 : -1}
              onClick={() => onPeriodChange(opt.value)}
              onKeyDown={(e) => handlePeriodKeyDown(e, i)}
              className={`px-2.5 py-1 text-xs font-medium rounded-md transition-colors ${
                period === opt.value
                  ? "bg-blue-600 text-white"
                  : "text-slate-400 hover:text-white hover:bg-slate-800"
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {/* Stats grid */}
      {isLoading ? (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-6">
          {Array.from({ length: 6 }).map((_, i) => (
            <StatSkeleton key={i} />
          ))}
        </div>
      ) : error ? (
        <div className="flex items-center gap-2 text-red-400 text-sm py-4 justify-center" role="alert">
          <AlertCircle className="h-4 w-4" aria-hidden="true" />
          <p>Failed to load CGM stats. Try again later.</p>
        </div>
      ) : noData ? (
        <p className="text-slate-500 text-sm text-center py-4">
          No CGM data available for this period.
        </p>
      ) : (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-6">
          <StatCard
            icon={<TrendingUp className="h-4 w-4 text-blue-400" aria-hidden="true" />}
            label="Avg Glucose"
            value={isReasonableGlucose(stats.mean_glucose) ? safeRound(stats.mean_glucose) : "--"}
            subtitle="mg/dL"
            ariaLabel={`Average glucose: ${isReasonableGlucose(stats.mean_glucose) ? `${safeRound(stats.mean_glucose)} mg/dL` : "unavailable"}`}
          />

          <StatCard
            icon={<BarChart3 className="h-4 w-4 text-purple-400" aria-hidden="true" />}
            label="Std Dev"
            value={isReasonableGlucose(stats.std_dev) ? safeRound(stats.std_dev) : "--"}
            subtitle="mg/dL"
            ariaLabel={`Standard deviation: ${isReasonableGlucose(stats.std_dev) ? `${safeRound(stats.std_dev)} mg/dL` : "unavailable"}`}
          />

          <StatCard
            icon={<Percent className="h-4 w-4 text-amber-400" aria-hidden="true" />}
            label="CV%"
            value={safePercent1(stats.cv_pct)}
            subtitle={cvAssessment ? `Target <36% | ${cvAssessment.label}` : "Target <36%"}
            subtitleColor={cvAssessment?.color ?? "text-slate-500"}
            ariaLabel={`Coefficient of variation: ${safeFixed1(stats.cv_pct)} percent. ${cvAssessment?.label ?? ""}`}
          />

          <StatCard
            icon={<Heart className="h-4 w-4 text-rose-400" aria-hidden="true" />}
            label="GMI (est. A1C)"
            value={safePercent1(stats.gmi)}
            subtitle="Glucose Management Indicator"
            ariaLabel={`Glucose Management Indicator: ${safeFixed1(stats.gmi)} percent estimated A1C`}
          />

          <StatCard
            icon={<Radio className="h-4 w-4 text-emerald-400" aria-hidden="true" />}
            label="CGM Active"
            value={safePercent0(stats.cgm_active_pct)}
            subtitle={cgmAssessment ? `Target >70% | ${cgmAssessment.label}` : "Target >70%"}
            subtitleColor={cgmAssessment?.color ?? "text-slate-500"}
            ariaLabel={`CGM active time: ${safeRound(stats.cgm_active_pct)} percent. ${cgmAssessment?.label ?? ""}`}
          />

          <StatCard
            icon={<Hash className="h-4 w-4 text-slate-400" aria-hidden="true" />}
            label="Readings"
            value={safeCount(stats.readings_count)}
            subtitle={`in ${periodLabel.toLowerCase()}`}
            ariaLabel={`${safeCount(stats.readings_count)} readings in ${periodLabel.toLowerCase()}`}
          />
        </div>
      )}
    </section>
  );
}
