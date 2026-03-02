/**
 * Dashboard Components
 *
 * Barrel export for dashboard-specific components.
 */

export {
  GlucoseHero,
  type GlucoseHeroProps,
  type GlucoseRange,
  classifyGlucose,
  shouldPulse,
  GLUCOSE_THRESHOLDS,
} from "./glucose-hero";

export {
  TrendArrow,
  type TrendArrowProps,
  type TrendDirection,
  type TrendArrowSize,
  TREND_ARROWS,
  TREND_DESCRIPTIONS,
  getTrendArrow,
  getTrendDescription,
  isRising,
  isFalling,
  isRapidChange,
  isStable,
  isUnknown,
} from "./trend-arrow";

export {
  TimeInRangeBar,
  type TimeInRangeBarProps,
  type RangeData,
  type TimePeriod,
  normalizePercentages,
  sanitizeRangeData,
  formatPercentage,
  getQualityAssessment,
  PERIOD_LABELS,
} from "./time-in-range-bar";

export {
  ConnectionStatusBanner,
  type ConnectionStatusBannerProps,
} from "./connection-status-banner";

export {
  AIInsightCard,
  type AIInsightCardProps,
  type InsightData,
} from "./ai-insight-card";

export { AlertCard, type AlertCardProps } from "./alert-card";

export { EscalationTimeline } from "./escalation-timeline";

export {
  GlucoseTrendChart,
  type GlucoseTrendChartProps,
  getPointColor,
  PERIOD_TO_MS,
} from "./glucose-trend-chart";

export {
  CgmSummaryStats,
  type CgmSummaryStatsProps,
} from "./cgm-summary-stats";
